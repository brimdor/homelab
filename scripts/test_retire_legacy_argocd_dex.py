#!/usr/bin/env python3
"""Closed synthetic API tests: no real cluster, credentials, subprocess or fixtures."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('legacy_dex', Path(__file__).with_name('retire-legacy-argocd-dex.py'))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)
HEAD = 'a' * 40
TCP_EMPTY = '  sl  local_address rem_address st tx_queue rx_queue\n' * 2


def obj(kind, name, uid, namespace=r.NS, **fields):
    return {'apiVersion': 'v1', 'kind': kind,
            'metadata': {'name': name, 'namespace': namespace, 'uid': uid, 'resourceVersion': '1'}, **fields}


def fixture():
    goals = {}
    for key, uid in r.GOALS.items():
        x = obj(r.KINDS[key], r.NAME, uid)
        x['apiVersion'] = key[0]
        x['metadata']['labels'] = {'helm.sh/chart': 'argo-cd-7.0.0'}
        goals[key] = x
    goals[('apps/v1', 'deployments')]['spec'] = {'replicas': 1, 'template': {'spec': {
        'serviceAccountName': r.NAME,
        'volumes': [{'name': 'static-files', 'emptyDir': {}}, {'name': 'dexconfig', 'emptyDir': {}},
                    {'name': r.NAME + '-tls', 'secret': {'secretName': r.NAME + '-tls', 'optional': True}}],
        'containers': [{'image': 'ghcr.io/dexidp/dex:v2.38.0',
                        'command': ['/shared/argocd-dex', '--logformat=text', '--loglevel=info'], 'args': ['rundex']}],
        'initContainers': [{'image': 'quay.io/argoproj/argocd:v2.11.2'}]}}}
    goals[('v1', 'services')]['spec'] = {'type': 'ClusterIP', 'clusterIP': '10.43.107.60',
        'selector': {'app.kubernetes.io/instance': r.NS, 'app.kubernetes.io/name': r.NAME},
        'ports': [{'port': 5556, 'targetPort': 'http', 'protocol': 'TCP'},
                  {'port': 5557, 'targetPort': 'grpc', 'protocol': 'TCP'}]}
    goals[(r.RBAC, 'roles')]['rules'] = [{'apiGroups': [''], 'resources': ['secrets', 'configmaps'],
                                       'verbs': ['get', 'list', 'watch']}]
    goals[(r.RBAC, 'rolebindings')].update(subjects=[{'kind': 'ServiceAccount', 'name': r.NAME, 'namespace': r.NS}],
        roleRef={'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': r.NAME})
    active = [obj('Namespace', r.NS, 'ns-uid', namespace='', spec={'finalizers': ['kubernetes']}),
              obj('Deployment', 'argocd-server', 'server-uid', spec={'replicas': 1, 'template': {'spec': {
                  'containers': [{'name': 'server', 'env': [{'name': 'ARGOCD_SERVER_DEX_SERVER',
                      'valueFrom': {'configMapKeyRef': {'name': 'argocd-cmd-params-cm', 'key': 'server.dex.server', 'optional': True}}}],
                      'volumeMounts': [{'name': r.NAME + '-tls', 'mountPath': '/tls'}]}],
                  'volumes': [{'name': r.NAME + '-tls', 'secret': {'secretName': r.NAME + '-tls', 'optional': True}}]}}},
                  status={'readyReplicas': 1, 'observedGeneration': 1}),
              obj('ConfigMap', 'argocd-cm', 'cm-uid', data={'admin.enabled': 'true'}),
              obj('ConfigMap', 'argocd-cmd-params-cm', 'params-uid', data={'server.insecure': 'true'}),
              obj('Role', 'argocd-server', 'role-uid', rules=[{'resources': ['configmaps']}]),
              obj('PersistentVolume', 'pv', 'pv-uid', namespace='', spec={'capacity': {'storage': '1Gi'}}, status={'phase': 'Bound'}),
              obj('PersistentVolumeClaim', 'claim', 'pvc-uid', namespace='active', spec={'volumeName': 'pv'}, status={'phase': 'Bound'})]
    parents = {uid: (r.KINDS[key], r.NAME) for key, uid in r.GOALS.items()}
    parents.update({uid: (child[0], child[1]) for uid, child in r.CHILDREN.items()})
    children = []
    for uid, (kind, name, owner) in r.CHILDREN.items():
        x = obj(kind, name, uid)
        x['metadata']['ownerReferences'] = [{'kind': parents[owner][0], 'name': parents[owner][1], 'uid': owner}]
        children.append(x)
    secrets = [obj('Secret', 'argocd-secret', 'secret-uid'), obj('Secret', r.NAME + '-tls', 'tls-uid')]
    return goals, active, children, secrets


class FakeAPI:
    def __init__(self):
        self.goals, self.active, self.children, self.secrets = fixture()
        self.writes = []
        self.health_calls = 0
        self.protected_reads = 0
        self.runtime_calls = 0
        self.unknown_write = False
        self.stalled = False
        self.replace = False
        self.changed_storage = False

    def health(self, head):
        assert head == HEAD
        self.health_calls += 1

    def manifests(self, head):
        assert head == HEAD
        return copy.deepcopy([x for x in self.active if x['kind'] in ['Deployment', 'ConfigMap']])

    def objects(self):
        self.protected_reads += 1
        objects = copy.deepcopy([*self.goals.values(), *self.active, *self.children])
        if self.changed_storage:
            next(x for x in objects if x['kind'] == 'PersistentVolume')['spec']['capacity']['storage'] = '2Gi'
        return objects

    def metadata(self):
        return copy.deepcopy([{'kind': x['kind'], 'metadata': x['metadata']}
                              for x in [*self.goals.values(), *self.active, *self.children, *self.secrets]
                              if x['metadata'].get('namespace') == r.NS])

    def get(self, key):
        assert key in r.GOALS
        x = copy.deepcopy(self.goals.get(key))
        if x and self.replace and self.writes:
            x['metadata']['uid'] = 'replacement-uid'
        return x

    def observe(self, key, budget):
        assert 0 < budget <= r.OBSERVE_SECONDS
        parent = self.get(key)
        return ([parent] if parent else []) + copy.deepcopy([x for x in self.children
            if x['metadata']['uid'] in r.descendant_uids(r.GOALS[key])])

    def runtime(self):
        self.runtime_calls += 1
        r.runtime_gate(True, 'argocd-dex\nsh\n', TCP_EMPTY)

    def delete(self, key, x):
        path, options = r.delete_request(key, x)
        self.writes.append((path, options))
        if self.unknown_write:
            raise r.Refusal('DELETE outcome uncertain')
        if self.stalled:
            self.goals[key]['metadata']['deletionTimestamp'] = '2026-10-18T00:00:00Z'
            return
        uid = self.goals.pop(key)['metadata']['uid']
        gone = {uid}
        for _ in range(4):
            gone.update(x['metadata']['uid'] for x in self.children
                        if any(o['uid'] in gone for o in x['metadata']['ownerReferences']))
        self.children = [x for x in self.children if x['metadata']['uid'] not in gone]


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.no_process = patch.object(subprocess, 'run', side_effect=AssertionError('Real subprocess forbidden in tests'))
        self.no_process.start()
        self.addCleanup(self.no_process.stop)
        self.api = FakeAPI()

    def execute(self, apply=False, **kwargs):
        r.execute(self.api, gate=lambda writing: (HEAD, writing), apply=apply, emit=lambda _: None, **kwargs)

    def test_default_is_read_only_with_final_protected_and_health_checks(self):
        self.execute()
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.api.runtime_calls, 1)
        self.assertGreaterEqual(self.api.protected_reads, 2)
        self.assertGreaterEqual(self.api.health_calls, 2)

    def test_apply_deletes_only_five_exact_parents(self):
        self.execute(True)
        self.assertEqual(len(self.api.writes), 5)
        self.assertEqual(self.api.children, [])
        self.assertEqual({x[1]['preconditions']['uid'] for x in self.api.writes}, set(r.GOALS.values()))
        for path, options in self.api.writes:
            self.assertIn('/namespaces/argocd/', path)
            self.assertTrue(path.endswith('/argocd-dex-server'))
            self.assertEqual(options['preconditions']['resourceVersion'], '1')
            self.assertEqual(options['propagationPolicy'], 'Foreground')
            self.assertEqual(set(options), {'apiVersion', 'kind', 'preconditions', 'propagationPolicy'})

    def test_forbidden_resource_paths_never_construct(self):
        for resource in ['namespaces', 'secrets', 'configmaps', 'persistentvolumes', 'persistentvolumeclaims', 'pods', 'replicasets']:
            with self.subTest(resource=resource), self.assertRaises(r.Refusal):
                r.delete_request(('v1', resource), self.api.goals[('v1', 'services')])

    def test_uid_or_namespace_replacement_refused(self):
        for field, value in [('uid', 'new'), ('namespace', 'other'), ('name', 'shared'), ('resourceVersion', '')]:
            x = copy.deepcopy(self.api.goals[('v1', 'services')])
            x['metadata'][field] = value
            with self.subTest(field=field), self.assertRaises(r.Refusal):
                r.delete_request(('v1', 'services'), x)

    def test_finalizer_owner_or_existing_deletion_refused(self):
        for field, value in [('finalizers', ['retain']), ('ownerReferences', [{'uid': 'owner'}]), ('deletionTimestamp', 'now')]:
            x = copy.deepcopy(self.api.goals[('v1', 'services')])
            x['metadata'][field] = value
            with self.subTest(field=field), self.assertRaises(r.Refusal):
                r.delete_request(('v1', 'services'), x)

    def test_ssoconfig_or_override_refused(self):
        for key in ['dex.config', 'oidc.config', 'server.dex.server', 'server.dex.server.strict.tls']:
            with self.subTest(key=key), self.assertRaises(r.Refusal):
                r.no_sso({key: 'opaque value never printed'})

    def test_render_cannot_recreate_candidate(self):
        documents = self.api.manifests(HEAD)
        for goal in self.api.goals.values():
            with self.subTest(kind=goal['kind']), self.assertRaises(r.Refusal):
                r.manifest_gate(documents + [goal])

    def test_incomplete_render_refused(self):
        with self.assertRaises(r.Refusal):
            r.manifest_gate([self.api.manifests(HEAD)[0]])

    def test_runtime_requires_idle_and_no_dex_process(self):
        for idle, comm in [(False, 'argocd-dex\n'), (True, 'argocd-dex\ndex\n'), (True, 'sh\n')]:
            with self.subTest(idle=idle, comm=comm), self.assertRaises(r.Refusal):
                r.runtime_gate(idle, comm, TCP_EMPTY)

    def test_each_serving_port_refused_ipv4_or_ipv6(self):
        for port in [5556, 5557, 5558]:
            for address in ['00000000', '0' * 32]:
                table = TCP_EMPTY + f'0: {address}:{port:04X} 00000000:0000 0A 0 0 0 0 0 0\n'
                with self.subTest(port=port, address=address), self.assertRaises(r.Refusal):
                    r.runtime_gate(True, 'argocd-dex\n', table)

    def test_runtime_incomplete_or_malformed_evidence_refused(self):
        for table in ['', TCP_EMPTY.splitlines()[0], TCP_EMPTY + 'malformed\n']:
            with self.subTest(table=table), self.assertRaises(r.Refusal):
                r.runtime_gate(True, 'argocd-dex\n', table)

    def test_new_consumer_in_config_annotation_rbac_or_workload_refused(self):
        for x in [obj('ConfigMap', 'consumer', 'new', data={'url': 'http://' + r.NAME}),
                  obj('RoleBinding', 'consumer', 'new', subjects=[{'kind': 'ServiceAccount', 'name': r.NAME}]),
                  obj('Pod', 'consumer', 'new', spec={'serviceAccountName': r.NAME}),
                  obj('Ingress', 'consumer', 'new')]:
            if x['kind'] == 'Ingress':
                x['metadata']['annotations'] = {'nginx.ingress.kubernetes.io/auth-url': 'http://10.43.107.60:5556'}
            with self.subTest(kind=x['kind']), self.assertRaises(r.Refusal):
                r.consumer_gate(self.api.objects() + [x])

    def test_alias_service_and_broad_monitor_refused(self):
        for x in [obj('Service', 'alias', 'new', spec={'selector': {'app.kubernetes.io/instance': r.NS}}),
                  obj('ServiceMonitor', 'all', 'new', namespace='monitoring', spec={'namespaceSelector': {'any': True}, 'selector': {}})]:
            with self.subTest(kind=x['kind']), self.assertRaises(r.Refusal):
                r.consumer_gate(self.api.objects() + [x])

    def test_optional_disabled_wiring_allowed_shared_secret_protected(self):
        r.consumer_gate(self.api.objects())
        guard = r.protected(self.api.objects(), self.api.metadata())
        self.assertIn(('Secret', r.NS, r.NAME + '-tls'), guard)
        self.assertNotIn(('v1', 'secrets'), r.GOALS)

    def test_explicit_dex_env_value_refused(self):
        server = next(x for x in self.api.active if x['kind'] == 'Deployment')
        server['spec']['template']['spec']['containers'][0]['env'] = [{'name': 'ARGOCD_SERVER_DEX_SERVER', 'value': 'other'}]
        with self.assertRaises(r.Refusal):
            r.consumer_gate(self.api.objects())

    def test_new_tls_secret_consumer_refused(self):
        x = obj('Pod', 'new', 'new', spec={'volumes': [{'name': 'tls', 'secret': {'secretName': r.NAME + '-tls'}}]})
        with self.assertRaises(r.Refusal):
            r.consumer_gate(self.api.objects() + [x])

    def test_shared_role_binding_or_sa_auth_ref_refused(self):
        self.api.goals[(r.RBAC, 'rolebindings')]['subjects'].append({'kind': 'ServiceAccount', 'name': 'active', 'namespace': r.NS})
        self.api.goals[('v1', 'serviceaccounts')]['secrets'] = [{'name': 'token'}]
        for key in [(r.RBAC, 'rolebindings'), ('v1', 'serviceaccounts')]:
            with self.subTest(key=key), self.assertRaises(r.Refusal):
                r.object_gate(key, self.api.goals[key])

    def test_new_cascading_secret_dependent_refused(self):
        x = obj('Secret', 'data', 'unknown')
        x['metadata']['ownerReferences'] = [{'uid': next(iter(r.GOALS.values()))}]
        with self.assertRaises(r.Refusal):
            r.descendant_gate(self.api.metadata() + [x], set())

    def test_descendant_replacement_and_wrong_owner_refused(self):
        for field in ['uid', 'ownerReferences']:
            metadata = self.api.metadata()
            x = next(x for x in metadata if x['kind'] == 'Pod')
            x['metadata'][field] = 'replacement' if field == 'uid' else [{'uid': 'wrong'}]
            with self.subTest(field=field), self.assertRaises(r.Refusal):
                r.descendant_gate(metadata, set())

    def test_partial_initial_cleanup_not_auto_success(self):
        self.api.goals.pop(('v1', 'services'))
        with self.assertRaises(r.Refusal):
            self.execute(True)
        self.assertEqual(self.api.writes, [])

    def test_descendant_finalizers_and_termination_refused_before_delete(self):
        for kind in ['Pod', 'ReplicaSet', 'EndpointSlice', 'CiliumEndpoint']:
            for field, value in [('finalizers', ['foregroundDeletion']), ('deletionTimestamp', 'now')]:
                metadata = self.api.metadata()
                item = next(x for x in metadata if x['kind'] == kind)
                item['metadata'][field] = value
                with self.subTest(kind=kind, field=field), self.assertRaises(r.Refusal):
                    r.descendant_gate(metadata, set())

    def test_observation_allows_only_terminating_gc_finalizer(self):
        metadata = self.api.metadata()
        item = next(x for x in metadata if x['kind'] == 'ReplicaSet')
        item['metadata']['finalizers'] = ['foregroundDeletion']
        with self.assertRaises(r.Refusal):
            r.descendant_gate(metadata, set(), observing=True)
        item['metadata']['deletionTimestamp'] = 'now'
        r.descendant_gate(metadata, set(), observing=True)
        item['metadata']['finalizers'].append('example.test/hold')
        with self.assertRaises(r.Refusal):
            r.descendant_gate(metadata, set(), observing=True)

    def test_unknown_write_stops_and_finally_checks_protected_state(self):
        self.api.unknown_write = True
        with self.assertRaisesRegex(r.Refusal, 'uncertain'):
            self.execute(True)
        self.assertEqual(len(self.api.writes), 1)
        self.assertGreaterEqual(self.api.protected_reads, 3)
        self.assertGreaterEqual(self.api.health_calls, 3)

    def test_stalled_delete_has_bounded_observation_no_retry(self):
        self.api.stalled = True
        ticks = iter(range(0, 1000, 100))
        with self.assertRaisesRegex(r.Refusal, 'stalled'):
            self.execute(True, clock=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(len(self.api.writes), 1)

    def test_replaced_object_during_delete_stops(self):
        self.api.stalled = self.api.replace = True
        with self.assertRaisesRegex(r.Refusal, 'identity'):
            self.execute(True)
        self.assertEqual(len(self.api.writes), 1)

    def test_source_changes_before_first_delete_block(self):
        calls = iter([(HEAD, True), ('b' * 40, True)])
        with self.assertRaises(r.Refusal):
            r.execute(self.api, gate=lambda _: next(calls), apply=True, emit=lambda _: None)
        self.assertEqual(self.api.writes, [])

    def test_unclean_apply_gate_block(self):
        calls = iter([(HEAD, False), (HEAD, False)])
        with self.assertRaises(r.Refusal):
            r.execute(self.api, gate=lambda _: next(calls), apply=True, emit=lambda _: None)
        self.assertEqual(self.api.writes, [])

    def test_storage_spec_change_finally_detected(self):
        original = self.api.delete
        def deleting(key, x):
            original(key, x)
            self.api.changed_storage = True
        self.api.delete = deleting
        with self.assertRaisesRegex(r.Refusal, 'protected'):
            self.execute(True)
        self.assertEqual(len(self.api.writes), 1)

    def test_active_controller_unready_refused(self):
        next(x for x in self.api.active if x['kind'] == 'Deployment')['status']['readyReplicas'] = 0
        with self.assertRaises(r.Refusal):
            self.execute(True)
        self.assertEqual(self.api.writes, [])

    def test_secret_metadata_change_changes_protection(self):
        before = r.protected(self.api.objects(), self.api.metadata())
        self.api.secrets[0]['metadata']['resourceVersion'] = '2'
        self.assertNotEqual(before, r.protected(self.api.objects(), self.api.metadata()))

    def test_safe_output_never_echoes_opaque_values(self):
        canary = 'SYNTHETIC-AUTH-STATE-DO-NOT-PRINT'
        next(x for x in self.api.active if x['kind'] == 'ConfigMap')['data']['unrelated'] = canary
        lines = []
        r.execute(self.api, gate=lambda _: (HEAD, False), emit=lines.append)
        self.assertNotIn(canary, '\n'.join(lines))

    def test_subprocess_errors_never_echo_secret_stderr(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'SYNTHETIC-SECRET')):
            with self.assertRaises(r.Refusal) as failure:
                r.run(['fake', 'read'])
        self.assertNotIn('SYNTHETIC-SECRET', str(failure.exception))

    def test_raw_delete_transport_contains_both_preconditions(self):
        api = object.__new__(r.API)
        calls = []
        api.call = lambda *args, **kwargs: calls.append((args, kwargs)) or '{}'
        key = ('v1', 'services')
        api.delete(key, self.api.goals[key])
        self.assertEqual(calls[0][0], ('delete', '--raw', '/api/v1/namespaces/argocd/services/argocd-dex-server', '-f', '-'))
        self.assertEqual(json.loads(calls[0][1]['payload'])['preconditions'], {'uid': r.GOALS[key], 'resourceVersion': '1'})

    def test_tls_bypass_and_wrong_api_refused(self):
        for cluster in [{'server': r.SERVER, 'insecure-skip-tls-verify': True},
                        {'server': 'https://other', 'certificate-authority-data': 'redacted'}, {'server': r.SERVER}]:
            with self.subTest(cluster=cluster), self.assertRaises(r.Refusal):
                r.tls_gate({'clusters': [{'cluster': cluster}], 'contexts': [{}]})

    def test_core_profile_is_single_path_not_overlay(self):
        api = object.__new__(r.API)
        api.profile = Path('/synthetic/core.kubeconfig')
        with patch.object(r, 'run', return_value='{}') as call:
            api.argo('app', 'get', 'argocd')
        self.assertEqual(call.call_args.kwargs['env']['KUBECONFIG'], '/synthetic/core.kubeconfig')

    def test_observation_subprocess_is_bounded_and_never_reads_secrets(self):
        api = object.__new__(r.API)
        api.base = ['kubectl', '--cache-dir=/synthetic/cache']
        with patch.object(r, 'run', return_value='{"items": []}') as call:
            self.assertEqual(api.observe(('apps/v1', 'deployments'), 12), [])
        self.assertEqual(call.call_args.kwargs['timeout'], 12)
        self.assertNotIn('secrets', ' '.join(call.call_args.args[0]))

    def test_observation_timeout_does_not_retry(self):
        self.api.observe = lambda *_: (_ for _ in ()).throw(r.Refusal('bounded observation timeout'))
        with self.assertRaisesRegex(r.Refusal, 'timeout'):
            self.execute(True)
        self.assertEqual(len(self.api.writes), 1)

    def test_secret_metadata_never_falls_back_to_payload(self):
        class Transport:
            _list_paths = set()
            def metadata_resources(self):
                return [{'kind': 'Secret', 'path': '/api/v1/secrets'}]
            def _read(self, *args, **kwargs):
                return {'apiVersion': 'meta.k8s.io/v1', 'kind': 'PartialObjectMetadataList',
                        'items': [{'metadata': {'name': 'secret', 'namespace': r.NS, 'uid': 's', 'resourceVersion': '1'},
                                   'data': {'credential': 'SYNTHETIC-DO-NOT-EMIT'}}]}
        api = object.__new__(r.API)
        api.metadata_api = Transport()
        with self.assertRaises(r.Refusal) as failure:
            api.metadata()
        self.assertNotIn('SYNTHETIC', str(failure.exception))

    def test_legacy_sa_token_metadata_blocks_retirement(self):
        class Transport:
            _list_paths = set()
            def metadata_resources(self):
                return [{'kind': 'Secret', 'path': '/api/v1/secrets'}]
            def _read(self, *args, **kwargs):
                return {'apiVersion': 'meta.k8s.io/v1', 'kind': 'PartialObjectMetadataList',
                        'items': [{'metadata': {'name': 'token', 'namespace': r.NS, 'uid': 's', 'resourceVersion': '1',
                            'annotations': {'kubernetes.io/service-account.name': r.NAME}}}]}
        api = object.__new__(r.API)
        api.metadata_api = Transport()
        with self.assertRaisesRegex(r.Refusal, 'authentication data protected'):
            api.metadata()


if __name__ == '__main__':
    unittest.main(verbosity=2)
