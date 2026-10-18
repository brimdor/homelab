#!/usr/bin/env python3
"""Maintenance #103: exact, stateless legacy Dex retirement; default is read-only.

The five UID constants are the retirement plan. --apply requires these sources on
pushed master. No adoption, ordinary Argo prune, storage deletion, or write retry.
"""

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import yaml

sys.dont_write_bytecode = True
ROOT = Path('/Users/chris/Documents/Github/homelab')
SERVER = 'https://10.0.20.50:6443'
ORIGIN = 'git@git.eaglepass.io:ops/homelab.git'
REPO = 'http://gitea-http.gitea:3000/ops/homelab'
NS, NAME = 'argocd', 'argocd-dex-server'
RBAC = 'rbac.authorization.k8s.io/v1'
# Order keeps credentials/RBAC available until the idle controller is gone.
GOALS = {
    ('apps/v1', 'deployments'): '9843513f-0815-40fa-9126-32646b11a2e6',
    ('v1', 'services'): '18e96b1a-52ca-4950-ab61-90c57fa0707f',
    (RBAC, 'rolebindings'): '0efa4b0e-90c0-45d6-97fa-d173f6bbb316',
    (RBAC, 'roles'): '6619b2a5-42be-4240-8f03-0b278cc4eacf',
    ('v1', 'serviceaccounts'): 'd74958b5-42a8-41ac-ab0f-68c5649a153b',
}
KINDS = dict(zip(GOALS, ['Deployment', 'Service', 'RoleBinding', 'Role', 'ServiceAccount']))
POD = NAME + '-b4d796b55-2pv6l'
POD_UID = 'c8c5166b-022a-49c4-a9c0-ba6019514b6c'
# Only these observed descendants may be garbage-collected, never directly deleted.
CHILDREN = {
    '6efa1a6c-13a3-4d48-aa82-0b8edd75cf77': ('ReplicaSet', NAME + '-b4d796b55', GOALS[('apps/v1', 'deployments')]),
    POD_UID: ('Pod', POD, '6efa1a6c-13a3-4d48-aa82-0b8edd75cf77'),
    '88a180e9-a06a-4cb4-a990-d06212055475': ('EndpointSlice', NAME + '-6m9zz', GOALS[('v1', 'services')]),
    '57f946d7-8d14-48ac-bec5-26ade4d36d52': ('CiliumEndpoint', POD, POD_UID),
}
CHILD_RESOURCES = {'ReplicaSet': 'replicasets.apps', 'Pod': 'pods',
                   'EndpointSlice': 'endpointslices.discovery.k8s.io', 'CiliumEndpoint': 'ciliumendpoints.cilium.io'}
SCOPED = ['scripts/retire-legacy-argocd-dex.py', 'scripts/test_retire_legacy_argocd_dex.py',
          'docs/how-to-guides/retire-legacy-argocd-dex.md', 'scripts/retire-workloads.py',
          'system/argocd', 'AGENTS.md', '.agent/rules/foundational-rules.md']
WORKLOADS = {'Deployment', 'StatefulSet', 'DaemonSet', 'ReplicaSet', 'ReplicationController', 'Job', 'CronJob', 'Pod'}
COLLECTIONS = ['deployments,statefulsets,daemonsets,replicasets,replicationcontrollers,jobs,cronjobs,pods',
               'services,ingresses,endpointslices,configmaps,serviceaccounts,roles,rolebindings,networkpolicies',
               'clusterroles,clusterrolebindings,persistentvolumes,persistentvolumeclaims,customresourcedefinitions,namespaces']
REFERENCE = re.compile(r'argocd-dex-server|10\.43\.107\.60|10\.0\.2\.215', re.I)
OBSERVE_SECONDS = 180


