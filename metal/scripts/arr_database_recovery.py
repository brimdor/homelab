#!/usr/bin/env python3
"""Protect reviewed Arr databases without traversing NAS or replacing live Pods."""

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
import sys
import tempfile
import time
import urllib.parse

import etcd_recovery as common
import grafana_recovery as files
import prometheus_recovery as process
import sporecast_recovery as transfer


LABEL = 'io.eaglepass.arr-database-recovery-103'
S6 = '/package/admin/s6-2.13.2.0/command/'
SHUTDOWN = '/package/admin/s6-linux-init-1.1.3.0/command/s6-linux-init-shutdownd'
SOURCES = {
    'radarr': {'node': 'charmander', 'pid': 8241, 'app_pid': 8723,
               'pod_uid': 'cf016efa-f55f-4b0b-b3bc-af3a237f7cfd',
               'container_id': '85ebe232a17fdb1b84aa12ede041790d9cc3288ad679bf3cdd18d8ab980a79a8',
               'digest': 'ea6822c956d26db648b237919f41340318f32e5b7dcc4ba702cf256a0f5f3c12',
               'pvc_uid': '9a72e224-8f4f-4676-832b-836f06e81b1a', 'pv_uid': 'c24a4aae-338a-4abf-98c8-4e7ec956c10e',
               'pv_name': 'pvc-edaac728-7287-4b7b-99b9-c41cd9334459', 'device': 64320, 'inode': 2,
               'tasks': {8241: S6 + 's6-svscan', 8344: S6 + 's6-supervise', 8346: SHUTDOWN,
                         8382: S6 + 's6-supervise', 8383: S6 + 's6-supervise', 8385: S6 + 's6-supervise',
                         8386: S6 + 's6-supervise', 8412: S6 + 's6-ipcserverd', 8723: '/app/radarr/bin/Radarr', 8724: '/usr/bin/busybox'}},
    'sonarr': {'node': 'pikachu', 'pid': 11270, 'app_pid': 11428,
               'pod_uid': 'fff2f81f-a8f6-4a3c-afd7-a6e420ec060a',
               'container_id': '198539c0ff5f0e92674a238b7116c958cfeef1c42010fe36ee778913dbcf2aa2',
               'digest': '44b06045a98bc1f237b9ffefc4b28dab64cb29305e4a2a94875ae93b5224e4cc',
               'pvc_uid': '1a0abfcd-a3e9-44e9-b632-8c3f42cec27c', 'pv_uid': '58c09e20-41c6-4cb9-941f-c61e606e38db',
               'pv_name': 'pvc-1a0abfcd-a3e9-44e9-b632-8c3f42cec27c', 'device': 64288, 'inode': 2,
               'tasks': {11270: S6 + 's6-svscan', 11293: S6 + 's6-supervise', 11296: SHUTDOWN,
                         11312: S6 + 's6-supervise', 11313: S6 + 's6-supervise', 11314: S6 + 's6-supervise',
                         11315: S6 + 's6-supervise', 11323: S6 + 's6-ipcserverd', 11428: '/app/sonarr/bin/Sonarr', 11429: '/usr/bin/busybox'}},
}
# JSON profile identities use string keys so the protected wire representation is exact.
for profile in SOURCES.values():
    profile['tasks'] = {str(pid): exe for pid, exe in profile['tasks'].items()}


def image(namespace):
    return 'ghcr.io/linuxserver/' + namespace + '@sha256:' + SOURCES[namespace]['digest']


def source_path(namespace):
    p = SOURCES[namespace]
    return Path('/var/lib/kubelet/pods') / p['pod_uid'] / 'volumes/kubernetes.io~csi' / p['pv_name'] / 'mount'


