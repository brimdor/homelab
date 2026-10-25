"""Guard the isolated real-API driver's trust, response-loss and refusal boundaries."""

import gzip
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import maintenance_drain_qualification as qualification


class DrainQualificationTests(unittest.TestCase):
    def test_workloads_have_no_host_or_storage_channel_and_preserve_normal_pdbs(self):
        for minimum in (2, 3):
            objects = qualification.fixtures(minimum)
            pdb = next(o for o in objects if o['kind'] == 'PodDisruptionBudget')
            self.assertEqual(pdb['spec']['minAvailable'], minimum)
            self.assertNotIn('unhealthyPodEvictionPolicy', pdb['spec'])
            for obj in objects:
                if obj['kind'] not in ('DaemonSet', 'Deployment'):continue
                spec = obj['spec']['template']['spec']
                for field in ('hostNetwork', 'hostPID', 'hostIPC', 'volumes', 'nodeName'):
                    self.assertNotIn(field, spec)
                self.assertTrue(spec['securityContext']['runAsNonRoot'])
                for container in spec['containers']:
                    self.assertIn('@sha256:', container['image'])
                    self.assertNotIn('volumeMounts', container)
                    self.assertEqual(container['securityContext']['capabilities'], {'drop': ['ALL']})
                    self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
            workload = next(o for o in objects if o['kind'] == 'Deployment')
            self.assertEqual(workload['spec']['replicas'], 3)
            affinity = workload['spec']['template']['spec']['affinity']['podAntiAffinity']
            self.assertNotIn('requiredDuringSchedulingIgnoredDuringExecution', affinity)

    def test_lost_response_occurs_only_after_actual_post_return_and_is_not_retried(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"kind":"Status","status":"Success"}'))
        api = qualification.API(fixture);api.lose_response = True
        with self.assertRaisesRegex(RuntimeError, 'after actual eviction'):
            api.call('create', '--raw=/exact-eviction', '-f', '-', data=b'{}')
        self.assertEqual(fixture.kubectl.call_count, 1)
        self.assertEqual(api.posts, [{'argv': ['create', '--raw=/exact-eviction', '-f', '-'], 'body': {}}])
        fixture.identity.assert_called_once_with()
        self.assertFalse(api.lose_response)

    def test_read_does_not_mutate_and_preserves_explicit_context_adapter(self):
        fixture = SimpleNamespace(identity=Mock(), kubectl=Mock(return_value=b'{"items":[]}'))
        api = qualification.API(fixture)
        self.assertEqual(api.call('get', 'pods', '-A', '-o', 'json'), {'items': []})
        fixture.kubectl.assert_called_once_with('get', 'pods', '-A', '-o', 'json', data=None, json_output=False)
        fixture.identity.assert_not_called();self.assertFalse(api.posts)

    def test_only_actual_pdb_error_classifies_refusal_and_all_errors_still_raise(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for error, expected in ((b'Error from server (TooManyRequests): Cannot evict pod as it would violate the pod disruption budget.\n', True),
                                    (b'Error from server (Forbidden): access denied\n', False),
                                    (b'certificate verification failed\n', False),
                                    (b'Error from server (TooManyRequests): rate limit\n', False)):
                (root / '1.log.gz').write_bytes(gzip.compress(error))
                fixture = SimpleNamespace(identity=Mock(), work=root, count=1,
                                          kubectl=Mock(side_effect=RuntimeError('native refusal')))
                api = qualification.API(fixture)
                with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, 'native refusal'):
                    api.call('create', '--raw=/exact', '-f', '-', data=b'{}')
                self.assertEqual(api.rejection is not None, expected)
                self.assertEqual(fixture.kubectl.call_count, 1)


if __name__ == '__main__':
    unittest.main()
