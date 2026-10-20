#!/usr/bin/env python3
"""Protect both homelab Builder SQLite stores at one stopped-writer instant."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import tempfile
import time

import etcd_recovery as common
import prometheus_recovery as process
import grafana_recovery as files
import sporecast_recovery as transfer

LABEL = 'io.eaglepass.builder-recovery-103'
SOURCES = {
    'builder': {'node': 'squirtle', 'pid': 4754, 'pod_uid': '06c70c83-f7e8-4a0c-be23-a3293d0d4c29',
                'container_id': '3a4e0b0be518313d2965286ccf0f9d8123e775cc418b038036d4610dbeca2eb0',
                'digest': '39ef6b0c5551140226a900d633feca7b7808c32cc36e4466ab8299aed0c45d5f',
                'source_revision': '5fd3162d2777920e229917a427c056be1f2981be',
                'git_tree': '6018fa02f42a1863d1aafe459287d49090b9f8c6',
                'bundle_sha256': 'baa631388688e140b592f67c6af5dbfcddcd4fb83aea5e362258779aac0bf49f',
                'stores': {'data': {'pvc_uid': '5a2ce7ec-bc5e-4ce9-8c3f-dc06ac5d31b8', 'pv_uid': 'ca1b0177-9249-4ef0-9fd7-132741c4ef0b', 'device': 64272, 'inode': 2},
                           'recovery': {'pvc_uid': '318b777f-6cd0-4c6b-bc20-d6feef0251b5', 'pv_uid': '56a7f1fc-8bf8-4761-85fd-2c263508f1f6', 'device': 64288, 'inode': 2}}},
    'builder-canary': {'node': 'bulbasaur', 'pid': 7894, 'pod_uid': '72085e4e-c167-4cb5-8649-f59084fc658f',
                       'container_id': '494d49ab34d885c4b53fdd4ea16f6555cef317cf474a66de6704ddc1140fde9b',
                       'digest': 'b172f5e79939a43e7fb5440fb096666282ff18d7d7124b4949657cb9ff543db8',
                       'source_revision': '30249d73ac075143e7c8f15a6a0c204e83c7c19e',
                       'git_tree': 'e8688dbffe827e6077a4fdffc99a89dbb4924365',
                       'bundle_sha256': '178ed695827f3a0c7445fb592100017d6d770ff832b0c267591c010976912282',
                       'stores': {'data': {'pvc_uid': '456b7a66-0d8d-4d6c-b95e-62609befbfc8', 'pv_uid': '82f8fd05-9472-42f9-a740-38db15803bb8', 'device': 64272, 'inode': 2},
                                  'recovery': {'pvc_uid': '3e248490-f827-4f29-8f59-5af59c79fefb', 'pv_uid': 'e45c19f1-0f0b-4f6a-8238-1eb4b6c22d2b', 'device': 64304, 'inode': 2}}},
}
DATABASES = {'data': 'workspace/workspace.sqlite', 'recovery': 'control/control.sqlite'}
TMPFS = {'/tmp': 'rw,nosuid,nodev', '/backups': 'rw,nosuid,nodev,uid=1000,gid=1000,mode=0700'}


def image(namespace):
    return 'registry.eaglepass.io/pointsite-builder@sha256:' + SOURCES[namespace]['digest']


def source_paths(namespace):
    profile = SOURCES[namespace]
    root = Path('/var/lib/kubelet/pods') / profile['pod_uid'] / 'volumes/kubernetes.io~csi'
    return {name: root / ('pvc-' + store['pvc_uid']) / 'mount' for name, store in profile['stores'].items()}


def source_identity(namespace):
    expected = SOURCES[namespace]; common.require_host(expected['node']); cid = expected['container_id']
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', cid]).stdout)
    status = runtime['status']; labels = status['labels']; spec = runtime['info']['runtimeSpec']; pid = expected['pid']
    if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'].split('@')[-1] != 'sha256:' + expected['digest'] or
            labels.get('io.kubernetes.pod.uid') != expected['pod_uid'] or labels.get('io.kubernetes.pod.namespace') != namespace or
            labels.get('io.kubernetes.container.name') != 'main' or runtime['info']['pid'] != pid or
            spec['process']['user'] != {'uid': 1000, 'gid': 1000, 'additionalGids': [1000]}):
        raise RuntimeError('reviewed Builder source runtime changed')
    identity = process.process_identity(pid)
    if identity['exe'] != '/usr/local/bin/node' or expected['pod_uid'].replace('-', '_') not in identity['cgroup']:
        raise RuntimeError('Builder process identity changed')
    tasks = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode().splitlines()[1:]
    if [int(line.split()[0]) for line in tasks if line.strip()] != [pid]: raise RuntimeError('unreviewed additional writer process')
    root = Path('/proc') / str(pid) / 'root'
    release = json.loads((root / 'app/dist/release.json').read_text())
    if (release.get('sourceRevision') != expected['source_revision'] or release.get('gitTree') != expected['git_tree'] or
            release.get('sourceClean') is not True or hashlib.sha256((root / 'app/dist/server/index.js').read_bytes()).hexdigest() != expected['bundle_sha256']):
        raise RuntimeError('exact original clean Builder release changed')
    for name, path in source_paths(namespace).items():
        store = expected['stores'][name]
        if any(p.is_symlink() for p in (path, *path.parents)): raise RuntimeError('unsafe source CSI ancestry')
        mounts = [m for m in spec['mounts'] if m['destination'] == '/' + name]
        a, b = path.stat(), (root / name).stat()
        if (len(mounts) != 1 or mounts[0]['source'] != str(path) or
                (a.st_dev, a.st_ino) != (store['device'], store['inode']) or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
            raise RuntimeError('exact two-store CSI source changed')
    return {'namespace': namespace, 'profile': expected, 'process': identity, 'image': image(namespace)}


def validate_manifest(value, namespace):
    expected = SOURCES[namespace]
    if (not isinstance(value, dict) or value.get('format') != 1 or value.get('cluster_uid') != common.CLUSTER_UID or
            not isinstance(value.get('source'), dict) or value['source'].get('profile') != expected or
            value['source'].get('namespace') != namespace or value['source'].get('image') != image(namespace) or
            not isinstance(value['source'].get('process'), dict) or value['source']['process'].get('pid') != expected['pid'] or
            value['source']['process'].get('exe') != '/usr/local/bin/node' or not isinstance(value.get('pause'), dict) or
            type(value['pause'].get('stopped_seconds')) not in (int, float) or not 0 < value['pause']['stopped_seconds'] < 10 or
            value.get('original_process_resumed') is not True or value.get('two_stores_same_pause') is not True):
        raise RuntimeError('protected Builder source or shared pause changed')
    size = transfer.validate_tree(value.get('tree'))
    if type(value.get('bytes')) is not int or size != value['bytes']: raise RuntimeError('protected byte count differs')
    required = {name + '/' + database + suffix for name, database in DATABASES.items() for suffix in ('', '-wal', '-shm')}
    tree = value['tree']
    if (not required <= set(tree['files']) or not set(DATABASES) <= set(tree['directories']) or
            any(Path(name).parts[0] not in DATABASES for name in [*tree['files'], *tree['directories']])):
        raise RuntimeError('both complete SQLite WAL stores are required')
    return value


def verify(point, checksum, namespace):
    return transfer.verify(point, checksum, namespace, validator=validate_manifest)


def store_tree(root):
    device = root.stat().st_dev
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            value = (Path(parent) / name).lstat()
            if value.st_dev != device or not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):
                raise RuntimeError('store contains a foreign device, symlink or special file')
    return files.tree(root)


def snapshot(paths):
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))) * 1024
    before = {name: store_tree(root) for name, root in paths.items()}
    if sum(r['bytes'] for tree in before.values() for r in tree['files'].values()) * 2 >= available:
        raise RuntimeError('actual available memory cannot hold both stores')
    inventory = {'directories': sorted(paths), 'files': {}}; payloads = {}
    for name, root in paths.items():
        tree, data = transfer.memory_snapshot(root)
        if tree != before[name]: raise RuntimeError('store changed during joint capture')
        inventory['directories'].extend(name + '/' + directory for directory in tree['directories'])
        inventory['files'].update({name + '/' + path: record for path, record in tree['files'].items()})
        payloads.update({name + '/' + path: value for path, value in data.items()})
    if before != {name: store_tree(root) for name, root in paths.items()}: raise RuntimeError('two-store source changed before resume')
    inventory['directories'].sort(); return inventory, payloads


def send(namespace, output):
    before = source_identity(namespace)
    with tempfile.TemporaryDirectory(prefix='homelab-builder-103-', dir='/run') as marker_dir:
        marker = Path(marker_dir) / 'watchdog-fired'
        with process.frozen(before['process'], marker) as pause:
            if source_identity(namespace) != before: raise RuntimeError('source changed before pause')
            tree, payloads = snapshot(source_paths(namespace))
            if source_identity(namespace) != before: raise RuntimeError('source changed during pause')
        if marker.exists() or source_identity(namespace) != before: raise RuntimeError('original source did not resume unchanged')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'tree': tree, 'pause': pause,
                'bytes': sum(len(v) for v in payloads.values()), 'original_process_resumed': True, 'two_stores_same_pause': True}
    validate_manifest(manifest, namespace); raw = common.canonical(manifest)
    if len(raw) > 1048576: raise RuntimeError('manifest exceeds frame contract')
    output.write(raw + b'\n')
    for name in sorted(payloads): output.write(payloads[name])
    output.write(common.canonical({'commit': hashlib.sha256(raw).hexdigest()}) + b'\n'); output.flush()


def point_path(namespace, run_id):
    common.require_host('pikachu'); common.private_root()
    return common.ROOT / (namespace + '-' + common.run_identifier(run_id))


def environment(namespace):
    canary = namespace.endswith('-canary')
    return {'DATA_DIRECTORY': '/data/workspace', 'RECOVERY_DIRECTORY': '/recovery/control', 'BACKUP_DIRECTORY': '/backups/native',
            'ENVIRONMENT': 'canary' if canary else 'production', 'BUILDER_ORIGIN': 'https://' + namespace + '.eaglepass.io',
            'STAGING_REPOSITORY': 'PointCommunity/pointsite-staging' + ('-canary' if canary else ''),
            'APP_VERSION': SOURCES[namespace]['source_revision'], 'DRAFT_STORAGE_FORMAT': 'compact-v1', 'PORT': '3000',
            'NODE_ENV': 'production', 'PRODUCTION_ENABLED': 'false', 'GITHUB_APP_ID': '1', 'GITHUB_STAGING_INSTALLATION_ID': '1',
            'GITHUB_APP_PRIVATE_KEY': 'synthetic-' + 'x' * 128, 'GITHUB_CLIENT_ID': 'synthetic-client',
            'GITHUB_CLIENT_SECRET': 'synthetic-' + 'x' * 32, 'SESSION_SECRET': 'synthetic-' + 'x' * 64}


def require_container(value, scratch, namespace, run_id, phase):
    host = value['HostConfig']; config = value['Config']; env = dict(e.split('=', 1) for e in config.get('Env', []) if '=' in e)
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 1000000000, 'Tmpfs': TMPFS}
    mounts = {(str(scratch / phase / name), '/' + name, True) for name in DATABASES}
    mounts.add((str(scratch / 'tools'), '/tool', False))
    args = ['dist/server/index.js'] if phase == 'native' else ['--disable-warning=ExperimentalWarning', '/tool/probe.cjs']
    if (config['Image'] != image(namespace) or config['User'] != '1000:1000' or config.get('WorkingDir') != '/app' or
            config.get('Labels', {}).get(LABEL) != run_id or config.get('Entrypoint') != ['/usr/local/bin/node'] or config.get('Cmd') != args or
            set(env) - (set(environment(namespace)) | {'PATH', 'NODE_VERSION', 'YARN_VERSION'}) or
            any(env.get(k) != v for k, v in environment(namespace).items()) or any(host.get(k) != v for k, v in expected.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            len(value['Mounts']) != len(mounts) or any(m.get('Type') != 'bind' for m in value['Mounts']) or
            {(m['Source'], m['Destination'], m['RW']) for m in value['Mounts']} != mounts):
        raise RuntimeError('native Builder isolation changed')


def probe_program():
    return """const {DatabaseSync}=require('node:sqlite');const {snapshot,check}=require('/tool/sqlite_recovery.cjs');const crypto=require('node:crypto');const out={};let instance;
