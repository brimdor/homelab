#!/usr/bin/env python3
"""Refuse changed native CSI sources, backend identities and stale auth evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ceph_csi_native_contract as contract
import ceph_csi_native_runtime as runtime
import ceph_runtime_qualification as ceph


MAINTENANCE = Path(__file__).resolve().parents[1] / 'maintenance'


class NativeCsiRefusals(unittest.TestCase):
    def test_bound_static_volume_accepts_only_empty_pv_class_and_explicit_empty_claim_class(self):
        cluster = 'd370fba8-2ebc-4193-ab28-5c6ae368648d'
        for kind in ('rbd', 'cephfs'):
            pv, pvc = contract.static_binding(kind, cluster)
            pv['metadata']['uid'], pvc['metadata']['uid'] = 'pv-uid', 'pvc-uid'
            pv['status'], pvc['status'] = {'phase': 'Bound'}, {'phase': 'Bound'}
            pv['spec']['claimRef']['uid'] = 'pvc-uid'
            for omitted in (False, True):
                volume = copy.deepcopy(pv)
                if omitted:
                    volume['spec'].pop('storageClassName')
                with patch.object(runtime, 'get', side_effect=[volume, pvc]):
                    accepted = runtime.binding(kind, cluster)
                self.assertEqual(accepted['spec']['storageClassName'], '')
                self.assertEqual((accepted['pv_uid'], accepted['pvc_uid']), ('pv-uid', 'pvc-uid'))
            for target, key, value in (
                    ('pv', 'storageClassName', 'foreign'), ('pv', 'storageClassName', None),
                    ('pv', 'persistentVolumeReclaimPolicy', 'Delete'), ('pv', 'capacity', {'storage': '1Gi'}),
                    ('pv', 'accessModes', ['ReadOnlyMany']), ('pv', 'mountOptions', ['ms_mode=crc']),
                    ('pv', 'claimRef', {'name': kind, 'namespace': contract.CLIENT, 'uid': 'foreign'}),
                    ('pvc', 'storageClassName', 'foreign'), ('pvc', 'storageClassName', None),
                    ('pvc', 'volumeName', 'foreign')):
                volume, claim = copy.deepcopy(pv), copy.deepcopy(pvc)
                (volume if target == 'pv' else claim)['spec'][key] = value
                with self.subTest(kind=kind, target=target, key=key, value=value):
                    with patch.object(runtime, 'get', side_effect=[volume, claim]):
                        with self.assertRaises(AssertionError):
                            runtime.binding(kind, cluster)
            claim = copy.deepcopy(pvc)
            claim['spec'].pop('storageClassName')
            with patch.object(runtime, 'get', side_effect=[pv, claim]):
                with self.assertRaises(KeyError):
                    runtime.binding(kind, cluster)

    def test_native_import_finishes_unpack_and_requires_exact_cri_digest(self):
        records = json.loads((MAINTENANCE / 'ceph-csi-native-images.json').read_bytes())
        calls = []

        def native(*args):
            calls.append(args)
            if args[1:3] == ('crictl', 'inspecti'):
                return json.dumps({'status': {'repoDigests': [args[-1]]}}).encode()
            self.assertEqual(args[1:4], ('ctr', 'images', 'import'))
            self.assertNotIn('--no-unpack', args)
            self.assertEqual(args[args.index('--snapshotter') + 1], 'overlayfs')
            return b''

        with patch.object(runtime, 'native', side_effect=native):
            imported = runtime.import_images(records, Path('/owned/images'))
        self.assertEqual(len(imported), len(records))
        self.assertEqual(len(calls), len(records) * 2)
        self.assertTrue(all(row['elapsed_seconds'] >= 0 for row in imported))
        with patch.object(runtime, 'native', side_effect=[b'', b'{"status":{"repoDigests":["foreign"]}}']):
            with self.assertRaises(AssertionError):
                runtime.import_images(records, Path('/owned/images'))

    def test_exact_upstream_and_static_actor_contract(self):
        bundle = json.loads((MAINTENANCE / 'ceph-csi-native-bundle.json').read_bytes())
        records = json.loads((MAINTENANCE / 'ceph-csi-native-images.json').read_bytes())
        objects = contract.reviewed_objects(bundle, records)
        controllers = [obj for obj in objects if obj['kind'] == 'Deployment']
        self.assertEqual(len(controllers), 2)
        for obj in controllers:
            self.assertEqual(obj['spec']['replicas'], 1)
            containers = obj['spec']['template']['spec']['containers']
            self.assertEqual(len(containers), 2)
            self.assertIn('csi-attacher', [row['name'] for row in containers])
            self.assertTrue(all(row['imagePullPolicy'] == 'Never' and '@sha256:' in row['image'] for row in containers))
        for obj in [obj for obj in objects if obj['kind'] == 'CSIDriver']:
            self.assertEqual(obj['spec'], {'attachRequired': True, 'podInfoOnMount': True,
                                          'seLinuxMount': True, 'fsGroupPolicy': 'File'})
        changed = copy.deepcopy(bundle)
        first = next(iter(changed['sources'].values()))['objects'][0]
        first['metadata']['namespace'] = 'production'
        with self.assertRaisesRegex(RuntimeError, 'bundle changed'):
            contract.reviewed_objects(changed, records)
        for image in ('registry.example/foreign:v1', records[0]['image'] + ':foreign'):
            changed_records = copy.deepcopy(records)
            changed_records[0]['image'] = image
            with self.assertRaisesRegex(RuntimeError, 'image inventory changed'):
                contract.reviewed_objects(bundle, changed_records)

    def test_retained_static_backend_names_and_foreign_identity_refusals(self):
        cluster = 'd370fba8-2ebc-4193-ab28-5c6ae368648d'
        for kind in ('rbd', 'cephfs'):
            pv, pvc = contract.static_binding(kind, cluster)
            self.assertEqual(pv['spec']['persistentVolumeReclaimPolicy'], 'Retain')
            self.assertEqual(pv['spec']['csi']['volumeAttributes']['clusterID'], cluster)
            self.assertEqual(pv['spec']['csi']['volumeAttributes']['staticVolume'], 'true')
            if kind == 'rbd':
                self.assertEqual(pv['spec']['csi']['volumeAttributes']['mapOptions'], 'krbd:ms_mode=secure')
            else:
                self.assertEqual(pv['spec']['mountOptions'], ['ms_mode=secure'])
            self.assertEqual(pv['metadata']['name'], pvc['spec']['volumeName'])
            self.assertEqual(pv['spec']['claimRef'], pvc['metadata'])
        for kind, value in (('foreign', cluster), ('rbd', None), ('rbd', 'x' * 36),
                            ('cephfs', '-' * 36), ('cephfs', cluster.upper()), ('rbd', '../production')):
            with self.subTest(kind=kind, value=value), self.assertRaisesRegex(RuntimeError, 'backend identity'):
                contract.static_binding(kind, value)

    def test_monitor_endpoint_preserves_loopback_and_refuses_production_or_external(self):
        fixture = object.__new__(ceph.Runtime)
        self.assertEqual(fixture.monitor_endpoint(), '[v2:127.0.0.1:13300,v1:127.0.0.1:13301]')
        fixture.public_address = '203.0.113.254'
        self.assertEqual(fixture.monitor_endpoint(), '[v2:203.0.113.254:13300,v1:203.0.113.254:13301]')
        for address in ('10.0.20.50', '10.0.40.3', '1.1.1.1', '0.0.0.0', 'localhost', '203.0.113.253'):
            fixture.public_address = address
            with self.subTest(address=address), self.assertRaisesRegex(RuntimeError, 'foreign synthetic'):
                fixture.monitor_endpoint()

    def test_authentication_evidence_binds_fresh_regular_log_and_exact_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = object.__new__(runtime.Runtime)
            fixture.root = Path(temporary)
            log = fixture.root / 'mon.log'
            old = b'cephx server client.csi-rbd: unexpected key: PRIVATE_SENTINEL\n'
            log.write_bytes(old)
            before = fixture.auth_position()
            self.assertEqual(fixture.fresh_refusals(before, 'rbd'), 0)
            with log.open('ab') as output:
                output.write(b'cephx server client.foreign: unexpected key: PRIVATE_SENTINEL\n')
                output.write(b'cephx server client.csi-cephfs: unexpected key: PRIVATE_SENTINEL\n')
            self.assertEqual(fixture.fresh_refusals(before, 'rbd'), 0)
            self.assertEqual(fixture.fresh_refusals(before, 'cephfs'), 1)
            log.rename(fixture.root / 'original')
            log.write_bytes(old * 4)
            with self.assertRaises(AssertionError):
                fixture.fresh_refusals(before, 'rbd')
            log.unlink()
            (fixture.root / 'original').rename(log)
            log.write_bytes(b'')
            with self.assertRaises(AssertionError):
                fixture.fresh_refusals(before, 'rbd')
            log.unlink()
            log.symlink_to(fixture.root / 'original')
            with self.assertRaises(OSError):
                fixture.fresh_refusals(before, 'rbd')


if __name__ == '__main__':
    unittest.main()
