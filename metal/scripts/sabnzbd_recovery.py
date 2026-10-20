#!/usr/bin/env python3
"""Protect both reviewed SABnzbd Ceph stores without accessing NAS or providers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import sys
import tempfile
import time

import arr_database_recovery as coordinated
import builder_recovery as stores
import etcd_recovery as common
import grafana_recovery as files
import prometheus_recovery as process
import sporecast_recovery as transfer

IMAGE = 'docker.io/linuxserver/sabnzbd@sha256:7a13af91cf296399e302d2fb6fc709d6e2ea15e3094f220684611fbe1dd43625'
LABEL = 'io.eaglepass.sabnzbd-recovery-103'
POD = 'cdc9877a-93d8-4eab-b566-39379f93427b'
PROFILE = {
    'node': 'pikachu', 'pod_uid': POD, 'app_pid': 12466,
    'script_sha256': 'f20b0a7fa96b66856afb851bc63e361f01b9ddea2c19891e5cc1c3a4b644bd4e',
    'containers': {
        'main': {'id': 'be79415daaa0f415a4c4106a181abc0a4403d50d6b865f86f229c5fbb1515ecb', 'pid': 12302,
                 'digest': IMAGE.split('@')[1],
                 'tasks': {12302: coordinated.S6 + 's6-svscan', 12325: coordinated.S6 + 's6-supervise',
                           12327: coordinated.SHUTDOWN, 12344: coordinated.S6 + 's6-supervise',
                           12345: coordinated.S6 + 's6-supervise', 12346: coordinated.S6 + 's6-supervise',
                           12347: coordinated.S6 + 's6-supervise', 12355: coordinated.S6 + 's6-ipcserverd',
                           12466: '/usr/bin/python3.14', 12467: '/usr/bin/busybox'}},
        'fix-host': {'id': '72512e1530d626938fa7488b15dfee5fefb00d4004545ef30894facfc236a4f5', 'pid': 12268,
                     'digest': 'sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6',
                     'tasks': {12268: '/usr/bin/busybox', 12288: '/usr/bin/busybox'}},
    },
    'stores': {
        'config': {'pvc_uid': '0de2e927-1652-432b-97e7-fd3b7e48c9af', 'pv_uid': 'b79a4981-80c6-4de5-aada-34ee89b69afe', 'device': 64320, 'inode': 2},
        'intermediate': {'pvc_uid': '1e21206c-8f35-4d01-8487-29c50d1d5926', 'pv_uid': '715b618a-94a6-4092-aa05-e40210a4319b', 'device': 64304, 'inode': 2},
    },
}
for container_profile in PROFILE['containers'].values():
    container_profile['tasks'] = {str(pid): exe for pid, exe in container_profile['tasks'].items()}
HISTORY = 'config/admin/history1.db'
TMPFS = {'/tmp': 'rw,nosuid,nodev,uid=99,gid=100,mode=1777',
         '/downloads': 'rw,nosuid,nodev,uid=99,gid=100,mode=0700',
         '/backups': 'rw,nosuid,nodev,uid=99,gid=100,mode=0700',
         '/apps': 'ro,nosuid,nodev,uid=99,gid=100,mode=0555'}
ARGS = ['-B', '/app/sabnzbd/SABnzbd.py', '--config-file', '/config', '--server', '127.0.0.1:8080', '--browser', '0']


def source_paths():
    root = Path('/var/lib/kubelet/pods') / POD / 'volumes/kubernetes.io~csi'
    return {name: root / ('pvc-' + p['pvc_uid']) / 'mount' for name, p in PROFILE['stores'].items()}


def source_identity():
    common.require_host('pikachu')
    identities = []
    for name, expected in PROFILE['containers'].items():
        runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', expected['id']]).stdout)
        status = runtime['status']
        if (status['state'] != 'CONTAINER_RUNNING' or runtime['info']['pid'] != expected['pid'] or
                status['imageRef'].split('@')[-1] != expected['digest'] or
                status['labels'].get('io.kubernetes.pod.uid') != POD or
                status['labels'].get('io.kubernetes.pod.namespace') != 'sabnzbd' or
                status['labels'].get('io.kubernetes.container.name') != name):
            raise RuntimeError('reviewed SABnzbd container changed')
        tasks = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', expected['id']]).stdout.decode().splitlines()[1:]
        pids = {line.split()[0] for line in tasks if line.strip()}
        if pids != set(expected['tasks']):
            raise RuntimeError('reviewed SABnzbd task set changed')
        for pid in sorted(map(int, pids)):
            identity = process.process_identity(pid)
            if (identity['exe'] != expected['tasks'][str(pid)] or POD.replace('-', '_') not in identity['cgroup'] or
                    (Path('/proc') / str(pid)).stat().st_uid != (99 if pid == PROFILE['app_pid'] else 0)):
                raise RuntimeError('reviewed SABnzbd process changed')
            identities.append(identity)
        for store, path in source_paths().items():
            destination = '/config' if store == 'config' else '/incomplete-downloads'
            if name == 'fix-host' and store != 'config':
                continue
            mounts = [m for m in runtime['info']['runtimeSpec']['mounts'] if m['destination'] == destination]
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise RuntimeError('unsafe SABnzbd CSI ancestry')
            a = path.stat()
            b = (Path('/proc') / str(PROFILE['app_pid']) / 'root' / destination.lstrip('/')).stat()
            profile = PROFILE['stores'][store]
            if (len(mounts) != 1 or mounts[0]['source'] != str(path) or
                    (a.st_dev, a.st_ino) != (profile['device'], profile['inode']) or
                    (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
                raise RuntimeError('reviewed SABnzbd CSI store changed')
    script = Path('/proc') / str(PROFILE['app_pid']) / 'root/app/sabnzbd/SABnzbd.py'
    if hashlib.sha256(script.read_bytes()).hexdigest() != PROFILE['script_sha256']:
        raise RuntimeError('native SABnzbd script changed')
    return {'namespace': 'sabnzbd', 'profile': PROFILE, 'image': IMAGE, 'processes': sorted(identities, key=lambda p: p['pid'])}


def validate_manifest(value, namespace):
    if (namespace != 'sabnzbd' or not isinstance(value, dict) or value.get('format') != 1 or
            value.get('cluster_uid') != common.CLUSTER_UID or not isinstance(value.get('source'), dict) or
            value['source'].get('namespace') != namespace or value['source'].get('profile') != PROFILE or
            value['source'].get('image') != IMAGE or value.get('two_stores_same_pause') is not True or
            value.get('original_processes_resumed') is not True or value.get('scope') != 'both-ceph-stores-only'):
        raise RuntimeError('SABnzbd protected source contract changed')
    expected = {pid: exe for c in PROFILE['containers'].values() for pid, exe in c['tasks'].items()}
    identities = value['source'].get('processes')
    pause = value.get('pause')
    if (not isinstance(identities, list) or len(identities) != 12 or any(not isinstance(p, dict) for p in identities) or
            {str(p.get('pid')): p.get('exe') for p in identities} != expected or
            any(not str(p.get('start_ticks', '')).isdigit() or POD.replace('-', '_') not in p.get('cgroup', '') for p in identities) or
            not isinstance(pause, dict) or pause.get('process_count') != 12 or
            type(pause.get('stopped_seconds')) not in (int, float) or not 0 < pause['stopped_seconds'] < 10):
        raise RuntimeError('complete SABnzbd coordinated pause evidence missing')
    size = transfer.validate_tree(value.get('tree'))
    tree = value['tree']
    if (type(value.get('bytes')) is not int or size != value['bytes'] or
            not set(PROFILE['stores']) <= set(tree['directories']) or
            not {'config/sabnzbd.ini', HISTORY} <= set(tree['files']) or
            any(Path(n).parts[0] not in PROFILE['stores'] for n in [*tree['directories'], *tree['files']]) or
            any(n.endswith('.db') and n != HISTORY for n in tree['files'])):
        raise RuntimeError('both complete reviewed SABnzbd stores are required')
    return value


def verify(point, checksum, namespace):
    return transfer.verify(point, checksum, namespace, validator=validate_manifest)


def point_path(run_id):
    common.require_host('pikachu')
    common.private_root()
    return common.ROOT / ('sabnzbd-' + common.run_identifier(run_id))


def send(output):
    before = source_identity()
    paths = source_paths()
    for root in paths.values():
        stores.store_tree(root)
    if source_identity() != before:
        raise RuntimeError('SABnzbd changed while warming stores')
    with tempfile.TemporaryDirectory(prefix='sabnzbd-pause-103-', dir='/run') as temporary:
        with coordinated.stopped(before['processes'], Path(temporary) / 'markers') as pauses:
            if source_identity() != before:
                raise RuntimeError('SABnzbd changed before capture')
            tree, payloads = stores.snapshot(paths)
            if source_identity() != before:
                raise RuntimeError('SABnzbd changed during capture')
        if source_identity() != before:
            raise RuntimeError('SABnzbd originals did not resume unchanged')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'tree': tree,
                'scope': 'both-ceph-stores-only', 'bytes': sum(len(p) for p in payloads.values()),
                'two_stores_same_pause': True, 'original_processes_resumed': True,
                'pause': {'process_count': len(pauses), 'stopped_seconds': max(p['stopped_seconds'] for p in pauses)}}
    validate_manifest(manifest, 'sabnzbd')
    encoded = common.canonical(manifest)
    if len(encoded) > 1048576:
        raise RuntimeError('SABnzbd manifest exceeds framing contract')
    output.write(encoded + b'\n')
    for name in sorted(payloads):
        output.write(payloads[name])
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def history(root, target):
    source = sqlite3.connect(root / HISTORY)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.execute('PRAGMA journal_mode=DELETE')
    finally:
        source.close()
        destination.close()
    return files.fingerprint(target)


def native_arguments(scratch, run_id):
    args = ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=99:100', '--group-add=1000',
            '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--memory=2g', '--cpus=1',
            '--label=' + LABEL + '=' + run_id, '--env=HOME=/tmp', '--env=TZ=America/Chicago']
    args += ['--tmpfs=' + path + ':' + options for path, options in TMPFS.items()]
    args += ['--mount=type=bind,source=' + str(scratch / 'native' / name) + ',target=' + target
             for name, target in (('config', '/config'), ('intermediate', '/incomplete-downloads'))]
    return args + ['--entrypoint=/lsiopy/bin/python3', IMAGE, *ARGS]


def require_container(value, scratch, run_id):
    c, h = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 1000000000, 'GroupAdd': ['1000'], 'Tmpfs': TMPFS}
    mounts = {m.get('Destination'): (m.get('Type'), m.get('Source'), m.get('RW')) for m in value['Mounts']}
    wanted = {target: ('bind', str(scratch / 'native' / name), True)
              for name, target in (('config', '/config'), ('intermediate', '/incomplete-downloads'))}
    if (c['Image'] != IMAGE or c['User'] != '99:100' or c['Entrypoint'] != ['/lsiopy/bin/python3'] or c['Cmd'] != ARGS or
            c.get('Labels', {}).get(LABEL) != run_id or any(h.get(k) != v for k, v in expected.items()) or
            any(h.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            h.get('RestartPolicy', {}).get('Name') != 'no' or len(value['Mounts']) != 2 or mounts != wanted):
        raise RuntimeError('native SABnzbd restore isolation changed')


def restore(run_id, checksum):
    point = point_path(run_id)
    manifest = verify(point, checksum, 'sabnzbd')
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned SABnzbd restore already active')
    if shutil.disk_usage(common.ROOT).free <= manifest['bytes'] * 6:
        raise RuntimeError('actual recovery capacity cannot hold copies')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='sabnzbd-native-restore-', dir=common.ROOT))
    scratch.chmod(0o700)
    container = image_id = None
    result = {'accepted': False, 'scope': manifest['scope'], 'manifest_sha256': checksum}
    try:
        common.docker('pull', IMAGE)
        description = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = description['Id']
        if (description['Architecture'] != 'amd64' or description['Os'] != 'linux' or
                description['Config'].get('Volumes') != {'/config': {}} or
                not {IMAGE, IMAGE.removeprefix('docker.io/')}.intersection(description['RepoDigests'])):
            raise RuntimeError('exact native SABnzbd image contract changed')
        files.copy_tree(point / 'data', scratch / 'before')
        result['history_before'] = history(scratch / 'before', scratch / 'before.sqlite')
        files.copy_tree(point / 'data', scratch / 'native')
        for parent, directories, names in os.walk(scratch / 'native'):
            os.chown(parent, 99, 100)
            for name in [*directories, *names]:
                os.chown(Path(parent) / name, 99, 100)
        container = common.docker(*native_arguments(scratch, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('invalid owned SABnzbd container identity')
        require_container(common.inspect(container), scratch, run_id)
        common.docker('start', container)
        deadline = time.monotonic() + 180
        while True:
            if not common.inspect(container)['State']['Running']:
                raise RuntimeError('native SABnzbd stopped before version response')
            response = common.docker('exec', container, 'curl', '--silent', '--show-error', '--fail', '--max-time', '3',
                                     'http://127.0.0.1:8080/api?mode=version&output=json', check=False)
            if response.returncode == 0:
                if json.loads(response.stdout) != {'version': '5.1.3'}:
                    raise RuntimeError('unexpected native SABnzbd version response')
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('native SABnzbd version endpoint timed out')
            time.sleep(0.25)
        devices = common.docker('exec', container, 'cat', '/proc/net/dev').stdout.decode()
        if {l.split(':')[0].strip() for l in devices.splitlines() if ':' in l} != {'lo'}:
            raise RuntimeError('native SABnzbd has a non-loopback interface')
        require_container(common.inspect(container), scratch, run_id)
        common.docker('stop', '--time=40', container)
        state = common.inspect(container)['State']
        if state['Running'] or state['ExitCode'] != 0 or state.get('OOMKilled'):
            raise RuntimeError('native SABnzbd did not stop cleanly')
        files.copy_tree(scratch / 'native', scratch / 'after')
        result['history_after'] = history(scratch / 'after', scratch / 'after.sqlite')
        if any(result['history_before'][k] != result['history_after'][k] for k in ('schema_sha256', 'metadata_sha256')):
            raise RuntimeError('native SABnzbd changed history schema or metadata')
        result.update(accepted=True, version='5.1.3', native_version_status=200, clean_exit=0, network='none', only_loopback=True)
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned SABnzbd container remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError('owned SABnzbd scratch remains')
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused SABnzbd image remains')
        verify(point, checksum, 'sabnzbd')
        result['cleanup'] = {'container_absent': True, 'scratch_absent': True, 'protected_unchanged': True,
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
        result = transfer.receive(sys.stdin.buffer, point, 'sabnzbd', validator=validate_manifest, verifier=verify)
    else:
        if not args.manifest_sha256 or not re.fullmatch('[a-f0-9]{64}', args.manifest_sha256):
            parser.error('protected manifest SHA256 is required')
        result = restore(args.run_id, args.manifest_sha256) if args.mode == 'restore' else {'verified': bool(verify(point, args.manifest_sha256, 'sabnzbd'))}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, coordinated.interrupted)
    main()
