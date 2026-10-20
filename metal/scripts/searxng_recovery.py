#!/usr/bin/env python3
"""Protect the reviewed empty SearxNG CSI stores and effective Git-owned overlays."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
import time

import arr_database_recovery as coordinated
import builder_recovery as stores
import etcd_recovery as common
import grafana_recovery as files
import prometheus_recovery as process
import sporecast_recovery as transfer

IMAGE = 'docker.io/searxng/searxng@sha256:b4e34a39f76b1c860bbc53a0f35b10492029b2b18ef1d868df464fe43d7e0b93'
POD = 'e387c878-9c07-4ee2-a450-1cc2a0caac15'
CONTAINER = 'a6a515725b4130d02f369bb479727ce11b7f03a8ef80a940fb84c07bf5c5e91d'
TASKS = {str(pid): '/usr/bin/python3.14' for pid in (7420, 8316, 8317)}
PROFILE = {
    'etc': {'pvc_uid': '0cf8a4be-983c-4fc0-97b4-ef92dea29276', 'pv_uid': '55778a89-0f40-42b1-87cf-2fd82a17a51c', 'device': 64288, 'inode': 2},
    'cache': {'pvc_uid': '5536c27e-9a6f-4564-bd4e-4628899803e5', 'pv_uid': 'a8da26de-2e49-4078-aa90-6a548d08946c', 'device': 64256, 'inode': 2},
}
OVERLAYS = {
    'settings.yml': {'bytes': 9199, 'sha256': 'd7b4ec531078dad40a721c240ad5f7efedfc48bb7ab0649fe18f0c747529acbf'},
    'limiter.toml': {'bytes': 452, 'sha256': 'e6266df52c2d049a42c6c958fa7b2eb0d951e3623c7a58eba3154a088678e404'},
}
DESTINATIONS = {'etc': '/etc/searxng', 'cache': '/var/cache/searxng'}
LABEL = 'io.eaglepass.searxng-recovery-103'
ENTRYPOINT = '/usr/local/searxng/.venv/bin/granian'
TMPFS = {'/tmp': 'rw,nosuid,nodev,mode=1777', '/run': 'rw,nosuid,nodev,mode=0700'}
ENVIRONMENT = {'HOME': '/tmp', 'PYTHONDONTWRITEBYTECODE': '1', 'GRANIAN_HOST': '127.0.0.1', 'GRANIAN_PORT': '8080',
               'GRANIAN_INTERFACE': 'wsgi', 'GRANIAN_WORKERS': '1',
               **{k: 'synthetic-recovery-only-' + 'x' * 64 for k in ('SERVER_SECRET_KEY', 'SECRET_KEY', 'SEARXNG_SECRET')}}


def source_paths():
    root = Path('/var/lib/kubelet/pods') / POD / 'volumes/kubernetes.io~csi'
    return {n: root / ('pvc-' + p['pvc_uid']) / 'mount' for n, p in PROFILE.items()}


def source_identity():
    common.require_host('growlithe')
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', CONTAINER]).stdout)
    status = runtime['status']
    if (status['state'] != 'CONTAINER_RUNNING' or runtime['info']['pid'] != 7420 or
            status['imageRef'].split('@')[-1] != IMAGE.split('@')[1] or
            status['labels'].get('io.kubernetes.pod.uid') != POD or
            status['labels'].get('io.kubernetes.pod.namespace') != 'searxng' or
            status['labels'].get('io.kubernetes.container.name') != 'main'):
        raise RuntimeError('reviewed SearxNG runtime changed')
    raw = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', CONTAINER]).stdout.decode()
    tasks = {line.split()[0] for line in raw.splitlines()[1:] if line.strip()}
    if tasks != set(TASKS):
        raise RuntimeError('reviewed SearxNG tasks changed')
    identities = [process.process_identity(pid) for pid in sorted(map(int, tasks))]
    if any(i['exe'] != TASKS[str(i['pid'])] or POD.replace('-', '_') not in i['cgroup'] or
           (Path('/proc') / str(i['pid'])).stat().st_uid != 0 for i in identities):
        raise RuntimeError('reviewed SearxNG process changed')
    for name, path in source_paths().items():
        matches = [m for m in runtime['info']['runtimeSpec']['mounts'] if m['destination'] == DESTINATIONS[name]]
        a = path.stat()
        b = (Path('/proc/7420/root') / DESTINATIONS[name].lstrip('/')).stat()
        if (len(matches) != 1 or matches[0]['source'] != str(path) or any(p.is_symlink() for p in (path, *path.parents)) or
                (a.st_dev, a.st_ino) != (PROFILE[name]['device'], PROFILE[name]['inode']) or
                (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
            raise RuntimeError('reviewed SearxNG CSI mount changed')
    for name, expected in OVERLAYS.items():
        data = (Path('/proc/7420/root/etc/searxng') / name).read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise RuntimeError('effective Git-owned SearxNG overlay changed')
    return {'pod_uid': POD, 'container_id': CONTAINER, 'image': IMAGE, 'stores': PROFILE, 'processes': identities}


def validate_manifest(value, namespace):
    source = value.get('source', {}) if isinstance(value, dict) else {}
    pause = value.get('pause', {}) if isinstance(value, dict) else {}
    identities = source.get('processes', []) if isinstance(source, dict) else []
    if (not isinstance(value, dict) or not isinstance(source, dict) or not isinstance(pause, dict) or
            namespace != 'searxng' or value.get('format') != 1 or value.get('cluster_uid') != common.CLUSTER_UID or
            source.get('pod_uid') != POD or source.get('container_id') != CONTAINER or source.get('image') != IMAGE or
            source.get('stores') != PROFILE or value.get('scope') != 'empty-ceph-stores-and-git-overlays' or
            value.get('original_processes_resumed') is not True or pause.get('process_count') != 3 or
            type(pause.get('stopped_seconds')) not in (int, float) or not 0 < pause['stopped_seconds'] < 10 or
            not isinstance(identities, list) or len(identities) != 3 or any(not isinstance(i, dict) for i in identities) or
            {str(i.get('pid')): i.get('exe') for i in identities} != TASKS or
            any(not str(i.get('start_ticks', '')).isdigit() or POD.replace('-', '_') not in i.get('cgroup', '') for i in identities)):
        raise RuntimeError('SearxNG protected source/pause contract changed')
    size = transfer.validate_tree(value.get('tree'))
    tree = value['tree']
    if (not {'etc', 'cache', 'overlays'} <= set(tree['directories']) or
            any(Path(n).parts[0] not in ('etc', 'cache', 'overlays') for n in [*tree['files'], *tree['directories']]) or
            {n: v for n, v in tree['files'].items() if n.startswith('overlays/')} != {'overlays/' + n: v for n, v in OVERLAYS.items()} or
            any(v['bytes'] != 0 for n, v in tree['files'].items() if not n.startswith('overlays/')) or
            type(value.get('bytes')) is not int or value['bytes'] != size):
        raise RuntimeError('SearxNG empty CSI/complete effective overlay contract changed')
    return value


def verify(point, checksum, namespace):
    return transfer.verify(point, checksum, namespace, validator=validate_manifest)


def send(output):
    before = source_identity()
    paths = source_paths()
    for root in paths.values():
        if any(v['bytes'] for v in stores.store_tree(root)['files'].values()):
            raise RuntimeError('nonempty SearxNG CSI data requires a new review')
    with tempfile.TemporaryDirectory(prefix='searxng-pause-103-', dir='/run') as temporary:
        with coordinated.stopped(before['processes'], Path(temporary) / 'markers') as pauses:
            if source_identity() != before:
                raise RuntimeError('SearxNG changed before capture')
            tree, payloads = stores.snapshot(paths)
            tree['directories'].append('overlays')
            for name, expected in OVERLAYS.items():
                data = (Path('/proc/7420/root/etc/searxng') / name).read_bytes()
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise RuntimeError('SearxNG overlay changed during capture')
                tree['files']['overlays/' + name] = expected
                payloads['overlays/' + name] = data
            tree['directories'].sort()
            if source_identity() != before:
                raise RuntimeError('SearxNG changed during capture')
        if source_identity() != before:
            raise RuntimeError('original SearxNG processes changed after resumption')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'tree': tree,
                'scope': 'empty-ceph-stores-and-git-overlays', 'bytes': sum(map(len, payloads.values())),
                'original_processes_resumed': True,
                'pause': {'process_count': len(pauses), 'stopped_seconds': max(p['stopped_seconds'] for p in pauses)}}
    validate_manifest(manifest, 'searxng')
    encoded = common.canonical(manifest)
    if len(encoded) > 1048576:
        raise RuntimeError('SearxNG manifest exceeds framing contract')
    output.write(encoded + b'\n')
    for name in sorted(payloads):
        output.write(payloads[name])
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def native_arguments(scratch, run_id):
    args = ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=0:0',
            '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--memory=2g', '--cpus=1',
            '--label=' + LABEL + '=' + run_id]
    args += ['--env=' + k + '=' + v for k, v in ENVIRONMENT.items()]
    args += ['--tmpfs=' + k + ':' + v for k, v in TMPFS.items()]
    args += ['--mount=type=bind,source=' + str(scratch / 'native' / n) + ',target=' + destination for n, destination in DESTINATIONS.items()]
    return args + ['--entrypoint=' + ENTRYPOINT, IMAGE, 'searx.webapp:app']


def require_container(value, scratch, run_id):
    c, h = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 1000000000, 'Tmpfs': TMPFS}
    mounts = {m.get('Destination'): (m.get('Type'), m.get('Source'), m.get('RW')) for m in value['Mounts']}
    wanted = {d: ('bind', str(scratch / 'native' / n), True) for n, d in DESTINATIONS.items()}
    environment = dict(v.split('=', 1) for v in c['Env'] if '=' in v)
    if (c['Image'] != IMAGE or c['User'] != '0:0' or c['Entrypoint'] != [ENTRYPOINT] or c['Cmd'] != ['searx.webapp:app'] or
            c.get('Labels', {}).get(LABEL) != run_id or any(h.get(k) != v for k, v in expected.items()) or
            any(environment.get(k) != v for k, v in ENVIRONMENT.items()) or
            any(h.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            h.get('RestartPolicy', {}).get('Name') != 'no' or len(value['Mounts']) != 2 or mounts != wanted):
        raise RuntimeError('native SearxNG copy isolation changed')


def point_path(run_id):
    common.require_host('pikachu')
    common.private_root()
    return common.ROOT / ('searxng-' + common.run_identifier(run_id))


def restore(run_id, checksum):
    point = point_path(run_id)
    manifest = verify(point, checksum, 'searxng')
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned SearxNG fixture already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='searxng-native-restore-', dir=common.ROOT))
    scratch.chmod(0o700)
    container = image_id = None
    result = {'accepted': False, 'scope': manifest['scope'], 'manifest_sha256': checksum}
    try:
        common.docker('pull', IMAGE)
        description = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = description['Id']
        if (description['Architecture'] != 'amd64' or description['Os'] != 'linux' or
                description['Config'].get('Volumes') != {v: {} for v in DESTINATIONS.values()} or
                not {IMAGE, IMAGE.removeprefix('docker.io/')}.intersection(description['RepoDigests'])):
            raise RuntimeError('exact SearxNG image contract changed')
        files.copy_tree(point / 'data', scratch / 'native')
        if files.tree(scratch / 'native') != manifest['tree']:
            raise RuntimeError('full copied SearxNG tree differs before native startup')
        for name in OVERLAYS:
            shutil.copyfile(scratch / 'native/overlays' / name, scratch / 'native/etc' / name)
        native_before = files.tree(scratch / 'native')
        container = common.docker(*native_arguments(scratch, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('invalid owned SearxNG container')
        require_container(common.inspect(container), scratch, run_id)
        common.docker('start', container)
        probe = "import urllib.request,hashlib,json; r=urllib.request.urlopen('http://127.0.0.1:8080/',timeout=3); b=r.read(); assert r.status==200 and b'searxng' in b.lower(); print(json.dumps({'status':r.status,'body_sha256':hashlib.sha256(b).hexdigest()}))"
        deadline = time.monotonic() + 180
        while True:
            if not common.inspect(container)['State']['Running']:
                raise RuntimeError('native SearxNG stopped before root response')
            response = common.docker('exec', container, '/usr/local/searxng/.venv/bin/python', '-B', '-c', probe, check=False)
            if response.returncode == 0:
                result['root'] = json.loads(response.stdout)
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('native SearxNG root response timed out')
            time.sleep(0.25)
        devices = common.docker('exec', container, 'cat', '/proc/net/dev').stdout.decode()
        if {l.split(':')[0].strip() for l in devices.splitlines() if ':' in l} != {'lo'}:
            raise RuntimeError('native SearxNG has a non-loopback interface')
        require_container(common.inspect(container), scratch, run_id)
        common.docker('stop', '--time=40', container)
        state = common.inspect(container)['State']
        if state['Running'] or state['ExitCode'] != 0 or state.get('OOMKilled'):
            raise RuntimeError('native SearxNG did not stop cleanly')
        native_after = files.tree(scratch / 'native')
        first, last = native_before['files'], native_after['files']
        result.update(accepted=True, clean_exit=0, network='none', only_loopback=True,
                      native_tree_sha256=hashlib.sha256(common.canonical(native_after)).hexdigest(),
                      native_changes={'added_files': len(last.keys() - first.keys()),
                                      'removed_files': len(first.keys() - last.keys()),
                                      'changed_files': sum(first[n] != last[n] for n in first.keys() & last.keys()),
                                      'directories_changed': native_before['directories'] != native_after['directories']})
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned SearxNG container remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError('owned SearxNG scratch remains')
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused SearxNG image remains')
        verify(point, checksum, 'searxng')
        result['cleanup'] = {'scratch_absent': True, 'container_absent': True, 'protected_unchanged': True,
                             'allocated_bytes_removed': allocated}
        files.write_json(point / 'native-restore.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['send', 'receive', 'verify', 'restore'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args()
    common.run_identifier(args.run_id)
    if args.mode == 'send':
        send(sys.stdout.buffer)
        return
    point = point_path(args.run_id)
    if args.mode == 'receive':
        result = transfer.receive(sys.stdin.buffer, point, 'searxng', validator=validate_manifest, verifier=verify)
    else:
        if not args.manifest_sha256 or not re.fullmatch('[a-f0-9]{64}', args.manifest_sha256):
            parser.error('protected manifest SHA256 is required')
        result = restore(args.run_id, args.manifest_sha256) if args.mode == 'restore' else {'verified': bool(verify(point, args.manifest_sha256, 'searxng'))}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, coordinated.interrupted)
    main()
