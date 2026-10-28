import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import maintenance_sprigatito_shutdown as shutdown


class ShutdownTests(unittest.TestCase):
    def test_native_hold_compiles_and_requires_fresh_exact_global_owner(self):
        from types import SimpleNamespace
        owner = {'owner': 'homelab-maintenance-103-00000000-0000-0000-0000-000000000000', 'revision': '0' * 40}
        args = SimpleNamespace(identity='/key', known_hosts='/hosts')
        for acquire in (True, False):
            child = MagicMock()
            child.stdin = io.StringIO()
            child.stdout = iter([json.dumps({'rpc': 'verify_owner', 'token': owner['owner']}), json.dumps({'result': owner})])
            child.returncode = 0
            child.poll.return_value = 0
            api = MagicMock()
            api.call.return_value = {'items': [{'metadata': {'name': 'sprigatito', 'uid': shutdown.recovery.UID}}]}
            with patch.object(shutdown.subprocess, 'Popen', return_value=child), patch.object(shutdown, 'Ownership') as controller:
                controller.return_value.resume.return_value = owner
                self.assertEqual(shutdown.actor_hold(args, api, owner, acquire=acquire), owner)
                controller.return_value.resume.assert_called_once_with(owner['owner'])
            lines = child.stdin.getvalue().splitlines()
            compile(json.loads(lines[0])['program'], '<native-hold>', 'exec')
            self.assertEqual(json.loads(lines[1]), {'verified': True})

    def test_completed_job_needs_matching_uid_and_successful_containers(self):
        pod = {'metadata': {'name': 'completed', 'namespace': 'test', 'uid': 'pod',
                            'ownerReferences': [{'kind': 'Job', 'name': 'completed', 'uid': 'job', 'controller': True}]},
               'spec': {'restartPolicy': 'Never', 'containers': [{'name': 'main'}]},
               'status': {'phase': 'Succeeded', 'containerStatuses': [
                   {'name': 'main', 'ready': False, 'state': {'terminated': {'exitCode': 0}}}]}}
        job = {'kind': 'Job', 'metadata': {'name': 'completed', 'namespace': 'test', 'uid': 'job'},
               'spec': {}, 'status': {'succeeded': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}}
        class API:
            def call(self, *argv):
                return {'items': []} if argv[1] == 'daemonsets' else {'items': [pod]} if argv[1] == 'pods' else job
        self.assertEqual(len(shutdown.inventory(API())['kept']), 1)
        original = copy.deepcopy(pod)
        for change in ('owner', 'exit'):
            pod.clear();pod.update(copy.deepcopy(original))
            if change == 'owner':
                pod['metadata']['ownerReferences'][0]['uid'] = 'foreign'
            else:
                pod['status']['containerStatuses'][0]['state']['terminated']['exitCode'] = 1
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                shutdown.inventory(API())

    def test_native_shutdown_is_exact_graceful_and_observation_does_not_dispatch(self):
        owner = {'owner': 'homelab-maintenance-103-00000000-0000-0000-0000-000000000000'}
        inspect = shutdown.shutdown_native(owner)
        dispatch = shutdown.shutdown_native(owner, dispatch=True)
        compile(inspect, '<native-observation>', 'exec')
        compile(dispatch, '<native-dispatch>', 'exec')
        self.assertNotIn("subprocess.run(['systemd-run'", inspect)
        self.assertIn("'/usr/bin/systemctl','poweroff'", dispatch)
        self.assertIn('DI0403Y002080', dispatch)
        for forbidden in ('osd out', 'osd in', 'zap', 'mkfs', 'dnf -', 'setenforce'):
            self.assertNotIn(forbidden, dispatch)
