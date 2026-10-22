"""Reject damaged or unowned complete-file copy points before native restoration."""

import copy
import io
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

    def test_stream_roundtrip_and_incomplete_or_changed_stream_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value, checksum = cold.capture(fixture(root), root / 'point', STATE)
            stream = io.BytesIO()
            cold.send(root / 'point', checksum, stream)
            raw = stream.getvalue()
            self.assertEqual(cold.receive(io.BytesIO(raw), root / 'received'), (value, checksum))
            for number, damaged in enumerate((raw[:-1], raw + b'foreign', raw[:80],
                                              raw.replace(b'16\n', b'17\n'))):
                with self.subTest(number=number), self.assertRaises((RuntimeError, ValueError)):
                    cold.receive(io.BytesIO(damaged), root / ('damaged-' + str(number)))
                self.assertFalse((root / ('damaged-' + str(number)) / 'verified.json').exists())

    def test_production_provenance_is_separate_from_historical_copy(self):
        # Synthetic parser metadata is not evidence of an actual held production runtime.
        binding = {'cluster_uid': cold.common.CLUSTER_UID, 'namespace': 'gitea',
                   'pod': 'gitea-postgresql-0', 'pod_uid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                   'controller_uid': '80aac4a0-46ec-4564-84db-d99c440780e9', 'node': 'totodile',
                   'container_id': 'a' * 64, 'image': cold.control.IMAGE,
                   'claim': 'data-gitea-postgresql-0', 'claim_uid': '4d6d356d-ec5d-4f2e-961e-090eae9e0c21',
                   'pv': 'pvc-4d6d356d-ec5d-4f2e-961e-090eae9e0c21',
                   'pv_uid': '5cadac3d-dd99-4e3e-8551-4d165826cf44', 'revision': 'b' * 40,
                   'hba_sha256': '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05',
                   'volume': {'source': '', 'device': 1, 'inode': 2},
                   'guard': {'namespace_pid': 3, 'host_pid': 4, 'start_ticks': 5,
                             'lock_device': 6, 'lock_inode': 7}}
        binding['volume']['source'] = ('/var/lib/kubelet/pods/' + binding['pod_uid'] +
                                      '/volumes/kubernetes.io~csi/' + binding['pv'] + '/mount')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value, checksum = cold.capture(fixture(root), root / 'point', STATE, source_binding=binding)
            self.assertEqual(value['format'], cold.GUARDED_FORMAT)
            self.assertNotIn('original_manifest_sha256', value)
            self.assertEqual(cold.verify(root / 'point', checksum), value)
            for field in ('namespace', 'claim_uid', 'pv_uid', 'image', 'controller_uid'):
                altered = copy.deepcopy(value)
                altered['source'][field] = 'foreign'
                with self.subTest(field=field), self.assertRaises(RuntimeError):
                    cold.validate(altered)
            altered = copy.deepcopy(value)
            altered['source']['guard']['host_pid'] = True
            with self.assertRaises(RuntimeError):
                cold.validate(altered)


if __name__ == '__main__':
    unittest.main()