def source_identity(namespace):
    p = SOURCES[namespace]
    common.require_host(p['node'])
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', p['container_id']]).stdout)
    status, spec = runtime['status'], runtime['info']['runtimeSpec']
    labels = status['labels']
    if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'].split('@')[-1] != 'sha256:' + p['digest'] or
            runtime['info']['pid'] != p['pid'] or labels.get('io.kubernetes.pod.uid') != p['pod_uid'] or
            labels.get('io.kubernetes.pod.namespace') != namespace or labels.get('io.kubernetes.container.name') != 'main'):
        raise RuntimeError('reviewed Arr runtime changed')
    raw = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', p['container_id']]).stdout.decode()
    tasks = {line.split()[0] for line in raw.splitlines()[1:] if line.strip()}
    if tasks != set(p['tasks']):
        raise RuntimeError('reviewed Arr container task set changed')
    identities = []
    for pid in sorted(map(int, tasks)):
        identity = process.process_identity(pid)
        if (identity['exe'] != p['tasks'][str(pid)] or p['pod_uid'].replace('-', '_') not in identity['cgroup'] or
                (Path('/proc') / str(pid)).stat().st_uid != (99 if pid == p['app_pid'] else 0)):
            raise RuntimeError('reviewed Arr executable, process or user changed')
        identities.append(identity)
    path = source_path(namespace)
    if any(x.is_symlink() for x in (path, *path.parents)):
        raise RuntimeError('unsafe Arr CSI source ancestry')
    mounts = [m for m in spec['mounts'] if m['destination'] == '/config']
    a, b = path.stat(), (Path('/proc') / str(p['app_pid']) / 'root/config').stat()
    if (len(mounts) != 1 or mounts[0]['source'] != str(path) or
            (a.st_dev, a.st_ino) != (p['device'], p['inode']) or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
        raise RuntimeError('reviewed Arr CSI identity changed')
    return {'namespace': namespace, 'profile': p, 'image': image(namespace), 'processes': identities}


def selected(root, namespace):
    required = {'config.xml', namespace + '.db', 'logs.db'}
    names = required | {database + suffix for database in (namespace + '.db', 'logs.db')
                        for suffix in ('-wal', '-shm', '-journal') if (root / (database + suffix)).exists()}
    device = root.stat().st_dev
    result = {}
    for name in sorted(names):
        p = root / name
        value = p.lstat()
        if value.st_dev != device or not stat.S_ISREG(value.st_mode) or (name in required and value.st_size <= 0):
            raise RuntimeError('selected Arr database is missing, foreign or unsafe')
        result[name] = process.file_identity(p)
    for database in (namespace + '.db', 'logs.db'):
        if (database + '-wal' in names) != (database + '-shm' in names):
            raise RuntimeError('selected Arr WAL companions are incomplete')
    return result


def warm(root, namespace):
    for name in selected(root, namespace):
        with os.fdopen(os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
            while source.read(1048576):
                pass


@contextmanager
def stopped(identities, markers):
    if (not identities or len({i['pid'] for i in identities}) != len(identities) or
            markers.exists() or any(process.process_identity(i['pid']) != i for i in identities)):
        raise RuntimeError('unsafe coordinated pause identity')
    markers.mkdir(mode=0o700)
    pauses = []
    with ExitStack() as stack:
        for identity in identities:
            pauses.append(stack.enter_context(process.frozen(identity, markers / str(identity['pid']))))
        if any(any(s != 'T' for s in process.thread_states(i['pid']).values()) for i in identities):
            raise RuntimeError('not every container thread stopped')
        yield pauses
    if any(markers.iterdir()) or any(process.process_identity(i['pid']) != i or
                                   any(s in ('T', 't') for s in process.thread_states(i['pid']).values()) for i in identities):
        raise RuntimeError('coordinated Arr source resumption failed')


def available_memory():
    return int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))) * 1024


