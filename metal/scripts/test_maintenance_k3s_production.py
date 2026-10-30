"""Production bridge trust boundaries; no live cluster or host mutations."""

import copy
import ast
import hashlib
import json
import io
from contextlib import redirect_stdout
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

    def test_production_cannot_select_unintegrated_stage_or_touch_unknown_host(self):
        class Hold:
            state = None
        for node, source, target in (('charmander', contract.VERSIONS[2], contract.VERSIONS[3]),
                                     ('unknown', production.SOURCE, production.TARGET)):
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


class DrainAcceptanceTests(unittest.TestCase):
    def test_final_acceptance_uses_real_lock_without_reentry_or_dispatch(self):
        from test_maintenance_node_drain import NodeDrainTests
        fixture = NodeDrainTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.start()
        while True:
            accepted = fixture.advance()
            if accepted.get('complete'):
                break
        posts = copy.deepcopy(fixture.pod_api.posts)
        journal = fixture.journal
        result = journal.accept(accepted['parent_intent']['sha256'], production.hashed(accepted),
            lambda step, digest: step == 'drain' and digest == production.hashed(accepted) and
            production.verified_completed_drain(fixture.worker, accepted))
        self.assertEqual(result['completed'], ['cordon', 'drain'])
        self.assertEqual(fixture.pod_api.posts, posts)

    def test_final_acceptance_refuses_changed_inventory_or_completion_receipt(self):
        from test_maintenance_node_drain import NodeDrainTests
        fixture = NodeDrainTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.start()
        while True:
            accepted = fixture.advance()
            if accepted.get('complete'):
                break
        self.assertTrue(production.verified_completed_drain(fixture.worker, accepted))
        for field, value in [('records_sha256', 'f' * 64), ('completed', []),
                             ('inventory_sha256', 'f' * 64), ('plan_sha256', 'f' * 64)]:
            with self.subTest(field=field):
                self.assertFalse(production.verified_completed_drain(fixture.worker, dict(accepted, **{field: value})))
        fixture.pod_api.pods[0]['spec']['containers'][0]['image'] = 'changed'
        self.assertFalse(production.verified_completed_drain(fixture.worker, accepted))


class SchedulingRecoveryTests(unittest.TestCase):
    def test_uncordon_dispatch_once_then_accepts_fresh_recovered_controllers(self):
        import maintenance_actor_hold as actors
        import maintenance_hop_journal as hops
        from maintenance_node_scheduling import Scheduling
        from test_maintenance_actor_hold import IDENTITY, Systemd
        from test_maintenance_coordination import API
        from test_maintenance_node_scheduling import NodeAPI
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root = Path(temporary.name);units = root / 'units';units.mkdir()
        api = API();api.nodes[0].update(apiVersion='v1', kind='Node', spec={})
        api.nodes[0]['metadata']['resourceVersion'] = '10'
        owner = api.controller().acquire('fixture-a', production.SOURCE, production.TARGET,
                                        'a' * 40, component='k3s')
        hold = actors.Hold(Systemd(), lambda: dict(IDENTITY),
            lambda token: api.controller().resume(token) == owner, root / 'state', units)
        hold.acquire(owner['owner'], IDENTITY, 'a' * 40)
        journal = hops.Journal(api.controller(), hold, owner['owner']);journal.initialize()
        nodes = NodeAPI(api);worker = Scheduling(journal, nodes);cordon = worker.plan('cordon')
        worker.dispatch(cordon, production.hashed(cordon), 'c' * 64, lambda *_: True)
        worker.observe(cordon, 'c' * 64, lambda *_: True)
        actors.exclusive_file(hold.state / ('cordon-' + owner['owner'] + '.json'),
                              hops.canonical(cordon), 0o600)
        for step in hops.steps(owner)[1:hops.steps(owner).index('restore_scheduling')]:
            state = journal.begin(step, 'c' * 64, 'd' * 64, lambda *_: True)
            journal.accept(state['pending']['sha256'], 'e' * 64, lambda *_: True)
        def evidence(_kind):
            return {'held_controllers': ['pinned'] if nodes.node['spec'].get('unschedulable') else []}
        context = {'api': nodes, 'controller': api.controller(), 'hold': hold, 'owner': owner,
                   'native': None, 'identity': lambda: dict(IDENTITY), 'rpc': evidence,
                   'operation': 'restore-scheduling'}
        with patch.object(production, 'HOSTS', ('fixture-a',)), \
                patch.object(hops, 'Journal', return_value=journal):
            output = io.StringIO()
            with redirect_stdout(output):
                production.native_operation(context)
            dispatched = json.loads(output.getvalue())['result']
            self.assertFalse(dispatched['accepted'])
            self.assertEqual(len(nodes.patches), 2)
            output = io.StringIO()
            with redirect_stdout(output):
                production.native_operation(context)
            accepted = json.loads(output.getvalue())['result']
            self.assertTrue(accepted['accepted'])
            self.assertEqual(len(nodes.patches), 2)
            self.assertEqual(accepted['journal']['completed'][-1], 'restore_scheduling')


if __name__ == '__main__':
    unittest.main()
