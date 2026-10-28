import io
import copy
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import emby_volume_recovery as recovery


class ColdRecoveryTests(unittest.TestCase):
    def test_direct_server_launch_preserves_service_environment_and_isolation(self):
        arguments = recovery.restore_arguments(Path('/private/reconstruction'), 'owned-test')
        environment = dict(item[len('--env='):].split('=', 1) for item in arguments if item.startswith('--env='))
        self.assertEqual(environment['HOME'], '/config')
        self.assertEqual(environment['LD_LIBRARY_PATH'], '/app/emby/lib:/app/emby/extra/lib')
        self.assertEqual(environment['SSL_CERT_FILE'], '/app/emby/etc/ssl/certs/ca-certificates.crt')
        self.assertIn('--workdir=/app/emby', arguments)
        for flag in ('--log-driver=none', '--network=none', '--read-only', '--cap-drop=ALL',
                     '--user=99:100', '--security-opt=no-new-privileges:true'):
            self.assertIn(flag, arguments)
        self.assertEqual([item for item in arguments if item.startswith('--volume=')],
                         ['--volume=/private/reconstruction:/config:Z'])
        self.assertIn(recovery.IMAGE, arguments)

    def test_reconstruction_accepts_only_verified_destination_label_addition(self):
        label = b'system_u:object_r:var_lib_t:s0\0'.hex()
        original = {'': {'kind': 'directory', 'mode': 448, 'uid': 99, 'gid': 100,
                         'mtime_ns': 123, 'xattrs': {'user.retained': 'abcd'}}}
        actual = copy.deepcopy(original)
        actual['']['xattrs']['security.selinux'] = label
        accepted = recovery.compare_reconstruction(actual, original, label)
        self.assertEqual(accepted['destination_selinux_labels_added'], 1)
        for field, value in [('mode', 511), ('mtime_ns', 124), ('uid', 0), ('kind', 'file')]:
            changed = copy.deepcopy(actual)
            changed[''][field] = value
            with self.assertRaisesRegex(RuntimeError, 'source metadata differs'):
                recovery.compare_reconstruction(changed, original, label)
        for attributes in ({'security.selinux': 'deadbeef', 'user.retained': 'abcd'},
                           {'security.selinux': label},
                           {'security.selinux': label, 'user.retained': 'abcd', 'user.unexpected': 'ab'}):
            changed = copy.deepcopy(actual)
            changed['']['xattrs'] = attributes
            with self.assertRaises(RuntimeError):
                recovery.compare_reconstruction(changed, original, label)
        with self.assertRaises(RuntimeError):
            recovery.compare_reconstruction({}, original, label)
        # A retained source security label must match exactly, even when the host differs.
        original['']['xattrs']['security.selinux'] = 'deadbeef'
        with self.assertRaisesRegex(RuntimeError, 'source metadata differs'):
            recovery.compare_reconstruction(actual, original, label)
        actual['']['xattrs']['security.selinux'] = 'deadbeef'
        self.assertEqual(recovery.compare_reconstruction(actual, original, label)['destination_selinux_labels_added'], 0)

    def test_tree_and_archive_detect_payload_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            root.mkdir()
            (root / 'retained').write_bytes(b'protected retained bytes')
            (root / 'link').symlink_to('retained')
            # Native Linux qualification verifies real xattrs; this fixture has none.
            with mock.patch.object(recovery.os, 'listxattr', return_value=[], create=True):
                records = recovery.tree(root)
            archive = Path(temporary) / 'volume.tar'
            with tarfile.open(archive, 'w', format=tarfile.PAX_FORMAT) as saved:
                saved.add(root, arcname='.')
            recovery.check_archive(archive, records)
            records['retained']['sha256'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                recovery.check_archive(archive, records)

    def test_archive_rejects_traversal_and_descendants_of_links(self):
        for name in ('../escape', '/absolute', 'dir/../escape'):
            with self.assertRaises(RuntimeError):
                recovery.safe_name(name)
        with self.assertRaisesRegex(RuntimeError, 'beneath a link'):
            recovery.validate_tree({'': {'kind': 'directory'}, 'link': {'kind': 'symlink'},
                                    'link/payload': {'kind': 'file'}})
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'bad.tar'
            with tarfile.open(archive, 'w') as saved:
                member = tarfile.TarInfo('../escape')
                member.size = 1
                saved.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(RuntimeError):
                recovery.check_archive(archive, {'': {'kind': 'directory'}})
