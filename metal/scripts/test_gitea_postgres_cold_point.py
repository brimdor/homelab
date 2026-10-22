"""Reject damaged or unowned complete-file copy points before native restoration."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gitea_postgres_cold_point as cold


STATE = {'control_version': 1300, 'catalog_version': 202307071, 'cluster_state': 'shut down',
         'data_page_checksum_version': 0, 'system_identifier_sha256': 'a' * 64,
         'checkpoint_sha256': 'b' * 64, 'complete_control_output_sha256': 'c' * 64}


def fixture(root):
    source = root / 'source'
    (source / 'data/global').mkdir(parents=True)
    (source / 'data/PG_VERSION').write_bytes(b'16\n')
    (source / 'data/global/pg_control').write_bytes(b'\0' * 8192)
    (source / 'data/empty').write_bytes(b'')
    return source


class ColdPointTests(unittest.TestCase):
    def setUp(self):
        # Only this tiny parser fixture stubs Linux xattrs and /proc/meminfo.
        self.xattrs = patch.object(cold.retained.os, 'listxattr', return_value=[], create=True)
        self.xattrs.start()
        self.addCleanup(self.xattrs.stop)
        self.memory = patch.object(cold.retained, 'available_memory', return_value=1024 * 1024)
        self.memory.start()
        self.addCleanup(self.memory.stop)
        # Receiver kubelet capacity applies on Linux; this fixture writes only 8 KiB.
        self.capacity = patch.object(cold.retained, 'require_capacity')
        self.capacity.start()
        self.addCleanup(self.capacity.stop)

    def test_complete_protected_readback_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            before = cold.retained.snapshot(source)[0]
            value, checksum = cold.capture(source, root / 'point', STATE)
            self.assertEqual(cold.verify(root / 'point', checksum), value)
            self.assertEqual(cold.retained.snapshot(source)[0], before)
            self.assertEqual(value['tree']['data/empty']['bytes'], 0)
            with self.assertRaises(RuntimeError):
                cold.capture(source, root / 'point', STATE)

    def test_payload_mutation_extra_missing_and_manifest_damage_refused(self):
        for change in ('payload', 'extra', 'missing', 'manifest'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                point = root / 'point'
                value, checksum = cold.capture(fixture(root), point, STATE)
                number = next(n for n, (name, _) in enumerate(sorted(value['tree'].items()))
                              if name == 'data/PG_VERSION')
                payload = point / 'data' / str(number)
                if change == 'payload':
                    payload.write_bytes(b'17\n')
                elif change == 'extra':
                    (point / 'data/foreign').write_bytes(b'foreign')
                elif change == 'missing':
                    payload.unlink()
                else:
                    (point / 'verified.json').write_bytes(b'{}')
                with self.assertRaises((RuntimeError, FileNotFoundError)):
                    cold.verify(point, checksum)

    def test_running_uncovered_source_and_unsafe_tree_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            tree, _ = cold.retained.snapshot(source)
            original = {'format': cold.FORMAT, 'original_manifest_sha256': cold.control.CHECKSUM,
                        'control': STATE, 'tree': tree}
            cold.validate(original)
            changes = [lambda v: v['control'].update(cluster_state='in production'),
                       lambda v: v['control'].update(data_page_checksum_version=True),
                       lambda v: v['control'].update(cluster_state='shut down in recovery'),
                       lambda v: v['control'].update(password='foreign'),
                       lambda v: v.update(original_manifest_sha256='d' * 64),
                       lambda v: v['tree'].update({'../foreign': tree['data/PG_VERSION']}),
                       lambda v: v['tree'].update({'missing/child': tree['data/PG_VERSION']}),
                       lambda v: v['tree'].update({'data/postmaster.pid': tree['data/PG_VERSION']}),
                       lambda v: v['tree']['data/PG_VERSION'].update(kind='symlink'),
                       lambda v: v['tree']['data/PG_VERSION'].update(uid=True),
                       lambda v: v['tree']['data/PG_VERSION'].update(xattrs={'user.example': 'z'}),
                       lambda v: v['tree']['data/PG_VERSION'].update(sha256='e' * 64)]
            for change in changes:
                altered = copy.deepcopy(original)
                change(altered)
                with self.assertRaises(RuntimeError):
                    cold.validate(altered)
            (source / 'data/postmaster.pid').write_bytes(b'123\n')
            with self.assertRaises(RuntimeError):
                cold.capture(source, root / 'rejected', STATE)
            self.assertFalse((root / 'rejected').exists())

    def test_linked_source_and_changed_point_permissions_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            (root / 'linked').symlink_to(source, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                cold.capture(root / 'linked', root / 'rejected', STATE)
            _, checksum = cold.capture(source, root / 'point', STATE)
            (root / 'point/data').chmod(0o755)
            with self.assertRaises(RuntimeError):
                cold.verify(root / 'point', checksum)


if __name__ == '__main__':
    unittest.main()
