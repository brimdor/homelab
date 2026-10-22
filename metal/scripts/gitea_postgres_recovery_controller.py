"""Prefetched controller for the approved existing PostgreSQL-role recovery.

The caller publishes the reviewed recovery profile through canonical GitOps and
restores the plain profile afterward. All credentials/catalogs remain in RAM.
"""

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

import gitea_init_guard as application
import gitea_postgres_guarded_source as source
import gitea_recovery_transport as transport
import gitea_shared_guarded_source as shared


recovery = source.recovery
common = source.common
PG = 'gitea-postgresql-0'
NAMESPACE = 'gitea'
DEPLOYMENT_UID = '478cb556-8f9e-45c0-9cd9-413c8a33ef3d'
STATEFULSET_UID = '80aac4a0-46ec-4564-84db-d99c440780e9'


class Controller:
    def __init__(self, kubectl, bundle, *, capture_only=False, source_image=source.cold.control.IMAGE):
        if source_image not in (source.cold.control.IMAGE, source.cold.control.MAINTAINED_IMAGE):
            raise RuntimeError('unreviewed production PostgreSQL source image')
        if source_image == source.cold.control.MAINTAINED_IMAGE and not capture_only:
            raise RuntimeError('maintained PostgreSQL source permits capture only, never role recovery')
        self.source_image = source_image
        self.kubectl = list(kubectl)
        self.bundle = bundle
        self.namespace_uid = None
        self.old_uids = set()
        self.valkey = {}
        self.secrets = {}
        self.revision = None
        self.credentials = None
        self.hba = None
        self.capture_only = capture_only

    def call(self, *args, data=None, check=True):
        result = subprocess.run([*self.kubectl, *args], input=data, capture_output=True)
        if check and result.returncode:
            raise RuntimeError('production recovery Kubernetes command failed; raw output withheld; exit=' + str(result.returncode))
        return result

    def get(self, kind, name=None, namespace=NAMESPACE):
        return json.loads(self.call('get', kind, *([name] if name else []),
                                    *(['-n', namespace] if namespace else []), '-o', 'json').stdout)

    def execute(self, item, *args, data=None, check=True):
        pod = self.get('pod', item['pod'])
        if pod['metadata']['uid'] != item['uid'] or pod['metadata'].get('deletionTimestamp'):
            raise RuntimeError('production recovery Pod binding changed')
        return self.call('exec', '-i', '-n', NAMESPACE, item['pod'], '-c', item['container'],
                         '--', *args, data=data, check=check)

    @staticmethod
    def wait_for(check, message, seconds=300):
        end = time.monotonic() + seconds
        while not check():
            if time.monotonic() >= end:
                raise RuntimeError(message)
            time.sleep(0.2)

    def identity(self):
        if self.get('namespace', 'kube-system', namespace=None)['metadata']['uid'] != common.CLUSTER_UID:
            raise RuntimeError('production recovery cluster differs')
        namespace = self.get('namespace', NAMESPACE, namespace=None)['metadata']
        if namespace.get('deletionTimestamp') or (self.namespace_uid and namespace['uid'] != self.namespace_uid):
            raise RuntimeError('production recovery namespace changed')
        self.namespace_uid = namespace['uid']
        owner = self.get('application', 'gitea', namespace='argocd')
        if (owner['spec']['source']['path'] != 'platform/gitea' or
                owner['spec']['source']['repoURL'] != 'http://gitea-http.gitea:3000/ops/homelab' or
                owner['spec']['source']['targetRevision'] != 'master' or
                owner['spec']['destination']['namespace'] != NAMESPACE):
            raise RuntimeError('production Gitea owning source differs')
        if self.revision and (owner['status']['sync']['revision'] != self.revision or
                              owner['status']['sync']['status'] != 'Synced'):
            raise RuntimeError('production recovery profile has not reached its exact revision')
        deployment = self.get('deployment', 'gitea')
        stateful = self.get('statefulset', 'gitea-postgresql')
        if (deployment['metadata']['uid'] != DEPLOYMENT_UID or deployment['spec']['replicas'] != 1 or
                deployment['spec']['strategy']['type'] != 'Recreate' or
                stateful['metadata']['uid'] != STATEFULSET_UID or stateful['spec']['replicas'] != 1):
            raise RuntimeError('production database/application owning controller differs')
        claim = self.get('persistentvolumeclaim', 'data-gitea-postgresql-0')
        volume = self.get('persistentvolume', 'pvc-4d6d356d-ec5d-4f2e-961e-090eae9e0c21', namespace=None)
        if (claim['metadata']['uid'] != '4d6d356d-ec5d-4f2e-961e-090eae9e0c21' or
                claim['status']['phase'] != 'Bound' or claim['spec']['volumeName'] != volume['metadata']['name'] or
                volume['metadata']['uid'] != '5cadac3d-dd99-4e3e-8551-4d165826cf44' or
                volume['spec']['claimRef']['uid'] != claim['metadata']['uid'] or
                volume['spec']['claimRef']['namespace'] != NAMESPACE or
                volume['spec']['csi']['driver'] != 'rook-ceph.rbd.csi.ceph.com'):
            raise RuntimeError('production PostgreSQL PVC/PV/CSI binding differs')
        return owner

    def wait_application_ready(self, item=None, seconds=300):
        # A deliberate startup hold can expire rollout's progress deadline before release.
        bound_uid = item['uid'] if item else None

        def ready():
            nonlocal bound_uid
            self.identity()
            deployment = self.get('deployment', 'gitea')
            if deployment['metadata'].get('deletionTimestamp'):
                raise RuntimeError('production application controller is deleting')
            candidates = []
            for pod in self.get('pods')['items']:
                owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
                if len(owners) != 1 or owners[0]['kind'] != 'ReplicaSet':
                    continue
                replica = self.get('replicaset', owners[0]['name'])
                if replica['metadata']['uid'] != owners[0]['uid']:
                    raise RuntimeError('production application ReplicaSet binding changed')
                if any(o.get('controller') and o['uid'] == DEPLOYMENT_UID
                       for o in replica['metadata'].get('ownerReferences', [])):
                    candidates.append(pod)
            if len(candidates) != 1:
                raise RuntimeError('released production application must have one owned Pod')
            pod = candidates[0]
            if (pod['metadata'].get('deletionTimestamp') or
                    (bound_uid and pod['metadata']['uid'] != bound_uid) or
                    (item and pod['metadata']['name'] != item['pod'])):
                raise RuntimeError('released production application Pod binding changed')
            bound_uid = pod['metadata']['uid']
            statuses = pod['status'].get('initContainerStatuses', [])
            if any(s.get('state', {}).get('terminated', {}).get('exitCode', 0) != 0 for s in statuses):
                raise RuntimeError('released production application init failed')
            init_names = {c['name'] for c in pod['spec'].get('initContainers', [])}
            init_ready = ({s['name'] for s in statuses} == init_names and
                          all(s.get('state', {}).get('terminated', {}).get('exitCode') == 0 for s in statuses))
            main = pod['status'].get('containerStatuses', [])
            conditions = {c['type']: c['status'] for c in deployment['status'].get('conditions', [])}
            return (init_ready and pod['status'].get('phase') == 'Running' and
                    any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status'].get('conditions', [])) and
                    {s['name'] for s in main} == {c['name'] for c in pod['spec']['containers']} and
                    all(s.get('ready') and s.get('state', {}).get('running') for s in main) and
                    deployment['status'].get('observedGeneration') == deployment['metadata']['generation'] and
                    all(deployment['status'].get(k) == 1 for k in
                        ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')) and
                    conditions.get('Available') == 'True' and conditions.get('Progressing') == 'True')

        self.wait_for(ready, 'released production application did not become ready', seconds=seconds)

    def baseline(self):
        self.identity()
        pods = self.get('pods')['items']
        if len(pods) != 8 or any(not all(s['ready'] for s in p['status'].get('containerStatuses', []))
                                 or not p['status'].get('containerStatuses') for p in pods):
            raise RuntimeError('production Gitea baseline must have eight ready workloads')
        self.old_uids = {p['metadata']['uid'] for p in pods}
        self.valkey = {p['metadata']['uid']: p['status']['containerStatuses'] for p in pods
                       if p['metadata']['name'].startswith('gitea-valkey-cluster-')}
        if len(self.valkey) != 6:
            raise RuntimeError('production six-member Valkey baseline differs')
        for name in ('gitea', 'gitea-init', 'gitea-inline-config', 'gitea-postgresql'):
            value = self.get('secret', name)
            self.secrets[name] = (value['metadata']['uid'], value['data'])
        secret = self.secrets['gitea-postgresql'][1]
        self.credentials = {'admin': base64.b64decode(secret['postgres-password'], validate=True).decode(),
                            'app': base64.b64decode(secret['password'], validate=True).decode()}
        pod = next(p for p in pods if p['metadata']['name'] == PG)
        item = {'pod': PG, 'uid': pod['metadata']['uid'], 'container': 'postgresql'}
        if next(s for s in pod['status']['containerStatuses'] if s['name'] == 'postgresql')['imageID'] != self.source_image:
            raise RuntimeError('production PostgreSQL baseline image differs')
        hba_path = ('/configuration/pg_hba.conf' if self.source_image == source.cold.control.MAINTAINED_IMAGE
                    else '/opt/bitnami/postgresql/conf/pg_hba.conf')
        self.hba = self.execute(item, '/bin/cat', hba_path).stdout
        if hashlib.sha256(self.hba).hexdigest() != '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05':
            raise RuntimeError('production existing HBA differs')

    def preserved(self):
        pods = self.get('pods')['items']
        if {p['metadata']['uid']: p['status'].get('containerStatuses') for p in pods
                if p['metadata']['name'].startswith('gitea-valkey-cluster-')} != self.valkey:
            raise RuntimeError('unmodified production Valkey runtime changed')
        for name, expected in self.secrets.items():
            value = self.get('secret', name)
            if (value['metadata']['uid'], value['data']) != expected:
                raise RuntimeError('existing production Secret identity or bytes changed')

    def attach(self, pod, container, command):
        item = {'pod': pod['metadata']['name'], 'uid': pod['metadata']['uid'], 'container': container}
        child = subprocess.Popen([*self.kubectl, 'exec', '-i', '-n', NAMESPACE, item['pod'],
                                  '-c', container, '--', *command],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        item['child'] = child
        return item

    @contextmanager
    def held(self):
        held, children = {}, []
        try:
            def acquire():
                for pod in self.get('pods')['items']:
                    name, uid = pod['metadata']['name'], pod['metadata']['uid']
                    if uid in self.old_uids or pod['metadata'].get('deletionTimestamp'):
                        continue
                    is_pg = name == PG
                    kind = 'postgresql' if is_pg else 'application'
                    if kind in held:
                        continue
                    owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
                    if len(owners) != 1:
                        raise RuntimeError('new production Pod owner missing')
                    if is_pg:
                        if owners[0]['uid'] != STATEFULSET_UID:
                            raise RuntimeError('new production PostgreSQL owner differs')
                    else:
                        if owners[0]['kind'] != 'ReplicaSet' or not name.startswith('gitea-'):
                            continue
                        replica = self.get('replicaset', owners[0]['name'])
                        if (replica['metadata']['uid'] != owners[0]['uid'] or
                                not any(o.get('controller') and o['uid'] == DEPLOYMENT_UID
                                        for o in replica['metadata'].get('ownerReferences', []))):
                            raise RuntimeError('new production application owner differs')
                    container = 'postgresql' if is_pg else 'maintenance-103-init'
                    statuses = pod['status'].get('containerStatuses' if is_pg else 'initContainerStatuses', [])
                    running = next((s for s in statuses if s['name'] == container and s.get('state', {}).get('running')), None)
                    if not running:
                        continue
                    image = self.source_image if is_pg else application.IMAGE
                    if running['imageID'] != image:
                        raise RuntimeError('production recovery native image differs')
                    module = source.startup if is_pg else application
                    item = {'pod': name, 'uid': uid, 'container': container}
                    phase = self.execute(item, '/bin/cat', module.STATE + '/phase', check=False)
                    if phase.returncode:
                        continue
                    if phase.stdout != b'waiting\n':
                        raise RuntimeError('production recovery claim window closed; no SQL allowed')
                    command = ((source.CAPTURE_CONTROLLER if self.capture_only else source.CONTROLLER)
                               if is_pg else ['/bin/bash', '-ceu', application.CLAIM])
                    item = self.attach(pod, container, command)
                    children.append(item['child'])
                    with selectors.DefaultSelector() as selector:
                        selector.register(item['child'].stdout, selectors.EVENT_READ)
                        if not selector.select(20):
                            raise RuntimeError('production controller handshake missing; no SQL allowed')
                        match = re.fullmatch(rb'HOMELAB103:CLAIMED:([0-9]+)\n', item['child'].stdout.readline())
                    if not match:
                        raise RuntimeError('production controller did not acquire guard; no SQL allowed')
                    item['namespace_pid'] = int(match[1])
                    held[kind] = item
                return len(held) == 2
            self.wait_for(acquire, 'new production recovery guards were not acquired')
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
        pods = self.get('pods')['items']
        if any(p['metadata']['uid'] in self.old_uids and p['metadata']['uid'] not in self.valkey for p in pods):
            raise RuntimeError('an old production application/database writer remains')
        pg = self.get('pod', PG)
        consumers = [p['metadata']['uid'] for p in pods if any(
            v.get('persistentVolumeClaim', {}).get('claimName') == 'data-gitea-postgresql-0'
            for v in p['spec']['volumes'])]
        if consumers != [pg['metadata']['uid']]:
            raise RuntimeError('production database claim has an unexpected consumer')
        for kind, item in held.items():
            module = source.startup if kind == 'postgresql' else application
            if item['child'].poll() is not None or self.execute(item, '/bin/cat', module.STATE + '/phase').stdout != b'waiting\n':
                raise RuntimeError('production startup hold was lost')
            if kind == 'application':
                p = next(p for p in pods if p['metadata']['uid'] == item['uid'])
                if any(s.get('state', {}).get('running') for s in p['status'].get('containerStatuses', [])):
                    raise RuntimeError('new production application started before recovery verification')
        self.preserved()

    def source_core(self, held):
        self.identity()
        self.assert_held(held)
        pg = self.get('pod', PG)
        status = next(s for s in pg['status']['containerStatuses'] if s['name'] == 'postgresql')
        match = re.fullmatch('containerd://([a-f0-9]{64})', status['containerID'])
        if not match:
            raise RuntimeError('production PostgreSQL runtime ID differs')
        node = self.get('node', pg['spec']['nodeName'], namespace=None)
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        if (conditions.get('Ready') != 'True' or any(conditions.get(c) != 'False' for c in
                ('MemoryPressure', 'DiskPressure', 'PIDPressure')) or node['metadata']['name'] not in self.bundle.nodes):
            raise RuntimeError('production PostgreSQL source node is not ready active inventory')
        return {'cluster_uid': common.CLUSTER_UID, 'namespace': NAMESPACE, 'pod': PG,
                'pod_uid': pg['metadata']['uid'], 'controller_uid': STATEFULSET_UID,
                'node': node['metadata']['name'], 'container_id': match[1], 'image': self.source_image,
                'claim': 'data-gitea-postgresql-0', 'claim_uid': '4d6d356d-ec5d-4f2e-961e-090eae9e0c21',
                'pv': 'pvc-4d6d356d-ec5d-4f2e-961e-090eae9e0c21',
                'pv_uid': '5cadac3d-dd99-4e3e-8551-4d165826cf44', 'revision': self.revision,
                'hba_sha256': hashlib.sha256(self.hba).hexdigest()}

    def shared_core(self, held):
        self.identity()
        self.assert_held(held)
        item = held['application']
        pod = self.get('pod', item['pod'])
        claim = self.get('persistentvolumeclaim', 'gitea-shared-storage')
        volume = self.get('persistentvolume', 'pvc-' + shared.CLAIM_UID, namespace=None)
        consumers = [p['metadata']['uid'] for p in self.get('pods')['items'] if any(
            v.get('persistentVolumeClaim', {}).get('claimName') == 'gitea-shared-storage'
            for v in p['spec']['volumes'])]
        if (claim['metadata']['uid'] != shared.CLAIM_UID or claim['status']['phase'] != 'Bound' or
                claim['spec']['volumeName'] != volume['metadata']['name'] or
                volume['metadata']['uid'] != shared.PV_UID or
                volume['spec']['claimRef']['uid'] != shared.CLAIM_UID or
                volume['spec']['claimRef']['namespace'] != NAMESPACE or
                volume['spec']['csi']['driver'] != 'rook-ceph.rbd.csi.ceph.com' or
                claim['spec']['accessModes'] != ['ReadWriteOnce'] or
                claim['spec']['storageClassName'] != 'standard-rwo' or consumers != [item['uid']]):
            raise RuntimeError('production shared-file claim has a changed binding or unexpected consumer')
        status = next(s for s in pod['status']['initContainerStatuses'] if s['name'] == item['container'])
        match = re.fullmatch('containerd://([a-f0-9]{64})', status['containerID'])
        node = self.get('node', pod['spec']['nodeName'], namespace=None)
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        if (not match or status['imageID'] != application.IMAGE or node['metadata']['name'] not in self.bundle.nodes or
                conditions.get('Ready') != 'True' or any(conditions.get(c) != 'False' for c in
                ('MemoryPressure', 'DiskPressure', 'PIDPressure'))):
            raise RuntimeError('production shared-file native image or active source node differs')
        return shared.validate_core({'cluster_uid': common.CLUSTER_UID, 'namespace': NAMESPACE,
            'pod': item['pod'], 'pod_uid': item['uid'], 'controller_uid': DEPLOYMENT_UID,
            'node': node['metadata']['name'], 'container_id': match[1], 'image': application.IMAGE,
            'claim': 'gitea-shared-storage', 'claim_uid': shared.CLAIM_UID, 'pv': 'pvc-' + shared.CLAIM_UID,
            'pv_uid': shared.PV_UID, 'revision': self.revision})

    @staticmethod
    def read_catalog(child):
        raw = bytearray()
        end = time.monotonic() + 60
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while time.monotonic() < end:
                if not selector.select(max(0, end - time.monotonic())):
                    break
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if re.search(rb'HOMELAB103:[0-9a-f]+\r?\n', raw):
                    return recovery.parse_catalog(bytes(raw))
        raise RuntimeError('offline catalog response missing; raw output withheld; never replay SQL')

    def client(self, item, role, binary, *args):
        password = self.credentials['admin' if role == 'postgres' else 'app']
        if any(c in password for c in '\r\n\0'):
            raise RuntimeError('production declared credential framing differs')
        script = 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"'
        binary_dir = ('/usr/lib/postgresql/16/bin/' if self.source_image == source.cold.control.MAINTAINED_IMAGE
                      else recovery.BIN)
        return self.execute(item, '/bin/sh', '-c', script, 'credential-stdin', binary_dir + binary,
                            '-h', '127.0.0.1', '-U', role, *args,
                            data=(password + '\n').encode()).stdout

    def recover(self, run_id, persist):
        """Run after the caller publishes/refreshes the exact reviewed profile."""
        if self.capture_only:
            raise RuntimeError('capture-only controller cannot run role recovery')
        common.run_identifier(run_id)
        if self.credentials is None or not self.old_uids or not self.revision:
            raise RuntimeError('prefetched baseline or deployed profile binding missing')
        with self.held() as held:
            core = self.source_core(held)
            capture = self.bundle.run(core['node'], 'capture', core=core,
                                      namespace_pid=held['postgresql']['namespace_pid'], run_id=run_id)
            self.assert_held(held)
            persist('source-point', **capture)
            received = self.bundle.transfer(core['node'], capture['point'], capture['manifest_sha256'], capture['source'], run_id)
            persist('received-point', **received)
            response = self.bundle.run('pikachu', 'restore', **transport.restore_args(
                received['point'], received['manifest_sha256'], self.credentials, self.hba, run_id))
            if not response['summary']['accepted'] or response['summary']['independent_copies'] != 2:
                raise RuntimeError('fresh independent restore acceptance missing; no role SQL allowed')
            baseline = response['catalog']
            expected_dumps = response['summary']['copies'][0]['full_dump_sha256']
            persist('fresh-restores', **response['summary'])
            self.identity()
            self.assert_held(held)
            self.bundle.run(core['node'], 'observe', core=core, namespace_pid=held['postgresql']['namespace_pid'])
            item = held['postgresql']
            preparation = recovery.prepare_standalone_directory(lambda *args: self.execute(item, *args))
            persist('native-data-directory-prepared', **preparation)
            prepare = ('umask 077; set -C; cat > /tmp/source-hba.conf; : > /tmp/fixture.conf; '
                       '[[ $(stat -c "%u:%a:%h" /tmp/source-hba.conf) == 1001:600:1 ]]; '
                       '[[ $(stat -c "%u:%a:%h" /tmp/fixture.conf) == 1001:600:1 ]]')
            self.execute(item, '/bin/bash', '-ceu', prepare, data=self.hba)
            item['child'].stdin.write(b'run\n' + recovery.catalog_sql().encode())
            item['child'].stdin.flush()
            before = self.read_catalog(item['child'])
            if before != baseline:
                raise RuntimeError('actual offline source catalog differs from both fresh restores; no role SQL allowed')
            declared = 'md5' + hashlib.md5((self.credentials['admin'] + 'postgres').encode()).hexdigest()
            changed = next(r for r in before['roles'] if r['rolname'] == 'postgres')['rolpassword'] != declared
            if changed:
                intent = self.bundle.run('pikachu', 'intent', point=received['point'], checksum=received['manifest_sha256'],
                    expected=received['source'], catalog_sha256=hashlib.sha256(common.canonical(before)).hexdigest(),
                    secret_uid=self.secrets['gitea-postgresql'][0], application_uid=held['application']['uid'])
                if not intent['exclusive_creation']:
                    raise RuntimeError('exclusive durable recovery intent missing; no role SQL allowed')
                persist('durable-intent', **intent)
                item['child'].stdin.write(recovery.role_transaction(self.credentials['admin'], 'commit') + recovery.catalog_sql().encode())
                item['child'].stdin.flush()
            output, errors = item['child'].communicate()
            # Never replay an uncertain child. Normal authenticated observation decides its outcome.
            acknowledged = item['child'].returncode == 0 and not errors
            if changed and acknowledged:
                recovery.require_role_only(before, recovery.parse_catalog(output), self.credentials['admin'])
            self.call('wait', '--for=condition=Ready', 'pod/' + PG, '-n', NAMESPACE, '--timeout=300s')
            observed = self.client(item, 'postgres', 'psql', '-XAtq', '-d', 'postgres', '-c', recovery.CATALOG)
            after = json.loads(observed)
            if changed:
                recovery.require_role_only(before, after, self.credentials['admin'])
            elif after != before:
                raise RuntimeError('already-correct production role changed authorization')
            for role in ('gitea', 'postgres'):
                for database in ('gitea', 'postgres', 'template1'):
                    raw = self.client(item, role, 'pg_dump', '--no-comments', '--dbname=' + database)
                    if hashlib.sha256(recovery.logical.normalized_dump(raw)).hexdigest() != expected_dumps[database]:
                        raise RuntimeError('normal production recovery changed complete logical data; application remains held')
            if self.execute(item, '/bin/cat', '/opt/bitnami/postgresql/conf/pg_hba.conf').stdout != self.hba:
                raise RuntimeError('normal production recovery changed existing HBA')
            self.assert_held({'application': held['application']})
            persist('role-recovered', administrator_and_application_auth=True, complete_logical_data_equal=True,
                    only_existing_postgres_password_changed=changed, native_acknowledgement=acknowledged,
                    transaction_replayed=False, unchanged_hba=True)
            app = held['application']
            output, errors = app['child'].communicate()
            if app['child'].returncode or output or errors:
                raise RuntimeError('production application hold release differs')
            self.wait_application_ready(held['application'])
            self.preserved()
            persist('application-restarted', production_mutated=True, original_secrets_and_valkey_preserved=True)


def main():
    request = json.load(sys.stdin)
    root = Path(__file__).resolve().parents[2]
    if (set(request) != {'code_revision', 'profile_revision', 'nodes', 'kubectl', 'run_id'} or
            not re.fullmatch('[a-f0-9]{40}', request['profile_revision']) or
            subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip() != request['profile_revision'] or
            subprocess.check_output(['git', '-C', str(root), 'remote', 'get-url', 'origin']).decode().strip() !=
            'git@git.eaglepass.io:ops/homelab.git'):
        raise RuntimeError('prefetched production controller checkout/candidate differs')
    transport.Bundle.exact(root, request['code_revision'], 'metal/scripts/gitea_postgres_recovery_controller.py')
    bundle = transport.Bundle(root, request['code_revision'], request['nodes'])
    instance = Controller(request['kubectl'], bundle)
    def interrupted(_number, _frame):
        raise RuntimeError('owned recovery controller interrupted; native outcome must be observed, never replayed')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    def persist(stage, **summary):
        print(json.dumps({'stage': stage, **summary}), flush=True)
    instance.baseline()
    instance.revision = request['profile_revision']
    persist('prefetched-ready', code_revision=request['code_revision'], profile_revision=instance.revision)
    instance.recover(request['run_id'], persist)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'stage': 'failed', 'error_type': type(error).__name__,
                          'error': str(error) if isinstance(error, RuntimeError) else 'recovery failed; raw details withheld'}), flush=True)
        sys.exit(70)
