#!/usr/bin/env python3
"""Real eviction/PDB/rescheduling proof in a caller-owned, disposable three-node VM."""

import argparse
import gzip
import json
import os
from pathlib import Path
import re
import signal
import socket
import time

import cilium_qualification as cluster
from cilium_l2_qualification import IMAGE, PAYLOAD, SERVER
import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_node_drain as drain
from test_maintenance_actor_hold import Systemd


NAMESPACE = 'qualification-drain'


def fixtures(minimum):
    labels = {'app': 'qualification-drain'}
    security = {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                'capabilities': {'drop': ['ALL']}}
    kured_spec = {'serviceAccountName': 'kured', 'securityContext': {
        'runAsNonRoot': True, 'runAsUser': 65532, 'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'kured', 'image': coordination.IMAGE,
                        'command': ['/usr/bin/kured'], 'args': coordination.ARGS, 'env': coordination.ENV,
                        'ports': [{'containerPort': 8080}], 'securityContext': security,
                        'readinessProbe': {'httpGet': {'path': '/metrics', 'port': 8080}}}]}
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name, 'labels': {
            'pod-security.kubernetes.io/enforce': 'restricted'}}} for name in ('kured', NAMESPACE)
    ] + [
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': 'kured', 'namespace': 'kured'}},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole',
         'metadata': {'name': 'qualification-kured'}, 'rules': [
             {'apiGroups': [''], 'resources': ['nodes'], 'verbs': ['get', 'list', 'watch']}]},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding',
         'metadata': {'name': 'qualification-kured'}, 'roleRef': {
             'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'qualification-kured'},
         'subjects': [{'kind': 'ServiceAccount', 'name': 'kured', 'namespace': 'kured'}]},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role',
         'metadata': {'name': 'kured', 'namespace': 'kured'}, 'rules': [
             {'apiGroups': ['apps'], 'resources': ['daemonsets'], 'resourceNames': ['kured'],
              'verbs': ['get', 'update', 'patch']}]},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
         'metadata': {'name': 'kured', 'namespace': 'kured'}, 'roleRef': {
             'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'kured'},
         'subjects': [{'kind': 'ServiceAccount', 'name': 'kured', 'namespace': 'kured'}]},
        {'apiVersion': 'apps/v1', 'kind': 'DaemonSet', 'metadata': {'name': 'kured', 'namespace': 'kured'},
         'spec': {'selector': {'matchLabels': {'app': 'kured'}}, 'template': {
             'metadata': {'labels': {'app': 'kured'}}, 'spec': kured_spec}}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'workload', 'namespace': NAMESPACE},
         'spec': {'replicas': 3, 'selector': {'matchLabels': labels}, 'template': {
             'metadata': {'labels': labels}, 'spec': {
                 'automountServiceAccountToken': False, 'securityContext': kured_spec['securityContext'],
                 'affinity': {'podAntiAffinity': {'preferredDuringSchedulingIgnoredDuringExecution': [
                     {'weight': 100, 'podAffinityTerm': {'labelSelector': {'matchLabels': labels},
                                                       'topologyKey': 'kubernetes.io/hostname'}}]}},
                 'containers': [{'name': 'http', 'image': IMAGE, 'command': ['python3', '-B', '-c', SERVER],
                                 'securityContext': security, 'ports': [{'containerPort': 8080}],
                                 'readinessProbe': {'httpGet': {'path': '/', 'port': 8080}}}]}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'workload', 'namespace': NAMESPACE},
         'spec': {'selector': labels, 'ports': [{'port': 8080, 'targetPort': 8080}]}},
        {'apiVersion': 'policy/v1', 'kind': 'PodDisruptionBudget',
         'metadata': {'name': 'workload', 'namespace': NAMESPACE},
         'spec': {'minAvailable': minimum, 'selector': {'matchLabels': labels}}},
    ]


class API(coordination.Kubectl):
    def __init__(self, fixture):
        self.fixture, self.posts, self.lose_response, self.rejection = fixture, [], False, None

    def call(self, *args, data=None):
        mutation = args[0] in ('create', 'patch')
        if mutation:
            self.fixture.identity()
        if args[0] == 'create':
            self.posts.append({'argv': list(args), 'body': json.loads(data)})
        try:
            raw = self.fixture.kubectl(*args, data=data, json_output=False)
        except RuntimeError:
            log = self.fixture.work / (str(self.fixture.count) + '.log.gz')
            raw = gzip.decompress(log.read_bytes())
            if args[0] == 'create' and b'Error from server (TooManyRequests)' in raw and b'disruption budget' in raw.lower():
                self.rejection = {'class': 'PDB-TooManyRequests', 'output_sha256': hops.digest(raw)}
            raise
        result = json.loads(raw)
        if args[0] == 'create' and self.lose_response:
            self.lose_response = False
            raise RuntimeError('qualification lost controller response after actual eviction')
        return result


