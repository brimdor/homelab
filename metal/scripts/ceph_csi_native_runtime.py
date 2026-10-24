#!/usr/bin/env python3
"""Exercise static Ceph CSI volumes only in the owned enforcing Fedora VM."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import traceback

sys.path.insert(0, '/work')
from ceph_kernel_runtime import Runtime as KernelRuntime  # noqa: E402
from ceph_runtime_qualification import block_identity  # noqa: E402
from cephfs_kernel_runtime import CORPUS  # noqa: E402
from ceph_csi_native_contract import CLIENT, NAMESPACE, static_binding  # noqa: E402
from nfs_csi_native_runtime import native, kubectl, get, apply, domains  # noqa: E402
from cilium_native_runtime import wait_api_ready, EVIDENCE as API_EVIDENCE  # noqa: E402


ASSETS = Path('/var/tmp/qualification-ceph-csi-assets')
NODE = 'qualification-fedora44'
K3S = '/usr/local/bin/k3s'
EVIDENCE = {'accepted': False, 'stages': []}


def persist(stage, **values):
    EVIDENCE['stages'].append({'stage': stage, 'at_ns': time.time_ns(), **values})
    (ASSETS / 'runtime-evidence.json').write_text(json.dumps(EVIDENCE, indent=2))


def route():
    assert os.geteuid() == 0 and native('hostname').strip() == NODE.encode()
    assert native('uname', '-r').strip() == b'7.2.11-200.fc44.x86_64'
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    assert not json.loads(native('ip', '-j', 'route', 'show', 'default'))
    unit = Path('/etc/systemd/system/qualification-airgap-route.service')
    assert not unit.exists()
    unit.write_text('[Unit]\nBefore=qualification-k3s.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\n'
                    'ExecStart=/usr/sbin/ip link add dummy0 type dummy\nExecStart=/usr/sbin/ip link set dummy0 up\n'
                    'ExecStart=/usr/sbin/ip addr add 203.0.113.254/31 dev dummy0\n'
                    'ExecStart=/usr/sbin/ip route add default via 203.0.113.255 dev dummy0 metric 1000\n')
    native('systemctl', 'daemon-reload')
    native('systemctl', 'start', 'qualification-airgap-route.service')
    routes = json.loads(native('ip', '-j', 'route', 'show', 'default'))
    assert len(routes) == 1 and routes[0]['dev'] == 'dummy0' and routes[0]['gateway'] == '203.0.113.255'
    addresses = json.loads(native('ip', '-j', 'address', 'show', 'dev', 'dummy0'))
    assert len(addresses) == 1 and any(row.get('local') == '203.0.113.254' and row['prefixlen'] == 31
                                       for row in addresses[0]['addr_info'])


def start_k3s(inputs):
    for name, digest in inputs['assets'].items():
        value = hashlib.sha256()
        with (ASSETS / name).open('rb') as source:
            for block in iter(lambda: source.read(1048576), b''):
                value.update(block)
        assert value.hexdigest() == digest
    runtime = Path('/var/lib/rancher/k3s')
    expected = {'data', 'agent', 'agent/containerd', 'agent/containerd/io.containerd.snapshotter.v1.overlayfs',
                'agent/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots'}
    assert runtime.is_dir() and {str(path.relative_to(runtime)) for path in runtime.rglob('*')} == expected
    assert all(path.is_dir() and not path.is_symlink() for path in runtime.rglob('*')) and not Path(K3S).exists()
    shutil.move(str(ASSETS / 'k3s'), K3S)
    Path(K3S).chmod(0o755)
    native('chcon', '-u', 'system_u', '-r', 'object_r', '-t', 'container_runtime_exec_t', K3S)
    assert os.getxattr(K3S, 'security.selinux').decode().split(':')[2] == 'container_runtime_exec_t'
    assert b'v1.33.6+k3s1' in native(K3S, '--version')
    images = runtime / 'agent/images'
    images.mkdir(parents=True)
    shutil.move(str(ASSETS / 'airgap.tar.zst'), str(images / 'airgap.tar.zst'))
    for index in range(len(inputs['records'])):
        shutil.move(str(ASSETS / ('image-' + str(index) + '.tar')), str(images / ('image-' + str(index) + '.tar')))
    unit = Path('/etc/systemd/system/qualification-k3s.service')
    assert not unit.exists()
    unit.write_text('[Unit]\nAfter=network-online.target qualification-airgap-route.service\n'
                    'Wants=network-online.target\nRequires=qualification-airgap-route.service\n[Service]\n'
                    'Type=notify\nKillMode=process\nDelegate=yes\nLimitNOFILE=1048576\nTasksMax=infinity\n'
                    'TimeoutStartSec=0\nExecStart=' + K3S + ' server --cluster-init --selinux '
                    '--write-kubeconfig-mode=600 --disable=traefik,servicelb,local-storage,metrics-server,coredns '
                    '--disable-network-policy --prefer-bundled-bin\n[Install]\nWantedBy=multi-user.target\n')
    native('systemctl', 'daemon-reload')
    native('systemctl', 'enable', '--now', 'qualification-k3s.service')
    wait_api_ready()
    config = (runtime / 'agent/etc/containerd/config.toml').read_text()
    assert re.search(r'^\s*enable_selinux\s*=\s*true\s*$', config, re.M)
    pid = int(native('systemctl', 'show', 'qualification-k3s.service', '--property=MainPID', '--value'))
    assert pid > 1 and Path('/proc/' + str(pid) + '/attr/current').read_text().split(':')[2] == 'container_runtime_t'
    for index, record in enumerate(inputs['records']):
        repository = record['image'].rsplit(':', 1)[0]
        native(K3S, 'ctr', 'images', 'import', '--local', '--digests', '--all-platforms', '--no-unpack',
               '--base-name', repository, str(images / ('image-' + str(index) + '.tar')))
        image = json.loads(native(K3S, 'crictl', 'inspecti', repository + '@' + record['digest']))
        assert repository + '@' + record['digest'] in image['status']['repoDigests']
    kubectl('wait', '--for=create', 'node/' + NODE, '--timeout=900s')
    kubectl('wait', '--for=condition=Ready', 'node/' + NODE, '--timeout=900s')
    assert [node['metadata']['name'] for node in get('nodes')['items']] == [NODE]


class Runtime(KernelRuntime):
    public_address = '203.0.113.254'

    def setup_volumes(self):
        self.stage = 'owned static backend creation'
        admin = self.initialize_rbd_pool()
        self.command([*admin, 'create', 'qualification-rbd/qualification-csi-rbd', '--size=128M',
                      '--image-feature=layering'])
        mds = self.root / 'mds'
        mds.mkdir(mode=0o700)
        (mds / 'keyring').write_bytes(self.ceph('auth', 'get-or-create', 'mds.a', 'mon', 'allow profile mds',
                'mgr', 'allow profile mds', 'osd', 'allow rw tag cephfs *=*', 'mds', 'allow', '--key-type=aes256k'))
        (mds / 'keyring').chmod(0o600)
        with (self.root / 'ceph.conf').open('a') as output:
            output.write('\n[mds.a]\nmds data = /work/mds\nkeyring = /work/mds/keyring\nmds cache memory limit = 268435456\n')
        for pool in ('qualificationfs_metadata', 'qualificationfs_data'):
            self.ceph('osd', 'pool', 'create', pool, '4')
        self.ceph('fs', 'new', 'qualificationfs', 'qualificationfs_metadata', 'qualificationfs_data')
        self.ceph('fs', 'set', 'qualificationfs', 'standby_count_wanted', '0')
        self.start('mds', 'a')
        self.mds_ready()
        caps = {'rbd': ['mon', 'profile rbd', 'osd', 'profile rbd pool=qualification-rbd',
                        'mgr', 'profile rbd pool=qualification-rbd'],
                'cephfs': ['mon', 'allow r fsname=qualificationfs', 'mds', 'allow rw fsname=qualificationfs',
                           'osd', 'allow rw tag cephfs data=qualificationfs']}
        for kind, values in caps.items():
            path = self.root / ('csi-' + kind + '.keyring')
            path.write_bytes(self.ceph('auth', 'get-or-create', 'client.csi-' + kind, *values, '--key-type=aes256k'))
            path.chmod(0o600)

    def mds_ready(self):
        until = time.monotonic() + 180
        while True:
            self.running()
            rows = json.loads(self.ceph('fs', 'dump', '--format=json'))['filesystems']
            assert len(rows) == 1 and rows[0]['mdsmap']['fs_name'] == 'qualificationfs'
            active = list(rows[0]['mdsmap']['info'].values())
            if len(active) == 1 and active[0]['name'] == 'a' and active[0]['state'] == 'up:active':
                self.steady()
                return
            if time.monotonic() >= until:
                raise RuntimeError('owned synthetic MDS did not become active')
            time.sleep(1)

    def credential(self, kind):
        return self.command(['ceph-authtool', str(self.root / ('csi-' + kind + '.keyring')),
                             '-n', 'client.csi-' + kind, '-p']).stdout.decode().strip()

    def backend(self):
        image = json.loads(self.command(['rbd', *self.conf, '-n', 'client.admin', '-k', str(self.root / 'admin.keyring'),
                                         'info', 'qualification-rbd/qualification-csi-rbd', '--format=json']).stdout)
        filesystem = json.loads(self.ceph('fs', 'dump', '--format=json'))['filesystems']
        assert len(filesystem) == 1 and image['name'] == 'qualification-csi-rbd' and image['size'] == 128 * 1024**2
        row = filesystem[0]
        assert row['mdsmap']['fs_name'] == 'qualificationfs'
        return {'fsid': self.status()['fsid'], 'rbd_id': image['id'], 'rbd_size': image['size'],
                'fscid': row['id'], 'data_pools': row['mdsmap']['data_pools'],
                'metadata_pool': row['mdsmap']['metadata_pool'], 'block': block_identity(self.root)}

    def auth_position(self):
        value = (self.root / 'mon.log').lstat()
        assert stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid()
        return value.st_dev, value.st_ino, value.st_size

    def fresh_refusals(self, before, kind):
        descriptor = os.open(self.root / 'mon.log', os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source:
            value = os.fstat(source.fileno())
            assert stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid()
            assert (value.st_dev, value.st_ino) == before[:2] and value.st_size >= before[2]
            source.seek(before[2])
            return sum(bool(re.search(rb'cephx server client\.csi-' + kind.encode() + rb':\s+unexpected key:', line))
                       for line in source)


def components():
    for kind in ('rbd', 'cephfs'):
        for resource, suffix in (('daemonset', ''), ('deployment', '-provisioner')):
            kubectl('rollout', 'status', resource + '/csi-' + kind + 'plugin' + suffix,
                    '-n', NAMESPACE, '--timeout=900s')
    rows = get('pods', '-n', NAMESPACE)['items']
    assert len(rows) == 4 and all(not row['metadata'].get('deletionTimestamp') for row in rows)
    observed = []
    for row in rows:
        values = domains(row)
        owner = row['metadata']['ownerReferences']
        assert len(owner) == 1 and owner[0]['controller'] is True
        expected = 'spc_t' if owner[0]['kind'] == 'DaemonSet' else 'container_t'
        assert owner[0]['kind'] in ('DaemonSet', 'ReplicaSet')
        assert all(value['context'].split(':')[2] == expected for value in values)
        observed.extend(values)
    registration = get('csinode', NODE)['spec']['drivers']
    assert len(registration) == 2 and {row['name'] for row in registration} == {
        'rbd.csi.ceph.com', 'cephfs.csi.ceph.com'}
    assert all(row['nodeID'] == NODE for row in registration)
    return {'pod_uids': sorted(row['metadata']['uid'] for row in rows), 'domains': observed,
            'registration': registration}


def secret(kind, value):
    apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': kind + '-credential', 'namespace': NAMESPACE},
           'type': 'Opaque', 'stringData': {'userID': 'csi-' + kind, 'userKey': value}})


def binding(kind, cluster):
    expected, claim = static_binding(kind, cluster)
    pv = get('pv', expected['metadata']['name'])
    pvc = get('pvc', kind, '-n', CLIENT)
    assert pv['status']['phase'] == pvc['status']['phase'] == 'Bound'
    assert pvc['spec']['volumeName'] == expected['metadata']['name']
    assert pv['spec']['claimRef']['uid'] == pvc['metadata']['uid']
    assert pv['spec']['claimRef']['name'] == kind and pv['spec']['claimRef']['namespace'] == CLIENT
    assert all(pv['spec'][key] == expected['spec'][key] for key in (
        'csi', 'accessModes', 'volumeMode', 'storageClassName', 'persistentVolumeReclaimPolicy', 'capacity'))
    assert pv['spec'].get('mountOptions') == expected['spec'].get('mountOptions')
    assert all(pvc['spec'][key] == claim['spec'][key] for key in ('accessModes', 'volumeMode', 'storageClassName', 'volumeName'))
    return {'pv_uid': pv['metadata']['uid'], 'pvc_uid': pvc['metadata']['uid'], 'spec': expected['spec']}


def pod(kind, image):
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': kind, 'namespace': CLIENT}, 'spec': {
        'automountServiceAccountToken': False,
        'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'runAsNonRoot': True,
                            'fsGroup': 1000, 'fsGroupChangePolicy': 'OnRootMismatch',
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'consumer', 'image': image, 'imagePullPolicy': 'Never',
                        'command': ['python3', '-B', '-c', 'import time;time.sleep(86400)'],
                        'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                            'capabilities': {'drop': ['ALL']}},
                        'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
        'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': kind}}]}}


LOCK = '''import fcntl,json,select,subprocess,sys
holder="import fcntl,sys;f=open('/data/corpus/renamed','r+b');fcntl.flock(f,fcntl.LOCK_EX);print('LOCKED',flush=True);sys.stdin.buffer.read(1)"
child=subprocess.Popen([sys.executable,'-B','-c',holder],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:
 assert select.select([child.stdout],[],[],30)[0]and child.stdout.readline()==b'LOCKED\\n'
 with open('/data/corpus/renamed','r+b')as source:
  try:fcntl.flock(source,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:pass
  else:raise RuntimeError('independent process did not exclude lock')
 child.communicate(input=b'x',timeout=10);assert child.returncode==0
 with open('/data/corpus/renamed','r+b')as source:fcntl.flock(source,fcntl.LOCK_EX|fcntl.LOCK_NB)
 print(json.dumps({'within_pod_process_lock_exclusion':True,'release_reacquire':True}))
finally:
 if child.poll()is None:child.kill()
 child.communicate()
'''


def consume(image, create=False):
    result = {}
    contexts = []
    for kind in ('rbd', 'cephfs'):
        apply(pod(kind, image))
        kubectl('wait', '--for=condition=Ready', 'pod/' + kind, '-n', CLIENT, '--timeout=900s')
        row = get('pod', kind, '-n', CLIENT)
        identities = domains(row)
        assert len(identities) == 1 and identities[0]['context'].split(':')[2] == 'container_t'
        contexts.append(identities[0]['context'].split(':', 3)[3])
        setup = "import pathlib,sys\nif sys.argv[2]=='create':\n p=pathlib.Path(sys.argv[1])/'corpus';p.mkdir(mode=0o2770);p.chmod(0o2770)\n"
        corpus = json.loads(kubectl('exec', '-n', CLIENT, kind, '--', 'python3', '-B', '-c', setup + CORPUS,
                                    '/data', 'create' if create else 'verify'))
        locking = json.loads(kubectl('exec', '-n', CLIENT, kind, '--', 'python3', '-B', '-c', LOCK))
        mount = json.loads(kubectl('exec', '-n', CLIENT, kind, '--', 'python3', '-B', '-c',
                                  "import json,pathlib;rows=[r.split()for r in pathlib.Path('/proc/self/mountinfo').read_text().splitlines()];rows=[r for r in rows if r[4]=='/data'];assert len(rows)==1;r=rows[0];i=r.index('-');print(json.dumps({'device':r[2],'type':r[i+1],'source':r[i+2],'options':r[i+3]}))"))
        if kind == 'rbd':
            mappings = json.loads(native('rbd', 'device', 'list', '--format=json'))
            assert len(mappings) == 1 and mappings[0]['pool'] == 'qualification-rbd'
            assert mappings[0]['name'] == 'qualification-csi-rbd' and mount['source'] == mappings[0]['device']
            assert mount['type'] == 'ext4' and re.fullmatch(r'/dev/rbd[0-9]+', mount['source'])
            config = Path('/sys/bus/rbd/devices') / str(int(mappings[0]['id'])) / 'config_info'
            assert re.search(r'(?:^|[, ])ms_mode=secure(?:[, ]|$)', config.read_text().strip())
        else:
            assert mount['type'] == 'ceph' and 'ms_mode=secure' in mount['options'].split(',')
        result[kind] = {'pod_uid': row['metadata']['uid'], 'domains': identities, 'corpus': corpus, 'locking': locking,
                        'mount': {key: mount[key] for key in ('device', 'type', 'source')}, 'secure_kernel_connection': True}
    assert contexts[0] != contexts[1]
    return result


def remove_consumers():
    kubectl('delete', 'pod', 'rbd', 'cephfs', '-n', CLIENT, '--ignore-not-found=true', '--wait=true', '--timeout=180s')
    until = time.monotonic() + 180
    while True:
        mappings = json.loads(native('rbd', 'device', 'list', '--format=json'))
        assert all(row['pool'] == 'qualification-rbd' and row['name'] == 'qualification-csi-rbd' for row in mappings)
        mounts = subprocess.run(['findmnt', '--json', '--list', '--types', 'ceph', '--output=TARGET,SOURCE,FSTYPE'], capture_output=True)
        assert mounts.returncode in (0, 1) and not mounts.stderr
        rows = json.loads(mounts.stdout)['filesystems'] if mounts.returncode == 0 else []
        assert all(row['target'].startswith('/var/lib/kubelet/') for row in rows)
        if not mappings and not rows:
            return
        if time.monotonic() >= until:
            raise RuntimeError('owned static CSI mappings or mounts remain')
        time.sleep(1)


def replace_plugins():
    before = components()
    rows = get('pods', '-n', NAMESPACE)['items']
    kubectl('delete', 'pod', *[row['metadata']['name'] for row in rows], '-n', NAMESPACE,
            '--wait=true', '--timeout=180s')
    after = components()
    assert not set(before['pod_uids']) & set(after['pod_uids'])
    return after


def run(runtime):
    inputs = json.loads((ASSETS / 'input.json').read_bytes())
    booleans = hashlib.sha256(native('getsebool', '-a')).hexdigest()
    persist('native-rados', result=runtime.run())
    runtime.setup_volumes()
    backend = runtime.backend()
    start_k3s(inputs)
    apply(*[{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name}} for name in (NAMESPACE, CLIENT)])
    apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'ceph-csi-config', 'namespace': NAMESPACE},
           'data': {'config.json': json.dumps([{'clusterID': backend['fsid'], 'monitors': ['203.0.113.254:13300']}])}},
          {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'ceph-csi-encryption-kms-config', 'namespace': NAMESPACE},
           'data': {'config.json': '{}'}},
          {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'ceph-config', 'namespace': NAMESPACE},
           'data': {'ceph.conf': '[global]\nms_client_mode = secure\n', 'keyring': ''}})
    apply(*inputs['objects'])
    initial_components = components()
    persist('native-csi-components', **initial_components)
    plugin = next(row for row in get('pods', '-n', NAMESPACE)['items'] if row['metadata']['labels']['app'] == 'csi-rbdplugin')
    versions = kubectl('exec', '-n', NAMESPACE, plugin['metadata']['name'], '-c', 'csi-rbdplugin', '--',
                       'rpm', '-q', '--qf', '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n',
                       'ceph-common', 'librados2', 'librbd1', 'libcephfs2').decode().splitlines()
    assert len(versions) == 4 and all(re.fullmatch(r'[a-z0-9-]+ [A-Za-z0-9.+_~-]+', value) for value in versions)
    persist('native-image-client-libraries', packages=versions)
    original_credentials = {}
    for kind in ('rbd', 'cephfs'):
        original_credentials[kind] = runtime.credential(kind)
        secret(kind, original_credentials[kind])
        apply(*static_binding(kind, backend['fsid']))
        kubectl('wait', '--for=jsonpath={.status.phase}=Bound', 'pvc/' + kind, '-n', CLIENT, '--timeout=180s')
    bindings = {kind: binding(kind, backend['fsid']) for kind in ('rbd', 'cephfs')}
    image = inputs['records'][-1]['image'].rsplit(':', 1)[0] + '@' + inputs['records'][-1]['digest']
    original = consume(image, create=True)
    persist('initial-csi-workload-data', result=original, backend=backend, bindings=bindings)
    for phase in ('consumer-replacement', 'plugin-replacement'):
        remove_consumers()
        if phase == 'plugin-replacement':
            persist('replaced-csi-components', **replace_plugins())
        current = consume(image)
        assert all(current[kind]['pod_uid'] != original[kind]['pod_uid'] and
                   current[kind]['corpus'] == original[kind]['corpus'] for kind in original)
        assert runtime.backend() == backend and {kind: binding(kind, backend['fsid']) for kind in original} == bindings
        persist(phase + '-csi-workload-data', result=current)
    remove_consumers()
    for kind in ('rbd', 'cephfs'):
        keyring = runtime.root / ('csi-' + kind + '.keyring')
        runtime.rotate_keyring('client.csi-' + kind, keyring, keyring)
    for kind in ('rbd', 'cephfs'):
        replace_plugins()
        position = runtime.auth_position()
        apply(pod(kind, image))
        until = time.monotonic() + 120
        while True:
            row = get('pod', kind, '-n', CLIENT)
            assert not any(value.get('ready') for value in row.get('status', {}).get('containerStatuses', []))
            refusals = runtime.fresh_refusals(position, kind)
            if refusals:
                break
            if time.monotonic() >= until:
                raise RuntimeError('retired CSI credential lacks fresh exact-client authentication refusal')
            time.sleep(1)
        remove_consumers()
        persist(kind + '-retired-credential-refused', fresh_exact_client_monitor_refusals=refusals,
                consumer_never_ready=True, mappings_and_mounts_absent=True)
        secret(kind, runtime.credential(kind))
    replace_plugins()
    final = consume(image)
    assert all(final[kind]['corpus'] == original[kind]['corpus'] for kind in original)
    assert runtime.backend() == backend and {kind: binding(kind, backend['fsid']) for kind in original} == bindings
    persist('rotated-credentials-csi-workload-data', result=final)
    remove_consumers()
    assert hashlib.sha256(native('getsebool', '-a')).hexdigest() == booleans
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    assert not native('rpm', '-V', 'container-selinux', 'k3s-selinux')
    key_rows = json.loads(runtime.ceph('auth', 'dump-keys', '--format=json'))['data']['secrets']
    selected = {row['entity']['type_str'] + '.' + row['entity']['id']: row['auth']['key']['type_str']
                for row in key_rows if row['entity']['type_str'] + '.' + row['entity']['id'] in
                ('client.csi-rbd', 'client.csi-cephfs')}
    assert selected == {'client.csi-rbd': 'aes256k', 'client.csi-cephfs': 'aes256k'}
    EVIDENCE.update(accepted=True, backend=backend, bindings=bindings, key_types=selected,
                    booleans_sha256=booleans, selinux_enforcing=True, image_records=inputs['records'],
                    api_readiness=API_EVIDENCE['api_readiness'], final_health=runtime.steady(),
                    production_nas_dynamic_lifecycle_ha_cilium_and_csi_reboot_unqualified=True)
    return EVIDENCE


if __name__ == '__main__':
    runtime = None
    def cancel(_number, _frame):
        raise InterruptedError('owned native CSI fixture cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        route()
        runtime = Runtime()
        result = run(runtime)
    except BaseException as error:
        EVIDENCE.update(error=type(error).__name__ + ': ' + str(error),
                        failure_location=[{'file': Path(frame.filename).name, 'line': frame.lineno,
                                           'function': frame.name} for frame in traceback.extract_tb(error.__traceback__)])
        result = EVIDENCE
    finally:
        if runtime is not None:
            for name in list(reversed(runtime.children)):
                runtime.stop(name)
    print(json.dumps(result), flush=True)
