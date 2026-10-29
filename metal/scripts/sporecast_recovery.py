#!/usr/bin/env python3
"""Freeze exact Sporecast writers into memory; restore copied WAL state offline."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
import urllib.parse

import etcd_recovery as common
import prometheus_recovery as process
import grafana_recovery as files

IMAGE = 'registry.eaglepass.io/sporecast-backend@sha256:1eb8f84e6188481d0db009088b4b5d1a6ac3158dbc41a6f6db187bf787857063'
CACHED_IMAGE = '10.0.20.11:32309/sporecast-backend@' + IMAGE.split('@')[1]
CACHED_CONFIG = 'sha256:1f42d28483fbcc74dc5732327b8141f12486059cdb26ad9c5af9cc73eb9657dd'
LABEL = 'io.eaglepass.sporecast-recovery-103'
SOURCES = {
    'sporecast': {'pod_uid': 'a414ace7-de7d-4415-b87b-c3a1ab0916a9', 'pid': 8939,
                 'container_id': '2102a00253a0fffb68831cf4d4a8e12266aeb1999f22d69c1916e877d44d0634',
                 'pvc_uid': '683ae6bf-813c-49e5-aba5-ebadea1b18c5', 'pv_uid': '0c6012e9-40f1-4888-b949-f7a03f353aa0',
                 'device': 64288, 'inode': 2},
    'sporecast-canary': {'pod_uid': '249994fd-500c-4f54-a279-572a996a7dfa', 'pid': 8926,
                        'container_id': 'bd3066fb627b34865244b8c2556c32601e7d3d2a0a67809a8af4f41756a6383d',
                        'pvc_uid': '05d72126-6a3f-465e-b117-adb26e47830a', 'pv_uid': 'a4fdbcb0-7cbb-4148-bb44-52b3ada37ea5',
                        'device': 64336, 'inode': 2},
}
HISTORICAL_SOURCES = SOURCES
PIKACHU_20261027 = {
    'sporecast': {'pod_uid': '4b540b38-14ca-459c-8961-f58534cb4c78', 'pid': 14078,
                 'container_id': 'dc321fd9c7df9c7e916683e31b51de734300fbe3029b61466fd525f09ba8cf38',
                 'pvc_uid': '683ae6bf-813c-49e5-aba5-ebadea1b18c5', 'pv_uid': '0c6012e9-40f1-4888-b949-f7a03f353aa0',
                 'device': 64048, 'inode': 2, 'start_ticks': '353518',
                 'node': 'pikachu', 'machine': '0a7daf8b33244d9d85f46223c3582da9',
                 'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997',
                 'boot': '41d9cfe5-eb7a-4008-a0da-174712f52cec'},
}
GROWLITHE_CANARY_20261029 = {
    'sporecast-canary': {'pod_uid': 'f8832123-f4ba-4440-9f57-3e4caecdb9ea', 'pid': 7513,
                        'container_id': '0a4f77af9010626d305c2f47c5319f5f7f31d9b4ac1e41053f34c11cd6039339',
                        'pvc_uid': '05d72126-6a3f-465e-b117-adb26e47830a', 'pv_uid': 'a4fdbcb0-7cbb-4148-bb44-52b3ada37ea5',
                        'device': 64000, 'inode': 2, 'start_ticks': '76769',
                        'node': 'growlithe', 'machine': 'a26cbcc990c044dea41fbf4f957f453d',
                        'root_uuid': '710e2dca-691e-4123-a867-4994b9c6e612',
                        'boot': '9abbec7b-5f12-4d96-b833-9d76890eb23b'},
}
PROFILES = {'historical': HISTORICAL_SOURCES, 'pikachu-20261027': PIKACHU_20261027,
            'growlithe-canary-20261029': GROWLITHE_CANARY_20261029}
ENVIRONMENT = {'DATA_DIR': '/data', 'BACKUP_DIR': '/data/backups', 'BACKUP_INTERVAL_HOURS': '24',
               'LISTEN_ADDR': '127.0.0.1:8080', 'LOG_LEVEL': 'error'}


def select_profile(profile):
    global SOURCES
    if profile not in PROFILES:
        raise RuntimeError('unreviewed Sporecast recovery profile')
    SOURCES = PROFILES[profile]


def source_path(namespace):
    value = SOURCES[namespace]
    return Path('/var/lib/kubelet/pods') / value['pod_uid'] / 'volumes/kubernetes.io~csi' / ('pvc-' + value['pvc_uid']) / 'mount'


def source_identity(namespace):
    expected = SOURCES[namespace]; cid = expected['container_id']
    common.require_host(expected.get('node', 'bulbasaur'))
    if expected.get('machine') and (
            Path('/etc/machine-id').read_text().strip() != expected['machine'] or
            common.command(['findmnt', '-n', '-o', 'UUID', '/']).stdout.decode().strip() != expected['root_uuid'] or
            Path('/proc/sys/kernel/random/boot_id').read_text().strip() != expected['boot']):
        raise RuntimeError('reviewed Sporecast host identity changed')
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', cid]).stdout)
    status = runtime['status']; labels = status['labels']; pid = expected['pid']
    if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'].split('@')[-1] != IMAGE.split('@')[-1] or
            labels.get('io.kubernetes.pod.uid') != expected['pod_uid'] or labels.get('io.kubernetes.pod.namespace') != namespace or
            labels.get('io.kubernetes.container.name') != 'backend' or runtime['info']['pid'] != pid or
            runtime['info']['runtimeSpec']['process']['user'] != {'uid': 65532, 'gid': 65532, 'additionalGids': [65532]}):
        raise RuntimeError('reviewed Sporecast runtime changed')
    identity = process.process_identity(pid)
    if identity['exe'] != '/sporecast-backend' or expected['pod_uid'].replace('-', '_') not in identity['cgroup']:
        raise RuntimeError('reviewed Sporecast process changed')
    if expected.get('start_ticks') and identity['start_ticks'] != expected['start_ticks']:
        raise RuntimeError('reviewed Sporecast PID was reused')
    tasks = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode().splitlines()[1:]
    if [int(line.split()[0]) for line in tasks if line.strip()] != [pid]: raise RuntimeError('unreviewed additional writer process')
    path = source_path(namespace)
    if any(p.is_symlink() for p in (path, *path.parents)): raise RuntimeError('source CSI ancestry changed')
    mounts = [m for m in runtime['info']['runtimeSpec']['mounts'] if m['destination'] == '/data']
    if len(mounts) != 1 or mounts[0]['source'] != str(path): raise RuntimeError('source CSI path changed')
    a, b = path.stat(), (Path('/proc') / str(pid) / 'root/data').stat()
    if (a.st_dev, a.st_ino) != (expected['device'], expected['inode']) or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        raise RuntimeError('source CSI mount identity changed')
    return {**expected, 'process': identity, 'image': IMAGE, 'namespace': namespace}


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name: raise RuntimeError('unsafe recovery path')
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name or any(p in ('.', '..') for p in path.parts): raise RuntimeError('unsafe recovery path')
    return path


def validate_manifest(value, namespace):
    if (not isinstance(value, dict) or not isinstance(value.get('source'), dict) or
            not isinstance(value['source'].get('process'), dict) or not isinstance(value.get('pause'), dict) or
            type(value['pause'].get('stopped_seconds')) not in (int, float)):
        raise RuntimeError('invalid recovery manifest shape')
    expected = SOURCES[namespace]; source = value.get('source', {})
    if (value.get('format') != 1 or value.get('cluster_uid') != common.CLUSTER_UID or
            any(source.get(k) != v for k, v in expected.items()) or source.get('image') != IMAGE or
            source.get('namespace') != namespace or source.get('process', {}).get('pid') != expected['pid'] or
            source.get('process', {}).get('exe') != '/sporecast-backend' or
            expected.get('start_ticks') is not None and source['process'].get('start_ticks') != expected['start_ticks'] or
            not 0 < value.get('pause', {}).get('stopped_seconds', 0) < 10 or
            value.get('original_process_resumed') is not True or
            not isinstance(value.get('tree'), dict) or set(value['tree']) != {'directories', 'files'} or
            not isinstance(value['tree']['directories'], list) or not isinstance(value['tree']['files'], dict) or
            not {'sporecast.db', 'sporecast.db-wal', 'sporecast.db-shm'} <= set(value['tree']['files'])):
        raise RuntimeError('protected Sporecast source/paused WAL contract changed')
    if type(value.get('bytes')) is not int or value['bytes'] != validate_tree(value['tree']):
        raise RuntimeError('recovery byte accounting differs')
    return value


def validate_tree(tree):
    if (not isinstance(tree, dict) or set(tree) != {'directories', 'files'} or
            not isinstance(tree['directories'], list) or not isinstance(tree['files'], dict)):
        raise RuntimeError('invalid recovery tree')
    for name in tree['directories']: safe_name(name)
    if len(set(tree['directories'])) != len(tree['directories']): raise RuntimeError('duplicate recovery directories')
    directories = set(tree['directories'])
    names = set(tree['files'])
    if directories & names: raise RuntimeError('conflicting recovery paths')
    for name, record in tree['files'].items():
        safe_name(name)
        if (not isinstance(record, dict) or set(record) != {'bytes', 'sha256'} or type(record['bytes']) is not int or record['bytes'] < 0 or
                not isinstance(record['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', record['sha256'])): raise RuntimeError('unsafe recovery record')
    for name in directories | names:
        if any(str(p) in names for p in PurePosixPath(name).parents if str(p) != '.'):
            raise RuntimeError('recovery file has descendants')
    return sum(r['bytes'] for r in tree['files'].values())


def memory_snapshot(root):
    inventory = files.tree(root)
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))) * 1024
    if sum(r['bytes'] for r in inventory['files'].values()) * 2 >= available:
        raise RuntimeError('actual available memory cannot hold the paused source snapshot')
    payloads = {}
    for name, record in inventory['files'].items():
        safe_name(name); path = root / name; before = process.file_identity(path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source: data = source.read()
        if (process.file_identity(path) != before or len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']):
            raise RuntimeError('source changed during memory capture')
        payloads[name] = data
    if files.tree(root) != inventory: raise RuntimeError('complete paused source inventory changed')
    return inventory, payloads


def send(namespace, output):
    before = source_identity(namespace)
    with tempfile.TemporaryDirectory(prefix='homelab-sporecast-103-', dir='/run') as marker_dir:
        marker = Path(marker_dir) / 'watchdog-fired'
        with process.frozen(before['process'], marker) as pause:
            if source_identity(namespace) != before: raise RuntimeError('source changed before pause')
            inventory, payloads = memory_snapshot(source_path(namespace))
            if source_identity(namespace) != before: raise RuntimeError('source changed during pause')
        if marker.exists() or source_identity(namespace) != before: raise RuntimeError('original source did not resume unchanged')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'tree': inventory, 'pause': pause,
                'bytes': sum(len(v) for v in payloads.values()), 'original_process_resumed': True}
    validate_manifest(manifest, namespace); encoded = common.canonical(manifest)
    if len(encoded) > 1048576 or b'\n' in encoded: raise RuntimeError('manifest exceeds framing contract')
    output.write(encoded + b'\n')
    for name in sorted(payloads): output.write(payloads[name])
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n'); output.flush()


def point_path(namespace, run_id):
    common.require_host('pikachu'); common.private_root()
    point = common.ROOT / (namespace + '-' + common.run_identifier(run_id))
    if any(p.is_symlink() for p in (point, *point.parents)): raise RuntimeError('unsafe protected ancestry')
    return point


def receive(source, point, namespace, validator=None, verifier=None):
    validator = validator or validate_manifest; verifier = verifier or verify
    frame = source.readline(1048578)
    if not frame.endswith(b'\n') or len(frame) > 1048577: raise RuntimeError('invalid incoming manifest frame')
    encoded = frame[:-1]; manifest = validator(json.loads(encoded), namespace); checksum = hashlib.sha256(encoded).hexdigest()
    if any(p.is_symlink() for p in (point.parent, *point.parent.parents)): raise RuntimeError('unsafe receiver ancestry')
    if manifest['bytes'] >= shutil.disk_usage(point.parent).free: raise RuntimeError('actual recovery capacity exhausted')
    point.mkdir(mode=0o700); data = point / 'data'; data.mkdir(mode=0o700)
    for name in manifest['tree']['directories']: (data / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, record in sorted(manifest['tree']['files'].items()):
        target = data / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True); remaining = record['bytes']; checksummer = hashlib.sha256()
        with target.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            while remaining:
                chunk = source.read(min(1048576, remaining))
                if not chunk: raise RuntimeError('truncated payload; protected partial retained')
                output.write(chunk); checksummer.update(chunk); remaining -= len(chunk)
            output.flush(); os.fsync(output.fileno())
        if checksummer.hexdigest() != record['sha256']: raise RuntimeError('payload hash differs; protected partial retained')
    if common.read_frame(source) != {'commit': checksum} or source.read(1): raise RuntimeError('source commit missing or trailing bytes')
    files.write_json(point / 'verified.json', manifest); verifier(point, checksum, namespace)
    return {'point': str(point), 'manifest_sha256': checksum, 'files': len(manifest['tree']['files']), 'bytes': manifest['bytes'], 'pause': manifest['pause']}


def verify(point, checksum, namespace, validator=None):
    validator = validator or validate_manifest
    common.source_record('verified.json', point / 'verified.json'); raw = (point / 'verified.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum: raise RuntimeError('protected manifest changed')
    manifest = validator(json.loads(raw), namespace)
    if (any(p.is_symlink() for p in (point, *point.parents)) or point.stat().st_uid != os.geteuid() or
            stat.S_IMODE(point.stat().st_mode) != 0o700 or files.tree(point / 'data') != manifest['tree']):
        raise RuntimeError('protected source tree changed')
    for name in manifest['tree']['files']:
        path = point / 'data' / name
        if path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError('protected file ownership or permissions changed')
    for name in ['', *manifest['tree']['directories']]:
        directory = point / 'data' / name
        if directory.stat().st_uid != os.geteuid() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise RuntimeError('protected directory ownership or permissions changed')
    return manifest


def wal_fingerprint(root, target):
    files.tree(root)
    if (not (root / 'sporecast.db').is_file() or target.exists() or
            any(p.is_symlink() for p in (target, *target.parents))):
        raise RuntimeError('unsafe SQLite reader or destination')
    with target.open('xb') as output: os.fchmod(output.fileno(), 0o600)
    source = sqlite3.connect('file:' + urllib.parse.quote(str(root / 'sporecast.db')) + '?mode=rw', uri=True, timeout=0)
    try:
        destination = sqlite3.connect(str(target), timeout=0)
        try:
            source.backup(destination)
            if destination.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',): raise RuntimeError('canonical copy journal differs')
        finally:
            destination.close()
    finally:
        source.close()
    return files.fingerprint(target)


def cached_archive(path):
    """Check every OCI blob and the Docker load mapping without extracting files."""
    with tarfile.open(path, 'r:') as archive:
        entries = archive.getmembers(); names = [entry.name for entry in entries]
        if len(names) != len(set(names)): raise RuntimeError('duplicate cached archive member')
        blobs = {}
        for entry in entries:
            if entry.isdir() and entry.name.rstrip('/') in ('blobs', 'blobs/sha256'): continue
            if not entry.isfile(): raise RuntimeError('cached archive contains a non-file')
            if entry.name in ('index.json', 'oci-layout', 'manifest.json'): continue
            if not re.fullmatch('blobs/sha256/[a-f0-9]{64}', entry.name): raise RuntimeError('unreviewed cached archive member')
            stream = archive.extractfile(entry)
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry.name.split('/')[-1]:
                raise RuntimeError('cached image blob hash differs')
            blobs['sha256:' + entry.name.split('/')[-1]] = entry.size
        def record(name):
            entry = archive.getmember(name)
            if entry.size > 1048576: raise RuntimeError('cached image metadata too large')
            return json.load(archive.extractfile(entry))
        index = record('index.json'); digest = IMAGE.split('@')[1]
        if len(index['manifests']) != 1 or index['manifests'][0]['digest'] != digest:
            raise RuntimeError('cached image manifest differs')
        annotations = index['manifests'][0].get('annotations', {})
        if (record('oci-layout') != {'imageLayoutVersion': '1.0.0'} or
                annotations.get('io.containerd.image.name') not in (None, CACHED_IMAGE) or
                annotations.get('org.opencontainers.image.ref.name') not in (None, digest, '@' + digest)):
            raise RuntimeError('cached OCI import reference differs')
        manifest = record('blobs/sha256/' + digest.split(':')[1])
        if manifest.get('schemaVersion') != 2 or manifest['config']['digest'] != CACHED_CONFIG:
            raise RuntimeError('cached image config differs')
        expected = {digest: archive.getmember('blobs/sha256/' + digest.split(':')[1]).size}
        for descriptor in [manifest['config'], *manifest['layers']]: expected[descriptor['digest']] = descriptor['size']
        docker_manifest = record('manifest.json')
        if (not isinstance(docker_manifest, list) or len(docker_manifest) != 1 or
                docker_manifest[0].get('RepoTags') not in (None, [], [CACHED_IMAGE])):
            raise RuntimeError('cached archive would import unreviewed Docker tags')
        docker_manifest[0]['RepoTags'] = None
        if (blobs != expected or index['manifests'][0]['size'] != expected[digest] or
                docker_manifest != [{'Config': 'blobs/sha256/' + CACHED_CONFIG.split(':')[1],
                                     'RepoTags': None,
                                     'Layers': ['blobs/sha256/' + layer['digest'].split(':')[1] for layer in manifest['layers']]}]):
            raise RuntimeError('cached image descriptors or Docker mapping differ')
        config = record('blobs/sha256/' + CACHED_CONFIG.split(':')[1])
        if config['architecture'] != 'amd64' or config['os'] != 'linux' or config.get('config', {}).get('Volumes'):
            raise RuntimeError('cached image platform or anonymous volumes differ')
        with path.open('rb') as stream: archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        return {'config': CACHED_CONFIG, 'rootfs': {'Type': config['rootfs']['type'], 'Layers': config['rootfs']['diff_ids']},
                'blobs': len(blobs), 'archive_sha256': archive_hash, 'source_image': CACHED_IMAGE}


def require_container(value, scratch, run_id):
    host = value['HostConfig']; config = value['Config']; environment = dict(e.split('=', 1) for e in config.get('Env', []) if '=' in e)
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 536870912, 'NanoCpus': 1000000000, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'},
                'Binds': [str(scratch / 'data') + ':/data:Z']}
    expected_image = IMAGE if SOURCES is HISTORICAL_SOURCES else CACHED_CONFIG
    if (config['Image'] != expected_image or config['User'] != '65532:65532' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Entrypoint') != ['/sporecast-backend'] or config.get('Cmd') not in (None, []) or
            any(environment.get(k) != v for k, v in ENVIRONMENT.items()) or
            any(host.get(k) != v for k, v in expected.items()) or host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or len(value['Mounts']) != 1 or
            value['Mounts'][0].get('Type') != 'bind' or value['Mounts'][0].get('Source') != str(scratch / 'data') or
            value['Mounts'][0].get('Destination') != '/data' or value['Mounts'][0].get('RW') is not True or
            value['Mounts'][0].get('Mode') != 'Z'):
        raise RuntimeError('native Sporecast isolation changed')


def docker_load_archive(source, target):
    """Keep verified layer bytes; omit OCI names and Docker tags from this copy."""
    verified = cached_archive(source)
    with tarfile.open(source, 'r:') as incoming, target.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        with tarfile.open(fileobj=output, mode='w|') as archive:
            for entry in incoming.getmembers():
                if entry.name in ('index.json', 'oci-layout'): continue
                if entry.name == 'manifest.json':
                    mapping = json.load(incoming.extractfile(entry)); mapping[0]['RepoTags'] = None
                    content = common.canonical(mapping); entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
                else:
                    archive.addfile(entry, incoming.extractfile(entry) if entry.isfile() else None)
    return verified


def restore(namespace, run_id, checksum):
    point = point_path(namespace, run_id); manifest = verify(point, checksum, namespace)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip(): raise RuntimeError('owned restore already active')
    if shutil.disk_usage(common.ROOT).free <= manifest['bytes'] * 3: raise RuntimeError('actual restore capacity cannot hold the copies')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=namespace + '-restore-', dir=common.ROOT)); scratch.chmod(0o700)
    container = image_id = None; result = {'accepted': False, 'manifest_sha256': checksum, 'namespace': namespace}
    try:
        files.copy_tree(point / 'data', scratch / 'data'); files.copy_tree(point / 'data', scratch / 'reader')
        snapshot = wal_fingerprint(scratch / 'reader', scratch / 'canonical.db')
        if files.tree(scratch / 'data') != manifest['tree']: raise RuntimeError('untouched raw restore copy differs')
        image_reference = IMAGE; cached = None
        if SOURCES is not HISTORICAL_SOURCES:
            # Both current profiles restore on the same protected Pikachu receiver.
            expected = PIKACHU_20261027['sporecast']; common.require_host(expected['node'])
            if (Path('/etc/machine-id').read_text().strip() != expected['machine'] or
                    common.command(['findmnt', '-n', '-o', 'UUID', '/']).stdout.decode().strip() != expected['root_uuid']):
                raise RuntimeError('cached image source host changed')
            archive = scratch / 'image.tar'
            common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'images', 'export',
                            '--platform', 'linux/amd64', str(archive), CACHED_IMAGE])
            load_archive = scratch / 'docker-image.tar'
            cached = docker_load_archive(archive, load_archive); image_id = image_reference = CACHED_CONFIG
            if image_id not in images: common.docker('image', 'load', '--input', str(load_archive))
        else:
            common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', image_reference).stdout)[0]; image_id = image['Id']
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or image['Config'].get('Volumes') or
                (cached is not None and (image_id != CACHED_CONFIG or image['RootFS'] != cached['rootfs'])) or
                (cached is None and not any(r.split('@')[-1] == IMAGE.split('@')[-1] and r.split('@')[0] == 'registry.eaglepass.io/sporecast-backend' for r in image.get('RepoDigests', [])))):
            raise RuntimeError('exact native Sporecast image contract changed')
        for parent, _, names in os.walk(scratch / 'data'):
            os.chown(parent, 65532, 65532)
            for name in names: os.chown(Path(parent) / name, 65532, 65532)
        args = ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=65532:65532',
                '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--memory=512m', '--cpus=1',
                '--label=' + LABEL + '=' + run_id, '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/sporecast-backend',
                # Relabel only the disposable copy for this isolated container.
                '--volume=' + str(scratch / 'data') + ':/data:Z']
        for key, value in ENVIRONMENT.items(): args.extend(['--env', key + '=' + value])
        container = common.docker(*args, image_reference).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container): raise RuntimeError('invalid owned container')
        require_container(common.inspect(container), scratch, run_id); common.docker('start', container)
        state = common.inspect(container); require_container(state, scratch, run_id); pid = str(state['State']['Pid'])
        net = ['nsenter', '-t', pid, '-n', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
                               sum((json.loads(common.command([*net, 'ip', f, '-j', 'route', 'show', 'table', 'all']).stdout) for f in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0: raise RuntimeError('production route exists')
        deadline = time.monotonic() + 300
        while True:
            if not common.inspect(container)['State']['Running']: raise RuntimeError('native Sporecast restore exited')
            code = "import hashlib,json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/api/health/ready',timeout=5);b=r.read();print(json.dumps({'status':r.status,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}))"
            response = common.command([*net, 'python3', '-B', '-c', code], check=False)
            if response.returncode == 0:
                health = json.loads(response.stdout)
                if health['status'] != 200: raise RuntimeError('native readiness differs')
                break
            if time.monotonic() >= deadline: raise RuntimeError('native readiness exceeded300seconds')
            time.sleep(1)
        require_container(common.inspect(container), scratch, run_id); common.docker('stop', '--time=30', container)
        stopped = common.inspect(container)['State']
        if stopped['Running'] or stopped['ExitCode'] not in (0, 143): raise RuntimeError('native stop failed or required force')
        files.copy_tree(scratch / 'data', scratch / 'stopped-reader')
        after = wal_fingerprint(scratch / 'stopped-reader', scratch / 'stopped.db')
        verify(point, checksum, namespace)
        if snapshot != after: raise RuntimeError('native Sporecast restore changed canonical data')
        result.update(accepted=True, image=IMAGE, cached_image=cached, source_snapshot=snapshot, stopped_native_snapshot=after,
                      native_exit_code=stopped['ExitCode'], native_ready=health, original_raw_unmounted=True,
                      untouched_wal_copy_started=True, production_network_unroutable=True, source_writers_quiesced=False,
                      providers_webhooks_nas_later_writes_unqualified=True)
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id); common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0: raise RuntimeError('owned container remains')
        removed = False
        if image_id and image_id not in images and common.docker('image', 'inspect', image_id, check=False).returncode == 0:
            if common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip(): raise RuntimeError('new image has another consumer; retained')
            common.docker('image', 'rm', '-f', image_id); removed = common.docker('image', 'inspect', image_id, check=False).returncode != 0
            if not removed: raise RuntimeError('new unused image remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch); verify(point, checksum, namespace)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'owned_container_absent': True,
                             'new_unused_image_removed': removed, 'protected_hashes_unchanged': True, 'allocated_bytes_removed': allocated}
        files.write_json(point / ('restore-' + str(time.time_ns()) + '.json'), result); print(json.dumps(result), flush=True)
    return result


def main():
    os.umask(0o077)
    def cancel(_number, _frame): raise InterruptedError('owned Sporecast recovery interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, cancel)
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('mode', choices=('send', 'receive', 'restore'))
    parser.add_argument('--namespace', choices=sorted(HISTORICAL_SOURCES), required=True); parser.add_argument('--run-id', type=common.run_identifier, required=True)
    parser.add_argument('--profile', choices=sorted(PROFILES), default='historical')
    parser.add_argument('--manifest'); args = parser.parse_args()
    select_profile(args.profile)
    if args.namespace not in SOURCES: parser.error('namespace is not included in the selected profile')
    if args.mode == 'send': send(args.namespace, sys.stdout.buffer)
    elif args.mode == 'receive': print(json.dumps(receive(sys.stdin.buffer, point_path(args.namespace, args.run_id), args.namespace)), flush=True)
    else:
        if not re.fullmatch('[a-f0-9]{64}', args.manifest or ''): parser.error('restore requires exact manifest SHA256')
        return 0 if restore(args.namespace, args.run_id, args.manifest)['accepted'] else 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