for(const [name,path] of Object.entries({data:'/data/workspace/workspace.sqlite',recovery:'/recovery/control/control.sqlite'})){
 const db=new DatabaseSync(path,{timeout:10000,allowExtension:false});try{check(db);out[name]=snapshot(db);const row=db.prepare('SELECT origin,instance_id FROM builder_instance WHERE id=1').get();if(!row||row.origin!==process.env.BUILDER_ORIGIN||instance&&instance!==row.instance_id)throw Error('copied instance mismatch');instance=row.instance_id;}finally{db.close();}}
out.instance_sha256=crypto.createHash('sha256').update(instance).digest('hex');out.node_version=process.version;console.log(JSON.stringify(out));"""


def restore(namespace, run_id, checksum):
    point = point_path(namespace, run_id); manifest = verify(point, checksum, namespace)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip(): raise RuntimeError('owned Builder restore already active')
    if shutil.disk_usage(common.ROOT).free <= manifest['bytes'] * 3: raise RuntimeError('actual restore capacity cannot hold copies')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=namespace + '-restore-', dir=common.ROOT)); scratch.chmod(0o700)
    owned = {}; image_id = None; result = {'accepted': False, 'namespace': namespace, 'manifest_sha256': checksum}

    def remove(container, phase):
        require_container(common.inspect(container), scratch, namespace, run_id, phase); common.docker('rm', '-f', container)
        if common.docker('inspect', container, check=False).returncode == 0: raise RuntimeError('owned native container remains')
        del owned[container]

    def create(phase):
        for parent, _, names in os.walk(scratch / phase):
            os.chown(parent, 1000, 1000)
            for name in names: os.chown(Path(parent) / name, 1000, 1000)
        args = ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=1000:1000', '--workdir=/app',
                '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--memory=2g', '--cpus=1',
                '--label=' + LABEL + '=' + run_id, '--entrypoint=/usr/local/bin/node']
        for name, options in TMPFS.items(): args.append('--tmpfs=' + name + ':' + options)
        for name in DATABASES: args.append('--mount=type=bind,source=' + str(scratch / phase / name) + ',target=/' + name)
        args.append('--mount=type=bind,source=' + str(scratch / 'tools') + ',target=/tool,readonly')
        for key, value in environment(namespace).items(): args.extend(['--env', key + '=' + value])
        args.extend([image(namespace), *(['dist/server/index.js'] if phase == 'native' else ['--disable-warning=ExperimentalWarning', '/tool/probe.cjs'])])
        container = common.docker(*args).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container): raise RuntimeError('invalid owned container identity')
        owned[container] = phase; require_container(common.inspect(container), scratch, namespace, run_id, phase)
        return container

    def probe(phase):
        container = create(phase); output = common.docker('start', '-a', container)
        state = common.inspect(container)['State']
        if state['Running'] or state['ExitCode'] != 0: raise RuntimeError('native copied database verification failed')
        value = json.loads(output.stdout)
        if value.get('node_version') != 'v22.23.2' or any(value.get(name, {}).get('tables', 0) <= 0 for name in DATABASES):
            raise RuntimeError('exact native SQLite runtime differs')
        remove(container, phase); return value

    try:
        common.docker('pull', image(namespace)); description = json.loads(common.docker('image', 'inspect', image(namespace)).stdout)[0]; image_id = description['Id']
        if (description['Architecture'] != 'amd64' or description['Os'] != 'linux' or description['Config'].get('Volumes') or
                image(namespace) not in description.get('RepoDigests', [])):
            raise RuntimeError('exact native Builder image contract changed')
        tools = scratch / 'tools'; tools.mkdir(mode=0o700); os.chown(tools, 1000, 1000)
        program = globals().get('SQLITE_PROGRAM') or Path(__file__).with_name('sqlite_recovery.cjs').read_text()
        for name, text in {'sqlite_recovery.cjs': program, 'probe.cjs': probe_program()}.items():
            path = tools / name; path.write_text(text); path.chmod(0o600); os.chown(path, 1000, 1000)
        for phase in ('before', 'native'): files.copy_tree(point / 'data', scratch / phase)
        before = probe('before')
        if files.tree(scratch / 'native') != manifest['tree']: raise RuntimeError('untouched raw two-store copy changed')
        container = create('native'); common.docker('start', container); state = common.inspect(container)
        require_container(state, scratch, namespace, run_id, 'native'); pid = str(state['State']['Pid']); net = ['nsenter', '-t', pid, '-n', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
                               sum((json.loads(common.command([*net, 'ip', f, '-j', 'route', 'show', 'table', 'all']).stdout) for f in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0: raise RuntimeError('production route exists')
        deadline = time.monotonic() + 300
        while True:
            if not common.inspect(container)['State']['Running']: raise RuntimeError('native Builder restore exited')
            code = "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:3000/readyz',timeout=5);v=json.load(r);assert r.status==200 and v=={'ready':True};print(json.dumps(v))"
            response = common.command([*net, 'python3', '-B', '-c', code], check=False)
            if response.returncode == 0: break
            if time.monotonic() >= deadline: raise RuntimeError('native readiness exceeded300seconds')
            time.sleep(1)
        require_container(common.inspect(container), scratch, namespace, run_id, 'native'); common.docker('stop', '--time=40', container)
        state = common.inspect(container)['State']
        if state['Running'] or state['ExitCode'] != 0: raise RuntimeError('native server did not stop cleanly')
        remove(container, 'native'); files.copy_tree(scratch / 'native', scratch / 'after'); after = probe('after')
        verify(point, checksum, namespace)
        result.update(accepted=True, image=image(namespace), before_native=before, after_native=after, ready=True,
                      clean_exit=0, raw_two_store_copy_started=True, network_none=True, production_route_absent=True,
                      original_and_nas_unmounted=True, synthetic_credentials_only=True,
                      public_login_publication_provider_nas_offsite_later_writes_unqualified=True)
    finally:
        for container, phase in list(owned.items()): remove(container, phase)
        removed = False
        if image_id and image_id not in images:
            if common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip(): raise RuntimeError('new image has another consumer; retained')
            common.docker('image', 'rm', image(namespace)); removed = common.docker('image', 'inspect', image(namespace), check=False).returncode != 0
            if not removed: raise RuntimeError('new unused image remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch); verify(point, checksum, namespace)
        result['cleanup'] = {'owned_containers_absent': not owned, 'scratch_absent': not scratch.exists(),
                             'protected_hashes_unchanged': True, 'new_unused_image_removed': removed, 'allocated_bytes_removed': allocated}
        files.write_json(point / ('restore-' + str(time.time_ns()) + '.json'), result); print(json.dumps(result), flush=True)
    return result


def main():
    os.umask(0o077)
    def cancel(_number, _frame): raise InterruptedError('owned Builder recovery interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, cancel)
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('mode', choices=('send', 'receive', 'restore'))
    parser.add_argument('--namespace', choices=sorted(SOURCES), required=True); parser.add_argument('--run-id', type=common.run_identifier, required=True)
    parser.add_argument('--manifest'); args = parser.parse_args()
    if args.mode == 'send': send(args.namespace, sys.stdout.buffer)
    elif args.mode == 'receive': print(json.dumps(transfer.receive(sys.stdin.buffer, point_path(args.namespace, args.run_id), args.namespace, validate_manifest, verify)), flush=True)
    else:
        if not re.fullmatch('[a-f0-9]{64}', args.manifest or ''): parser.error('restore requires exact manifest SHA256')
        return 0 if restore(args.namespace, args.run_id, args.manifest)['accepted'] else 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
