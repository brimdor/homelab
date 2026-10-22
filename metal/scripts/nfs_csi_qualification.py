#!/usr/bin/env python3
"""Qualify the exact NFS CSI candidate on synthetic storage in an owned VM."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import time
import urllib.request

import yaml

import cilium_qualification as isolated
from cilium_l2_qualification import IMAGE as CLIENT


CHART_URL = 'https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/master/charts/v4.13.5/csi-driver-nfs-4.13.5.tgz'
CHART_SHA256 = 'aace8754451ecbd87e090ec29e6cbffcf88dbd9980cecb165da8b9d0880f7fac'
NAMESPACE = 'nfs-csi-qualification'
SERVER = '172.31.240.1'
NETWORK = '172.31.240.0/24'
IMAGES = {
    'registry.k8s.io/sig-storage/nfsplugin:v4.13.5',
    'registry.k8s.io/sig-storage/csi-provisioner:v6.3.0',
    'registry.k8s.io/sig-storage/csi-resizer:v2.2.1',
    'registry.k8s.io/sig-storage/livenessprobe:v2.19.0',
    'registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.17.0',
}


def require_pv(pv, claim, share):
    spec = pv['spec']
    csi = spec.get('csi', {})
    ref = spec.get('claimRef', {})
    if (pv['status']['phase'] != 'Bound' or not pv['metadata'].get('uid') or
            ref.get('uid') != claim['metadata']['uid'] or ref.get('namespace') != NAMESPACE or
            ref.get('name') != claim['metadata']['name'] or csi.get('driver') != 'nfs.csi.k8s.io' or
            csi.get('volumeAttributes', {}).get('server') != SERVER or
            csi.get('volumeAttributes', {}).get('share') != share or
            not csi.get('volumeHandle') or 'nfs' in spec):
        raise RuntimeError('synthetic PVC/PV binding or server identity changed')


def require_mount(records, version):
    wanted = 'nfs' if version == '3' else 'nfs4'
    if (len(records) != 1 or records[0]['filesystem'] != wanted or
            not records[0]['source'].startswith(SERVER + ':') or
            'vers=' + version not in records[0]['options'].split(',')):
        raise RuntimeError('native kernel mount does not match the selected NFS protocol')


def pinned_image(image):
    if image not in IMAGES:
        raise RuntimeError('unreviewed CSI image')
    repository, tag = image.removeprefix('registry.k8s.io/').split(':')
    request = urllib.request.Request('https://registry.k8s.io/v2/' + repository + '/manifests/' + tag,
                                     headers={'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if response.headers.get('Docker-Content-Digest', digest) != digest:
            raise RuntimeError('official registry manifest digest disagrees with its bytes')
    manifest = json.loads(raw)
    if (manifest.get('schemaVersion') != 2 or not any(
            p.get('platform', {}).get('os') == 'linux' and p.get('platform', {}).get('architecture') == 'arm64'
            for p in manifest.get('manifests', []))):
        raise RuntimeError('official candidate has no Linux ARM64 image')
    return image.split(':')[0] + '@' + digest


class Qualification(isolated.Qualification):
    def __init__(self, args):
        super().__init__(args)
        for name in ('COLIMA_HOME', 'LIMA_HOME', 'DOCKER_CONFIG'):
            value = Path(os.environ[name])
            if not value.is_absolute() or not value.resolve().is_relative_to(args.work_dir):
                raise RuntimeError('VM control state is outside the exact owned fixture')
        self.export = '/srv/' + args.name
        self.claims = {}
        self.image_pins = {}

    def command(self, command, *, data=None, private=True):
        return super().command(command, data=data, private=True)

    def guest(self, *args):
        return self.command([self.args.colima, '-p', 'q', 'ssh', '--', *args])

    def kubectl(self, *args, json_output=True, data=None):
        if args and args[0] in ('apply', 'delete', 'patch'):
            self.identity()
        return super().kubectl(*args, json_output=json_output, data=data)

    def apply(self, *resources):
        return self.kubectl('apply', '-f', '-', data=yaml.safe_dump_all(resources).encode(), json_output=False)

    def persist(self, stage, **evidence):
        self.stages.append({'stage': stage, 'at_ns': time.time_ns(), **evidence})
        (self.work / 'progress.json').write_text(json.dumps(self.stages, indent=2))
        print('NFS_STAGE ' + stage, flush=True)

    def create(self):
        if (self.command(['docker', 'info', '--format', '{{.Name}}']).decode().strip() != self.args.docker_server or
                self.command(['docker', 'ps', '-aq']).strip()):
            raise RuntimeError('Docker must be the exact empty owned VM')
        self.guest('sudo', 'iptables', '-I', 'OUTPUT', '1', '-d', '10.0.0.0/8', '-j', 'REJECT')
        self.guest('sudo', 'iptables', '-I', 'DOCKER-USER', '1', '-d', '10.0.0.0/8', '-j', 'REJECT')
        self.guest('sudo', 'iptables', '-I', 'OUTPUT', '1', '-d', '100.64.0.0/10', '-j', 'REJECT')
        self.guest('sudo', 'iptables', '-I', 'DOCKER-USER', '1', '-d', '100.64.0.0/10', '-j', 'REJECT')
        self.guest('sudo', 'iptables', '-C', 'OUTPUT', '-d', '10.0.0.0/8', '-j', 'REJECT')
        self.guest('sudo', 'iptables', '-C', 'DOCKER-USER', '-d', '10.0.0.0/8', '-j', 'REJECT')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.creation_started = True
        self.command([self.args.k3d, 'cluster', 'create', self.args.name, '--servers=1', '--agents=2',
                      '--image=' + isolated.K3S, '--api-port=127.0.0.1:' + str(port), '--subnet=' + NETWORK,
                      '--kubeconfig-update-default=false', '--kubeconfig-switch-context=false',
                      '--k3s-arg=--disable=traefik,servicelb,local-storage,metrics-server@server:*'])
        raw = self.command([self.args.k3d, 'kubeconfig', 'get', self.args.name])
        with Path(self.env['KUBECONFIG']).open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        self.identity()
        self.kubectl('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=300s', json_output=False)
        self.persist('isolated-cluster', cluster_uid=self.cluster_uid,
                     production_routes_rejected=['10.0.0.0/8', '100.64.0.0/10'], k3s=isolated.K3S)

    def server(self):
        # Only the owned VM is changed. Its final deletion removes packages and exports.
        self.guest('sh', '-ec', '. /etc/os-release; test "$ID" = ubuntu')
        self.guest('sudo', 'apt-get', 'update', '-qq')
        self.guest('sudo', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', '-qq', 'nfs-kernel-server')
        self.guest('sudo', 'sh', '-ec',
                   'test ! -e "$1"; test -z "$(exportfs -v)"; mkdir -m 0777 "$1"; '
                   'printf "%s %s(rw,sync,root_squash,no_subtree_check,fsid=0)\\n" "$1" "$2" > /etc/exports.d/qualification.exports; '
                   'exportfs -ra; systemctl restart nfs-kernel-server; exportfs -v',
                   'qualification', self.export, NETWORK)
        exports = self.guest('sudo', 'exportfs', '-v').decode()
        if self.export not in exports or 'root_squash' not in exports or 'no_root_squash' in exports:
            raise RuntimeError('synthetic export identity or root squash changed')
        self.persist('synthetic-server', export=self.export, server=SERVER, clients=NETWORK,
                     root_squash=True, export_sha256=hashlib.sha256(exports.encode()).hexdigest(),
                     kernel=self.guest('uname', '-r').decode().strip())

    def install(self):
        archive = self.work / 'nfs.tgz'
        with urllib.request.urlopen(CHART_URL, timeout=60) as response:
            raw = response.read()
        if hashlib.sha256(raw).hexdigest() != CHART_SHA256:
            raise RuntimeError('exact reviewed NFS chart hash changed')
        archive.write_bytes(raw)
        rendered = self.helm('template', 'qualification', str(archive), '--namespace', NAMESPACE,
                             '--kube-version', '1.33.6',
                             '--set', 'controller.enableSnapshotter=false', '--set', 'storageClass.create=false',
                             '--set', 'externalSnapshotter.enabled=false',
                             '--set', 'externalSnapshotter.customResourceDefinitions.enabled=false',
                             '--set', 'driver.mountPermissions=0',
                             '--set', 'feature.enableInlineVolume=false', '--set', 'feature.propagateHostMountOptions=false')
        objects = list(yaml.safe_load_all(rendered))
        actual = {c['image'] for item in objects if item['kind'] in ('Deployment', 'DaemonSet')
                  for c in item['spec']['template']['spec']['containers']}
        if actual != IMAGES or len(objects) != 9:
            raise RuntimeError('reviewed chart resource or image contract changed')
        self.image_pins = {image: pinned_image(image) for image in sorted(actual)}
        for item in objects:
            if item['kind'] in ('Deployment', 'DaemonSet'):
                for container in item['spec']['template']['spec']['containers']:
                    container['image'] = self.image_pins[container['image']]
        self.apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NAMESPACE}}, *objects)
        for resource in ('deployment/csi-nfs-controller', 'daemonset/csi-nfs-node'):
            self.kubectl('rollout', 'status', resource, '-n', NAMESPACE, '--timeout=600s', json_output=False)
        driver = self.kubectl('get', 'csidriver', 'nfs.csi.k8s.io')
        if driver['spec'].get('fsGroupPolicy') != 'File':
            raise RuntimeError('candidate fsGroupPolicy changed')
        self.persist('csi-ready', image_pins=self.image_pins, fsGroupPolicy='File', chart_sha256=CHART_SHA256)

    def claim(self, version, policy):
        name = 'nfs-' + version.replace('.', '-') + '-' + policy
        share = self.export if version == '3' else '/'
        self.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': NAMESPACE},
                    'stringData': {'mountOptions': 'nfsvers=' + version + ',hard'}},
                   {'apiVersion': 'storage.k8s.io/v1', 'kind': 'StorageClass', 'metadata': {'name': name},
                    'provisioner': 'nfs.csi.k8s.io', 'reclaimPolicy': 'Delete', 'volumeBindingMode': 'Immediate',
                    'mountOptions': ['nfsvers=' + version, 'hard'], 'parameters': {
                        'server': SERVER, 'share': share, 'subDir': '${pv.metadata.name}', 'onDelete': policy,
                        'mountPermissions': '0777',
                        'csi.storage.k8s.io/provisioner-secret-name': name,
                        'csi.storage.k8s.io/provisioner-secret-namespace': NAMESPACE}},
                   {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': NAMESPACE},
                    'spec': {'storageClassName': name, 'accessModes': ['ReadWriteMany'],
                             'resources': {'requests': {'storage': '1Mi'}}}})
        self.kubectl('wait', '--for=jsonpath={.status.phase}=Bound', 'pvc/' + name, '-n', NAMESPACE,
                     '--timeout=300s', json_output=False)
        claim = self.kubectl('get', 'pvc', name, '-n', NAMESPACE)
        pv = self.kubectl('get', 'pv', claim['spec']['volumeName'])
        require_pv(pv, claim, share)
        if not re.fullmatch('pvc-[a-f0-9-]{36}', pv['metadata']['name']):
            raise RuntimeError('unexpected synthetic subdirectory')
        self.claims[name] = (claim, pv)
        return name

    def pod(self, claim, name, node, uid):
        self.apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NAMESPACE},
                    'spec': {'nodeName': 'k3d-' + self.args.name + '-agent-' + str(node), 'restartPolicy': 'Never',
                             'automountServiceAccountToken': False,
                             'securityContext': {'runAsUser': uid, 'runAsGroup': uid},
                             'containers': [{'name': 'client', 'image': CLIENT,
                                             'command': ['python3', '-c', 'import time;time.sleep(2147483647)'],
                                             'securityContext': {'readOnlyRootFilesystem': True,
                                                                 'allowPrivilegeEscalation': False,
                                                                 'capabilities': {'drop': ['ALL']}},
                                             'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                             'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}})
        self.kubectl('wait', '--for=condition=Ready', 'pod/' + name, '-n', NAMESPACE, '--timeout=300s', json_output=False)
        return name

    def execute(self, pod, code):
        return json.loads(self.kubectl('exec', '-n', NAMESPACE, pod, '--', 'python3', '-c', code, json_output=False))

    def remove_pods(self, *names):
        self.kubectl('delete', 'pod', *names, '-n', NAMESPACE, '--wait=true', '--timeout=180s', json_output=False)

    def protocol(self, version):
        claim = self.claim(version, 'retain')
        root = self.pod(claim, 'root-client', 0, 0)
        owner = self.execute(root, "import os,json;open('/data/squashed','w').write('root');s=os.stat('/data/squashed');print(json.dumps([s.st_uid,s.st_gid]))")
        if owner != [65534, 65534]:
            raise RuntimeError('root squash did not map synthetic root writes to nobody')
        self.remove_pods(root)
        pods = [self.pod(claim, 'writer-' + str(n), n, 1000) for n in (0, 1)]
        mount = self.execute(pods[0], "import json;out=[]\nfor l in open('/proc/self/mountinfo'):\n a,b=l.split(' - ');x=a.split();y=b.split()\n if x[4]=='/data':out.append({'filesystem':y[0],'source':y[1],'options':y[2]})\nprint(json.dumps(out))")
        require_mount(mount, version)
        def write(pod):
            return self.execute(pod, "import fcntl,os,json,time\np='/data/shared'\nwith open(p,'a') as f:\n for n in range(100):\n  fcntl.flock(f,fcntl.LOCK_EX);f.write(" + repr(pod) + "+':'+str(n)+'\\n');f.flush();os.fsync(f.fileno());fcntl.flock(f,fcntl.LOCK_UN);time.sleep(.005)\nprint(json.dumps({'written':100,'uid':os.getuid()}))")
        with ThreadPoolExecutor(max_workers=2) as pool:
            writes = list(pool.map(write, pods))
        if writes != [{'written': 100, 'uid': 1000}] * 2:
            raise RuntimeError('concurrent synthetic writers failed')
        verify = "import os,json,hashlib\nb=open('/data/shared','rb').read();s=os.stat('/data/shared');lines=b.decode().splitlines();expected={p+':'+str(n) for p in ['writer-0','writer-1'] for n in range(100)};assert len(lines)==200 and set(lines)==expected;assert s.st_uid==1000 and s.st_gid==1000;print(json.dumps({'sha256':hashlib.sha256(b).hexdigest(),'lines':len(lines),'uid':s.st_uid,'gid':s.st_gid}))"
        before = self.execute(pods[0], verify)
        if self.execute(pods[1], verify) != before:
            raise RuntimeError('RWX clients disagree on the complete corpus')
        self.remove_pods(*pods)
        node = 'k3d-' + self.args.name + '-agent-0'
        self.identity()
        container = json.loads(self.command(['docker', 'inspect', node]))[0]
        if (container['Name'] != '/' + node or not container.get('Id') or
                container['Config'].get('Labels', {}).get('k3d.cluster') != self.args.name or
                set(container['NetworkSettings']['Networks']) != {'k3d-' + self.args.name}):
            raise RuntimeError('owned node container changed before restart')
        self.command(['docker', 'restart', node])
        if json.loads(self.command(['docker', 'inspect', node]))[0]['Id'] != container['Id']:
            raise RuntimeError('owned node container was replaced during restart')
        self.kubectl('wait', '--for=condition=Ready', 'node/' + node, '--timeout=300s', json_output=False)
        restored = self.pod(claim, 'restarted-client', 0, 1000)
        if self.execute(restored, verify) != before:
            raise RuntimeError('pod/node restart changed synthetic data')
        self.remove_pods(restored)
        original_claim, pv = self.claims[claim]
        self.kubectl('delete', 'pvc', claim, '-n', NAMESPACE, '--wait=true', '--timeout=180s', json_output=False)
        self.kubectl('wait', '--for=delete', 'pv/' + pv['metadata']['name'], '--timeout=300s', json_output=False)
        # onDelete retain removes the API object but must preserve owned synthetic files.
        data_path = self.export + '/' + pv['metadata']['name']
        self.guest('sudo', 'test', '-f', data_path + '/shared')
        static_name = 'rebound-' + version.replace('.', '-')
        self.apply({'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': static_name},
                    'spec': {'storageClassName': '', 'capacity': {'storage': '1Mi'}, 'accessModes': ['ReadWriteMany'],
                             'persistentVolumeReclaimPolicy': 'Retain', 'mountOptions': ['nfsvers=' + version, 'hard'],
                             'csi': {'driver': 'nfs.csi.k8s.io', 'volumeHandle': static_name,
                                     'volumeAttributes': {'server': SERVER, 'share':
                                         data_path if version == '3' else '/' + pv['metadata']['name']}}}},
                   {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': static_name, 'namespace': NAMESPACE},
                    'spec': {'storageClassName': '', 'volumeName': static_name, 'accessModes': ['ReadWriteMany'],
                             'resources': {'requests': {'storage': '1Mi'}}}})
        restored = self.pod(static_name, 'rebound-client', 1, 1000)
        if self.execute(restored, verify) != before:
            raise RuntimeError('static recovery rebinding changed the complete corpus')
        rebound = self.kubectl('get', 'pvc', static_name, '-n', NAMESPACE)
        if rebound['metadata']['uid'] == original_claim['metadata']['uid']:
            raise RuntimeError('recovery must not falsely claim original API UID preservation')
        self.remove_pods(restored)
        self.persist('protocol-' + version, mount=mount, root_squash_owner=owner,
                     concurrent_rwx=before, restart_persistence=True, retained_data=True, recovery_rebind=True,
                     original_claim_uid=original_claim['metadata']['uid'], rebound_claim_uid=rebound['metadata']['uid'])

    def lifecycle(self, policy):
        name = self.claim('4.1', policy)
        _, pv = self.claims[name]
        path = self.export + '/' + pv['metadata']['name']
        self.guest('sudo', 'sh', '-ec', 'printf synthetic > "$1/marker"', 'qualification', path)
        self.kubectl('delete', 'pvc', name, '-n', NAMESPACE, '--wait=true', '--timeout=180s', json_output=False)
        self.kubectl('wait', '--for=delete', 'pv/' + pv['metadata']['name'], '--timeout=300s', json_output=False)
        self.guest('sudo', 'test', '!', '-e', path)
        if policy == 'archive':
            self.guest('sudo', 'test', '-f', self.export + '/archived-' + pv['metadata']['name'] + '/marker')
        self.persist('lifecycle-' + policy, synthetic_only=True, observed=True)

    def run(self):
        self.create()
        self.server()
        self.install()
        for version in ('3', '4.1'):
            self.protocol(version)
        for policy in ('archive', 'delete'):
            self.lifecycle(policy)
        return {'accepted': True, 'stages': self.stages, 'production_change': False,
                'production_nas_and_amd64_fedora_kernel_unqualified': True,
                'synthetic_dynamic_mountPermissions': '0777', 'consumer_fsGroup_not_set': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('name', 'docker-host', 'docker-server', 'k3d', 'kubectl', 'colima'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    q = Qualification(args)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, isolated.interrupted)
    try:
        result = q.run()
        (q.work / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        if q.creation_started:
            q.command([args.k3d, 'cluster', 'delete', args.name])
            if q.command(['docker', 'ps', '-aq']).strip():
                raise RuntimeError('owned synthetic cluster containers remain')
        # The tracked caller must delete this VM and all of its storage/images.


if __name__ == '__main__':
    main()