class Refusal(RuntimeError):
    """Only fixed, non-secret operator diagnostics may leave this executor."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def run(args, payload=None, env=None, timeout=60):
    try:
        p = subprocess.run(args, input=payload, text=True, capture_output=True,
                           cwd=ROOT, timeout=timeout, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise Refusal('Command unavailable/timed out; outcome unknown for writes; no retry') from None
    if p.returncode:
        reason = next((code for code, text in [('denied', 'forbidden'), ('denied', 'unauthorized'),
            ('denied', 'permission denied'), ('flag', 'unknown flag'), ('missing-file', 'no such file'),
            ('connection', 'failed to connect'), ('timeout', 'timed out')] if text in (p.stderr + p.stdout).lower()), 'command-error')
        operation = ' '.join(x for x in args if x in {'git', 'kubectl', 'argocd', 'config', 'version', 'get',
            'app', 'manifests', 'logs', 'exec', 'delete', 'ls-remote', 'status', 'rev-parse'})
        raise Refusal('Command failed (' + operation + '; ' + reason + '); raw diagnostics withheld; no automatic retry')
    return p.stdout


def source_gate(apply=False):
    def git(*args):
        return run(['git', *args]).strip()
    require(Path(__file__).resolve().parent.parent == ROOT and ROOT.resolve() == ROOT, 'Foreign executor checkout')
    require(git('rev-parse', '--show-toplevel') == str(ROOT) and git('branch', '--show-current') == 'master', 'Canonical master required')
    require(git('config', '--get-all', 'remote.origin.url') == ORIGIN and git('remote', 'get-url', 'origin') == ORIGIN,
            'Canonical Gitea origin required')
    head = git('rev-parse', 'HEAD')
    require(git('ls-remote', 'origin', 'refs/heads/master') == head + '\trefs/heads/master', 'HEAD is not pushed Gitea master')
    values = yaml.safe_load((ROOT / 'system/argocd/values.yaml').read_text())['argo-cd']
    require(values.get('dex', {}).get('enabled') is False, 'Repository Dex must stay disabled')
    no_sso(values.get('configs', {}).get('cm', {}))
    clean = not git('status', '--porcelain', '--untracked-files=all', '--', *SCOPED)
    if apply:
        require(clean, 'Scoped source is dirty/untracked; apply requires committed retirement plan')
        for path in SCOPED[:4]:
            require(git('ls-files', '--error-unmatch', path) == path, 'Required executor/test/runbook/transport not committed')
        for path in git('ls-files', '-z', '--', *SCOPED).split('\0'):
            if path:
                local = ROOT / path
                require(local.is_file() and not local.is_symlink()
                        and local.read_text() == run(['git', 'show', 'HEAD:' + path]), 'Scoped bytes differ from HEAD')
    return head, clean


def no_sso(data):
    require(not data.get('dex.config') and not data.get('oidc.config'), 'Dex/OIDC configuration is present')
    require(not any(k.startswith('server.dex.server') for k in data), 'Explicit Dex server override is present')


def tls_gate(config):
    require(len(config.get('clusters', [])) == 1 and len(config.get('contexts', [])) == 1, 'Ambiguous API context')
    cluster = config['clusters'][0]['cluster']
    require(cluster.get('server') == SERVER and not any(cluster.get(k) for k in
            ['insecure-skip-tls-verify', 'proxy-url', 'tls-server-name'])
            and (cluster.get('certificate-authority') or cluster.get('certificate-authority-data')), 'API TLS identity mismatch')


class API:
    def __init__(self):
        cache = os.environ.get('KUBECACHEDIR', '')
        require(cache and Path(cache).is_absolute() and Path(cache).is_dir(), 'Existing process-local KUBECACHEDIR required')
        self.base = ['kubectl', '--kubeconfig', str(ROOT / 'metal/kubeconfig.yaml'), '--cache-dir=' + cache]
        self.metadata_api = None
        self.profile = Path.home() / '.config/homelab/argocd-core.kubeconfig'

    def call(self, *args, payload=None):
        return run([*self.base, '--request-timeout=30s', *args], payload)

    def get(self, key, name=NAME, namespace=NS):
        version, plural = key
        resource = plural + ('.' + version.split('/')[0] if '/' in version else '')
        text = self.call('get', resource, name, '-n', namespace, '--ignore-not-found', '-o', 'json')
        return json.loads(text) if text.strip() else None

    def establish(self):
        require(not any(os.environ.get(k) for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']),
                'Proxy overrides are not allowed')
        tls_gate(json.loads(self.call('config', 'view', '--minify', '-o', 'json')))
        versions = json.loads(self.call('version', '-o', 'json'))
        parsed = [re.match(r'v(\d+)\.(\d+)\.', versions[k]['gitVersion']) for k in ['clientVersion', 'serverVersion']]
        require(all(parsed) and parsed[0][1] == parsed[1][1] and abs(int(parsed[0][2]) - int(parsed[1][2])) <= 1,
                'Unsupported kubectl/server skew')
        require(self.profile.is_file(), 'Existing secure Argo core profile required')
        tls_gate(json.loads(run(['kubectl', '--kubeconfig', str(self.profile), 'config', 'view', '--minify', '-o', 'json'])))

    def argo(self, *args):
        # GetManifests treats a colon-separated KUBECONFIG as one filename.
        return run(['argocd', '--core', '-N', NS, *args],
                   env={**os.environ, 'KUBECONFIG': str(self.profile)})

    def manifests(self, head):
        return list(yaml.safe_load_all(self.argo('app', 'manifests', 'argocd', '--revision', head)))

    def health(self, head):
        app = json.loads(self.argo('app', 'get', 'argocd', '-o', 'json'))
        spec, status = app['spec'], app.get('status', {})
        require(spec.get('source') == {'repoURL': REPO, 'path': 'system/argocd', 'targetRevision': 'master'}
                and not spec.get('sources') and spec.get('destination') == {'name': 'in-cluster', 'namespace': NS},
                'Argo source/destination changed')
        require(status.get('sync', {}).get('status') == 'Synced' and status['sync'].get('revision') == head
                and status.get('health', {}).get('status') == 'Healthy', 'Authenticated core Argo health/revision gate failed')
        require(status.get('operationState', {}).get('phase') not in ['Running', 'Terminating'] and not app.get('operation'),
                'Argo operation is active')

    def objects(self):
        items = []
        for resources in COLLECTIONS:
            items.extend(json.loads(self.call('get', resources, '-A', '-o', 'json'))['items'])
        for resource in self.metadata_api.metadata_resources():
            if re.match(r'^(servicemonitors|podmonitors|probes|httproutes|tcproutes|tlsroutes|grpcroutes|ingressroutes|gateways|ciliumnetworkpolicies|ciliumclusterwidenetworkpolicies)\.', resource['resource']):
                items.extend(json.loads(self.call('get', resource['resource'], '-A', '-o', 'json'))['items'])
        return items

    def metadata(self):
        result = []
        for resource in self.metadata_api.metadata_resources():
            prefix, plural = resource['path'].rsplit('/', 1)
            path = prefix + '/namespaces/' + NS + '/' + plural
            self.metadata_api._list_paths.add(path)
            continuation, seen = '', set()
            while True:
                doc = self.metadata_api._read(path, partial=True, continuation=continuation)
                require(doc.get('kind') == 'PartialObjectMetadataList' and doc.get('apiVersion') == 'meta.k8s.io/v1',
                        'Metadata negotiation failed; no full-object fallback')
                for item in doc.get('items') or []:
                    require(set(item) <= {'apiVersion', 'kind', 'metadata'}, 'Metadata response included a payload')
                    m = item['metadata']
                    require(m.get('namespace') == NS and m.get('uid') and m.get('resourceVersion'), 'Incomplete metadata identity')
                    if resource['kind'] == 'Secret':
                        annotations = m.get('annotations', {})
                        require(annotations.get('kubernetes.io/service-account.name') != NAME
                                and annotations.get('kubernetes.io/service-account.uid') != GOALS[('v1', 'serviceaccounts')],
                                'Secret metadata references legacy ServiceAccount; authentication data protected')
                    result.append({'kind': resource['kind'], 'metadata': {k: m[k] for k in
                        ['name', 'namespace', 'uid', 'resourceVersion', 'ownerReferences', 'deletionTimestamp', 'finalizers'] if k in m}})
                continuation = doc.get('metadata', {}).get('continue', '')
                if not continuation:
                    break
                require(continuation not in seen, 'Repeated metadata pagination token')
                seen.add(continuation)
        return result

    def runtime(self):
        pod = self.get(('v1', 'pods'), POD)
        identity(pod, POD_UID, POD)
        logs = self.call('logs', POD, '-n', NS, '-c', 'dex-server', '--tail=200')
        idle = any('dex is not configured' in line for line in logs.splitlines())
        del logs
        comm = self.call('exec', '-n', NS, POD, '-c', 'dex-server', '--', 'sh', '-c',
                         'for p in /proc/[0-9]*/comm; do cat "$p"; done')
        sockets = self.call('exec', '-n', NS, POD, '-c', 'dex-server', '--', 'cat', '/proc/net/tcp', '/proc/net/tcp6')
        runtime_gate(idle, comm, sockets)
        identity(self.get(('v1', 'pods'), POD), POD_UID, POD)

    def delete(self, key, obj):
        path, options = delete_request(key, obj)
        try:
            self.call('delete', '--raw', path, '-f', '-', payload=json.dumps(options))
        except Exception:
            raise Refusal('DELETE failed or outcome uncertain; stop without retry; inspect exact UID') from None

    def observe(self, key, budget):
        """One bounded subprocess observes only the parent and its exact child names."""
        version, plural = key
        parent = plural + ('.' + version.split('/')[0] if '/' in version else '') + '/' + NAME
        uids = descendant_uids(GOALS[key])
        names = [parent] + [CHILD_RESOURCES[kind] + '/' + name for uid, (kind, name, _) in CHILDREN.items() if uid in uids]
        text = run([*self.base, '--request-timeout=' + str(max(1, int(budget))) + 's',
                    'get', *names, '-n', NS, '--ignore-not-found', '-o', 'json'], timeout=budget)
        doc = json.loads(text) if text.strip() else {'items': []}
        return doc.get('items', [doc] if doc.get('kind') != 'List' else [])


def identity(obj, uid, name=NAME):
    require(obj is not None, 'Required exact object is missing')
    m = obj['metadata']
    require(m.get('uid') == uid and m.get('name') == name and m.get('namespace') == NS
            and m.get('resourceVersion'), 'Object identity/resourceVersion mismatch')


def runtime_gate(idle, comm, tables):
    require(idle, 'No explicit idle/no-Dex-config runtime evidence')
    names = set(comm.splitlines())
    require('argocd-dex' in names and 'dex' not in names, 'Unexpected Dex process state')
    ports, headers = set(), 0
    for line in tables.splitlines():
        fields = line.split()
        if fields and fields[0] == 'sl':
            headers += 1
        elif fields:
            require(len(fields) >= 10 and re.fullmatch(r'[0-9A-Fa-f]+:[0-9A-Fa-f]{4}', fields[1]) is not None,
                    'Unparseable TCP listener evidence')
            if fields[3] == '0A':
                ports.add(int(fields[1].rsplit(':', 1)[1], 16))
    require(headers == 2 and not ports.intersection({5556, 5557, 5558}), 'Dex listener present or incomplete TCP evidence')


def manifest_gate(documents):
    require(documents and all(isinstance(x, dict) for x in documents), 'Missing/invalid rendered manifests')
    seen = set()
    for obj in documents:
        m = obj.get('metadata', {})
        key = (obj.get('kind'), m.get('namespace', NS), m.get('name'))
        require(key not in seen, 'Duplicate rendered identity')
        seen.add(key)
        require(not (m.get('namespace', NS) == NS and (m.get('name') == NAME or m.get('name', '').startswith(NAME + '-'))),
                'Desired state recreates a legacy object')
        if obj.get('kind') == 'ConfigMap' and m.get('name') in ['argocd-cm', 'argocd-cmd-params-cm']:
            no_sso(obj.get('data', {}))
    require({('Deployment', NS, 'argocd-server'), ('ConfigMap', NS, 'argocd-cm'),
             ('ConfigMap', NS, 'argocd-cmd-params-cm')} <= seen, 'Incomplete Argo manifest set')


def object_gate(key, obj):
    require(key in GOALS, 'Deletion outside fixed five-object plan')
    identity(obj, GOALS[key])
    require(obj.get('kind') == KINDS[key] and obj.get('apiVersion') == key[0], 'Resource kind/version mismatch')
    m = obj['metadata']
    require(not m.get('ownerReferences') and not m.get('finalizers') and not m.get('deletionTimestamp'),
            'Unexpected owner/finalizer or deletion already in progress')
    require(m.get('labels', {}).get('helm.sh/chart') == 'argo-cd-7.0.0'
            and not m.get('annotations', {}).get('argocd.argoproj.io/tracking-id'), 'Legacy ownership changed')
    if key[1] == 'deployments':
        ps = obj['spec']['template']['spec']
        require(ps.get('serviceAccountName') == NAME and obj['spec'].get('replicas') == 1, 'Legacy controller shape changed')
        require([v['name'] for v in ps.get('volumes', [])] == ['static-files', 'dexconfig', NAME + '-tls']
                and all('emptyDir' in v or (v.get('secret', {}).get('secretName') == NAME + '-tls'
                                          and v['secret'].get('optional') is True) for v in ps['volumes']), 'Unproven legacy storage')
        require([c['image'] for c in ps.get('containers', [])] == ['ghcr.io/dexidp/dex:v2.38.0']
                and [c['image'] for c in ps.get('initContainers', [])] == ['quay.io/argoproj/argocd:v2.11.2'], 'Legacy images changed')
        container = ps['containers'][0]
        require(container.get('command') == ['/shared/argocd-dex', '--logformat=text', '--loglevel=info']
                and container.get('args') == ['rundex'] and not container.get('envFrom'), 'Legacy wrapper command changed')
    if key[1] == 'services':
        require(obj['spec'].get('type') == 'ClusterIP' and obj['spec'].get('clusterIP') == '10.43.107.60'
                and obj['spec'].get('selector') == {'app.kubernetes.io/instance': NS, 'app.kubernetes.io/name': NAME}, 'Legacy Service changed')
        require([(p['port'], p.get('targetPort'), p.get('protocol')) for p in obj['spec'].get('ports', [])]
                == [(5556, 'http', 'TCP'), (5557, 'grpc', 'TCP')], 'Legacy Service ports changed')
    if key[1] == 'serviceaccounts':
        require(not obj.get('secrets') and not obj.get('imagePullSecrets'), 'Legacy SA owns/references authentication data')
    if key[1] == 'roles':
        require(obj.get('rules') == [{'apiGroups': [''], 'resources': ['secrets', 'configmaps'],
                                     'verbs': ['get', 'list', 'watch']}], 'Legacy Role permissions changed')
    if key[1] == 'rolebindings':
        require(obj.get('subjects') == [{'kind': 'ServiceAccount', 'name': NAME, 'namespace': NS}]
                and obj.get('roleRef') == {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': NAME}, 'Legacy RBAC sharing changed')


def descendant_gate(metadata, removed, observing=False):
    known = set(GOALS.values()) | set(CHILDREN)
    expected_names = {(kind, name): uid for uid, (kind, name, _) in CHILDREN.items()}
    for obj in metadata:
        m = obj['metadata']
        pair = (obj['kind'], m['name'])
        if pair in expected_names:
            require(m['uid'] == expected_names[pair], 'Descendant UID replaced')
        owners = m.get('ownerReferences', [])
        if m['uid'] in CHILDREN or any(o.get('uid') in known for o in owners):
            require(m['uid'] in CHILDREN, 'Unexpected cascading dependent; deletion forbidden')
            finalizers = m.get('finalizers', [])
            if observing:
                require(not finalizers or (finalizers == ['foregroundDeletion'] and m.get('deletionTimestamp')),
                        'Unexpected descendant finalizer during deletion; do not remove it')
            else:
                require(not finalizers and not m.get('deletionTimestamp'), 'Descendant finalizer or termination blocks deletion')
            kind, name, parent = CHILDREN[m['uid']]
            require(pair == (kind, name) and len(owners) == 1 and owners[0].get('uid') == parent,
                    'Descendant owner proof failed')
            parents = {uid: (KINDS[key], NAME) for key, uid in GOALS.items()}
            parents.update({uid: (child[0], child[1]) for uid, child in CHILDREN.items()})
            require((owners[0].get('kind'), owners[0].get('name')) == parents[parent], 'Descendant owner name/kind changed')
            require(parent not in removed, 'Deleted parent still has descendants')


def pod_spec(obj):
    spec = obj.get('spec', {})
    if obj['kind'] == 'CronJob':
        spec = spec.get('jobTemplate', {}).get('spec', {})
    return spec.get('template', {}).get('spec', spec)


def selector_matches(selector, labels):
    if not all(labels.get(k) == v for k, v in selector.get('matchLabels', {}).items()):
        return False
    for rule in selector.get('matchExpressions', []):
        key, op, values = rule['key'], rule['operator'], rule.get('values', [])
        require(op in ['In', 'NotIn', 'Exists', 'DoesNotExist'], 'Unknown monitor selector')
        if not {'In': key in labels and labels[key] in values, 'NotIn': key not in labels or labels[key] not in values,
                'Exists': key in labels, 'DoesNotExist': key not in labels}[op]:
            return False
    return True


def consumer_gate(objects):
    server_uids = {x['metadata']['uid'] for x in objects if x['kind'] == 'Deployment'
                   and x['metadata'].get('namespace') == NS and x['metadata']['name'] == 'argocd-server'}
    for _ in range(2):
        server_uids.update(x['metadata']['uid'] for x in objects if x['kind'] in ['ReplicaSet', 'Pod']
                           and any(o.get('uid') in server_uids for o in x['metadata'].get('ownerReferences', [])))
    labels = {'app.kubernetes.io/instance': NS, 'app.kubernetes.io/name': NAME,
              'app.kubernetes.io/component': 'dex-server', 'app.kubernetes.io/part-of': NS,
              'app.kubernetes.io/managed-by': 'Helm', 'app.kubernetes.io/version': 'v2.11.2',
              'helm.sh/chart': 'argo-cd-7.0.0', 'pod-template-hash': 'b4d796b55'}
    for original in objects:
        m, kind = original['metadata'], original['kind']
        if m['uid'] in set(GOALS.values()) | set(CHILDREN):
            continue
        obj = copy.deepcopy(original)
        obj.pop('status', None)
        obj['metadata'] = {k: v for k, v in m.items() if k != 'managedFields'}
        obj['metadata']['annotations'] = {k: v for k, v in m.get('annotations', {}).items()
                                           if k != 'kubectl.kubernetes.io/last-applied-configuration'}
        if kind == 'ConfigMap' and m.get('namespace') == NS and m['name'] in ['argocd-cm', 'argocd-cmd-params-cm']:
            no_sso(obj.get('data', {}))
        if m['uid'] in server_uids:
            ps = pod_spec(obj)
            for container in ps.get('containers', []):
                allowed = {'ARGOCD_SERVER_DEX_SERVER': 'server.dex.server',
                           'ARGOCD_SERVER_DEX_SERVER_PLAINTEXT': 'server.dex.server.plaintext',
                           'ARGOCD_SERVER_DEX_SERVER_STRICT_TLS': 'server.dex.server.strict.tls'}
                for env in container.get('env', []):
                    if env.get('name') in allowed:
                        require(env == {'name': env['name'], 'valueFrom': {'configMapKeyRef': {
                            'name': 'argocd-cmd-params-cm', 'key': allowed[env['name']], 'optional': True}}}, 'Active Dex env wiring changed')
                container['volumeMounts'] = [v for v in container.get('volumeMounts', []) if v['name'] != NAME + '-tls']
            for volume in ps.get('volumes', []):
                if volume['name'] == NAME + '-tls':
                    require(volume.get('secret', {}).get('secretName') == NAME + '-tls'
                            and volume['secret'].get('optional') is True, 'Shared TLS mount changed')
            ps['volumes'] = [v for v in ps.get('volumes', []) if v['name'] != NAME + '-tls']
        require(not REFERENCE.search(json.dumps(obj)), 'New/unexplained legacy Dex consumer; details withheld')
        if kind == 'Service' and m.get('namespace') == NS and obj['spec'].get('selector'):
            require(not selector_matches({'matchLabels': obj['spec']['selector']}, labels), 'Another Service selects legacy Dex')
        if kind in ['ServiceMonitor', 'PodMonitor']:
            spec = obj['spec']
            ns = spec.get('namespaceSelector', {})
            eligible = ns.get('any') or NS in ns.get('matchNames', [m.get('namespace')])
            require(not (eligible and selector_matches(spec.get('selector', {}), labels)), 'Monitor selects legacy Dex')


def fingerprint(obj):
    return {'uid': obj['metadata']['uid'], 'labels': obj['metadata'].get('labels', {}), **{k: v for k, v in obj.items()
            if k not in ['metadata', 'status', 'apiVersion', 'kind']}}


def protected(objects, metadata):
    result = {}
    for obj in objects:
        m, kind = obj['metadata'], obj['kind']
        if m['uid'] in set(GOALS.values()) | set(CHILDREN):
            continue
        if m.get('namespace') != NS and kind not in ['PersistentVolume', 'PersistentVolumeClaim', 'ClusterRole', 'ClusterRoleBinding', 'CustomResourceDefinition'] and not (kind == 'Namespace' and m['name'] == NS):
            continue
        require(not m.get('deletionTimestamp'), 'Protected object is deleting')
        if kind in ['Deployment', 'StatefulSet', 'DaemonSet']:
            status = obj.get('status', {})
            count = obj['spec'].get('replicas', 1) if kind != 'DaemonSet' else status.get('desiredNumberScheduled', 0)
            ready = status.get('readyReplicas', 0) if kind != 'DaemonSet' else status.get('numberReady', 0)
            require(ready == count and status.get('observedGeneration', 0) >= m.get('generation', 1), 'Active Argo controller unready')
        if kind == 'Pod':
            require(obj.get('status', {}).get('phase') == 'Succeeded' or any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in obj.get('status', {}).get('conditions', [])), 'Active Argo Pod unready')
        if kind in ['PersistentVolume', 'PersistentVolumeClaim']:
            require(obj.get('status', {}).get('phase') == 'Bound', 'Protected storage not Bound')
        result[(kind, m.get('namespace', ''), m['name'])] = fingerprint(obj)
        if kind == 'Pod':
            result[(kind, m.get('namespace', ''), m['name'])]['restarts'] = {
                c['name']: c['restartCount'] for c in obj.get('status', {}).get('containerStatuses', [])}
    for obj in metadata:
        if obj['kind'] == 'Secret':
            m = obj['metadata']
            require(not m.get('deletionTimestamp'), 'Protected Secret deleting')
            result[('Secret', NS, m['name'])] = m
    require(('ConfigMap', NS, 'argocd-cm') in result and ('Deployment', NS, 'argocd-server') in result
            and ('Secret', NS, 'argocd-secret') in result and ('Namespace', '', NS) in result, 'Protected active Argo inventory incomplete')
    require(any(k[0] == 'PersistentVolume' for k in result) and any(k[0] == 'PersistentVolumeClaim' for k in result),
            'Protected storage inventory empty')
    return result


def snapshot(api, head, removed):
    api.health(head)
    manifest_gate(api.manifests(head))
    objects, metadata = api.objects(), api.metadata()
    consumer_gate(objects)
    descendant_gate(metadata, removed)
    goals = {}
    for key, uid in GOALS.items():
        obj = api.get(key)
        if uid in removed:
            require(obj is None, 'Deleted name was recreated')
        else:
            object_gate(key, obj)
            goals[key] = obj
    if GOALS[('apps/v1', 'deployments')] not in removed:
        require(set(CHILDREN) <= {x['metadata']['uid'] for x in metadata}, 'Initial descendant inventory incomplete')
        api.runtime()
    else:
        require(not any(x['metadata']['uid'] in CHILDREN and x['kind'] != 'EndpointSlice' for x in metadata), 'Legacy workload descendant remains')
    return goals, protected(objects, metadata)


def delete_request(key, obj):
    object_gate(key, obj)
    version, plural = key
    prefix = '/api/v1' if version == 'v1' else '/apis/' + version
    return prefix + '/namespaces/' + NS + '/' + plural + '/' + NAME, {
        'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
        'preconditions': {'uid': GOALS[key], 'resourceVersion': obj['metadata']['resourceVersion']}}


def descendant_uids(parent):
    pending = {parent}
    for _ in range(len(CHILDREN)):
        pending.update(uid for uid, (_, _, owner) in CHILDREN.items() if owner in pending)
    return pending


def wait_absent(api, key, clock=time.monotonic, sleep=time.sleep):
    end = clock() + OBSERVE_SECONDS
    while True:
        budget = end - clock()
        require(budget > 0, 'Individual DELETE observation stalled; do not remove finalizers')
        objects = api.observe(key, budget)
        require(clock() < end, 'Individual DELETE observation stalled')
        descendant_gate(objects, set(), observing=True)
        for obj in objects:
            if obj['kind'] == KINDS[key] and obj['metadata']['name'] == NAME:
                identity(obj, GOALS[key])
                require(obj['metadata'].get('deletionTimestamp'), 'DELETE outcome uncertain; never resubmit')
            else:
                require(obj['metadata']['uid'] in descendant_uids(GOALS[key]), 'Unexpected observed descendant')
        if not objects:
            return
        sleep(1)


def execute(api, gate=source_gate, apply=False, emit=print, clock=time.monotonic, sleep=time.sleep):
    head, clean = gate(apply)
    require(not apply or clean, 'Source not apply-eligible')
    goals, baseline = snapshot(api, head, set())
    emit(json.dumps({'mode': 'apply' if apply else 'check', 'head': head, 'scoped_clean': clean,
                     'targets': [{'resource': key[1], 'uid': GOALS[key]} for key in goals],
                     'protected_count': len(baseline), 'opaque_consumers': 'not inspected'}))
    removed = set()
    try:
        if not apply:
            require(gate(False)[0] == head, 'Source changed during read-only check')
            return
        for key in GOALS:
            require(gate(True) == (head, True), 'Source changed or not apply-eligible')
            current, guard = snapshot(api, head, removed)
            require(guard == baseline, 'Protected identities/specs/config/Secret metadata changed')
            fresh = api.get(key)
            object_gate(key, fresh)
            require(fresh == current[key], 'Target changed before DELETE; do not retry')
            api.delete(key, fresh)
            emit(json.dumps({'delete_submitted': key[1], 'uid': GOALS[key]}))
            wait_absent(api, key, clock, sleep)
            removed.add(GOALS[key])
        snapshot(api, head, removed)
        emit(json.dumps({'retired_exact_objects': len(removed), 'maintenance_complete': False}))
    finally:
        try:
            require(protected(api.objects(), api.metadata()) == baseline, 'Final protected-state verification failed')
        finally:
            api.health(head)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='execute only the committed five-UID plan')
    args = parser.parse_args()
    try:
        api = API()
        api.establish()
        spec = importlib.util.spec_from_file_location('retirement_metadata_transport', ROOT / 'scripts/retire-workloads.py')
        transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transport)
        transport.Refusal = Refusal
        with transport.metadata_api(api) as metadata:
            api.metadata_api = metadata
            execute(api, apply=args.apply)
        return 0
    except Refusal as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
    except Exception:
        print('BLOCKED: unexpected evidence error; details withheld to protect credentials', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