def snapshot(root, namespace):
    before = selected(root, namespace)
    size = sum(v[2] for v in before.values())
    if size * 2 >= available_memory():
        raise RuntimeError('actual available RAM cannot hold selected Arr databases')
    payloads, tree = {}, {'directories': [], 'files': {}}
    for name, identity in before.items():
        with os.fdopen(os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
            data = source.read()
        if process.file_identity(root / name) != identity or len(data) != identity[2]:
            raise RuntimeError('selected Arr source changed during capture')
        payloads[name] = data
        tree['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    if selected(root, namespace) != before:
        raise RuntimeError('selected Arr file set changed before resumption')
    return tree, payloads


def validate_manifest(value, namespace):
    p = SOURCES[namespace]
    if (not isinstance(value, dict) or value.get('format') != 1 or value.get('cluster_uid') != common.CLUSTER_UID or
            not isinstance(value.get('source'), dict) or
            value.get('source', {}).get('profile') != p or value['source'].get('namespace') != namespace or
            value['source'].get('image') != image(namespace) or value.get('original_process_resumed') is not True or
            value.get('scope') != 'selected-databases-and-config-only' or
            not isinstance(value.get('pause'), dict) or value['pause'].get('process_count') != len(p['tasks']) or
            type(value['pause'].get('stopped_seconds')) not in (int, float) or not 0 < value['pause']['stopped_seconds'] < 10):
        raise RuntimeError('Arr source or coordinated pause manifest changed')
    identities = value['source'].get('processes', [])
    if (not isinstance(identities, list) or len(identities) != len(p['tasks']) or any(not isinstance(i, dict) for i in identities) or
            {str(i.get('pid')): i.get('exe') for i in identities} != p['tasks'] or
            any(not str(i.get('start_ticks', '')).isdigit() or p['pod_uid'].replace('-', '_') not in i.get('cgroup', '') for i in identities)):
        raise RuntimeError('Arr task identities missing from protected point')
    size = transfer.validate_tree(value.get('tree'))
    required = {'config.xml', namespace + '.db', 'logs.db'}
    allowed = required | {db + suffix for db in (namespace + '.db', 'logs.db') for suffix in ('-wal', '-shm', '-journal')}
    names = set(value['tree']['files'])
    if (value['tree']['directories'] or not required <= names or not names <= allowed or
            any(value['tree']['files'][name]['bytes'] <= 0 for name in required) or
            any((db + '-wal' in names) != (db + '-shm' in names) for db in (namespace + '.db', 'logs.db')) or
            type(value.get('bytes')) is not int or value['bytes'] != size):
        raise RuntimeError('Arr selected database scope or byte accounting changed')
    return value


def send(namespace, output):
    before = source_identity(namespace)
    root = source_path(namespace)
    warm(root, namespace)
    if source_identity(namespace) != before:
        raise RuntimeError('Arr process identity changed while warming selected files')
    with tempfile.TemporaryDirectory(prefix='homelab-arr-databases-103-', dir='/run') as temporary:
        with stopped(before['processes'], Path(temporary) / 'markers') as pauses:
            if source_identity(namespace) != before:
                raise RuntimeError('Arr task set changed before coordinated pause')
            tree, payloads = snapshot(root, namespace)
            if source_identity(namespace) != before:
                raise RuntimeError('Arr source changed during capture')
        if source_identity(namespace) != before:
            raise RuntimeError('original Arr source did not resume unchanged')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'tree': tree,
                'scope': 'selected-databases-and-config-only', 'bytes': sum(len(x) for x in payloads.values()),
                'pause': {'stopped_seconds': max(p['stopped_seconds'] for p in pauses), 'process_count': len(pauses)},
                'original_process_resumed': True}
    validate_manifest(manifest, namespace)
    encoded = common.canonical(manifest)
    if len(encoded) > 1048576:
        raise RuntimeError('Arr manifest exceeds framing contract')
    output.write(encoded + b'\n')
    for name in sorted(payloads):
        output.write(payloads[name])
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def verify(point, checksum, namespace):
    return transfer.verify(point, checksum, namespace, validator=validate_manifest)


def point_path(namespace, run_id):
    common.require_host('pikachu')
    common.private_root()
    return common.ROOT / (namespace + '-databases-' + common.run_identifier(run_id))


def fingerprints(root, target, namespace):
    target.mkdir(mode=0o700)
    results = {}
    for name in (namespace + '.db', 'logs.db'):
        # Recovery and checkpointing occur only on a disposable copy, never live/protected files.
        source = sqlite3.connect(root / name)
        destination = sqlite3.connect(target / name)
        try:
            source.backup(destination)
            destination.execute('PRAGMA journal_mode=DELETE')
        finally:
            source.close()
            destination.close()
        results[name] = files.fingerprint(target / name)
    return results


def require_container(value, scratch, namespace, run_id):
    config, host = value['Config'], value['HostConfig']
    executable = SOURCES[namespace]['tasks'][str(SOURCES[namespace]['app_pid'])]
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 4294967296, 'NanoCpus': 1000000000, 'GroupAdd': ['1000'],
                'Tmpfs': {'/tmp': 'rw,nosuid,nodev,uid=99,gid=100,mode=1777'}}
    if (config['Image'] != image(namespace) or config['User'] != '99:100' or config['Entrypoint'] != [executable] or
            config['Cmd'] != ['-nobrowser', '-data=/config'] or config.get('Labels', {}).get(LABEL) != run_id or
            any(host.get(k) != v for k, v in expected.items()) or host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            len(value['Mounts']) != 1 or value['Mounts'][0].get('Type') != 'bind' or not value['Mounts'][0]['RW'] or
            value['Mounts'][0]['Source'] != str(scratch / 'native') or value['Mounts'][0]['Destination'] != '/config'):
        raise RuntimeError('native Arr restore isolation changed')


def require_image(description, namespace):
    if (description['Architecture'] != 'amd64' or description['Os'] != 'linux' or
            description['Config'].get('Volumes') != {'/config': {}} or
            image(namespace) not in description.get('RepoDigests', [])):
        raise RuntimeError('exact native Arr image contract changed')


def native_arguments(scratch, namespace, run_id):
    executable = SOURCES[namespace]['tasks'][str(SOURCES[namespace]['app_pid'])]
    return ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=99:100', '--group-add=1000',
            '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--memory=4g', '--cpus=1',
            '--label=' + LABEL + '=' + run_id, '--tmpfs=/tmp:rw,nosuid,nodev,uid=99,gid=100,mode=1777',
            '--mount=type=bind,source=' + str(scratch / 'native') + ',target=/config',
            '--env=HOME=/tmp', '--env=XDG_CONFIG_HOME=/config/xdg', '--env=TZ=America/Chicago',
            '--entrypoint=' + executable, image(namespace), '-nobrowser', '-data=/config']


