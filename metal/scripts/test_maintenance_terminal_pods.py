"""Reject active, changed or unowned Pods from terminal eviction cleanup."""

import copy
import unittest
from unittest.mock import patch

import maintenance_terminal_pods as cleanup


class TerminalCleanupTests(unittest.TestCase):
    def setUp(self):
        self.reference = {'name': 'old-pod', 'uid': 'old-uid'}
        self.owner = {'name': 'replicaset', 'uid': 'owner-uid'}
        self.pod = {'metadata': {'name': 'old-pod', 'uid': 'old-uid', 'resourceVersion': '123',
                                'ownerReferences': [dict(self.owner, kind='ReplicaSet', controller=True)]},
                    'spec': {'nodeName': 'pikachu'}, 'status': {'phase': 'Failed', 'reason': 'Evicted',
                    'containerStatuses': [{'state': {'terminated': {'exitCode': 137}}}]}}

    def test_terminal_boundary_rejects_changed_or_active_objects(self):
        self.assertTrue(cleanup.terminal(self.pod, 'pikachu', self.reference, self.owner))
        mutations = [
            lambda p: p['metadata'].update(uid='replacement-uid'),
            lambda p: p['metadata'].update(deletionTimestamp='now'),
            lambda p: p['metadata']['ownerReferences'][0].update(uid='foreign'),
            lambda p: p['metadata']['ownerReferences'][0].update(controller=False),
            lambda p: p['spec'].update(nodeName='cyndaquil'),
            lambda p: p['status'].update(phase='Running'),
            lambda p: p['status'].update(reason='Error'),
            lambda p: p['status']['containerStatuses'][0].update(state={'running': {}}),
        ]
        for index, mutate in enumerate(mutations):
            pod = copy.deepcopy(self.pod)
            mutate(pod)
            with self.subTest(index=index):
                self.assertFalse(cleanup.terminal(pod, 'pikachu', self.reference, self.owner))

    def test_delete_has_both_identity_preconditions_and_cannot_replay_absence(self):
        api = unittest.mock.Mock()
        with patch.object(cleanup, 'inspect', return_value=({'old-uid': ('example', self.pod)}, [])):
            cleanup.remove(api, {}, 'old-uid')
        import json
        args, kwargs = api.call.call_args
        self.assertEqual(args, ('delete', '--raw', '/api/v1/namespaces/example/pods/old-pod', '-f', '-'))
        self.assertEqual(json.loads(kwargs['data']), {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                         'preconditions': {'uid': 'old-uid', 'resourceVersion': '123'}})
        with patch.object(cleanup, 'inspect', return_value=({}, ['old-uid'])):
            with self.assertRaisesRegex(RuntimeError, 'do not replay'):
                cleanup.remove(api, {}, 'old-uid')
        self.assertEqual(api.call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
