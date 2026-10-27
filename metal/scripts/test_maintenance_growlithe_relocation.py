"""Refuse changed identities and incomplete original-image recovery."""

import copy
import unittest
from unittest.mock import patch

import maintenance_growlithe_relocation as relocation


class API:
    def __init__(self):
        template = {'metadata': {}, 'spec': {'fixture': 'synthetic'}}
        self.application = {'metadata': {'uid': relocation.APPLICATION}, 'status': {
            'sync': {'status': 'Synced'}, 'health': {'status': 'Healthy'},
            'operationState': {'phase': 'Succeeded'}}}
        self.deployment = {'metadata': {'uid': relocation.DEPLOYMENT, 'generation': 132},
                           'spec': {'replicas': 1, 'template': template},
                           'status': {'observedGeneration': 132, 'readyReplicas': 1, 'updatedReplicas': 1}}
        self.replicas = {}
        for name, uid, replicas in ((relocation.REF['controller']['name'], relocation.REF['controller']['uid'], 0),
                                   ('versa-canary-5c57fb798b', relocation.REPLICA, 1)):
            self.replicas[name] = {'metadata': {'uid': uid, 'ownerReferences': [
                {'controller': True, 'kind': 'Deployment', 'uid': relocation.DEPLOYMENT}]},
                'spec': {'replicas': replicas}}
        state = {'name': 'migrate', 'restartCount': 0, 'imageID': 'original@' + relocation.DIGEST,
                 'state': {'terminated': {'exitCode': 0}}}
        self.pod = {'metadata': {'uid': relocation.POD, 'name': 'synthetic', 'ownerReferences': [
            {'controller': True, 'kind': 'ReplicaSet', 'uid': relocation.REPLICA}]},
            'spec': {'nodeName': 'charmander'}, 'status': {'phase': 'Running',
            'initContainerStatuses': [state], 'containerStatuses': [
                dict(state, name=name, ready=True, state={'running': {}}) for name in ('web', 'worker')]}}
        self.warnings = []
        self.health = {'/healthz': 200, '/readyz': 200}

    def call(self, *args):
        if args[:2] == ('get', 'application'):value = self.application
        elif args[:2] == ('get', 'deployment'):value = self.deployment
        elif args[:2] == ('get', 'replicaset'):value = self.replicas[args[2]]
        elif args[:2] == ('get', 'pods'):value = {'items': [self.pod]}
        elif args[:2] == ('get', 'events'):value = {'items': self.warnings}
        elif args[0] == 'exec':value = self.health
        else:raise AssertionError('unexpected synthetic API call')
        return copy.deepcopy(value)


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        template = relocation.hashed(self.api.deployment['spec']['template'])
        self.guard = patch.object(relocation, 'TEMPLATE_SHA256', template)
        self.guard.start();self.addCleanup(self.guard.stop)

    def test_exact_original_recovery_returns_stable_observation(self):
        proof = relocation.observe(self.api, relocation.REF)
        self.assertEqual(proof, relocation.observe(self.api, relocation.REF))
        self.assertEqual(proof['replacement_uid'], relocation.POD)
        self.assertEqual(proof['configuration_commit'], relocation.CONFIGURATION)

    def test_unreviewed_old_target_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'unreviewed relocated'):
            relocation.observe(self.api, dict(relocation.REF, uid='foreign'))

    def test_changed_controller_template_old_replica_and_replacement_refused(self):
        for target, key, value in ((self.api.application['metadata'], 'uid', 'foreign'),
                                   (self.api.deployment['metadata'], 'generation', 133),
                                   (self.api.deployment['spec']['template']['spec'], 'fixture', 'changed'),
                                   (self.api.replicas[relocation.REF['controller']['name']]['spec'], 'replicas', 1),
                                   (self.api.pod['metadata'], 'uid', 'foreign'),
                                   (self.api.pod['spec'], 'nodeName', 'growlithe')):
            before = copy.deepcopy(target)
            target[key] = value
            with self.assertRaises(RuntimeError):relocation.observe(self.api, relocation.REF)
            target.clear();target.update(before)

    def test_failed_migration_wrong_image_warning_and_failed_behavior_refused(self):
        cases = [(self.api.pod['status']['initContainerStatuses'][0]['state']['terminated'], 'exitCode', 1),
                 (self.api.pod['status']['containerStatuses'][0], 'imageID', 'foreign'),
                 (self.api.pod['status']['containerStatuses'][0], 'restartCount', 1),
                 (self.api.pod['status']['containerStatuses'][0], 'ready', False),
                 (self.api.health, '/readyz', 503)]
        for target, key, value in cases:
            before = copy.deepcopy(target);target[key] = value
            with self.assertRaises(RuntimeError):relocation.observe(self.api, relocation.REF)
            target.clear();target.update(before)
        self.api.warnings.append({'reason': 'fixture-warning'})
        with self.assertRaisesRegex(RuntimeError, 'warning events'):
            relocation.observe(self.api, relocation.REF)


if __name__ == '__main__':
    unittest.main()
