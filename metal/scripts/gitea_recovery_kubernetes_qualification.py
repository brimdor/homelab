"""Observe and exercise only the temporary Argo-owned recovery fixture.

The tracked caller publishes each generation and removes the chart in finally.
No production account, volume, application or recovery SQL is used here.
"""

from contextlib import contextmanager
import hashlib
import json
import re
import selectors
import shlex
import subprocess
import time

import gitea_init_guard as application
import gitea_postgres_startup_guard as postgres


NAMESPACE = 'maintenance-recovery-103'
PG = 'synthetic-postgresql-0'
PURPOSE = 'synthetic-recovery-qualification'


class Qualification:
    def __init__(self, kubectl):
        self.kubectl = list(kubectl)
        self.namespace_uid = None
        self.controllers = {}

    def call(self, *args, data=None, check=True):
        result = subprocess.run([*self.kubectl, *args], input=data, capture_output=True)
        if check and result.returncode:
            raise RuntimeError('synthetic Kubernetes command failed; raw output discarded; exit=' +
                               str(result.returncode))
        return result

    def get(self, kind, name=None, namespace=NAMESPACE):
        args = ['get', kind, *([name] if name else []), '-o', 'json']
        if namespace:
            args.extend(['-n', namespace])
        return json.loads(self.call(*args).stdout)

    def identity(self):
        if self.get('namespace', 'kube-system', namespace=None)['metadata']['uid'] != application.common.CLUSTER_UID:
            raise RuntimeError('qualification target cluster differs')
        namespace = self.get('namespace', NAMESPACE, namespace=None)
        metadata = namespace['metadata']
        if (metadata.get('deletionTimestamp') or
                metadata.get('labels', {}).get('maintenance103.eaglepass.io/purpose') != PURPOSE or
                not metadata.get('uid') or
                (self.namespace_uid is not None and metadata['uid'] != self.namespace_uid)):
            raise RuntimeError('synthetic namespace identity differs')
        self.namespace_uid = metadata['uid']
        owner = self.get('application', NAMESPACE, namespace='argocd')
        if (owner['spec']['source']['path'] != 'apps/' + NAMESPACE or
                owner['spec']['destination']['namespace'] != NAMESPACE or
                'resources-finalizer.argocd.argoproj.io' not in owner['metadata'].get('finalizers', [])):
            raise RuntimeError('synthetic Argo owner or cascade finalizer differs')
        policy = self.get('networkpolicy', 'deny-all')['spec']
        if (policy.get('podSelector') != {} or set(policy['policyTypes']) != {'Ingress', 'Egress'} or
                policy.get('ingress', []) or policy.get('egress', [])):
            raise RuntimeError('synthetic traffic isolation differs')
        for kind, name in [('deployment', 'synthetic-gitea'), ('statefulset', 'synthetic-postgresql')]:
            item = self.get(kind, name)
            key = kind + '/' + name
            if key in self.controllers and self.controllers[key] != item['metadata']['uid']:
                raise RuntimeError('synthetic owning controller changed')
            self.controllers[key] = item['metadata']['uid']
        return self.namespace_uid

    def pods(self):
        self.identity()
        pods = self.get('pods')['items']
        for pod in pods:
            spec = pod['spec']
            if (spec.get('automountServiceAccountToken') is not False or
                    spec.get('hostNetwork') or spec.get('hostPID') or spec.get('hostIPC') or
                    spec.get('nodeName') not in (None, 'pikachu') or
                    any(not set(v) <= {'name', 'emptyDir', 'configMap', 'secret'} for v in spec['volumes'])):
                raise RuntimeError('synthetic Pod acquired unexpected access or storage')
            owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
            if len(owners) != 1:
                raise RuntimeError('synthetic Pod controller missing')
            owner = owners[0]
            if pod['metadata']['name'] == PG:
                expected = self.controllers['statefulset/synthetic-postgresql']
            else:
                if owner['kind'] != 'ReplicaSet':
                    raise RuntimeError('synthetic application ReplicaSet missing')
                replica = self.get('replicaset', owner['name'])
                if (replica['metadata']['uid'] != owner['uid'] or
                        not any(o.get('controller') and o['uid'] == self.controllers['deployment/synthetic-gitea']
                                for o in replica['metadata'].get('ownerReferences', []))):
                    raise RuntimeError('synthetic application owning Deployment differs')
                expected = replica['metadata']['uid']
            if owner['uid'] != expected:
                raise RuntimeError('synthetic Pod owner UID differs')
            for container in [*spec.get('initContainers', []), *spec['containers']]:
                security = container.get('securityContext', {})
                if (container['image'] not in {application.IMAGE, postgres.recovery.control.IMAGE} or
                        security.get('allowPrivilegeEscalation') is not False or
                        security.get('readOnlyRootFilesystem') is not True or
                        security.get('capabilities') != {'drop': ['ALL']}):
                    raise RuntimeError('synthetic container image or privileges differ')
        return pods

    def pod(self, name):
        matches = [p for p in self.pods() if p['metadata']['name'] == name]
        if len(matches) != 1:
            raise RuntimeError('synthetic Pod identity missing')
        return matches[0]

    def execute(self, pod, container, *args, data=None, check=True):
        self.pod(pod)
        return self.call('exec', '-i', '-n', NAMESPACE, pod, '-c', container, '--', *args,
                         data=data, check=check)

    @staticmethod
    def wait_for(check, message, seconds=180):
        deadline = time.monotonic() + seconds
        while not check():
            if time.monotonic() >= deadline:
                raise RuntimeError(message)
            time.sleep(0.2)

    def ready(self):
        for kind, name in [('deployment', 'synthetic-gitea'), ('statefulset', 'synthetic-postgresql')]:
            self.call('rollout', 'status', kind + '/' + name, '-n', NAMESPACE, '--timeout=300s')
        self.identity()

    def current_uids(self):
        pods = self.pods()
        if len(pods) != 2:
            raise RuntimeError('synthetic baseline must have exactly two Pods')
        return {p['metadata']['name']: p['metadata']['uid'] for p in pods}

    @contextmanager
    def held_generation(self, previous):
        children = []
        held = {}
        try:
            def acquire():
                for pod in self.pods():
                    name, uid = pod['metadata']['name'], pod['metadata']['uid']
                    if uid in previous.values() or pod['metadata'].get('deletionTimestamp'):
                        continue
                    is_pg = name == PG
                    kind = 'postgresql' if is_pg else 'application'
                    if kind in held:
                        continue
                    container = 'postgresql' if is_pg else 'maintenance-103-init'
                    states = pod['status'].get('containerStatuses' if is_pg else 'initContainerStatuses', [])
                    if not any(s['name'] == container and s.get('state', {}).get('running') for s in states):
                        continue
                    module = postgres if is_pg else application
                    phase = self.execute(name, container, '/bin/cat', module.STATE + '/phase', check=False)
                    if phase.returncode:
                        continue
                    if phase.stdout != b'waiting\n':
                        raise RuntimeError('synthetic claim window closed before acquisition')
                    command = [*self.kubectl, 'exec', '-i', '-n', NAMESPACE, name, '-c', container,
                               '--', '/bin/bash', '-ceu', module.CLAIM]
                    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    children.append(child)
                    with selectors.DefaultSelector() as selector:
                        selector.register(child.stdout, selectors.EVENT_READ)
                        if not selector.select(20):
                            raise RuntimeError('synthetic attached controller handshake missing')
                        match = re.fullmatch(rb'HOMELAB103:CLAIMED:([0-9]+)\n', child.stdout.readline())
                    if not match:
                        raise RuntimeError('synthetic attached controller did not acquire lock')
                    held[kind] = {'pod': name, 'uid': uid, 'container': container,
                                  'child': child, 'pid': match[1].decode()}
                return len(held) == 2
            self.wait_for(acquire, 'new synthetic guards were not acquired', seconds=300)
            if any(p['metadata']['uid'] in previous.values() for p in self.pods()):
                raise RuntimeError('previous synthetic writers remain')
            self.assert_held(held)
            yield held
        finally:
            for child in children:
                if child.poll() is None:
                    try:
                        child.communicate(timeout=20)
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream and not stream.closed:
                        stream.close()

    def assert_held(self, held):
        for kind, item in held.items():
            if self.pod(item['pod'])['metadata']['uid'] != item['uid'] or item['child'].poll() is not None:
                raise RuntimeError('synthetic guard ownership lost')
            module = postgres if kind == 'postgresql' else application
            phase = self.execute(item['pod'], item['container'], '/bin/cat', module.STATE + '/phase').stdout
            if phase != b'waiting\n':
                raise RuntimeError('synthetic ordinary startup escaped the hold')
            path = '/bitnami/postgresql/data/postmaster.pid' if kind == 'postgresql' else '/tmp/initialization-completed'
            self.execute(item['pod'], item['container'], '/bin/bash', '-ceu',
                         '[[ ! -e "$1" ]]', 'synthetic-no-writer', path)

    def release(self, item, killed=False):
        output, errors = item['child'].communicate()
        expected_error = b'command terminated with exit code 137\n' if killed else b''
        if item['child'].returncode != (137 if killed else 0) or output or errors != expected_error:
            raise RuntimeError('synthetic attached controller disposition differs')

    def kill_controller(self, item):
        self.execute(item['pod'], item['container'], '/bin/kill', '-KILL', item['pid'])
        self.release(item, killed=True)

    def pg_ready(self):
        self.call('wait', '--for=condition=Ready', 'pod/' + PG, '-n', NAMESPACE, '--timeout=300s')

    def corpus(self, create=False):
        sql = ('CREATE TABLE qualification_corpus (id integer PRIMARY KEY, value text); '
               "INSERT INTO qualification_corpus SELECT n,md5(n::text) FROM generate_series(1,1000) n; "
               if create else '')
        sql += 'COPY (SELECT * FROM qualification_corpus ORDER BY id) TO STDOUT;'
        raw = self.execute(PG, 'postgresql', '/usr/bin/env',
                           'PGPASSWORD=synthetic-qualification-app-only',
                           postgres.recovery.BIN + 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
                           '-h', '127.0.0.1', '-U', 'gitea', '-d', 'gitea', '-c', sql).stdout
        if len(raw.splitlines()) != 1000:
            raise RuntimeError('synthetic complete corpus row count differs')
        return hashlib.sha256(raw).hexdigest()

    def restart_container(self, pod, container):
        """Stop only an immutable, doubly checked synthetic CRI container ID."""
        self.identity()
        p = self.pod(pod)
        statuses = [*p['status'].get('containerStatuses', []), *p['status'].get('initContainerStatuses', [])]
        status = next(s for s in statuses if s['name'] == container)
        match = re.fullmatch('containerd://([a-f0-9]{64})', status['containerID'])
        if not match or not status.get('state', {}).get('running'):
            raise RuntimeError('synthetic running CRI container missing')
        request = {'id': match[1], 'namespace': NAMESPACE, 'pod': pod,
                   'uid': p['metadata']['uid'], 'container': container}
        source = '''import json,re,subprocess,sys
v=json.load(sys.stdin)
assert v['namespace']=='maintenance-recovery-103' and re.fullmatch('[a-f0-9]{64}',v['id'])
assert subprocess.check_output(['hostname','-s']).strip()==b'pikachu'
prefix=['/usr/local/bin/k3s','crictl','--runtime-endpoint','unix:///run/k3s/containerd/containerd.sock']
value=json.loads(subprocess.check_output(prefix+['inspect',v['id']]))['status']
assert value['id']==v['id'] and value['state']=='CONTAINER_RUNNING'
assert value['metadata']['name']==v['container']
for k,w in [('namespace',v['namespace']),('name',v['pod']),('uid',v['uid'])]:
 assert value['labels']['io.kubernetes.pod.'+k]==w
p=subprocess.run(prefix+['stop','--timeout','5',v['id']],capture_output=True)
assert p.returncode==0
print(json.dumps({'stopped_exact_synthetic_container':True}))
'''
        ssh = [*application.common.SSH, 'python3', '-B', '-c', shlex.quote(source)]
        result = subprocess.run(ssh, input=json.dumps(request).encode(), capture_output=True)
        if result.returncode or json.loads(result.stdout) != {'stopped_exact_synthetic_container': True}:
            raise RuntimeError('exact synthetic CRI stop refused; raw output discarded')
        return {'pod_uid': p['metadata']['uid'], 'old_container_id': status['containerID'],
                'old_restart_count': status['restartCount']}

    def verify_pg_restart(self, before, corpus):
        def restarted():
            pod = self.pod(PG)
            if pod['metadata']['uid'] != before['pod_uid']:
                raise RuntimeError('synthetic restart replaced the Pod')
            status = pod['status']['containerStatuses'][0]
            return (status['restartCount'] > before['old_restart_count'] and status['ready'] and
                    status['containerID'] != before['old_container_id'])
        self.wait_for(restarted, 'same-Pod PostgreSQL container did not restart', seconds=300)
        if self.corpus() != corpus:
            raise RuntimeError('same-Pod container restart changed synthetic corpus')
        if self.execute(PG, 'postgresql', '/bin/cat', postgres.STATE + '/phase').stdout != b'normal\n':
            raise RuntimeError('retained PostgreSQL claim window reopened')
        refused = self.execute(PG, 'postgresql', '/bin/bash', '-ceu', postgres.CLAIM, check=False)
        if refused.returncode != 1:
            raise RuntimeError('normal synthetic postmaster allowed a late controller')

    def exercise(self, next_generation, await_health, persist):
        """Caller prefetches this flow and guarantees canonical cleanup in finally."""
        self.identity()
        self.ready()
        await_health()
        persist('baseline', namespace_uid=self.namespace_uid, pod_uids=self.current_uids())
        for mode in ('eof', 'controller-killed', 'init-container-restarted'):
            old = self.current_uids()
            next_generation(mode)
            with self.held_generation(old) as held:
                end = time.monotonic() + 31
                while time.monotonic() < end:
                    self.assert_held(held)
                    time.sleep(0.5)
                persist('both-guards-held-' + mode, old_pods_gone=True,
                        ordinary_start_excluded_beyond_claim_window=True)
                if mode == 'controller-killed':
                    self.kill_controller(held['postgresql'])
                else:
                    self.release(held['postgresql'])
                self.pg_ready()
                corpus = self.corpus(create=True)
                self.assert_held({'application': held['application']})
                if mode == 'eof':
                    before = self.restart_container(PG, 'postgresql')
                    self.verify_pg_restart(before, corpus)
                    self.assert_held({'application': held['application']})
                    self.release(held['application'])
                    persist('same-pod-postgresql-restarted', corpus_sha256=corpus,
                            pod_uid=before['pod_uid'], retained_window_closed=True)
                elif mode == 'controller-killed':
                    self.kill_controller(held['application'])
                else:
                    item = held['application']
                    before = self.restart_container(item['pod'], item['container'])
                    self.ready()
                    pod = self.pod(item['pod'])
                    status = next(s for s in pod['status']['initContainerStatuses'] if s['name'] == item['container'])
                    if (pod['metadata']['uid'] != before['pod_uid'] or
                            status['restartCount'] <= before['old_restart_count'] or
                            status['state']['terminated']['exitCode'] != 0):
                        raise RuntimeError('same-Pod initialization container restart failed')
                    item['child'].communicate(timeout=20)
                    persist('same-pod-init-container-restarted', pod_uid=before['pod_uid'],
                            init_restart_count=status['restartCount'],
                            old_attached_controller_exit=item['child'].returncode,
                            retained_window_closed=True)
                self.ready()
                if self.corpus() != corpus:
                    raise RuntimeError('synthetic fallback changed complete corpus')
            await_health()
            persist('generation-' + mode, complete_synthetic_corpus_unchanged=True, automatic_fallback=True)
        old = self.current_uids()
        next_generation('controller-absent')
        self.ready()
        if set(self.current_uids().values()) & set(old.values()):
            raise RuntimeError('absent-controller generation retained an old Pod')
        self.corpus(create=True)
        await_health()
        persist('generation-controller-absent', automatic_fallback=True)