def restore(namespace, run_id, checksum):
    point = point_path(namespace, run_id)
    manifest = verify(point, checksum, namespace)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned Arr restore is already active')
    if shutil.disk_usage(common.ROOT).free <= manifest['bytes'] * 6:
        raise RuntimeError('actual restore capacity cannot hold selected copies')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=namespace + '-database-restore-', dir=common.ROOT))
    scratch.chmod(0o700)
    container = image_id = None
    result = {'accepted': False, 'namespace': namespace, 'manifest_sha256': checksum, 'scope': manifest['scope']}
    try:
        common.docker('pull', image(namespace))
        description = json.loads(common.docker('image', 'inspect', image(namespace)).stdout)[0]
        image_id = description['Id']
        require_image(description, namespace)
        files.copy_tree(point / 'data', scratch / 'before')
        result['source_snapshot'] = fingerprints(scratch / 'before', scratch / 'before-canonical', namespace)
        files.copy_tree(point / 'data', scratch / 'native')
        os.chown(scratch / 'native', 99, 100)
        for path in (scratch / 'native').iterdir():
            os.chown(path, 99, 100)
        container = common.docker(*native_arguments(scratch, namespace, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('invalid owned native Arr container')
        require_container(common.inspect(container), scratch, namespace, run_id)
        common.docker('start', container)
        port = '7878' if namespace == 'radarr' else '8989'
        deadline = time.monotonic() + 180
        while True:
            if not common.inspect(container)['State']['Running']:
                raise RuntimeError('native Arr stopped before readiness')
            response = common.docker('exec', container, 'curl', '--silent', '--show-error', '--fail', '--max-time', '3',
                                     'http://127.0.0.1:' + port + '/ping', check=False)
            if response.returncode == 0:
                if json.loads(response.stdout).get('status') != 'OK':
                    raise RuntimeError('unexpected native Arr ping response')
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('native Arr readiness failed')
            time.sleep(0.25)
        devices = common.docker('exec', container, 'cat', '/proc/net/dev').stdout.decode()
        if {line.split(':')[0].strip() for line in devices.splitlines() if ':' in line} != {'lo'}:
            raise RuntimeError('native Arr has a non-loopback interface')
        require_container(common.inspect(container), scratch, namespace, run_id)
        common.docker('stop', '--time=40', container)
        state = common.inspect(container)['State']
        if state['Running'] or state['ExitCode'] != 0 or state.get('OOMKilled'):
            raise RuntimeError('native Arr did not stop cleanly')
        files.copy_tree(scratch / 'native', scratch / 'after')
        result['stopped_native_snapshot'] = fingerprints(scratch / 'after', scratch / 'after-canonical', namespace)
        if any(result['source_snapshot'][db]['schema_sha256'] != result['stopped_native_snapshot'][db]['schema_sha256'] or
               result['source_snapshot'][db]['metadata_sha256'] != result['stopped_native_snapshot'][db]['metadata_sha256']
               for db in result['source_snapshot']):
            raise RuntimeError('exact native Arr startup changed database schema/metadata')
        result.update(accepted=True, native_ping_status=200, clean_exit=0, network='none', only_loopback=True)
    finally:
        if container:
            require_container(common.inspect(container), scratch, namespace, run_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned Arr container remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError('owned Arr scratch remains')
        if image_id and image_id not in images:
            if not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
                common.docker('image', 'rm', image(namespace))
                if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                    raise RuntimeError('new unused native Arr image remains')
        verify(point, checksum, namespace)
        result['cleanup'] = {'scratch_absent': True, 'container_absent': True, 'protected_unchanged': True,
                             'allocated_bytes_removed': allocated}
        files.write_json(point / 'native-restore.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['send', 'receive', 'verify', 'restore'])
    parser.add_argument('--namespace', choices=sorted(SOURCES), required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args()
    common.run_identifier(args.run_id)
    if args.mode == 'send':
        send(args.namespace, sys.stdout.buffer)
        return
    point = point_path(args.namespace, args.run_id)
    if args.mode == 'receive':
        result = transfer.receive(sys.stdin.buffer, point, args.namespace, validator=validate_manifest, verifier=verify)
    else:
        if not args.manifest_sha256 or not re.fullmatch('[a-f0-9]{64}', args.manifest_sha256):
            parser.error('protected manifest SHA256 is required')
        result = (restore(args.namespace, args.run_id, args.manifest_sha256) if args.mode == 'restore' else
                  {'verified': bool(verify(point, args.manifest_sha256, args.namespace))})
    print(json.dumps(result), flush=True)


def interrupted(_number, _frame):
    raise RuntimeError('Arr recovery interrupted')


if __name__ == '__main__':
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    main()
