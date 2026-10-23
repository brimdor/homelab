#!/usr/bin/env python3
"""Exercise only owned native CSI resources inside the disconnected Fedora VM."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time


DRIVER_NS = 'nfs-csi-native'
CLIENT_NS = 'nfs-consumer-native'
BACKUP_NS = 'nfs-backup-native'
NODE = 'qualification-fedora44'
EXPORT = Path('/srv/qualification-nfs-csi')
ASSETS = Path('/run/qualification-csi-assets')
K3S = '/usr/local/bin/k3s'
EVIDENCE = {'accepted': False, 'stages': []}


def native(*args, data=None):
    result = subprocess.run(args, input=data, capture_output=True)
    if result.returncode:
        lines = result.stderr.decode(errors='replace').splitlines()
        safe = [line[:500] for line in lines if not re.search(
            r'token|password|secret|credential|authorization|private.key', line, re.I)]
        raise RuntimeError(json.dumps({'argv': list(args), 'exit': result.returncode, 'stderr': safe[-10:]}))
    return result.stdout


def kubectl(*args, data=None):
    return native(K3S, 'kubectl', *args, data=data)


def get(*args):
    return json.loads(kubectl('get', *args, '-o', 'json'))


def apply(*objects):
    kubectl('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}).encode())


def persist(stage, **value):
    EVIDENCE['stages'].append({'stage': stage, 'at_ns': time.time_ns(), **value})
    Path('/work/native-csi-evidence.json').write_text(json.dumps(EVIDENCE, indent=2))


def pod_manifest(name, claim, image, uid=1000, group=1000, fs_group=1000):
    namespace = BACKUP_NS if uid == 0 else CLIENT_NS
    security = {'runAsUser': uid, 'runAsGroup': group, 'runAsNonRoot': uid != 0,
                'seccompProfile': {'type': 'RuntimeDefault'}}
    if fs_group is not None:
        security.update(fsGroup=fs_group, fsGroupChangePolicy='OnRootMismatch')
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace},
            'spec': {'nodeName': NODE, 'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                     'securityContext': security, 'containers': [{
                         'name': 'client', 'image': image, 'imagePullPolicy': 'Never',
                         'command': ['python3', '-B', '-c', 'import time;time.sleep(86400)'],
                         'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                             'capabilities': {'drop': ['ALL']}},
                         'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                     'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}}


def bound_domain(pod, container, inspected, context):
    """Do not accept an unrelated host PID or a stale/restarted CRI container."""
    statuses = [c for c in pod['status']['containerStatuses'] if c['name'] == container]
    status = inspected['status']
    labels = status.get('labels', {})
    pid = inspected.get('info', {}).get('pid')
    if (pod['metadata'].get('deletionTimestamp') or len(statuses) != 1 or
            not statuses[0].get('ready') or 'running' not in statuses[0].get('state', {}) or
            statuses[0].get('containerID') != 'containerd://' + status['id'] or
            labels.get('io.kubernetes.pod.uid') != pod['metadata']['uid'] or
            labels.get('io.kubernetes.pod.name') != pod['metadata']['name'] or
            labels.get('io.kubernetes.pod.namespace') != pod['metadata']['namespace'] or
            status.get('metadata', {}).get('name') != container or
            type(pid) is not int or pid <= 1 or len(context.split(':')) < 4):
        raise RuntimeError('native process is not bound to the current ready container')
    return {'pod_uid': pod['metadata']['uid'], 'pod': pod['metadata']['name'], 'container': container,
            'container_id': status['id'], 'pid': pid, 'context': context}


def domains(pod):
    records = []
    for status in pod['status']['containerStatuses']:
        cid = status['containerID'].removeprefix('containerd://')
        inspected = json.loads(native(K3S, 'crictl', 'inspect', cid))
        pid = inspected.get('info', {}).get('pid')
        if type(pid) is not int or pid <= 1:
            raise RuntimeError('missing native container PID')
        process = Path('/proc') / str(pid)
        before = (process / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        context = (process / 'attr/current').read_text().strip().rstrip(chr(0))
        after = (process / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        fresh = json.loads(native(K3S, 'crictl', 'inspect', cid))
        current = get('pod', pod['metadata']['name'], '-n', pod['metadata']['namespace'])
        if before != after or fresh['status']['id'] != inspected['status']['id'] or fresh['info']['pid'] != pid:
            raise RuntimeError('native PID identity changed during observation')
        record = bound_domain(current, status['name'], fresh, context)
        record['process_start_ticks'] = before
        if record['pod_uid'] != pod['metadata']['uid']:
            raise RuntimeError('Pod replaced during domain observation')
        records.append(record)
    return records


def ready(name, namespace=CLIENT_NS):
    kubectl('wait', '--for=condition=Ready', 'pod/' + name, '-n', namespace, '--timeout=900s')
    pod = get('pod', name, '-n', namespace)
    records = domains(pod)
    if namespace != DRIVER_NS and any(r['context'].split(':')[2] != 'container_t' for r in records):
        raise RuntimeError('ordinary consumer does not run in container_t')
    return pod, records


def execute(name, script, namespace=CLIENT_NS):
    return json.loads(kubectl('exec', '-n', namespace, name, '--', 'python3', '-B', '-c', script))


def metadata(path):
    st = path.stat()
    return {'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(st.st_mode & 0o7777),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}


def setup(inputs):
    assert native('hostname').strip() == NODE.encode()
    assert native('uname', '-r').strip() == b'7.2.11-200.fc44.x86_64'
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    assert not Path('/work').exists()
    Path('/work').mkdir(mode=0o700)
    for name, expected in inputs['assets'].items():
        assert hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() == expected
    booleans = native('getsebool', '-a')
    EVIDENCE['booleans_sha256'] = hashlib.sha256(booleans).hexdigest()
    EVIDENCE['nfs_booleans'] = [line for line in booleans.decode().splitlines() if 'nfs' in line]
    runtime = Path('/var/lib/rancher/k3s')
    expected = {'data', 'agent', 'agent/containerd', 'agent/containerd/io.containerd.snapshotter.v1.overlayfs',
                'agent/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots'}
    assert runtime.is_dir() and {str(p.relative_to(runtime)) for p in runtime.rglob('*')} == expected
    assert all(p.is_dir() and not p.is_symlink() for p in runtime.rglob('*'))
    assert not Path(K3S).exists()
    shutil.move(str(ASSETS / 'k3s'), K3S)
    Path(K3S).chmod(0o755)
    native('chcon', '-u', 'system_u', '-r', 'object_r', '-t', 'container_runtime_exec_t', K3S)
    assert os.getxattr(K3S, 'security.selinux').decode().split(':')[2] == 'container_runtime_exec_t'
    assert b'v1.33.6+k3s1' in native(K3S, '--version')
    images = runtime / 'agent/images'
    images.mkdir(parents=True)
    shutil.move(str(ASSETS / 'airgap.tar.zst'), str(images / 'airgap.tar.zst'))
    for number in range(6):
        shutil.move(str(ASSETS / ('image-' + str(number) + '.tar')), str(images / ('image-' + str(number) + '.tar')))
    assert json.loads(native('ip', '-j', 'route', 'show', 'default')) == []
    route = Path('/etc/systemd/system/qualification-airgap-route.service')
    unit = Path('/etc/systemd/system/qualification-k3s.service')
    assert not route.exists() and not unit.exists()
    route.write_text('[Unit]\nBefore=qualification-k3s.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\n'
                     'ExecStart=/usr/sbin/ip link add dummy0 type dummy\nExecStart=/usr/sbin/ip link set dummy0 up\n'
                     'ExecStart=/usr/sbin/ip addr add 203.0.113.254/31 dev dummy0\n'
                     'ExecStart=/usr/sbin/ip route add default via 203.0.113.255 dev dummy0 metric 1000\n')
    unit.write_text('[Unit]\nAfter=network-online.target qualification-airgap-route.service\n'
                    'Wants=network-online.target\nRequires=qualification-airgap-route.service\n[Service]\n'
                    'Type=notify\nKillMode=process\nDelegate=yes\nLimitNOFILE=1048576\nTasksMax=infinity\n'
                    'TimeoutStartSec=0\nExecStart=' + K3S + ' server --cluster-init --selinux '
                    '--write-kubeconfig-mode=600 --disable=traefik,servicelb,local-storage,metrics-server,coredns '
                    '--disable-network-policy --prefer-bundled-bin\n[Install]\nWantedBy=multi-user.target\n')
    native('systemctl', 'daemon-reload')
    native('systemctl', 'enable', '--now', 'qualification-k3s.service')
    routes = json.loads(native('ip', '-j', 'route', 'show', 'default'))
    assert len(routes) == 1 and routes[0]['dev'] == 'dummy0' and routes[0]['gateway'] == '203.0.113.255'
    config = runtime / 'agent/etc/containerd/config.toml'
    assert re.search(r'^\s*enable_selinux\s*=\s*true\s*$', config.read_text(), re.M)
    pid = int(native('systemctl', 'show', 'qualification-k3s.service', '--property=MainPID', '--value'))
    assert pid > 1 and Path('/proc/' + str(pid) + '/attr/current').read_text().split(':')[2] == 'container_runtime_t'
    for number, record in enumerate(inputs['records']):
        repository = record['image'].rsplit(':', 1)[0]
        native(K3S, 'ctr', 'images', 'import', '--local', '--digests', '--all-platforms', '--no-unpack',
               '--base-name', repository, str(images / ('image-' + str(number) + '.tar')))
        image = json.loads(native(K3S, 'crictl', 'inspecti', repository + '@' + record['digest']))
        assert repository + '@' + record['digest'] in image['status']['repoDigests']
    kubectl('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=900s')
    nodes = get('nodes')['items']
    assert len(nodes) == 1 and nodes[0]['metadata']['name'] == NODE
    persist('native-selinux-cluster', node_uid=nodes[0]['metadata']['uid'],
            cluster_uid=get('namespace', 'kube-system')['metadata']['uid'],
            containerd_selinux=True, enforcing=True, images=inputs['records'])
    assert not native('exportfs', '-v').strip() and not EXPORT.exists()
    EXPORT.mkdir(mode=0o755)
    for name, uid, gid, mode in (('builder', 0, 1000, 0o2770), ('incompatible', 0, 0, 0o755),
                                 ('backup', 65534, 65534, 0o2770)):
        directory = EXPORT / name
        directory.mkdir()
        os.chown(directory, uid, gid)
        directory.chmod(mode)
        marker = directory / 'marker'
        marker.write_bytes(b'qualification-original-' + name.encode() + b'\n')
        os.chown(marker, 1000 if name == 'builder' else uid, gid)
        marker.chmod(0o600)
    config = Path('/etc/exports.d/qualification-csi.exports')
    assert not config.exists()
    config.parent.mkdir(exist_ok=True)
    config.write_text(str(EXPORT) + ' 127.0.0.1(rw,sync,root_squash,no_subtree_check,fsid=0)\n')
    native('exportfs', '-ra')
    native('systemctl', 'start', 'nfs-server.service')
    exported = native('exportfs', '-v').decode()
    assert str(EXPORT) in exported and 'root_squash' in exported and 'no_root_squash' not in exported
    apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': DRIVER_NS}},
          {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
              'name': CLIENT_NS, 'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}},
          {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
              'name': BACKUP_NS, 'labels': {'pod-security.kubernetes.io/enforce': 'baseline'}}}, *inputs['objects'])
    for resource in ('deployment/csi-nfs-controller', 'daemonset/csi-nfs-node'):
        kubectl('rollout', 'status', resource, '-n', DRIVER_NS, '--timeout=900s')
    pods = get('pods', '-n', DRIVER_NS)['items']
    assert len(pods) == 2 and all(not p['metadata'].get('deletionTimestamp') for p in pods)
    records = [record for pod in pods for record in domains(pod)]
    assert len([r for r in records if r['container'] == 'nfs']) == 2
    assert all(r['context'].split(':')[2] == 'spc_t' for r in records if r['container'] == 'nfs')
    assert get('csidriver', 'nfs.csi.k8s.io')['spec']['fsGroupPolicy'] == 'File'
    persist('native-csi-ready', domains=records, export_sha256=hashlib.sha256(exported.encode()).hexdigest())


def claim(name, namespace):
    pv = 'qualification-' + name
    apply({'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': pv}, 'spec': {
        'capacity': {'storage': '1Mi'}, 'accessModes': ['ReadWriteMany'], 'storageClassName': '',
        'persistentVolumeReclaimPolicy': 'Retain', 'mountOptions': ['vers=4.1', 'hard'],
        'claimRef': {'name': name, 'namespace': namespace}, 'csi': {
            'driver': 'nfs.csi.k8s.io', 'volumeHandle': 'qualification-' + name,
            'volumeAttributes': {'server': '127.0.0.1', 'share': '/' + name, 'mountPermissions': '0'}}}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': namespace},
         'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '', 'volumeName': pv,
                  'resources': {'requests': {'storage': '1Mi'}}}})
    kubectl('wait', 'pvc/' + name, '-n', namespace, '--for=jsonpath={.status.phase}=Bound', '--timeout=120s')
    pvc = get('pvc', name, '-n', namespace)
    volume = get('pv', pv)
    return require_binding(volume, pvc, name, namespace)


def require_binding(volume, pvc, name, namespace, expected=None):
    csi = volume['spec']['csi']
    ref = volume['spec']['claimRef']
    if (volume['metadata']['name'] != 'qualification-' + name or pvc['metadata']['name'] != name or
            pvc['metadata']['namespace'] != namespace or not volume['metadata'].get('uid') or
            not pvc['metadata'].get('uid') or volume['metadata'].get('deletionTimestamp') or
            pvc['metadata'].get('deletionTimestamp') or volume['status']['phase'] != 'Bound' or
            pvc['status']['phase'] != 'Bound' or ref['uid'] != pvc['metadata']['uid'] or
            ref['name'] != name or ref['namespace'] != namespace or
            pvc['spec']['volumeName'] != volume['metadata']['name'] or
            csi['driver'] != 'nfs.csi.k8s.io' or csi['volumeHandle'] != 'qualification-' + name or
            csi['volumeAttributes']['server'] != '127.0.0.1' or csi['volumeAttributes']['share'] != '/' + name or
            csi['volumeAttributes']['mountPermissions'] != '0' or
            volume['spec']['persistentVolumeReclaimPolicy'] != 'Retain'):
        raise RuntimeError('native CSI binding identity differs')
    result = {'pv': volume['metadata']['name'], 'pv_uid': volume['metadata']['uid'],
              'claim': name, 'claim_uid': pvc['metadata']['uid'], 'namespace': namespace}
    if expected is not None and result != expected:
        raise RuntimeError('native CSI binding was replaced')
    return result


READ = '''import pathlib,json,hashlib,os
p=pathlib.Path('/data/corpus');raw=p.read_bytes();st=p.stat()
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'lines':raw.decode().splitlines(),
                  'uid':st.st_uid,'gid':st.st_gid,'context':pathlib.Path('/proc/self/attr/current').read_text().strip()}))'''


def exercise(inputs):
    image = inputs['records'][-1]['image'].rsplit(':', 1)[0] + '@' + inputs['records'][-1]['digest']
    before = {name: {part: metadata(EXPORT / name / part) if part else metadata(EXPORT / name)
                     for part in ('', 'marker')} for name in ('builder', 'incompatible', 'backup')}
    bindings = [claim(name, BACKUP_NS if name == 'backup' else CLIENT_NS)
                for name in ('builder', 'incompatible', 'backup')]
    for name in ('a', 'b'):
        apply(pod_manifest(name, 'builder', image))
    pods = [ready(name) for name in ('a', 'b')]
    mount = execute('a', '''import pathlib,json,os
records=[]
for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():
 left,right=line.split(' - ',1);fields=left.split();tail=right.split()
 if fields[4]=='/data':records.append({'device':fields[2],'type':tail[0],'source':tail[1],'options':tail[2]})
assert len(records)==1 and records[0]['type']=='nfs4' and records[0]['source']=='127.0.0.1:/builder'
assert 'vers=4.1'in records[0]['options'].split(',')and 'hard'in records[0]['options'].split(',')
print(json.dumps(records))''')
    # One owned transport prints after acquiring the real lock, then exits on an explicit release marker.
    owner_script = '''import fcntl,pathlib,time,json,os
p=pathlib.Path('/data');lock=(p/'lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX)
print(json.dumps({'locked':True}),flush=True)
end=time.monotonic()+60
while not(p/'release').exists():
 assert time.monotonic()<end;time.sleep(.05)
fcntl.flock(lock,fcntl.LOCK_UN)'''
    children = []
    try:
        owner = subprocess.Popen([K3S, 'kubectl', 'exec', '-n', CLIENT_NS, 'a', '--', 'python3', '-B', '-u', '-c', owner_script],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        children.append(owner)
        assert json.loads(owner.stdout.readline()) == {'locked': True}
        refusal = execute('b', '''import fcntl,pathlib,json
p=pathlib.Path('/data');f=(p/'lock').open('a+')
try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:blocked=True
else:blocked=False;fcntl.flock(f,fcntl.LOCK_UN)
(p/'release').write_bytes(b'release\\n');print(json.dumps({'blocked':blocked}))''')
        assert refusal == {'blocked': True}
        assert owner.wait(timeout=90) == 0
        for name in ('a', 'b'):
            script = '''import fcntl,pathlib,os,time,json
name=NAME;f=pathlib.Path('/data/corpus').open('a+')
for number in range(100):
 fcntl.flock(f,fcntl.LOCK_EX);f.seek(0,2);f.write(name+':'+str(number).zfill(3)+'\\n');f.flush();os.fsync(f.fileno());fcntl.flock(f,fcntl.LOCK_UN);time.sleep(.005)
print(json.dumps({'writer':name,'fsynced':100}))'''.replace('NAME', repr(name))
            child = subprocess.Popen([K3S, 'kubectl', 'exec', '-n', CLIENT_NS, name, '--', 'python3', '-B', '-c', script],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            children.append(child)
        for child, name in zip(children[1:], ('a', 'b')):
            out, _err = child.communicate()
            assert child.returncode == 0 and json.loads(out) == {'writer': name, 'fsynced': 100}
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            for stream in (child.stdout, child.stderr):
                stream.close()
    values = [execute(name, READ) for name in ('a', 'b')]
    expected = {name + ':' + str(number).zfill(3) for name in ('a', 'b') for number in range(100)}
    comparable = [{k: v for k, v in value.items() if k != 'context'} for value in values]
    assert comparable[0] == comparable[1] and len(values[0]['lines']) == 200 and set(values[0]['lines']) == expected
    assert values[0]['uid'] == 1000 and values[0]['gid'] == 1000
    assert hashlib.sha256((EXPORT / 'builder/corpus').read_bytes()).hexdigest() == values[0]['sha256']
    # MCS contexts may differ between Pods; compare content above without conflating their labels.
    apply(pod_manifest('incompatible', 'incompatible', image))
    _bad, bad_domains = ready('incompatible')
    denied = execute('incompatible', '''import pathlib,json
try:pathlib.Path('/data/forbidden').write_bytes(b'must-fail')
except PermissionError:denied=True
else:denied=False
print(json.dumps({'permission_denied':denied}))''')
    assert denied == {'permission_denied': True} and not (EXPORT / 'incompatible/forbidden').exists()
    apply(pod_manifest('backup', 'backup', image, uid=0, group=0, fs_group=None))
    _backup, backup_domains = ready('backup', BACKUP_NS)
    result = execute('backup', '''import pathlib,json,os
p=pathlib.Path('/data/squashed');p.write_bytes(b'squashed-backup\\n')
with p.open('r+')as f:f.flush();os.fsync(f.fileno())
s=p.stat();print(json.dumps({'uid':s.st_uid,'gid':s.st_gid}))''', BACKUP_NS)
    assert result == {'uid': 65534, 'gid': 65534}
    for name in before:
        assert before[name] == {part: metadata(EXPORT / name / part) if part else metadata(EXPORT / name)
                                for part in ('', 'marker')}
    prior_uid = pods[0][0]['metadata']['uid']
    kubectl('delete', 'pod/a', '-n', CLIENT_NS, '--wait=true', '--timeout=180s')
    apply(pod_manifest('a', 'builder', image))
    replacement, replacement_domains = ready('a')
    assert replacement['metadata']['uid'] != prior_uid
    restored = execute('a', READ)
    assert {k: v for k, v in restored.items() if k != 'context'} == {k: v for k, v in values[0].items() if k != 'context'}
    old = get('pods', '-n', DRIVER_NS, '-l', 'app=csi-nfs-node')['items']
    assert len(old) == 1
    kubectl('delete', 'pod/' + old[0]['metadata']['name'], '-n', DRIVER_NS, '--wait=true', '--timeout=180s')
    kubectl('rollout', 'status', 'daemonset/csi-nfs-node', '-n', DRIVER_NS, '--timeout=900s')
    current = get('pods', '-n', DRIVER_NS, '-l', 'app=csi-nfs-node')['items']
    assert len(current) == 1 and current[0]['metadata']['uid'] != old[0]['metadata']['uid']
    _driver, driver_domains = ready(current[0]['metadata']['name'], DRIVER_NS)
    after = execute('a', READ)
    assert after == restored
    final = execute('a', '''import pathlib,fcntl,os,hashlib,json
p=pathlib.Path('/data/corpus')
with p.open('a+')as f:
 fcntl.flock(f,fcntl.LOCK_EX);f.write('after-driver-restart\\n');f.flush();os.fsync(f.fileno());fcntl.flock(f,fcntl.LOCK_UN)
raw=p.read_bytes();print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}))''')
    raw = (EXPORT / 'builder/corpus').read_bytes()
    assert final == {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert raw.endswith(b'after-driver-restart\n') and len(raw.splitlines()) == 201
    assert hashlib.sha256(native('getsebool', '-a')).hexdigest() == EVIDENCE['booleans_sha256']
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    for binding in bindings:
        require_binding(get('pv', binding['pv']), get('pvc', binding['claim'], '-n', binding['namespace']),
                        binding['claim'], binding['namespace'], binding)
    persist('consumer-domains-and-io', bindings=bindings, consumers=[r for _p, rs in pods for r in rs],
            mount=mount, corpus={k: v for k, v in values[0].items() if k != 'lines'},
            locks_excluded=True, prepared_metadata_preserved=True, incompatible_denied=denied,
            incompatible_domains=bad_domains, backup_squashed=result, backup_domains=backup_domains,
            recreated_pod_uid=replacement['metadata']['uid'], replacement_domains=replacement_domains,
            restarted_driver_uid=current[0]['metadata']['uid'], restarted_driver_domains=driver_domains,
            final_corpus=final, booleans_unchanged=True, enforcing=True)
    return bindings


def cleanup(bindings):
    for binding in bindings:
        require_binding(get('pv', binding['pv']), get('pvc', binding['claim'], '-n', binding['namespace']),
                        binding['claim'], binding['namespace'], binding)
    for namespace in (CLIENT_NS, BACKUP_NS, DRIVER_NS):
        kubectl('delete', 'namespace', namespace, '--wait=true', '--timeout=300s')
    for name in ('builder', 'incompatible', 'backup'):
        kubectl('delete', 'pv/qualification-' + name, '--wait=true', '--timeout=120s')
    mounts = native('findmnt', '--json', '--output', 'SOURCE,TARGET,FSTYPE').decode()
    assert '127.0.0.1:/' not in mounts
    native('exportfs', '-u', '127.0.0.1:' + str(EXPORT))
    Path('/etc/exports.d/qualification-csi.exports').unlink()
    native('systemctl', 'stop', 'nfs-server.service')
    assert not native('exportfs', '-v').strip()
    shutil.rmtree(EXPORT)
    persist('synthetic-nfs-cleanup', mounts_absent=True, exports_absent=True, synthetic_data_absent=not EXPORT.exists())


def main():
    try:
        inputs = json.loads((ASSETS / 'input.json').read_bytes())
        setup(inputs)
        bindings = exercise(inputs)
        cleanup(bindings)
        EVIDENCE['accepted'] = True
    except Exception as error:
        EVIDENCE['error'] = type(error).__name__ + ': ' + str(error)
        logs = subprocess.run(['journalctl', '--no-pager', '--output=cat', '-n', '1000'], capture_output=True)
        EVIDENCE['safe_avcs'] = [line[:1500] for line in logs.stdout.decode(errors='replace').splitlines()
                                 if re.search(r'avc:.*denied', line, re.I) and not re.search(
                                     r'token|password|secret|credential|authorization|private.key', line, re.I)][-30:]
    print(json.dumps(EVIDENCE), flush=True)


if __name__ == '__main__':
    main()
