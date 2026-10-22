"""Observe the Argo-owned synthetic six-PVC Valkey migration fixture only."""

import json
import subprocess

import valkey_cluster_qualification as protocol


NAMESPACE = 'maintenance-valkey-103'
PURPOSE = 'synthetic-valkey-six-pvc'
LABEL = 'maintenance103.eaglepass.io/purpose'
NAME = 'synthetic-valkey'
IMAGES = {protocol.recovery.IMAGE, protocol.recovery.CANDIDATE}


class Qualification:
    def __init__(self, kubectl):
        self.kubectl = list(kubectl)
        self.namespace_uid = self.controller_uid = None
        self.claims = {}
        self.records = {n: {} for n in protocol.SLOTS}

    def call(self, *args, check=True):
        result = subprocess.run([*self.kubectl, *args], capture_output=True)
        if result.returncode and any(word in result.stderr.lower() for word in (b'forbidden', b'unauthorized', b'permission denied')):
            raise RuntimeError('synthetic six-PVC access denied; do not retry through another identity')
        if check and result.returncode:
            raise RuntimeError('synthetic six-PVC API/exec failed; raw output withheld')
        return result

    def get(self, kind, name=None, namespace=NAMESPACE):
        return json.loads(self.call('get', kind, *([name] if name else []),
            *(['-n', namespace] if namespace else []), '-o', 'json').stdout)

    def identity(self):
        if self.get('namespace', 'kube-system', None)['metadata']['uid'] != protocol.common.CLUSTER_UID:
            raise RuntimeError('synthetic six-PVC target cluster differs')
        ns = self.get('namespace', NAMESPACE, None)['metadata']
        if (ns.get('deletionTimestamp') or ns.get('labels', {}).get(LABEL) != PURPOSE or
                (self.namespace_uid and ns['uid'] != self.namespace_uid)):
            raise RuntimeError('synthetic six-PVC namespace differs')
        self.namespace_uid = ns['uid']
        app = self.get('application', NAMESPACE, 'argocd')
        if (app['spec']['source']['path'] != 'apps/' + NAMESPACE or
                app['spec']['source']['repoURL'] != 'http://gitea-http.gitea:3000/ops/homelab' or
                app['spec']['source']['targetRevision'] != 'master' or
                app['spec']['destination']['namespace'] != NAMESPACE):
            raise RuntimeError('synthetic six-PVC Argo owner differs')
        sts = self.get('statefulset', NAME)
        if (sts['metadata'].get('deletionTimestamp') or sts['metadata'].get('labels', {}).get(LABEL) != PURPOSE or
                sts['spec']['replicas'] != 6 or sts['spec']['serviceName'] != NAME + '-headless' or
                sts['spec']['podManagementPolicy'] != 'Parallel' or
                sts['spec']['persistentVolumeClaimRetentionPolicy'] != {'whenDeleted': 'Delete', 'whenScaled': 'Retain'} or
                (self.controller_uid and sts['metadata']['uid'] != self.controller_uid)):
            raise RuntimeError('synthetic six-PVC owning StatefulSet differs')
        self.controller_uid = sts['metadata']['uid']
        policy = self.get('networkpolicy', NAME + '-isolation')['spec']
        peers = [{'podSelector': {'matchLabels': {LABEL: PURPOSE}}}]
        ports = [{'protocol': 'TCP', 'port': n} for n in (6379, 16379)]
        if (policy['podSelector'] != {} or set(policy['policyTypes']) != {'Ingress', 'Egress'} or
                policy['ingress'] != [{'from': peers, 'ports': ports}] or
                policy['egress'] != [{'to': peers, 'ports': ports}]):
            raise RuntimeError('synthetic six-PVC traffic isolation differs')
        return sts

    def pods(self):
        items = self.get('pods')['items']
        result = {}
        for pod in items:
            name, spec = pod['metadata']['name'], pod['spec']
            if not name.startswith(NAME + '-') or name[len(NAME) + 1:] not in set(map(str, range(6))):
                raise RuntimeError('unrelated workload entered synthetic namespace')
            ordinal = int(name[len(NAME) + 1:])
            security = spec.get('securityContext', {})
            owner = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
            containers = spec['containers']
            if (len(owner) != 1 or owner[0]['kind'] != 'StatefulSet' or owner[0]['uid'] != self.controller_uid or
                    pod['metadata'].get('labels', {}).get(LABEL) != PURPOSE or
                    spec.get('automountServiceAccountToken') is not False or
                    spec.get('hostNetwork') or spec.get('hostPID') or spec.get('hostIPC') or
                    spec.get('nodeName') not in (None, 'pikachu', 'totodile') or
                    spec.get('initContainers') or len(containers) != 1 or containers[0]['name'] != 'valkey' or
                    containers[0]['image'] not in IMAGES or
                    security.get('runAsUser') != 1001 or security.get('runAsGroup') != 1001 or
                    security.get('fsGroup') != 1001 or security.get('runAsNonRoot') is not True or
                    security.get('seccompProfile') != {'type': 'RuntimeDefault'}):
                raise RuntimeError('synthetic six-PVC Pod access or owner differs')
            cs = containers[0]['securityContext']
            if (cs.get('allowPrivilegeEscalation') is not False or cs.get('readOnlyRootFilesystem') is not True or
                    cs.get('capabilities') != {'drop': ['ALL']}):
                raise RuntimeError('synthetic six-PVC container privileges differ')
            for volume in spec['volumes']:
                if not set(volume) <= {'name', 'persistentVolumeClaim', 'emptyDir', 'configMap'}:
                    raise RuntimeError('synthetic six-PVC acquired unexpected storage or credential')
                if 'persistentVolumeClaim' in volume and volume['persistentVolumeClaim']['claimName'] != 'data-' + name:
                    raise RuntimeError('synthetic six-PVC mounted a foreign claim')
            result[ordinal] = pod
        return result

    def cli(self, ordinal, *args, check=True):
        pod = self.pods().get(ordinal)
        if not pod or pod['metadata'].get('deletionTimestamp'):
            if check:
                raise RuntimeError('synthetic Valkey Pod is transitioning')
            return b''
        response = self.call('exec', '-n', NAMESPACE, pod['metadata']['name'], '-c', 'valkey', '--',
            'valkey-cli', '--raw', '-c', '-h', '127.0.0.1', *map(str, args), check=False)
        if response.stdout.startswith((b'NOAUTH ', b'NOPERM ')):
            raise RuntimeError('synthetic Valkey authorization denied')
        if response.returncode or response.stderr or response.stdout.startswith((b'ERR ', b'CLUSTERDOWN ', b'error:')):
            if check:
                raise RuntimeError('synthetic Valkey command failed; raw output withheld')
            return b''
        return response.stdout.rstrip(b'\r\n')

    def bind_claims(self):
        self.identity()
        pods = self.pods()
        if len(pods) != 6:
            raise RuntimeError('synthetic six-PVC binding requires all six Pods')
        current = {}
        for n, pod in pods.items():
            claim = self.get('persistentvolumeclaim', 'data-' + NAME + '-' + str(n))
            pv = self.get('persistentvolume', claim['spec']['volumeName'], None)
            if (claim['metadata'].get('labels', {}).get(LABEL) != PURPOSE or claim['status']['phase'] != 'Bound' or
                    claim['spec']['accessModes'] != ['ReadWriteOnce'] or claim['spec']['storageClassName'] != 'standard-rwo' or
                    claim['spec']['resources']['requests']['storage'] != '64Mi' or
                    pv['spec']['claimRef']['uid'] != claim['metadata']['uid'] or
                    pv['spec']['claimRef']['namespace'] != NAMESPACE or pv['spec']['persistentVolumeReclaimPolicy'] != 'Delete' or
                    pv['spec'].get('csi', {}).get('driver') != 'rook-ceph.rbd.csi.ceph.com' or
                    any(p['metadata']['uid'] != pod['metadata']['uid'] for p in pods.values() if any(
                        v.get('persistentVolumeClaim', {}).get('claimName') == claim['metadata']['name'] for v in p['spec']['volumes']))):
                raise RuntimeError('synthetic six-PVC binding/backend/exclusive consumer differs')
            current[n] = {'claim': claim['metadata']['name'], 'claim_uid': claim['metadata']['uid'],
                'pv': pv['metadata']['name'], 'pv_uid': pv['metadata']['uid'], 'csi': pv['spec']['csi']}
        if self.claims and current != self.claims:
            raise RuntimeError('synthetic six-PVC identities changed across migration')
        self.claims = current
        return current

    def healthy(self, masters=(0, 3, 5)):
        pods = self.pods()
        if len(pods) != 6 or any(p['metadata'].get('deletionTimestamp') for p in pods.values()):
            return False
        topology = []
        for n in range(6):
            cluster = protocol.recovery.info(self.cli(n, 'CLUSTER', 'INFO', check=False))
            repl = protocol.recovery.info(self.cli(n, 'INFO', 'replication', check=False))
            if any(cluster.get(k) != v for k, v in {'cluster_state': 'ok', 'cluster_slots_assigned': '16384',
                    'cluster_slots_ok': '16384', 'cluster_slots_pfail': '0', 'cluster_slots_fail': '0',
                    'cluster_known_nodes': '6'}.items()):
                return False
            original = n if n in protocol.SLOTS else protocol.REPLICAS[n]
            if n in masters:
                if repl.get('role') != 'master' or repl.get('connected_slaves') != '1':
                    return False
                own = [l.split()[8:] for l in self.cli(n, 'CLUSTER', 'NODES').decode().splitlines()
                       if 'myself' in l.split()[2].split(',')]
                if own != [[str(protocol.SLOTS[original][0]) + '-' + str(protocol.SLOTS[original][1])]]:
                    return False
            else:
                master = next(m for m in masters if (m if m in protocol.SLOTS else protocol.REPLICAS[m]) == original)
                if (repl.get('role') != 'slave' or repl.get('master_link_status') != 'up' or
                        repl.get('master_sync_in_progress') != '0' or repl.get('master_port') != '6379' or
                        repl.get('master_host') != pods[master]['status']['podIP']):
                    return False
            try:
                topology.append(protocol.recovery.topology(self.cli(n, 'CLUSTER', 'NODES')))
            except RuntimeError:
                return False
        return len(set(topology)) == 1

    def wait_healthy(self, masters=(0, 3, 5)):
        protocol.poll(lambda: self.healthy(masters), 'synthetic six-PVC cluster did not converge')

    def bootstrap(self):
        self.identity()
        protocol.poll(lambda: len(self.pods()) == 6 and all(self.cli(n, 'PING', check=False) == b'PONG'
            for n in range(6)), 'synthetic six-PVC servers did not start')
        self.bind_claims()
        ips = {n: p['status']['podIP'] for n, p in self.pods().items()}
        for n in range(6):
            assert self.cli(n, 'DBSIZE') == b'0'
            assert self.cli(n, 'CLUSTER', 'SET-CONFIG-EPOCH', n + 1) == b'OK'
        for n, (low, high) in protocol.SLOTS.items():
            assert self.cli(n, 'CLUSTER', 'ADDSLOTSRANGE', low, high) == b'OK'
        for n in range(1, 6):
            assert self.cli(n, 'CLUSTER', 'MEET', ips[0], 6379) == b'OK'
        protocol.poll(lambda: all(protocol.recovery.info(self.cli(n, 'CLUSTER', 'INFO')).get('cluster_known_nodes') == '6'
            for n in range(6)), 'synthetic six-PVC membership did not converge')
        for replica, master in protocol.REPLICAS.items():
            assert self.cli(replica, 'CLUSTER', 'REPLICATE', self.cli(master, 'CLUSTER', 'MYID').decode()) == b'OK'
        self.wait_healthy()
        for master in protocol.SLOTS:
            keys = protocol.fixture_keys(master)
            assert self.cli(4, 'EVAL', protocol.WRITE, len(keys), *keys) == b'fixture-created'
        self.verify()

    def verify(self, masters=(0, 3, 5)):
        self.wait_healthy(masters)
        self.bind_claims()
        for original in protocol.SLOTS:
            keys = protocol.fixture_keys(original)
            assert self.cli(4, 'EVAL_RO', protocol.VERIFY, len(keys), *keys) == b'fixture-verified'
            records = list(self.records[original].items())
            for offset in range(0, len(records), 1000):
                batch = records[offset:offset + 1000]
                if self.cli(4, 'MGET', *(key for key, _value in batch)).decode().splitlines() != [value for _key, value in batch]:
                    raise RuntimeError('acknowledged synthetic write lost or changed')
            owner = next(m for m in masters if (m if m in protocol.SLOTS else protocol.REPLICAS[m]) == original)
            if self.cli(owner, 'DBSIZE') != str(150 + len(records)).encode():
                raise RuntimeError('synthetic complete key inventory differs')
        offsets = {n: int(protocol.recovery.info(self.cli(n, 'INFO', 'replication'))['master_repl_offset']) for n in masters}
        def acknowledged():
            for n in set(range(6)) - set(masters):
                original = n if n in protocol.SLOTS else protocol.REPLICAS[n]
                owner = next(m for m in masters if (m if m in protocol.SLOTS else protocol.REPLICAS[m]) == original)
                if int(protocol.recovery.info(self.cli(n, 'INFO', 'replication')).get('slave_repl_offset', '-1')) < offsets[owner]:
                    return False
            return True
        protocol.poll(acknowledged, 'synthetic replicas did not acknowledge complete offsets')
        for n in range(6):
            p = protocol.recovery.info(self.cli(n, 'INFO', 'persistence'))
            if (p.get('aof_enabled') != '1' or p.get('aof_last_write_status') != 'ok' or
                    p.get('aof_last_bgrewrite_status') != 'ok' or p.get('loading') != '0'):
                raise RuntimeError('synthetic six-PVC persistence state is not healthy')

    def failover(self, replica, masters):
        assert self.cli(replica, 'CLUSTER', 'FAILOVER') == b'OK'
        self.verify(masters)

    def write_record(self, number):
        original = tuple(protocol.SLOTS)[number % 3]
        key = protocol.fixture_keys(original)[0] + ':acknowledged:' + str(number)
        value = 'synthetic-six-pvc-' + str(number)
        reply = self.cli(4, 'EVAL', "redis.call('SET',KEYS[1],ARGV[1]);return ARGV[1]", 1, key, value, check=False)
        if reply == value.encode():
            self.records[original][key] = value
            return True
        return False
