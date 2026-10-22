"""Refuse foreign resources and native access denial before synthetic writes."""

import copy
import subprocess
import unittest
from unittest.mock import patch

import valkey_pvc_qualification as fixture


class QualificationTests(unittest.TestCase):
    def test_parent_profile_mismatch_refuses_acceptance(self):
        instance = fixture.Qualification(['kubectl'])
        with patch.object(instance, 'cli', return_value=b'appendonly\nno'), \
                self.assertRaisesRegex(RuntimeError, 'parent configuration differs'):
            instance.verify_profile()

    def test_new_image_with_any_namespace_consumer_is_preserved(self):
        instance=fixture.Qualification(['kubectl'])
        image={'id':'new-fixture-image','repoDigests':[fixture.protocol.recovery.CANDIDATE]}
        replies=[b'pikachu\n',fixture.json.dumps({'images':[image]}).encode(),b'{"containers":[]}']
        foreign={'spec':{'nodeName':'pikachu','containers':[{'image':fixture.protocol.recovery.CANDIDATE}]}}
        calls=[subprocess.CompletedProcess([],0,b'',b''),subprocess.CompletedProcess([],0,
            fixture.json.dumps({'items':[foreign]}).encode(),b'')]
        with patch.object(instance,'call',side_effect=calls) as api, \
                patch.object(fixture.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,v,b'') for v in replies]) as remote, \
                self.assertRaisesRegex(RuntimeError,'another active consumer'):
            instance.cleanup_images('pikachu','10.0.20.14',set())
        self.assertIn('--all-namespaces',api.call_args.args)
        self.assertFalse(any(' rmi ' in call.args[0][-1] for call in remote.call_args_list))

    def test_image_cleanup_requires_disposed_namespace_before_ssh(self):
        instance = fixture.Qualification(['kubectl'])
        with patch.object(instance, 'call', return_value=subprocess.CompletedProcess([], 0, b'{"kind":"Namespace"}', b'')), \
                patch.object(fixture.subprocess, 'run') as remote, self.assertRaises(RuntimeError):
            instance.cleanup_images('pikachu', '10.0.20.14', set())
        remote.assert_not_called()

    def test_preexisting_image_never_removed(self):
        instance = fixture.Qualification(['kubectl'])
        image = {'id':'preexisting', 'repoDigests':[fixture.protocol.recovery.CANDIDATE]}
        replies = [b'pikachu\n', fixture.json.dumps({'images':[image]}).encode(), b'{"containers":[]}',
                   fixture.json.dumps({'images':[image]}).encode()]
        with patch.object(instance, 'call', return_value=subprocess.CompletedProcess([], 0, b'', b'')), \
                patch.object(instance, 'get', return_value={'items':[]}), \
                patch.object(fixture.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, value, b'') for value in replies]) as remote:
            result = instance.cleanup_images('pikachu', '10.0.20.14', {'preexisting'})
        self.assertEqual(result['new_images_removed'], 0)
        self.assertFalse(any(' rmi ' in call.args[0][-1] for call in remote.call_args_list))

    def test_denial_never_becomes_a_retryable_transition(self):
        instance = fixture.Qualification(['kubectl'])
        for text in (b'Forbidden', b'Unauthorized', b'permission denied'):
            with self.subTest(text=text), patch.object(fixture.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 1, b'', text)), self.assertRaises(RuntimeError):
                instance.call('exec', check=False)

    def test_foreign_cluster_refused_before_any_synthetic_command(self):
        instance = fixture.Qualification(['kubectl'])
        with patch.object(instance, 'get', return_value={'metadata': {'uid': 'foreign'}}), \
                patch.object(instance, 'cli') as cli, self.assertRaises(RuntimeError):
            instance.bootstrap()
        cli.assert_not_called()

    def test_unrelated_pod_or_credential_volume_refused(self):
        instance = fixture.Qualification(['kubectl'])
        instance.controller_uid = 'fixture-controller'
        pod = {'metadata': {'name': fixture.NAME + '-0', 'uid': 'synthetic',
                'labels': {fixture.LABEL: fixture.PURPOSE},
                'ownerReferences': [{'kind': 'StatefulSet', 'uid': 'fixture-controller', 'controller': True}]},
            'spec': {'automountServiceAccountToken': False, 'nodeName': 'pikachu',
                'securityContext': {'runAsUser': 1001, 'runAsGroup': 1001, 'fsGroup': 1001,
                    'runAsNonRoot': True, 'seccompProfile': {'type': 'RuntimeDefault'}},
                'containers': [{'name': 'valkey', 'image': fixture.protocol.recovery.IMAGE,
                    'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                        'capabilities': {'drop': ['ALL']}}}],
                'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data-' + fixture.NAME + '-0'}}]}}
        with patch.object(instance, 'get', return_value={'items': [pod]}):
            self.assertEqual(set(instance.pods()), {0})
        changes = (lambda p: p['metadata'].update(name='gitea-valkey-cluster-0'),
                   lambda p: p['spec']['volumes'].append({'name': 'credential', 'secret': {'secretName': 'foreign'}}),
                   lambda p: p['spec']['volumes'][0]['persistentVolumeClaim'].update(claimName='production'),
                   lambda p: p['spec']['containers'][0].update(image='unreviewed'),
                   lambda p: p['spec'].update(hostNetwork=True),
                   lambda p: p['spec']['securityContext'].update(runAsUser=0))
        for change in changes:
            altered = copy.deepcopy(pod)
            change(altered)
            with patch.object(instance, 'get', return_value={'items': [altered]}), self.assertRaises(RuntimeError):
                instance.pods()

    def test_acknowledged_values_recorded_only_after_exact_reply(self):
        instance = fixture.Qualification(['kubectl'])
        with patch.object(instance, 'cli', return_value=b''):
            self.assertFalse(instance.write_record(1))
        self.assertFalse(any(instance.records.values()))
        with patch.object(instance, 'cli', return_value=b'synthetic-six-pvc-1'):
            self.assertTrue(instance.write_record(1))
        self.assertEqual(sum(map(len, instance.records.values())), 1)
        with patch.object(instance, 'cli', return_value=b'synthetic-six-pvc-1'):
            self.assertTrue(instance.write_record(1))
        self.assertEqual(sum(map(len, instance.records.values())), 1)


if __name__ == '__main__':
    unittest.main()
