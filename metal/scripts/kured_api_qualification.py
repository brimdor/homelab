#!/usr/bin/env python3
"""Qualify maintenance ownership against a fresh isolated three-node K3s API.

The tracked caller owns the private Docker VM, SDK binary, proxy and cleanup.
This fixture has no host mounts, host privileges, production data or reboot actor.
"""

import copy
import gzip
import json
from pathlib import Path
import socket
import subprocess
import threading

import cilium_qualification as cluster
import maintenance_coordination as owner


class API:
    def __init__(self, qualification):
        self.q = qualification

    def snapshot(self):
        self.q.identity()
        return (self.q.kubectl('get', 'daemonset', 'kured', '-n', 'kured'),
                self.q.kubectl('get', 'pods', '-n', 'kured')['items'],
                self.q.kubectl('get', 'nodes')['items'])

    def patch(self, operations):
        return self.q.kubectl('patch', 'daemonset', 'kured', '-n', 'kured',
                              '--type=json', '-p', json.dumps(operations))


class Qualification(cluster.Qualification):
    def __init__(self, args):
        super().__init__(args)
        self.command_lock = threading.Lock()

    def command(self, command, *, data=None, private=False):
        # Two controllers still race their observed RVs; keep inherited log numbering exact.
        with self.command_lock:
            return super().command(command, data=data, private=private)

    def create(self):
        actual = self.command(['docker', 'info', '--format', '{{.Name}}'], private=True).decode().strip()
        owner.require(actual == self.args.docker_server and
                      not self.command(['docker', 'ps', '-aq'], private=True).strip(),
                      'fixture Docker VM is not owned and empty')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.creation_started = True
        self.command([self.args.k3d, 'cluster', 'create', self.args.name, '--servers=1', '--agents=2',
                      '--image=' + cluster.K3S, '--api-port=127.0.0.1:' + str(port),
                      '--subnet=172.31.240.0/24', '--kubeconfig-update-default=false',
                      '--kubeconfig-switch-context=false', '--k3s-arg=--disable=traefik@server:*',
                      '--k3s-arg=--disable=servicelb@server:*', '--k3s-arg=--disable=local-storage@server:*',
                      '--k3s-arg=--disable=metrics-server@server:*'])
        # The existing identity gate excludes the production UID and requires all three owned nodes.
        path = Path(self.env['KUBECONFIG'])
        raw = self.command([self.args.k3d, 'kubeconfig', 'get', self.args.name], private=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        self.identity()
        self.kubectl('wait', 'nodes', '--all', '--for=condition=Ready', '--timeout=600s', json_output=False)

    def deploy(self):
        self.identity()
        resources = [
            {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'kured'}},
            {'apiVersion': 'v1', 'kind': 'ServiceAccount',
             'metadata': {'name': 'kured-fixture', 'namespace': 'kured'}},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role',
             'metadata': {'name': 'kured-fixture', 'namespace': 'kured'},
             'rules': [{'apiGroups': ['apps'], 'resources': ['daemonsets'],
                        'resourceNames': ['kured'], 'verbs': ['get', 'update']}]},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
             'metadata': {'name': 'kured-fixture', 'namespace': 'kured'},
             'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'kured-fixture'},
             'subjects': [{'kind': 'ServiceAccount', 'name': 'kured-fixture', 'namespace': 'kured'}]},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole',
             'metadata': {'name': self.args.name},
             'rules': [{'apiGroups': [''], 'resources': ['nodes'], 'verbs': ['get', 'list', 'watch']}]},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding',
             'metadata': {'name': self.args.name},
             'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': self.args.name},
             'subjects': [{'kind': 'ServiceAccount', 'name': 'kured-fixture', 'namespace': 'kured'}]},
            {'apiVersion': 'apps/v1', 'kind': 'DaemonSet', 'metadata': {'name': 'kured', 'namespace': 'kured'},
             'spec': {'selector': {'matchLabels': {'app': 'kured'}}, 'template': {
                 'metadata': {'labels': {'app': 'kured'}}, 'spec': {
                     'serviceAccountName': 'kured-fixture',
                     'tolerations': [{'operator': 'Exists'}],
                     'securityContext': {'runAsUser': 65532, 'runAsGroup': 65532, 'runAsNonRoot': True},
                     'containers': [{'name': 'kured', 'image': owner.IMAGE, 'command': ['/usr/bin/kured'],
                                     'args': list(owner.ARGS), 'env': copy.deepcopy(owner.ENV),
                                     'securityContext': {'readOnlyRootFilesystem': True,
                                                         'allowPrivilegeEscalation': False,
                                                         'capabilities': {'drop': ['ALL']}},
                                     'readinessProbe': {'httpGet': {'path': '/metrics', 'port': 8080}},
                                     'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'},
                                                   'limits': {'memory': '128Mi'}}}]}}}},
        ]
        self.kubectl('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List',
                                                       'items': resources}).encode(), json_output=False)
        self.kubectl('rollout', 'status', 'daemonset/kured', '-n', 'kured', '--timeout=600s', json_output=False)

    def control(self, api=None):
        api = api or API(self)
        ds, _, nodes = api.snapshot()
        return owner.Ownership(api, ds['metadata']['uid'],
                               {n['metadata']['name']: n['metadata']['uid'] for n in nodes})

    def qualify(self, revision, native):
        control = self.control()
        ds, pods, nodes = control.api.snapshot()
        original = copy.deepcopy(ds['spec'])
        node_specs = {n['metadata']['name']: n['spec'] for n in nodes}
        pod_uids = sorted(p['metadata']['uid'] for p in pods)
        node = nodes[0]['metadata']['name']
        result = {'cluster_uid': self.cluster_uid, 'production_mutations': 0,
                  'node_count': len(nodes), 'daemonset_uid': ds['metadata']['uid']}
        first = native('acquire', 'native-fixture-owner')
        assert first == {'acquired': True, 'holder': 'native-fixture-owner'}
        try:
            control.acquire(node, 39, 41, revision)
        except RuntimeError as error:
            assert 'already exists' in str(error)
        else:
            raise AssertionError('maintenance stole native ownership')
        assert native('release', 'native-fixture-owner') == {'released': True}
        result['existing_native_owner_refused'] = True
        barrier = threading.Barrier(2)

        class Raced(API):
            def patch(self, operations):
                barrier.wait(timeout=30)
                return super().patch(operations)

        outcomes = []

        def acquire():
            try:
                outcomes.append(('acquired', self.control(Raced(self)).acquire(node, 39, 41, revision)))
            except RuntimeError as error:
                outcomes.append(('refused', str(error)))

        children = [threading.Thread(target=acquire) for _ in range(2)]
        for child in children:
            child.start()
        for child in children:
            child.join()
        assert sorted(x[0] for x in outcomes) == ['acquired', 'refused']
        # The failed API patch must be a tested resourceVersion refusal, not a network failure.
        logs = [gzip.decompress(p.read_bytes()).decode(errors='replace') for p in self.work.glob('*.log.gz')]
        assert any('test' in text.lower() and 'resourceVersion' in text for text in logs)
        journal = next(value for status, value in outcomes if status == 'acquired')
        token = journal['owner']
        assert native('acquire', 'native-fixture-owner') == {'acquired': False, 'holder': token}
        assert 'error' in native('release', 'native-fixture-owner')
        assert self.control().resume(token) == journal
        result['real_api_simultaneous_claim_and_native_exclusion'] = True
        try:
            control.release(token, lambda _: False)
        except RuntimeError as error:
            assert 'gates did not pass' in str(error)
        else:
            raise AssertionError('unsafe release passed')
        assert native('acquire', 'native-fixture-owner') == {'acquired': False, 'holder': token}
        control.release(token, lambda _: True)
        result['restart_resume_and_failed_release_retention'] = True

        class LostResponse(API):
            def patch(self, operations):
                super().patch(operations)
                raise RuntimeError('INJECTED_RESPONSE_LOSS_AFTER_COMMIT')

        try:
            self.control(LostResponse(self)).acquire(node, 39, 41, revision)
        except RuntimeError as error:
            assert 'INJECTED_RESPONSE_LOSS_AFTER_COMMIT' in str(error)
        else:
            raise AssertionError('lost response was not injected')
        observed = json.loads(control.api.snapshot()[0]['metadata']['annotations'][owner.JOURNAL])
        assert self.control().resume(observed['owner']) == observed
        assert native('acquire', 'native-fixture-owner') == {'acquired': False, 'holder': observed['owner']}
        control.release(observed['owner'], lambda _: True)
        result['committed_real_api_write_with_injected_response_loss_resumed'] = True
        assert native('acquire', 'native-fixture-owner') == {'acquired': True, 'holder': 'native-fixture-owner'}
        assert native('release', 'native-fixture-owner') == {'released': True}
        final_ds, final_pods, final_nodes = control.api.snapshot()
        assert final_ds['spec'] == original
        assert owner.LOCK not in final_ds['metadata'].get('annotations', {})
        assert owner.JOURNAL not in final_ds['metadata'].get('annotations', {})
        assert sorted(p['metadata']['uid'] for p in final_pods) == pod_uids
        assert {n['metadata']['name']: n['spec'] for n in final_nodes} == node_specs
        assert all(c['ready'] and c['restartCount'] == 0 for p in final_pods
                   for c in p['status']['containerStatuses'])
        result.update(explicit_release_restored_native_ownership=True,
                      node_specs_pod_uids_and_daemonset_template_unchanged=True,
                      all_fixture_kured_containers_ready_zero_restarts=True,
                      host_package_reboot_actors_qualified=False)
        return result
