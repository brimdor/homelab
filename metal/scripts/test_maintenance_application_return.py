"""Replicated application return must preserve ownership and every replica."""

import copy
import hashlib
import unittest

from maintenance_application_return import expected_http_status, returned_pod


class ApplicationReturnTests(unittest.TestCase):
    def test_woodpecker_health_is_204_without_weakening_other_endpoints(self):
        self.assertEqual(expected_http_status('woodpecker', '/healthz'), 204)
        self.assertEqual(expected_http_status('woodpecker', '/'), 200)
        self.assertEqual(expected_http_status('argocd', '/healthz'), 200)

    def setUp(self):
        self.after = '2026-10-30T06:14:22+00:00'
        self.reference = {'name': 'original', 'uid': 'original-uid', 'claims': [],
            'containers': [{'name': 'app', 'image': 'pinned:1'}],
            'owners': [{'kind': 'ReplicaSet', 'uid': 'rs', 'controller': True}],
            'deployment': {'uid': 'deployment', 'generation': 24,
                'template_sha256': hashlib.sha256(b'{}').hexdigest()}}
        self.deployment = {'metadata': {'uid': 'deployment', 'generation': 24},
            'spec': {'replicas': 2, 'template': {}},
            'status': {'observedGeneration': 24, 'replicas': 2, 'readyReplicas': 2,
                'availableReplicas': 2, 'updatedReplicas': 2}}
        self.rs = {'metadata': {'uid': 'rs', 'ownerReferences': [
            {'uid': 'deployment', 'controller': True}]}, 'spec': {'replicas': 2}}
        self.pods = [self.pod('survivor', '2026-10-29T20:03:48Z'),
                     self.pod('replacement', '2026-10-30T06:52:21Z')]

    def pod(self, uid, created):
        return {'metadata': {'uid': uid, 'creationTimestamp': created,
            'ownerReferences': [{'uid': 'rs', 'controller': True}]},
            'spec': {'containers': copy.deepcopy(self.reference['containers'])},
            'status': {'phase': 'Running', 'containerStatuses': [{'ready': True}]}}

    def accept(self):
        return returned_pod(self.reference, self.pods, self.deployment, self.rs, self.after)

    def test_two_healthy_original_controller_replicas_identify_replacement(self):
        self.assertEqual(self.accept()['metadata']['uid'], 'replacement')

    def test_single_replica_remains_supported(self):
        self.pods.pop(0)
        self.deployment['spec']['replicas'] = self.rs['spec']['replicas'] = 1
        for key in ('replicas', 'readyReplicas', 'availableReplicas', 'updatedReplicas'):
            self.deployment['status'][key] = 1
        self.assertEqual(self.accept()['metadata']['uid'], 'replacement')

    def test_missing_unready_changed_or_ambiguous_replica_refuses(self):
        for change in ('missing', 'unready', 'image', 'claim', 'old', 'ambiguous',
                       'deployment', 'template', 'rs_owner', 'desired', 'rollout'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'missing': self.pods.pop(0)
                if change == 'unready': self.pods[0]['status']['containerStatuses'][0]['ready'] = False
                if change == 'image': self.pods[0]['spec']['containers'][0]['image'] = 'changed'
                if change == 'claim': self.pods[0]['spec']['volumes'] = [{'persistentVolumeClaim': {'claimName': 'changed'}}]
                if change == 'old': self.pods[1]['metadata']['uid'] = 'original-uid'
                if change == 'ambiguous': self.pods[0]['metadata']['creationTimestamp'] = '2026-10-30T06:52:22Z'
                if change == 'deployment': self.deployment['metadata']['uid'] = 'changed'
                if change == 'template': self.deployment['spec']['template'] = {'changed': True}
                if change == 'rs_owner': self.rs['metadata']['ownerReferences'][0]['uid'] = 'changed'
                if change == 'desired': self.deployment['spec']['replicas'] = 3
                if change == 'rollout': self.deployment['status']['updatedReplicas'] = 1
                with self.assertRaises(AssertionError): self.accept()


if __name__ == '__main__':
    unittest.main()