class Qualification(cluster.Qualification):
    def __init__(self, args):
        actors.require(re.fullmatch('[a-f0-9]{40}', args.revision), 'exact published revision required')
        super().__init__(args)

    def save(self, name, value):
        (self.work / (name + '.json')).write_text(json.dumps(value, indent=2))

    def create(self):
        actors.require(self.command(['docker', 'info', '--format', '{{.Name}}'], private=True).decode().strip() ==
                       self.args.docker_server and not self.command(['docker', 'ps', '-aq'], private=True).strip(),
                       'Docker daemon is not the expected empty owned VM')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0));port = listener.getsockname()[1]
        self.creation_started = True
        flags = ['--k3s-arg=--disable=' + name + '@server:*'
                 for name in ('traefik', 'servicelb', 'local-storage', 'metrics-server')]
        flags += ['--k3s-arg=--resolv-conf=/etc/qualification-resolv.conf@' + role
                  for role in ('server:*', 'agent:*')]
        self.command([self.args.k3d, 'cluster', 'create', self.args.name, '--servers=1', '--agents=2',
                      '--image=' + cluster.K3S, '--api-port=127.0.0.1:' + str(port),
                      '--subnet=172.31.240.0/24', '--kubeconfig-update-default=false',
                      '--kubeconfig-switch-context=false', '--volume=' + self.args.guest_resolver_file +
                      ':/etc/qualification-resolv.conf:ro@all', *flags])
        path = Path(self.env['KUBECONFIG'])
        with path.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(self.command([self.args.k3d, 'kubeconfig', 'get', self.args.name], private=True))
        self.identity()
        self.kubectl('wait', 'nodes', '--all', '--for=condition=Ready', '--timeout=600s', json_output=False)

    def cleanup(self):
        if self.creation_started:
            self.command([self.args.k3d, 'cluster', 'delete', self.args.name])
            actors.require(not self.command(['docker', 'ps', '-aq'], private=True).strip(),
                           'owned VM still contains containers')
            self.creation_started = False
            path = Path(self.env['KUBECONFIG'])
            if path.exists():path.unlink()
            self.cluster_uid = None

    def availability(self):
        deployment = self.kubectl('get', 'deployment', 'workload', '-n', NAMESPACE)
        pods = self.kubectl('get', 'pods', '-n', NAMESPACE)['items']
        ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
                 len(p['status'].get('containerStatuses', [])) == 1 and
                 p['status']['containerStatuses'][0].get('ready') is True]
        actors.require(deployment['status'].get('observedGeneration') == deployment['metadata']['generation'] and
                       all(deployment['status'].get(k) == 3 for k in ('replicas', 'readyReplicas', 'availableReplicas',
                                                                    'updatedReplicas')) and len(ready) == 3,
                       'synthetic workload availability incomplete')
        endpoints = self.kubectl('get', 'endpointslice', '-n', NAMESPACE,
                                 '-l', 'kubernetes.io/service-name=workload')['items']
        endpoint_uids = {e['targetRef']['uid'] for item in endpoints for e in item.get('endpoints', [])
                         if e.get('conditions', {}).get('ready') is True}
        actors.require(endpoint_uids == {p['metadata']['uid'] for p in ready}, 'ready service endpoints differ')
        response = self.kubectl('get', '--raw=/api/v1/namespaces/' + NAMESPACE +
                                '/services/workload:8080/proxy/', json_output=False)
        actors.require(response == PAYLOAD, 'actual service HTTP response differs')
        return {'cluster_uid': self.cluster_uid, 'deployment_uid': deployment['metadata']['uid'],
                'ready_pods': sorted((p['metadata']['uid'], p['spec']['nodeName']) for p in ready),
                'endpoint_uids': sorted(endpoint_uids), 'http_sha256': hops.digest(response),
                'host_systemd_and_recovery_synthetic': True}

    def profile(self, scenario):
        minimum = 2 if scenario == 'lost-response' else 3
        self.kubectl('apply', '-f', '-', data=hops.canonical({'apiVersion': 'v1', 'kind': 'List',
                                                           'items': fixtures(minimum)}), json_output=False)
        self.kubectl('rollout', 'status', 'daemonset/kured', '-n', 'kured', '--timeout=600s', json_output=False)
        self.kubectl('rollout', 'status', 'deployment/workload', '-n', NAMESPACE, '--timeout=600s', json_output=False)
        initial = self.availability();api = API(self)
        ds, _pods, nodes = api.snapshot()
        node_uids = {n['metadata']['name']: n['metadata']['uid'] for n in nodes}
        actors.require({n for _uid,n in initial['ready_pods']} == set(node_uids), 'initial replicas are not spread')
        node_name = 'k3d-' + self.args.name + '-agent-0'
        ownership = coordination.Ownership(api, ds['metadata']['uid'], node_uids)
        owner = ownership.acquire(node_name, 39, 41, self.args.revision)
        local = self.work / scenario;local.mkdir(mode=0o700);(local / 'units').mkdir(mode=0o700)
        identity = {'machine': 'synthetic-host-' + owner['node_uid'], 'root_uuid': 'synthetic-root'}
        hold = actors.Hold(Systemd(), lambda: identity, lambda token: ownership.resume(token) == owner,
                           local / 'state', local / 'units')
        hold.acquire(owner['owner'], identity, self.args.revision)
        journal = hops.Journal(ownership, hold, owner['owner']);journal.initialize()
        before = api.call('get', 'node', node_name, '-o', 'json')
        actors.require(not before['spec'].get('unschedulable', False), 'fixture Node already cordoned')
        digest = drain.hashed(initial)
        pending = journal.begin('cordon', drain.hashed({'node': node_name, 'uid': owner['node_uid']}),
                                digest, lambda *_: self.availability() == initial)
        operations = [{'op': 'test', 'path': '/metadata/uid', 'value': owner['node_uid']},
                      {'op': 'test', 'path': '/metadata/resourceVersion', 'value': before['metadata']['resourceVersion']},
                      {'op': 'add', 'path': '/spec/unschedulable', 'value': True}]
        cordoned = api.call('patch', 'node', node_name, '--type=json', '--patch', coordination.encoded(operations), '-o', 'json')
        journal.accept(pending['pending']['sha256'], drain.hashed(cordoned['spec']),
                       lambda *_: api.call('get', 'node', node_name, '-o', 'json')['spec']['unschedulable'] is True)
        worker = drain.Drain(journal, api);plan = worker.inventory()
        selected = [p for p in plan['pods'] if not p['keep']]
        actors.require(len(selected) == 1 and selected[0]['namespace'] == NAMESPACE,
                       'fixture contains an unexpected eviction target')
        self.kubectl('wait', 'pdb/workload', '-n', NAMESPACE, '--for=jsonpath={.status.disruptionsAllowed}=' +
                     str(3-minimum), '--timeout=180s', json_output=False)
        worker.start(plan, drain.hashed(plan), digest, lambda *_: self.availability() == initial)
        api.lose_response = scenario == 'lost-response'
        try:worker.advance(digest, lambda *_: self.availability() == initial)
        except RuntimeError as error:
            if scenario == 'lost-response':
                actors.require(str(error) == 'qualification lost controller response after actual eviction',
                               'unexpected eviction failure')
            else:actors.require(api.rejection is not None, 'expected actual PDB refusal missing')
        else:raise RuntimeError('expected lost response or PDB refusal did not occur')
        actors.require(len(api.posts) == 1 and worker.read()['pending'], 'durable micro-intent missing')
        if scenario == 'lost-response':
            self.kubectl('wait', 'pod/' + selected[0]['name'], '-n', NAMESPACE, '--for=delete',
                         '--timeout=180s', json_output=False)
            self.kubectl('rollout', 'status', 'deployment/workload', '-n', NAMESPACE,
                         '--timeout=600s', json_output=False)
            current = self.availability();digest = drain.hashed(current)
            actors.require(selected[0]['uid'] not in current['endpoint_uids'] and
                           all(node != node_name for _uid,node in current['ready_pods']),
                           'workload was not replaced away from cordoned Node')
            fresh = drain.Drain(journal, api)
            observed = fresh.advance(digest, lambda *_: self.availability() == current)
            actors.require('observed' in observed and len(api.posts) == 1, 'lost eviction was replayed')
            outcome = fresh.advance(digest, lambda *_: self.availability() == current)
            actors.require(outcome['complete'] and len(api.posts) == 1, 'drain receipt incomplete or replayed')
        else:
            outcomes = [drain.Drain(journal, api).advance(digest, lambda *_: self.availability() == initial)
                        for _ in range(2)]
            actors.require(all('pending' in r and not r['mutation_performed'] for r in outcomes) and
                           len(api.posts) == 1 and self.availability() == initial,
                           'PDB refusal was replayed or availability changed')
            outcome = {'complete': False, 'pending_retained': True, 'rejection': api.rejection}
        final = journal.inspect()
        actors.require(final['pending']['step'] == 'drain' and final['completed'] == ['cordon'] and
                       hold.marker.exists() and ownership.resume(owner['owner']) == owner and
                       api.call('get', 'node', node_name, '-o', 'json')['spec']['unschedulable'] is True,
                       'fixture automatically accepted, released or uncordoned')
        result = {'scenario': scenario, 'cluster_uid': self.cluster_uid, 'node_uids': node_uids,
                  'plan': plan, 'posts': api.posts, 'outcome': outcome, 'parent': final,
                  'host_systemd_and_recovery_synthetic': True, 'production_changes': False}
        self.save(scenario + '-result', result)
        return result

    def run(self):
        results = []
        for scenario in ('lost-response', 'pdb-refusal'):
            try:
                self.create();results.append(self.profile(scenario))
            finally:self.cleanup()
        actors.require(results[0]['cluster_uid'] != results[1]['cluster_uid'], 'profiles did not use separate clusters')
        return {'actual_api_drain_profiles': results, 'production_changes': False,
                'native_systemd_packages_ceph_cilium_nas_and_safe_release_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('name', 'docker-host', 'docker-server', 'k3d', 'kubectl', 'guest-resolver-file', 'revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    fixture = Qualification(parser.parse_args())
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):signal.signal(number, cluster.interrupted)
    try:fixture.save('result', fixture.run())
    finally:fixture.cleanup()


if __name__ == '__main__':
    main()
