"""Reject changed bindings, lost exclusion and uncommitted snapshot streams."""

import copy
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import valkey_cohort_point as point


def binding(ordinal='0'):
    claim, pv = point.CLAIMS[ordinal]
    uid = 'aaaaaaaa-bbbb-cccc-dddd-' + ordinal.zfill(12)
    return {'ordinal': ordinal, 'cluster_uid': point.common.CLUSTER_UID, 'namespace': 'gitea',
            'pod': 'gitea-valkey-cluster-' + ordinal, 'pod_uid': uid,
            'controller_uid': point.recovery.OWNER, 'node': 'pikachu', 'container_id': ordinal * 64,
            'image': point.recovery.IMAGE, 'claim': 'valkey-data-gitea-valkey-cluster-' + ordinal,
            'claim_uid': claim, 'pv': 'pvc-' + claim, 'pv_uid': pv, 'revision': 'b' * 40,
            'volume': {'source': '/var/lib/kubelet/pods/' + uid + '/volumes/kubernetes.io~csi/pvc-' + claim + '/mount',
                       'device': 1, 'inode': 2}, 'process': {'host_pid': 3, 'start_ticks': 4}}


def core(ordinal='0'):
    value = binding(ordinal)
    return {k: value[k] for k in point.CORE_KEYS}


def stream(ordinal='0'):
    raw = b'REDIS0012\0\xff\r\nsynthetic-only'
    header = {'format': point.FORMAT, 'source': binding(ordinal),
              'file': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    encoded = point.common.canonical(header)
    return (encoded + b'\n' + raw +
            point.common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')


class CohortPointTests(unittest.TestCase):
    def test_distinct_provenance_requires_all_six_bindings_and_finite_exclusion(self):
        shards = {n: point.validate_header(point.common.read_frame(io.BytesIO(stream(n)))) for n in point.SLOTS}
        value = {'format': point.FORMAT, 'cluster_uid': point.common.CLUSTER_UID,
                 'owner_uid': point.recovery.OWNER, 'image': point.recovery.IMAGE,
                 'sources': {n: binding(n) for n in point.CLAIMS}, 'shards': shards,
                 'replicas': point.REPLICAS, 'slots': point.SLOTS, 'source_quiesced': True,
                 'cross_shard_atomic': False, 'topology_sha256': 'd' * 64,
                 'write_exclusion': {'lease_ms': point.LEASE_MS,
                    'elapsed_ms': 1234, 'all_six_probes_blocked': True}}
        self.assertEqual(point.validate(value), value)
        changes = (lambda v: v.update(source_quiesced=False), lambda v: v.update(cross_shard_atomic=True),
                   lambda v: v['write_exclusion'].update(elapsed_ms=point.LEASE_MS),
                   lambda v: v['write_exclusion'].update(elapsed_ms=True),
                   lambda v: v['write_exclusion'].update(all_six_probes_blocked=1),
                   lambda v: v['replicas'].update({'1': '0'}), lambda v: v['sources'].pop('4'),
                   lambda v: v['sources']['1'].update(revision='c' * 40),
                   lambda v: v['sources']['3']['process'].update(host_pid=True),
                   lambda v: v['shards']['3']['source'].update(pod_uid='foreign'))
        for change in changes:
            altered = copy.deepcopy(value)
            change(altered)
            with self.assertRaises(RuntimeError):
                point.validate(altered)
        with self.assertRaises(RuntimeError):
            point.recovery.require_manifest(value)

    def test_native_binding_refused_before_host_contact(self):
        with patch.object(point.common, 'require_host') as host:
            for field in ('namespace', 'image', 'controller_uid', 'claim_uid', 'pv_uid'):
                altered = core()
                altered[field] = 'foreign'
                with self.assertRaises(RuntimeError):
                    point.observe(altered)
            host.assert_not_called()

    def test_stream_roundtrip_tamper_truncation_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(point.common, 'ROOT', Path(temporary)), \
                patch.object(point.common, 'require_host'), patch.object(point.common, 'private_root'):
            value = point.receive('roundtrip-103', core(), io.BytesIO(stream()))
            root = point.point_path('roundtrip-103')
            received = root / 'shard-0.rdb'
            self.assertEqual({'bytes': received.stat().st_size,
                              'sha256': hashlib.sha256(received.read_bytes()).hexdigest()}, value['file'])
            self.assertEqual(received.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                point.receive('roundtrip-103', core(), io.BytesIO(stream()))
            for number, damaged in enumerate((stream()[:-1], stream() + b'foreign',
                                              stream().replace(b'\0\xff\r\n', b'BAD!'))):
                run_id = 'rejected-' + str(number)
                with self.assertRaises((RuntimeError, ValueError)):
                    point.receive(run_id, core(), io.BytesIO(damaged))
                self.assertFalse((point.point_path(run_id) / 'source-0.json').exists())
                self.assertFalse((point.point_path(run_id) / 'verified.json').exists())

    @unittest.skipUnless(os.geteuid() == 0 and hasattr(os, 'chown'), 'native Linux root metadata fixture')
    def test_native_rdb_link_permissions_and_changed_file_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'dump.rdb'
            path.write_bytes(b'REDIS0012synthetic-only')
            os.chown(path, 1001, 1001)
            path.chmod(0o644)
            record, _identity = point.source_file(path)
            self.assertEqual(record['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            link = path.with_name('link')
            os.link(path, link)
            with self.assertRaises(RuntimeError):
                point.source_file(path)
            link.unlink()
            path.chmod(0o666)
            with self.assertRaises(RuntimeError):
                point.source_file(path)

    @unittest.skipUnless(os.geteuid() == 0, 'protected native Linux root point')
    def test_complete_native_point_verification_and_protected_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(point.common, 'ROOT', Path(temporary)), \
                patch.object(point.common, 'require_host'), patch.object(point.common, 'private_root'):
            run_id = 'wholepoint-103'
            shards = {n: point.receive(run_id, core(n), io.BytesIO(stream(n))) for n in point.SLOTS}
            value = {'format': point.FORMAT, 'cluster_uid': point.common.CLUSTER_UID,
                     'owner_uid': point.recovery.OWNER, 'image': point.recovery.IMAGE,
                     'sources': {n: binding(n) for n in point.CLAIMS}, 'shards': shards,
                     'replicas': point.REPLICAS, 'slots': point.SLOTS, 'source_quiesced': True,
                     'cross_shard_atomic': False, 'topology_sha256': 'd' * 64,
                     'write_exclusion': {'lease_ms': point.LEASE_MS, 'elapsed_ms': 1234,
                                         'all_six_probes_blocked': True}}
            result = point.finalize(run_id, value)
            root, verified = point.verify(run_id, result['manifest_sha256'])
            self.assertEqual(verified, value)
            with self.assertRaises(FileExistsError):
                point.finalize(run_id, value)
            (root / 'shard-3.rdb').write_bytes(b'changed-protected-copy')
            with self.assertRaises(RuntimeError):
                point.verify(run_id, result['manifest_sha256'])


if __name__ == '__main__':
    unittest.main()
