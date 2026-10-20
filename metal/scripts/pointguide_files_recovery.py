"""Capture exact retained-volume writers; recover only private, disconnected copies."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import urllib.parse

import arr_database_recovery as coordinated
import etcd_recovery as common
import grafana_recovery as files
import prometheus_recovery as process
import sporecast_recovery as transfer


PROFILES = globals().get('PROFILE_DATA') or json.loads(
    Path(__file__).parents[1].joinpath('maintenance/pointguide-files-103.json').read_text())
DATABASES = {'memories_1.sqlite', 'queue_1.sqlite', 'logs_2.sqlite', 'goals_1.sqlite', 'state_5.sqlite'}


def available_memory():
    return coordinated.available_memory()


def source_identity(namespace):
    profile = PROFILES[namespace]
    common.require_host(profile['node'])
    root = Path(profile['volume']['source'])
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('unsafe Codex source ancestry')
    identities = []
    for expected in profile['runtime']:
        cid = expected['container_id']
        runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', cid]).stdout)
        status, info = runtime['status'], runtime['info']
        labels = status['labels']
        if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'] != expected['image'] or
                info['pid'] != expected['pid'] or labels.get('io.kubernetes.pod.uid') != profile['pod_uid'] or
                labels.get('io.kubernetes.pod.namespace') != namespace or
                labels.get('io.kubernetes.container.name') != expected['container'] or
                info['runtimeSpec']['process']['user'] != expected['user']):
            raise RuntimeError('reviewed Codex container changed')
        raw = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode()
        tasks = {int(line.split()[0]) for line in raw.splitlines()[1:] if line.strip()}
        if tasks != {p['pid'] for p in expected['processes']}:
            raise RuntimeError('reviewed Codex writer task set changed')
        for previous in expected['processes']:
            identity = process.process_identity(previous['pid'])
            if ({**identity, 'uid': (Path('/proc') / str(previous['pid'])).stat().st_uid} != previous or
                    profile['pod_uid'].replace('-', '_') not in identity['cgroup']):
                raise RuntimeError('reviewed Codex process changed')
            identities.append(identity)
        destination = profile['volume']['destination']
        mounts = [m for m in info['runtimeSpec']['mounts'] if m['destination'] == destination]
        a, b = root.stat(), (Path('/proc') / str(expected['pid']) / 'root' / destination.lstrip('/')).stat()
        if (len(mounts) != 1 or mounts[0]['source'] != str(root) or
                (a.st_dev, a.st_ino) != (profile['volume']['device'], profile['volume']['inode']) or
                (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
            raise RuntimeError('reviewed Codex CSI mount changed')
    if len(identities) != len({p['pid'] for p in identities}):
        raise RuntimeError('duplicated Codex writer')
    return identities


def metadata(path):
    value = path.lstat()
    if stat.S_ISDIR(value.st_mode):
        kind = 'directory'
    elif stat.S_ISREG(value.st_mode) and value.st_nlink == 1:
        kind = 'file'
    elif stat.S_ISLNK(value.st_mode):
        kind = 'symlink'
    else:
        raise RuntimeError('Codex store contains a hardlink or special file')
    result = {'kind': kind, 'mode': stat.S_IMODE(value.st_mode), 'uid': value.st_uid,
              'gid': value.st_gid, 'mtime_ns': value.st_mtime_ns,
              'xattrs': {name: os.getxattr(path, name, follow_symlinks=False).hex()
                         for name in sorted(os.listxattr(path, follow_symlinks=False))}}
    if kind == 'symlink':
        result['target'] = os.readlink(path)
    elif kind == 'file':
        result['bytes'] = value.st_size
    return result


def inventory(root):
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise RuntimeError('unsafe Codex tree root')
    result = {'': metadata(root)}
    device = root.stat().st_dev
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(parent) / name
            if path.lstat().st_dev != device:
                raise RuntimeError('Codex tree crosses a device')
            relative = str(path.relative_to(root))
            transfer.safe_name(relative)
            result[relative] = metadata(path)
    return dict(sorted(result.items()))


def read_payload(path):
    before = process.file_identity(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
        if process.file_identity(path) != before:
            raise RuntimeError('Codex file changed before open')
        data = source.read()
    if process.file_identity(path) != before or len(data) != before[2]:
        raise RuntimeError('Codex file changed while reading')
    return data


def snapshot(root):
    tree = inventory(root)
    if sum(v.get('bytes', 0) for v in tree.values()) * 2 >= available_memory():
        raise RuntimeError('actual available RAM cannot hold Codex snapshot')
    payloads = {}
    for name, record in tree.items():
        if record['kind'] == 'file':
            payloads[name] = read_payload(root / name)
            record['sha256'] = hashlib.sha256(payloads[name]).hexdigest()
    if inventory(root) != {name: {k: v for k, v in record.items() if k != 'sha256'}
                           for name, record in tree.items()}:
        raise RuntimeError('Codex tree changed during capture')
    return tree, payloads


def validate(value, namespace):
    if (not isinstance(value, dict) or set(value) != {'format', 'cluster_uid', 'profile', 'tree', 'pauses', 'resumed'} or
            value['format'] != 1 or value['cluster_uid'] != common.CLUSTER_UID or
            value['profile'] != PROFILES[namespace] or value['resumed'] is not True or
            not isinstance(value['pauses'], list) or len(value['pauses']) != sum(
                len(r['processes']) for r in PROFILES[namespace]['runtime']) or any(
                not isinstance(p, dict) or set(p) != {'stopped_seconds'} or
                type(p['stopped_seconds']) not in (int, float) or not 0 < p['stopped_seconds'] < 10
                for p in value['pauses']) or not isinstance(value['tree'], dict)):
        raise RuntimeError('Codex capture identity or pause contract changed')
    tree = value['tree']
    if '' not in tree or tree['']['kind'] != 'directory':
        raise RuntimeError('Codex root directory missing')
    for name, record in tree.items():
        if name:
            path = transfer.safe_name(name)
            if any(tree.get(str(p), {}).get('kind') != 'directory' for p in path.parents if str(p) != '.'):
                raise RuntimeError('Codex path lacks directory parent')
        if not isinstance(record, dict) or record.get('kind') not in ('directory', 'file', 'symlink'):
            raise RuntimeError('invalid Codex entry')
        extra = {'file': {'bytes', 'sha256'}, 'symlink': {'target'}, 'directory': set()}[record['kind']]
        if (set(record) != {'kind', 'mode', 'uid', 'gid', 'mtime_ns', 'xattrs'} | extra or
                any(type(record[k]) is not int or record[k] < 0 for k in ('mode', 'uid', 'gid', 'mtime_ns')) or
                record['mode'] > 0o7777 or not isinstance(record['xattrs'], dict)):
            raise RuntimeError('invalid Codex metadata')
        for key, raw in record['xattrs'].items():
            if not isinstance(key, str) or not key or '\0' in key or not isinstance(raw, str):
                raise RuntimeError('invalid Codex xattr')
            try:
                if bytes.fromhex(raw).hex() != raw:
                    raise ValueError()
            except ValueError:
                raise RuntimeError('invalid Codex xattr bytes') from None
        if record['kind'] == 'file' and (type(record['bytes']) is not int or record['bytes'] < 0 or
                not isinstance(record['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', record['sha256'])):
            raise RuntimeError('invalid Codex file checksum')
        if record['kind'] == 'symlink' and (not isinstance(record['target'], str) or not record['target'] or '\0' in record['target']):
            raise RuntimeError('invalid Codex link target')
    return value


def send(namespace, output):
    identities = source_identity(namespace)
    root = Path(PROFILES[namespace]['volume']['source'])
    # Warm reads occur in this separate process, never inside a SQLite writer.
    for name, record in inventory(root).items():
        if record['kind'] == 'file':
            read_payload(root / name)
    if source_identity(namespace) != identities:
        raise RuntimeError('Codex writers changed during warm read')
    with tempfile.TemporaryDirectory(prefix='homelab-codex-recovery-', dir='/run') as temporary:
        with coordinated.stopped(identities, Path(temporary) / 'markers') as pauses:
            if source_identity(namespace) != identities:
                raise RuntimeError('Codex writers changed before capture')
            tree, payloads = snapshot(root)
            if source_identity(namespace) != identities:
                raise RuntimeError('Codex writers changed during capture')
        if source_identity(namespace) != identities:
            raise RuntimeError('original Codex writers did not resume unchanged')
    value = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'profile': PROFILES[namespace],
             'tree': tree, 'pauses': pauses, 'resumed': True}
    validate(value, namespace)
    encoded = common.canonical(value)
    checksum = hashlib.sha256(encoded).hexdigest()
    output.write(common.canonical({'manifest_bytes': len(encoded), 'sha256': checksum}) + b'\n')
    output.write(encoded)
    for name in sorted(payloads):
        output.write(payloads[name])
    output.write(common.canonical({'commit': checksum}) + b'\n')
    output.flush()


def receive(source, point, namespace):
    header = common.read_frame(source)
    if (set(header) != {'manifest_bytes', 'sha256'} or type(header['manifest_bytes']) is not int or
            not 0 < header['manifest_bytes'] < available_memory() or
            not isinstance(header['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', header['sha256'])):
        raise RuntimeError('unsafe Codex manifest frame')
    encoded = source.read(header['manifest_bytes'])
    if len(encoded) != header['manifest_bytes'] or hashlib.sha256(encoded).hexdigest() != header['sha256']:
        raise RuntimeError('Codex manifest truncated or changed')
    value = validate(json.loads(encoded), namespace)
    if (any(p.is_symlink() for p in (point.parent, *point.parent.parents)) or
            sum(r.get('bytes', 0) for r in value['tree'].values()) >= shutil.disk_usage(point.parent).free):
        raise RuntimeError('Codex protected destination unsafe or full')
    point.mkdir(mode=0o700)
    data = point / 'data'
    data.mkdir(mode=0o700)
    for number, (name, record) in enumerate(sorted(value['tree'].items())):
        if record['kind'] != 'file':
            continue
        remaining, digest = record['bytes'], hashlib.sha256()
        with (data / str(number)).open('xb') as target:
            os.fchmod(target.fileno(), 0o600)
            while remaining:
                chunk = source.read(min(1048576, remaining))
                if not chunk:
                    raise RuntimeError('Codex payload truncated; protected partial retained')
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            target.flush()
            os.fsync(target.fileno())
        if digest.hexdigest() != record['sha256']:
            raise RuntimeError('Codex payload changed; protected partial retained')
    if common.read_frame(source) != {'commit': header['sha256']} or source.read(1):
        raise RuntimeError('Codex transfer commit or EOF missing')
    files.write_json(point / 'verified.json', value)
    for directory in (data, point, point.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    verify(point, header['sha256'], namespace)
    return {'point': str(point), 'manifest_sha256': header['sha256'],
            'files': sum(r['kind'] == 'file' for r in value['tree'].values()),
            'bytes': sum(r.get('bytes', 0) for r in value['tree'].values()), 'pauses': value['pauses']}


def verify(point, checksum, namespace):
    if (any(p.is_symlink() for p in (point, *point.parents)) or
            any(p.stat().st_uid != os.geteuid() or stat.S_IMODE(p.stat().st_mode) != 0o700
                for p in (point, point / 'data'))):
        raise RuntimeError('Codex protected directory changed')
    common.source_record('verified.json', point / 'verified.json')
    raw = (point / 'verified.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise RuntimeError('Codex protected manifest changed')
    value = validate(json.loads(raw), namespace)
    expected = {}
    for number, (_, record) in enumerate(sorted(value['tree'].items())):
        if record['kind'] == 'file':
            expected[str(number)] = {'bytes': record['bytes'], 'sha256': record['sha256']}
            path = point / 'data' / str(number)
            actual = path.lstat()
            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or
                    actual.st_uid != os.geteuid() or stat.S_IMODE(actual.st_mode) != 0o600):
                raise RuntimeError('Codex protected file permissions changed')
    # Ordinary retained files may be empty; the shared manifest-only reader forbids zero bytes.
    if files.tree(point / 'data') != {'directories': [], 'files': expected}:
        raise RuntimeError('Codex protected file set or checksum changed')
    return value


def apply_metadata(path, record):
    os.chown(path, record['uid'], record['gid'], follow_symlinks=False)
    if record['kind'] != 'symlink':
        os.chmod(path, record['mode'], follow_symlinks=False)
    for name in os.listxattr(path, follow_symlinks=False):
        if name not in record['xattrs']:
            os.removexattr(path, name, follow_symlinks=False)
    for name, raw in record['xattrs'].items():
        os.setxattr(path, name, bytes.fromhex(raw), follow_symlinks=False)
    os.utime(path, ns=(record['mtime_ns'], record['mtime_ns']), follow_symlinks=False)


def materialize(point, root, value):
    root.mkdir(mode=0o700)
    tree = value['tree']
    for name, record in sorted(tree.items(), key=lambda item: (len(Path(item[0]).parts), item[0])):
        if name and record['kind'] == 'directory':
            (root / name).mkdir(mode=0o700)
    for number, (name, record) in enumerate(sorted(tree.items())):
        if record['kind'] == 'file':
            with (point / 'data' / str(number)).open('rb') as source, (root / name).open('xb') as target:
                shutil.copyfileobj(source, target)
    # Links are inert metadata. Never follow them or start restored application code.
    for name, record in tree.items():
        if record['kind'] == 'symlink':
            os.symlink(record['target'], root / name)
    for name, record in sorted(tree.items(), key=lambda item: len(Path(item[0]).parts), reverse=True):
        apply_metadata(root / name, record)
    copied = inventory(root)
    expected = {name: {k: v for k, v in record.items() if k != 'sha256'} for name, record in tree.items()}
    if copied != expected or any(hashlib.sha256(read_payload(root / name)).hexdigest() != record['sha256']
                                 for name, record in tree.items() if record['kind'] == 'file'):
        raise RuntimeError('restored Codex bytes or metadata differ')


def sqlite_restore(root, target):
    # Open copied databases with their exact WAL/journal siblings; never original paths.
    source = sqlite3.connect('file:' + urllib.parse.quote(str(root)) + '?mode=rw', uri=True, timeout=0)
    try:
        destination = sqlite3.connect(str(target), timeout=0)
        try:
            source.backup(destination)
            if destination.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
                raise RuntimeError('canonical Codex SQLite journal differs')
        finally:
            destination.close()
    finally:
        source.close()
    return files.fingerprint(target)


def restore(point, checksum, namespace):
    value = verify(point, checksum, namespace)
    scratch = Path(tempfile.mkdtemp(prefix=namespace + '-codex-restore-', dir=point.parent))
    scratch.chmod(0o700)
    result = {'accepted': False, 'manifest_sha256': checksum}
    try:
        root = scratch / 'root'
        materialize(point, root, value)
        restored = {}
        databases = PROFILES[namespace].get('sqlite_databases', DATABASES)
        for number, name in enumerate(sorted(databases)):
            if value['tree'].get(name, {}).get('kind') != 'file':
                raise RuntimeError('reviewed Codex database missing')
            restored[name] = sqlite_restore(root / name, scratch / (str(number) + '.sqlite'))
        # The independent second restore starts from the same protected bytes, not the first recovered tree.
        second = scratch / 'second'
        materialize(point, second, value)
        for number, name in enumerate(sorted(databases)):
            if sqlite_restore(second / name, scratch / ('second-' + str(number) + '.sqlite')) != restored[name]:
                raise RuntimeError('independent Codex SQLite recoveries differ')
        result.update(accepted=True, databases=restored, sqlite_version=sqlite3.sqlite_version,
                      complete_bytes_metadata_and_symlinks_equal=True, complete_independent_file_restores_equal=True,
                      sqlite_databases_verified=len(restored), independent_sqlite_restore_equal=True if restored else None,
                      native_codex_application_and_external_link_targets_unqualified=True,
                      application_not_started=True, providers_not_invoked=True)
    finally:
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        for parent, directories, _ in os.walk(scratch, followlinks=False):
            os.chmod(parent, 0o700)
            for name in directories:
                p = Path(parent) / name
                if not p.is_symlink():
                    os.chmod(p, 0o700)
        shutil.rmtree(scratch)
        verify(point, checksum, namespace)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'allocated_bytes_removed': allocated,
                             'protected_point_unchanged': True}
    return result
