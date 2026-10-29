"""Real persistence/process boundaries with explicitly synthetic Kubernetes APIs."""

import copy
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_node_drain as drain
from test_maintenance_actor_hold import IDENTITY, Systemd
from test_maintenance_coordination import API


class PodAPI:
    def __init__(self, ownership):
        self.ownership = ownership
        self.posts = []
        self.before_post = None
        self.remove = True
        self.response = {'kind': 'Status', 'status': 'Success'}
        self.pods, self.controllers = [], {}
        for index, (pod_name, kind) in enumerate((('daemon', 'DaemonSet'), ('mirror', 'Node'),
                                                ('workload-a', 'ReplicaSet'), ('workload-b', 'Job'))):
            controller_name = 'fixture-a' if kind == 'Node' else pod_name + '-controller'
            uid = 'fixture-a-uid' if kind == 'Node' else controller_name + '-uid'
            version = 'v1' if kind == 'Node' else 'batch/v1' if kind == 'Job' else 'apps/v1'
            controller = {'apiVersion': version, 'kind': kind, 'name': controller_name,
                          'uid': uid, 'controller': True}
            self.controllers[(drain.CONTROLLERS[kind], controller_name)] = {
                'apiVersion': version, 'kind': kind, 'metadata': {'name': controller_name, 'uid': uid}}
            metadata = {'namespace': 'fixture', 'name': pod_name, 'uid': pod_name + '-uid',
                        'resourceVersion': str(index + 1), 'ownerReferences': [controller]}
            if kind == 'Node':metadata['annotations'] = {'kubernetes.io/config.mirror': 'synthetic'}
            self.pods.append({'metadata': metadata, 'spec': {'nodeName': 'fixture-a',
                             'containers': [{'name': 'fixture', 'image': 'synthetic-pinned-image'}]}})

    def call(self, *args, data=None):
        if args[:2] == ('get', 'node'):
            return copy.deepcopy(next(n for n in self.ownership.nodes if n['metadata']['name'] == args[2]))
        if args[:2] == ('get', 'pods'):
            return {'items': copy.deepcopy(self.pods)}
        if args[:2] == ('get', 'pod'):
            return copy.deepcopy(next(p for p in self.pods if p['metadata']['name'] == args[2]))
        if args[0] == 'get':return copy.deepcopy(self.controllers[args[1:3]])
        if args[0] == 'create':
            value = json.loads(data)
            self.posts.append((args, value))
            if self.before_post:self.before_post()
            meta = value['metadata']
            pod = next(p for p in self.pods if p['metadata']['name'] == meta['name'])
            assert value['deleteOptions'] == {'preconditions': {
                'uid': pod['metadata']['uid'], 'resourceVersion': pod['metadata']['resourceVersion']}}
            if self.remove:self.pods.remove(pod)
            return copy.deepcopy(self.response)
        raise AssertionError('unexpected synthetic API command')


class NodeDrainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = API()
        for node in self.api.nodes:
            node.update(apiVersion='v1', kind='Node')
            node['spec'] = {'unschedulable': node['metadata']['name'] == 'fixture-a'}
        self.owner = self.api.controller().acquire('fixture-a', 39, 41, 'a' * 40)
        self.units = self.root / 'units';self.units.mkdir()
        self.systemd = Systemd()
        self.hold = self.fresh_hold();self.hold.acquire(self.owner['owner'], IDENTITY, 'a' * 40)
        self.journal = self.fresh_journal();self.journal.initialize()
        intent = self.journal.begin('cordon', 'b' * 64, 'c' * 64, lambda *_: True)
        self.journal.accept(intent['pending']['sha256'], 'd' * 64, lambda *_: True)
        self.pod_api = PodAPI(self.api)
        self.worker = self.fresh_drain()

    def fresh_hold(self):
        return actors.Hold(self.systemd, lambda: dict(IDENTITY),
                           lambda token: self.api.controller().resume(token) == self.owner,
                           self.root / 'state', self.units)

    def fresh_journal(self):
        return hops.Journal(self.api.controller(), self.fresh_hold(), self.owner['owner'])

    def fresh_drain(self):
        return drain.Drain(self.fresh_journal(), self.pod_api)

    def start(self):
        plan = self.worker.inventory()
        self.worker.start(plan, drain.hashed(plan), 'c' * 64, lambda *_: True)
        return plan

    def advance(self, worker=None, verify=lambda *_: True):
        return (worker or self.worker).advance('c' * 64, verify)

    def wait_child(self, pid):
        reaped = False
        try:
            end = time.monotonic() + 10
            while time.monotonic() < end:
                found, status = os.waitpid(pid, os.WNOHANG)
                if found:
                    reaped = True
                    return os.waitstatus_to_exitcode(status)
                time.sleep(.01)
            self.fail('owned synthetic child did not finish')
        finally:
            if not reaped:
                try:os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:pass
                os.waitpid(pid, 0)

    def test_plan_covers_every_pod_and_only_exact_daemon_and_mirror_are_kept(self):
        plan = self.worker.inventory()
        self.assertEqual(len(plan['pods']), 4)
        self.assertEqual([p['name'] for p in plan['pods'] if p['keep']], ['daemon', 'mirror'])
        self.assertEqual([p['name'] for p in plan['pods'] if not p['keep']], ['workload-a', 'workload-b'])
        for mutate in (lambda: self.api.nodes[0]['spec'].update(unschedulable=False),
                       lambda: self.pod_api.pods[0]['metadata'].update(ownerReferences=[]),
                       lambda: self.pod_api.controllers[('daemonset', 'daemon-controller')]['metadata'].update(uid='foreign'),
                       lambda: self.pod_api.pods[0]['metadata'].update(annotations={'kubernetes.io/config.mirror': 'spoof'})):
            nodes, pods, controllers = copy.deepcopy((self.api.nodes, self.pod_api.pods, self.pod_api.controllers))
            mutate()
            with self.assertRaises(RuntimeError):self.worker.inventory()
            self.api.nodes, self.pod_api.pods, self.pod_api.controllers = nodes, pods, controllers
        self.assertFalse(self.pod_api.posts)

    def test_registry_exception_requires_exact_component_container_native_and_storage_proof(self):
        owner = {'node': 'charmander', 'component': 'k3s'}
        pod = {'metadata': {'namespace': 'zot', 'name': 'retained-zot', 'uid': drain.ZOT['pod_uid']},
               'spec': {'nodeName': 'charmander', 'containers': [{'name': 'zot', 'image': 'existing'}]},
               'status': {'phase': 'Running', 'containerStatuses': [{'name': 'zot', 'ready': True,
                          'restartCount': 0, 'containerID': drain.ZOT['container_id']}]}}
        proof = dict(drain.ZOT, spec_sha256=drain.hashed(pod['spec']))
        api = SimpleNamespace(protected_registry=lambda _: copy.deepcopy(proof))
        self.assertTrue(drain.retain_registry(api, pod, owner))
        self.assertFalse(drain.retain_registry(api, pod, dict(owner, component='fedora')))
        for key in drain.ZOT:
            changed = copy.deepcopy(proof);changed[key] = 'foreign'
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'native process or storage'):
                drain.retain_registry(SimpleNamespace(protected_registry=lambda _: changed), pod, owner)
        for key, value in (('uid', 'replacement'), ('deletionTimestamp', 'now')):
            changed = copy.deepcopy(pod);changed['metadata'][key] = value
            with self.assertRaisesRegex(RuntimeError, 'Pod identity'):
                drain.retain_registry(api, changed, owner)
        changed = copy.deepcopy(pod);changed['status']['containerStatuses'][0]['restartCount'] = 1
        with self.assertRaisesRegex(RuntimeError, 'container identity'):
            drain.retain_registry(api, changed, owner)
        with self.assertRaisesRegex(RuntimeError, 'observer missing'):
            drain.retain_registry(SimpleNamespace(), pod, owner)
        self.assertFalse(self.pod_api.posts)

    def add_osd_fixture(self):
        pod = copy.deepcopy(self.pod_api.pods[2])
        controller = pod['metadata']['ownerReferences'][0]
        controller.update(name='rook-ceph-osd-1-abcdef', uid='osd-controller-uid')
        pod['metadata'].update(namespace='rook-ceph', name='rook-ceph-osd-1-abcdef-pod', uid='osd-pod-uid')
        self.pod_api.controllers[('replicaset', controller['name'])] = {
            'apiVersion': 'apps/v1', 'kind': 'ReplicaSet',
            'metadata': {'name': controller['name'], 'uid': controller['uid']}}
        self.pod_api.pods.append(pod)
        self.pod_api.pods[3]['metadata']['namespace'] = 'volsync-system'

    def test_clusterpolicy_pod_requires_fresh_exact_cuda_proof_before_retention(self):
        pod = copy.deepcopy(self.pod_api.pods[2])
        pod['metadata'].update(namespace='gpu-operator', name='nvidia-cuda-validator-fixture', uid='cuda-pod')
        pod['metadata']['ownerReferences'] = [{'apiVersion': 'nvidia.com/v1', 'kind': 'ClusterPolicy',
            'name': 'cluster-policy', 'uid': 'policy', 'controller': True}]
        self.pod_api.pods.append(pod)
        with self.assertRaisesRegex(RuntimeError, 'unreviewed GPU'):
            self.worker.inventory()
        proof = {'pod_uid': 'cuda-pod', 'spec_sha256': drain.hashed(pod['spec']), 'cluster_policy_uid': 'policy'}
        calls = []
        def observe(ref):
            calls.append(ref)
            return dict(proof)
        self.pod_api.completed_cuda = observe
        plan = self.worker.inventory()
        kept = next(ref for ref in plan['pods'] if ref['uid'] == 'cuda-pod')
        self.assertTrue(kept['keep'])
        self.assertEqual(calls, [kept])
        for field in proof:
            original = proof[field]; proof[field] = 'changed'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'GPU completion identity'):
                self.worker.inventory()
            proof[field] = original
        self.assertFalse(self.pod_api.posts)

    def test_osd_eviction_follows_every_other_workload(self):
        self.add_osd_fixture()
        plan = self.worker.inventory()
        self.assertEqual([p['uid'] for p in plan['pods'] if not p['keep']],
                         ['workload-a-uid', 'workload-b-uid', 'osd-pod-uid'])
        self.assertEqual({p['uid'] for p in plan['pods']}, {p['metadata']['uid'] for p in self.pod_api.pods})
        self.assertFalse(self.pod_api.posts)

    def test_completed_job_precedes_workloads_without_moving_osds_forward(self):
        self.add_osd_fixture()
        job = next(p for p in self.pod_api.pods if p['metadata']['name'] == 'workload-b')
        job['status'] = {'phase': 'Succeeded'}
        job['metadata']['namespace'] = 'zzz-history'
        plan = self.worker.inventory()
        targets = [ref for ref in plan['pods'] if not ref['keep']]
        self.assertEqual([ref['uid'] for ref in targets],
                         ['workload-b-uid', 'workload-a-uid', 'osd-pod-uid'])
        self.assertEqual(targets[0]['controller'], job['metadata']['ownerReferences'][0])
        self.assertEqual(targets[0]['spec_sha256'], drain.hashed(job['spec']))
        self.assertEqual({p['uid'] for p in plan['pods']},
                         {p['metadata']['uid'] for p in self.pod_api.pods})
        self.assertFalse(self.pod_api.posts)

    def test_prior_lexical_plan_resumes_without_reordering_or_replay(self):
        self.add_osd_fixture()
        plan = self.worker.inventory()
        plan['pods'].sort(key=lambda ref: (ref['namespace'], ref['name'], ref['uid']))
        with patch.object(self.worker, 'inventory', return_value=copy.deepcopy(plan)):
            self.worker.start(plan, drain.hashed(plan), 'c' * 64, lambda *_: True)
        for ref in [p for p in plan['pods'] if not p['keep']]:
            self.assertEqual(self.advance()['queued']['uid'], ref['uid'])
            self.assertIn('observed', self.advance(self.fresh_drain()))
        self.assertTrue(self.advance()['complete'])
        self.assertEqual(len(self.pod_api.posts), 3)

    def test_review_and_prerequisites_refuse_before_parent_intent(self):
        plan = self.worker.inventory();before = self.journal.inspect()
        with self.assertRaisesRegex(RuntimeError, 'reviewed inventory'):
            self.worker.start(plan, 'e' * 64, 'c' * 64, lambda *_: True)
        with self.assertRaisesRegex(RuntimeError, 'prerequisite'):
            self.worker.start(plan, drain.hashed(plan), 'c' * 64, lambda *_: False)
        self.assertEqual(self.journal.inspect(), before)
        self.assertFalse(self.worker.path.exists())

    def test_serial_eviction_intents_observations_and_partial_drain_resume(self):
        plan = self.start();pending = self.journal.inspect()
        for index in range(2):
            result = self.advance(self.fresh_drain())
            self.assertTrue(result['mutation_performed']);self.assertFalse(result['accepted'])
            args, value = self.pod_api.posts[-1]
            target = [p for p in plan['pods'] if not p['keep']][index]
            self.assertEqual(args, ('create', '--raw=/api/v1/namespaces/fixture/pods/' + target['name'] + '/eviction', '-f', '-'))
            self.assertEqual(value['apiVersion'], 'policy/v1')
            self.assertEqual(set(value['deleteOptions']), {'preconditions'})
            intent = drain.private_json(self.worker.path / (str(index).zfill(8) + '.intent.json'))
            self.assertEqual(value['deleteOptions']['preconditions']['resourceVersion'], intent['resource_version'])
            self.assertEqual(self.worker.read()['pending']['pod']['uid'], target['uid'])
            observed = self.advance(self.fresh_drain())
            self.assertFalse(observed['mutation_performed']);self.assertIn('observed', observed)
            self.assertEqual(len(self.pod_api.posts), index + 1)
        complete = self.advance(self.fresh_drain())
        self.assertTrue(complete['complete']);self.assertEqual(len(complete['completed']), 2)
        self.assertEqual(complete['records_sha256'], self.worker.read()['records_sha256'])
        self.assertEqual(complete['prerequisites_sha256'], 'c' * 64)
        self.assertEqual(self.journal.inspect(), pending)
        self.assertTrue(self.hold.marker.exists());self.assertTrue(self.api.nodes[0]['spec']['unschedulable'])

    def test_pending_and_terminating_pod_never_reposts(self):
        self.start();self.pod_api.remove = False
        self.advance();pod = next(p for p in self.pod_api.pods if p['metadata']['name'] == 'workload-a')
        pod['metadata']['deletionTimestamp'] = '2026-10-25T05:00:00Z'
        for _ in range(2):
            result = self.advance(self.fresh_drain())
            self.assertFalse(result['mutation_performed']);self.assertIn('pending', result)
        self.assertEqual(len(self.pod_api.posts), 1)
        self.pod_api.pods.remove(pod);self.assertIn('observed', self.advance())

    def test_refused_response_keeps_intent_without_retry(self):
        self.start();self.pod_api.remove = False
        self.pod_api.response = {'kind': 'Status', 'status': 'Failure'}
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):self.advance()
        self.assertIsNotNone(self.worker.read()['pending'])
        self.assertIn('pending', self.advance(self.fresh_drain()))
        self.assertEqual(len(self.pod_api.posts), 1)

    def test_lost_response_after_deletion_is_observed_without_retry(self):
        self.start();original = self.pod_api.call
        def lost(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[0] == 'create':raise RuntimeError('synthetic lost API response')
            return result
        with patch.object(self.pod_api, 'call', side_effect=lost), self.assertRaisesRegex(RuntimeError, 'lost API'):
            self.advance()
        self.assertIn('observed', self.advance(self.fresh_drain()))
        self.assertEqual(len(self.pod_api.posts), 1)

    def test_native_controller_death_after_durable_intent_does_not_repeat_post(self):
        self.start();marker = self.root / 'native-post'
        pid = os.fork()
        if pid == 0:
            def die():
                state = self.worker.read();assert state['pending']
                actors.exclusive_file(marker, b'one synthetic API mutation', 0o600)
                os._exit(73)
            self.pod_api.before_post = die
            self.advance();os._exit(91)
        self.assertEqual(self.wait_child(pid), 73)
        self.assertTrue(marker.exists())
        self.assertIn('pending', self.advance(self.fresh_drain()))
        self.assertFalse(self.pod_api.posts)
        self.pod_api.pods = [p for p in self.pod_api.pods if p['metadata']['name'] != 'workload-a']
        self.assertIn('observed', self.advance(self.fresh_drain()))

    def test_changed_inventory_owner_or_prerequisites_never_posts(self):
        self.start()
        with self.assertRaisesRegex(RuntimeError, 'prerequisites refused'):
            self.advance(verify=lambda *_: False)
        pod = self.pod_api.pods[-1];pod['spec']['new'] = True
        with self.assertRaisesRegex(RuntimeError, 'new or changed'):self.advance()
        del pod['spec']['new']
        self.api.nodes[0]['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'identities changed'):self.advance()
        self.assertFalse(self.pod_api.posts)

    def test_new_pods_missing_keep_and_unstarted_disappearance_refuse(self):
        self.start();original = copy.deepcopy(self.pod_api.pods)
        extra = copy.deepcopy(original[-1]);extra['metadata'].update(name='new-pod', uid='new-uid')
        self.pod_api.pods.append(extra)
        with self.assertRaisesRegex(RuntimeError, 'new or changed'):self.advance()
        self.pod_api.pods = copy.deepcopy(original[1:])
        with self.assertRaisesRegex(RuntimeError, 'keep-set changed'):self.advance()
        self.pod_api.pods = copy.deepcopy(original[:-2])
        with self.assertRaisesRegex(RuntimeError, 'unstarted eviction Pod disappeared'):self.advance()
        self.assertFalse(self.pod_api.posts)

    def test_owner_change_after_durable_intent_retains_it_without_post(self):
        self.start();original = actors.exclusive_file
        def change(path, data, mode):
            original(path, data, mode)
            if path.name.endswith('.intent.json'):
                self.api.nodes[0]['metadata']['uid'] = 'changed'
        with patch.object(actors, 'exclusive_file', side_effect=change), \
                self.assertRaisesRegex(RuntimeError, 'identities changed'):
            self.advance()
        self.assertTrue((self.worker.path / '00000000.intent.json').exists())
        self.assertFalse(self.pod_api.posts)

    def test_reviewed_successful_job_removal_has_separate_record_without_eviction(self):
        self.start();self.advance();self.advance()
        ref = self.worker.read()['targets'][1]
        self.pod_api.pods = [p for p in self.pod_api.pods if p['metadata']['uid'] != ref['uid']]
        proof = {'kind': 'successful-job-removal', 'pod_uid': ref['uid'],
                 'job_uid': ref['controller']['uid'], 'prior_success_sha256': 'e' * 64,
                 'recovery_sha256': 'f' * 64}
        result = self.worker.advance('c' * 64, lambda *_: True, lambda actual: proof if actual == ref else None)
        self.assertFalse(result['mutation_performed'])
        self.assertEqual(len(self.pod_api.posts), 1)
        self.assertTrue((self.worker.path / '00000001.external.json').exists())
        self.assertFalse((self.worker.path / '00000001.intent.json').exists())
        self.assertTrue(self.advance(self.fresh_drain())['complete'])

    def test_external_removal_refuses_wrong_uid_missing_proof_and_changed_prerequisites(self):
        self.start();self.advance();self.advance()
        ref = self.worker.read()['targets'][1]
        self.pod_api.pods = [p for p in self.pod_api.pods if p['metadata']['uid'] != ref['uid']]
        proof = {'kind': 'successful-job-removal', 'pod_uid': ref['uid'],
                 'job_uid': ref['controller']['uid'], 'prior_success_sha256': 'e' * 64,
                 'recovery_sha256': 'f' * 64}
        for bad in (None, dict(proof, pod_uid='foreign'), dict(proof, job_uid='foreign'),
                    dict(proof, prior_success_sha256=''), dict(proof, recovery_sha256='')):
            with self.assertRaisesRegex(RuntimeError, 'exact prior success'):
                self.worker.advance('c' * 64, lambda *_: True, lambda _: bad)
        calls = []
        def changed(*_):
            calls.append(True)
            return len(calls) == 1
        with self.assertRaisesRegex(RuntimeError, 'external removal prerequisites'):
            self.worker.advance('c' * 64, changed, lambda _: proof)
        self.assertFalse((self.worker.path / '00000001.external.json').exists())
        self.assertEqual(len(self.pod_api.posts), 1)

    def test_approved_controller_replacement_is_observed_without_eviction(self):
        self.start();ref = self.worker.read()['targets'][0]
        self.pod_api.pods = [p for p in self.pod_api.pods if p['metadata']['uid'] != ref['uid']]
        proof = {'kind': 'verified-controller-replacement', 'pod_uid': ref['uid'],
                 'controller_uid': ref['controller']['uid'], 'replacement_uid': 'replacement',
                 'application_uid': 'application', 'configuration_commit': 'a' * 40,
                 'artifact_sha256': 'b' * 64, 'acceptance_sha256': 'c' * 64}
        for bad in (dict(proof, pod_uid='foreign'), dict(proof, controller_uid='foreign'),
                    dict(proof, replacement_uid=ref['uid']), dict(proof, configuration_commit=0),
                    dict(proof, acceptance_sha256='')):
            with self.assertRaisesRegex(RuntimeError, 'exact replacement acceptance'):
                self.worker.advance('c' * 64, lambda *_: True, lambda _: bad)
        result = self.worker.advance('c' * 64, lambda *_: True, lambda _: proof)
        self.assertFalse(result['mutation_performed'])
        self.assertFalse(self.pod_api.posts)
        self.assertEqual(self.fresh_drain().read()['completed'], [ref['uid']])

    def test_controller_replacement_is_rechecked_before_durable_record(self):
        self.start();ref = self.worker.read()['targets'][0]
        self.pod_api.pods = [p for p in self.pod_api.pods if p['metadata']['uid'] != ref['uid']]
        proof = {'kind': 'verified-controller-replacement', 'pod_uid': ref['uid'],
                 'controller_uid': ref['controller']['uid'], 'replacement_uid': 'replacement',
                 'application_uid': 'application', 'configuration_commit': 'a' * 40,
                 'artifact_sha256': 'b' * 64, 'acceptance_sha256': 'c' * 64}
        observations = iter((proof, dict(proof, acceptance_sha256='d' * 64)))
        with self.assertRaisesRegex(RuntimeError, 'replacement changed'):
            self.worker.advance('c' * 64, lambda *_: True, lambda _: next(observations))
        self.assertFalse((self.worker.path / '00000000.external.json').exists())
        self.assertFalse(self.pod_api.posts)

    def test_corruption_foreign_files_and_permissions_refuse(self):
        self.start();path = self.worker.path / 'header.json';original = path.read_bytes()
        path.write_bytes(original + b'\n')
        with self.assertRaisesRegex(RuntimeError, 'noncanonical'):self.advance()
        path.write_bytes(original);path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'unsafe drain record'):self.advance()
        path.chmod(0o600);extra = self.worker.path / 'foreign';extra.write_bytes(b'foreign')
        with self.assertRaisesRegex(RuntimeError, 'foreign or out-of-order'):self.advance()
        extra.unlink();target = self.root / 'original';path.rename(target);path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'unsafe actor ownership path'):self.advance()
        self.assertFalse(self.pod_api.posts)

    def test_attach_after_initial_header_interruption_never_begins_again(self):
        plan = self.worker.inventory()
        self.journal.begin('drain', drain.hashed(plan), 'c' * 64, lambda *_: True)
        self.worker.parent.mkdir(mode=0o700);self.worker.path.mkdir(mode=0o700)
        self.fresh_drain().attach(plan)
        self.assertEqual(self.worker.read()['completed'], [])
        with self.assertRaisesRegex(RuntimeError, 'pending or out-of-order'):
            self.worker.start(plan, drain.hashed(plan), 'c' * 64, lambda *_: True)

    def test_second_process_cannot_enter_during_post(self):
        self.start()
        def check_lock():
            pid = os.fork()
            if pid == 0:
                try:self.advance(self.fresh_drain())
                except BlockingIOError:os._exit(42)
                except BaseException:os._exit(91)
                os._exit(92)
            self.assertEqual(self.wait_child(pid), 42)
        self.pod_api.before_post = check_lock
        self.advance();self.assertEqual(len(self.pod_api.posts), 1)

    def test_kubectl_adapter_sends_exact_stdin_without_shell(self):
        adapter = coordination.Kubectl('/absolute/compatible/kubectl')
        with patch.object(coordination.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=b'{"kind":"Status","status":"Success"}')) as run:
            self.assertEqual(adapter.call('create', '--raw=/exact', '-f', '-', data=b'{}')['status'], 'Success')
        run.assert_called_once_with(['/absolute/compatible/kubectl', 'create', '--raw=/exact', '-f', '-'],
                                    input=b'{}', capture_output=True, check=False)


if __name__ == '__main__':
    unittest.main()
