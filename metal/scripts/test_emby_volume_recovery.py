import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import emby_volume_recovery as recovery


class ColdRecoveryTests(unittest.TestCase):
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
