"""Exercise stream parsing, secret containment and refusal before transaction."""

import copy
import json
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gitea_postgres_recovery_controller as controller
from test_gitea_postgres_account_recovery import catalog


class ControllerTests(unittest.TestCase):
    def released_fixture(self):
        deployment = {'metadata': {'uid': controller.DEPLOYMENT_UID, 'generation': 7},
                      'status': {'observedGeneration': 7, 'replicas': 1, 'updatedReplicas': 1,
                                 'readyReplicas': 1, 'availableReplicas': 1,
                                 'conditions': [{'type': k, 'status': 'True'} for k in ('Available', 'Progressing')]}}
        pod = {'metadata': {'name': 'gitea-synthetic', 'uid': 'released-pod',
                            'ownerReferences': [{'controller': True, 'kind': 'ReplicaSet', 'name': 'replica', 'uid': 'replica-uid'}]},
               'spec': {'initContainers': [{'name': 'guard'}], 'containers': [{'name': 'gitea'}]},
               'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                          'initContainerStatuses': [{'name': 'guard', 'state': {'terminated': {'exitCode': 0}}}],
                          'containerStatuses': [{'name': 'gitea', 'ready': True, 'state': {'running': {'startedAt': 'synthetic'}}}]}}
        replica = {'metadata': {'uid': 'replica-uid', 'ownerReferences': [
            {'controller': True, 'uid': controller.DEPLOYMENT_UID}]}}
        return deployment, pod, replica

    def test_released_exact_pod_waits_through_stale_deadline(self):
        deployment, pod, replica = self.released_fixture()
        stale = copy.deepcopy(deployment)
        stale['status']['conditions'][1]['status'] = 'False'
        observations = [stale, deployment]
        instance = controller.Controller(['kubectl'], None)
        def get(kind, *_a, **_k):
            return observations.pop(0) if kind == 'deployment' else ({'items': [pod]} if kind == 'pods' else replica)
        with patch.object(instance, 'identity'), patch.object(instance, 'get', side_effect=get), \
                patch.object(controller.time, 'sleep') as sleep:
            instance.wait_application_ready({'pod': 'gitea-synthetic', 'uid': 'released-pod'})
        self.assertEqual(observations, [])
        sleep.assert_called_once_with(0.2)

    def test_release_never_accepts_incomplete_startup_or_stale_generation(self):
        for field in ('generation', 'main', 'init', 'conditions'):
            with self.subTest(field=field):
                deployment, pod, replica = self.released_fixture()
                if field == 'generation':
                    deployment['status']['observedGeneration'] = 6
                elif field == 'main':
                    pod['status']['containerStatuses'][0]['ready'] = False
                elif field == 'init':
                    pod['status']['initContainerStatuses'] = []
                else:
                    pod['status']['conditions'] = []
                instance = controller.Controller(['kubectl'], None)
                def get(kind, *_a, **_k):
                    return deployment if kind == 'deployment' else ({'items': [pod]} if kind == 'pods' else replica)
                with patch.object(instance, 'identity'), patch.object(instance, 'get', side_effect=get), \
                        self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                    instance.wait_application_ready(seconds=-1)

    def test_release_refuses_changed_identity_failed_init_and_api_denial(self):
        for field, error in (('uid', 'binding changed'), ('init', 'init failed'), ('api', 'access denied')):
            with self.subTest(field=field):
                deployment, pod, replica = self.released_fixture()
                if field == 'uid':
                    pod['metadata']['uid'] = 'foreign-pod'
                if field == 'init':
                    pod['status']['initContainerStatuses'][0]['state']['terminated']['exitCode'] = 1
                instance = controller.Controller(['kubectl'], None)
                def get(kind, *_a, **_k):
                    if field == 'api':
                        raise RuntimeError('access denied')
                    return deployment if kind == 'deployment' else ({'items': [pod]} if kind == 'pods' else replica)
                with patch.object(instance, 'identity'), patch.object(instance, 'get', side_effect=get), \
                        self.assertRaisesRegex(RuntimeError, error):
                    instance.wait_application_ready({'pod': 'gitea-synthetic', 'uid': 'released-pod'})

    def test_actual_child_catalog_stream_with_prompt_and_eof_failure(self):
        raw = b'backend> HOMELAB103:' + json.dumps(catalog()).encode().hex().encode() + b'\nbackend> '
        for payload, accepted in ((raw, True), (b'backend> no catalog\n', False)):
            child = subprocess.Popen([sys.executable, '-B', '-c', 'import sys;sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))', payload.hex()],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if accepted:
                    self.assertEqual(controller.Controller.read_catalog(child), catalog())
                else:
                    with self.assertRaises(RuntimeError):
                        controller.Controller.read_catalog(child)
            finally:
                child.communicate()
                child.stdout.close()
                child.stderr.close()

    def test_client_existing_password_only_on_attached_stdin(self):
        instance = controller.Controller(['kubectl'], None)
        instance.credentials = {'admin': "synthetic'$(never)", 'app': 'synthetic-app'}
        with patch.object(instance, 'execute', return_value=SimpleNamespace(stdout=b'accepted')) as execute:
            self.assertEqual(instance.client({}, 'postgres', 'psql', '-X'), b'accepted')
            self.assertNotIn('synthetic', str(execute.call_args.args))
            self.assertEqual(execute.call_args.kwargs['data'], b"synthetic'$(never)\n")

    def test_missing_prefetched_baseline_never_contacts_cluster(self):
        instance = controller.Controller(['kubectl'], None)
        with patch.object(instance, 'call') as call:
            with self.assertRaises(RuntimeError):
                instance.recover('fixture-103', lambda *_a, **_k: None)
            call.assert_not_called()

    def test_capture_only_controller_cannot_enter_role_recovery(self):
        instance = controller.Controller(['kubectl'], None, capture_only=True)
        with patch.object(instance, 'call') as call:
            with self.assertRaisesRegex(RuntimeError, 'capture-only'):
                instance.recover('fixture-103', lambda *_a, **_k: None)
            call.assert_not_called()

    def test_foreign_cluster_refused_before_any_secret_read(self):
        instance = controller.Controller(['kubectl'], None)
        with patch.object(instance, 'get', return_value={'metadata': {'uid': 'foreign'}}) as get:
            with self.assertRaises(RuntimeError):
                instance.baseline()
            self.assertEqual(get.call_count, 1)

    def test_maintained_image_refuses_role_recovery_and_selects_native_client(self):
        image = controller.source.cold.control.MAINTAINED_IMAGE
        with self.assertRaisesRegex(RuntimeError, 'capture only'):
            controller.Controller(['kubectl'], None, source_image=image)
        with self.assertRaisesRegex(RuntimeError, 'unreviewed'):
            controller.Controller(['kubectl'], None, capture_only=True, source_image='foreign')
        instance = controller.Controller(['kubectl'], None, capture_only=True, source_image=image)
        instance.credentials = {'admin': 'synthetic-admin', 'app': 'synthetic-app'}
        with patch.object(instance, 'execute', return_value=SimpleNamespace(stdout=b'ok')) as execute:
            instance.client({}, 'postgres', 'psql')
            self.assertIn('/usr/lib/postgresql/16/bin/psql', execute.call_args.args)
        with self.assertRaisesRegex(RuntimeError, 'capture-only'):
            instance.recover('synthetic', lambda *_a, **_k: None)


if __name__ == '__main__':
    unittest.main()
