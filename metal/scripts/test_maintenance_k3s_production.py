"""Production bridge trust boundaries; no live cluster or host mutations."""

import copy
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_k3s_contract as contract
import maintenance_k3s_production as production
import maintenance_production_node as shared


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.before = {'boot': 'original', 'configs': {'/config': 'digest'}, 'unit_sha256': 'unit',
                       'selinux': 'Enforcing', 'stargz': True, 'pid': 10, 'version': production.SOURCE}
        self.after = dict(self.before, pid=11, version=production.TARGET)

    def test_retains_host_state_and_requires_one_observed_restart(self):
        production.unchanged_runtime(self.before, self.after)
        with self.assertRaisesRegex(RuntimeError, 'restart not observed'):
            production.unchanged_runtime(self.before, dict(self.after, pid=10))
        for field in ('boot', 'configs', 'unit_sha256', 'selinux', 'stargz'):
            changed = copy.deepcopy(self.after); changed[field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'protected host state'):
                production.unchanged_runtime(self.before, changed)

    def test_production_cannot_cross_etcd_36_gate_or_touch_an_osd_host(self):
        class Hold:
            state = None
        for node, source, target in (('charmander', contract.VERSIONS[1], contract.VERSIONS[2]),
                                     ('cyndaquil', production.SOURCE, production.TARGET)):
            context = dict.fromkeys(('api', 'controller', 'native', 'identity', 'rpc'))
            context.update(hold=Hold(), operation='activate-binary', owner={
                'component': 'k3s', 'node': node, 'source': source, 'target': target})
            with self.subTest(node=node), self.assertRaisesRegex(RuntimeError, 'unreviewed production bridge'):
                production.native_operation(context)

    def test_all_embedded_remote_programs_compile_after_string_decoding(self):
        tree = ast.parse(Path(production.__file__).read_text())
        count = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                    ('sender_program', 'receiver_program', 'program') for t in node.targets)):
                value = node.value.right if isinstance(node.value, ast.BinOp) else node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and '\n' in value.value:
                    compile(value.value, 'decoded-remote-program', 'exec'); count += 1
        self.assertGreaterEqual(count, 5)


class BehaviorTests(unittest.TestCase):
    def test_missing_mesh_member_stops_before_dns_or_http(self):
        class API:
            def call(self, *args):
                return {'nodes': []}
        pod = {'metadata': {'name': 'cilium-fixture', 'labels': {'k8s-app': 'cilium'}}}
        with patch.object(production.subprocess, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'mesh membership differs'):
                production.behavior(None, API(), [pod])
        command.assert_not_called()

    def test_registry_ref_requires_exact_existing_pod_and_spec(self):
        import maintenance_production_node as shared
        pod = {'metadata': {'name': 'zot', 'uid': 'different'}, 'spec': {}}
        class API:
            def call(self, *args):
                return {'items': [pod]}
        with patch.object(shared, 'protected_registry'), patch.object(shared, 'remote') as remote:
            with self.assertRaisesRegex(RuntimeError, 'registry drain reference differs'):
                production.registry(None, API(), {'namespace': 'zot', 'name': 'zot', 'uid': 'different'})
        remote.assert_not_called()


class CompletedRemovalTests(unittest.TestCase):
    def test_only_exact_current_bridge_owner_can_select_new_profile(self):
        owner = {'owner': 'homelab-maintenance-103-841116fb-5b65-4d37-b2d4-e189e54e25c7',
                 'component': 'k3s', 'node': 'charmander',
                 'node_uid': '9108f105-f73d-41bb-891f-ac2db6658714',
                 'source': production.SOURCE, 'target': production.TARGET}
        with patch.object(shared, 'removed_completed_job', return_value={'accepted': True}) as observed:
            self.assertEqual(production.completed_removal(None, owner, {'uid': 'prior'}), {'accepted': True})
            self.assertEqual(observed.call_args.args[2],
                             Path('metal/maintenance/k3s-charmander-completed-job-removal.json'))
            for field in owner:
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'removal owner'):
                    production.completed_removal(None, dict(owner, **{field: 'different'}), {'uid': 'prior'})
            self.assertEqual(observed.call_count, 1)

    def test_prior_success_requires_current_matching_legitimate_recovery(self):
        ref = {'uid': 'old-pod', 'name': 'old-pod', 'controller': {'uid': 'old-job', 'name': 'old-job'}}
        cron = {'metadata': {'uid': 'cron'}, 'spec': {'successfulJobsHistoryLimit': 3},
                'status': {'lastSuccessfulTime': '2026-10-29T19:06:34Z'}}
        job = {'kind': 'Job', 'metadata': {'uid': 'new-job', 'name': 'new-job', 'namespace': 'strata', 'ownerReferences': [
            {'kind': 'CronJob', 'name': 'strata-backup', 'controller': True, 'uid': 'cron'}]}, 'spec': {},
            'status': {'succeeded': 1, 'completionTime': '2026-10-29T19:06:34Z',
                       'conditions': [{'type': 'Complete', 'status': 'True'}]}}
        pod = {'metadata': {'uid': 'new-pod', 'name': 'new-pod', 'namespace': 'strata',
                           'ownerReferences': [{'kind': 'Job', 'controller': True,
                                                'uid': 'new-job', 'name': 'new-job'}]},
               'spec': {'restartPolicy': 'OnFailure', 'containers': [{'name': 'backup'}]},
               'status': {'phase': 'Succeeded', 'containerStatuses': [{'name': 'backup',
                   'state': {'terminated': {'exitCode': 0}}, 'restartCount': 0,
                   'imageID': 'registry/strata@sha256:' + 'a' * 64}]}}
        profile = {'ref': ref, 'prior_success': {'verified': 'earlier exact Pod and Job'},
                   'cron_uid': 'cron', 'cron_spec': hashlib.sha256(
                       json.dumps(cron['spec'], sort_keys=True).encode()).hexdigest(),
                   'recovery': {'job_uid': 'new-job', 'pod_uid': 'new-pod',
                                'completion_time': '2026-10-29T19:06:34Z',
                                'image_digest': 'sha256:' + 'a' * 64}}

        class API:
            def call(self, *args):
                if args[1] == 'pods':
                    return {'items': [pod]}
                if args[1] == 'jobs':
                    return {'items': [job]}
                return cron if args[1] == 'cronjob' else job

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'; raw = json.dumps(profile).encode();path.write_bytes(raw)
            with patch.object(shared.subprocess, 'check_output', return_value=raw):
                result = shared.removed_completed_job(API(), ref, path)
                self.assertEqual(result['pod_uid'], 'old-pod')
                self.assertEqual(result['job_uid'], 'old-job')
                pod['status']['containerStatuses'][0]['state']['terminated']['exitCode'] = 1
                with self.assertRaisesRegex(RuntimeError, 'legitimately succeed'):
                    shared.removed_completed_job(API(), ref, path)
                pod['status']['containerStatuses'][0]['state']['terminated']['exitCode'] = 0
                job['status']['failed'] = 1
                with self.assertRaisesRegex(RuntimeError, 'not successfully complete'):
                    shared.removed_completed_job(API(), ref, path)
                job['status'].pop('failed');cron['spec']['successfulJobsHistoryLimit'] = 4
                with self.assertRaisesRegex(RuntimeError, 'history policy changed'):
                    shared.removed_completed_job(API(), ref, path)
                with self.assertRaisesRegex(RuntimeError, 'unreviewed missing Pod'):
                    shared.removed_completed_job(API(), dict(ref, uid='foreign'), path)


if __name__ == '__main__':
    unittest.main()
