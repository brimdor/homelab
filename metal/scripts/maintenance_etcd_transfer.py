"""Stream a complete stopped etcd member tree to a protected off-node point.

The parent owns stop/start intents and independently binds host and transaction
identity. This module never stops a service or removes a recovery point.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import maintenance_actor_hold as actors
import maintenance_etcd_legacy as legacy


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def frame(stream):
    raw = stream.readline(4 * 1024 * 1024 + 1)
    actors.require(raw.endswith(b'\n') and len(raw) <= 4 * 1024 * 1024,
                   'incomplete or oversized etcd transfer frame')
    value = json.loads(raw)
    actors.require(isinstance(value, dict) and raw == canonical(value) + b'\n',
                   'noncanonical etcd transfer frame')
    return value


def send(source, output, binding, expected, confirm_stopped):
    """No final commit is emitted unless the exact source remains stopped and stable."""
    source = Path(source)
    actors.require(isinstance(binding, dict) and binding and confirm_stopped() is True,
                   'owned stopped-source proof required')
    actors.require(legacy.member_manifest(source) == expected, 'stopped etcd source changed before transfer')
    header = {'version': 1, 'binding': binding, 'manifest': expected}
    encoded = canonical(header)
    actors.require(len(encoded) < 4 * 1024 * 1024, 'etcd transfer manifest too large')
    output.write(encoded + b'\n')
    for name, entry in sorted(expected['entries'].items()):
        if entry['kind'] != 'file':
            continue
        path = source / name
        actors.safe(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as origin:
            actors.require(legacy.identity(os.fstat(origin.fileno())) == entry['identity'],
                           'stopped etcd file identity changed')
            digest = hashlib.sha256();length = 0
            for chunk in iter(lambda: origin.read(1048576), b''):
                output.write(chunk);digest.update(chunk);length += len(chunk)
            actors.require(legacy.identity(os.fstat(origin.fileno())) == entry['identity'] and
                           length == entry['size'] and digest.hexdigest() == entry['sha256'],
                           'stopped etcd file changed during transfer')
    actors.require(confirm_stopped() is True and legacy.member_manifest(source) == expected,
                   'stopped etcd source changed before transfer commit')
    output.write(canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def validate_manifest(value):
    actors.require(isinstance(value, dict) and set(value) == {'version', 'root', 'entries'} and
                   type(value['version']) is int and value['version'] == 1 and
                   isinstance(value['root'], dict) and value['root'].get('kind') == 'directory' and
                   value['root'].get('mode') == 0o700 and isinstance(value['entries'], dict),
                   'invalid etcd transfer manifest')
    entries = value['entries']
    for name, entry in entries.items():
        actors.require(isinstance(name, str) and re.fullmatch(r'member(?:/[A-Za-z0-9_.-]+)*', name) and
                       all(part not in ('.', '..') for part in name.split('/')) and isinstance(entry, dict),
                       'unsafe etcd transfer path')
        base = {'kind', 'mode', 'uid', 'gid', 'identity', 'xattrs'}
        kind = entry.get('kind')
        actors.require(kind in ('directory', 'file') and
                       set(entry) == base | ({'size', 'sha256'} if kind == 'file' else set()) and
                       type(entry['mode']) is int and 0 <= entry['mode'] <= 0o777 and
                       not entry['mode'] & 0o022 and entry['uid'] == os.geteuid() and
                       type(entry['gid']) is int and entry['gid'] >= 0 and
                       isinstance(entry['xattrs'], dict) and isinstance(entry['identity'], list) and
                       len(entry['identity']) == 5 and all(type(n) is int and n >= 0 for n in entry['identity']),
                       'unsafe etcd transfer metadata')
        if name != 'member':
            actors.require(entries.get(str(Path(name).parent), {}).get('kind') == 'directory',
                           'etcd transfer parent directory missing')
        if kind == 'file':
            actors.require(type(entry['size']) is int and entry['size'] >= 0 and
                           isinstance(entry['sha256'], str) and re.fullmatch('[0-9a-f]{64}', entry['sha256']),
                           'invalid etcd transfer file digest or length')
    actors.require(entries.get('member', {}).get('kind') == 'directory' and
                   entries.get('member/snap/db', {}).get('kind') == 'file' and
                   entries['member/snap/db']['size'] > 0 and
                   any(re.fullmatch(r'member/wal/[0-9a-f]{16}-[0-9a-f]{16}\.wal', name) and
                       entry['kind'] == 'file' and entry['size'] > 0 for name, entry in entries.items()),
                   'complete nonempty etcd database and WAL required')


def receive(stream, point, binding, expected_manifest_sha256, native):
    """Retain partial points on any failure; verified.json is written only at the end."""
    point = Path(point)
    actors.require(point.is_absolute() and legacy.directory_record(point.parent)['mode'] == 0o700 and
                   native('findmnt', '-n', '-o', 'FSTYPE', '-T', str(point.parent)) == 'ext4',
                   'private ext4 recovery parent required')
    actors.safe(point)
    header = frame(stream)
    actors.require(set(header) == {'version', 'binding', 'manifest'} and
                   type(header['version']) is int and header['version'] == 1 and
                   header['binding'] == binding and isinstance(binding, dict) and binding and
                   isinstance(expected_manifest_sha256, str) and
                   re.fullmatch('[0-9a-f]{64}', expected_manifest_sha256) and
                   legacy.manifest_sha256(header['manifest']) == expected_manifest_sha256,
                   'etcd transfer transaction or manifest binding differs')
    manifest = header['manifest'];validate_manifest(manifest)
    actors.require(sum(v.get('size', 0) for v in manifest['entries'].values()) <
                   shutil.disk_usage(point.parent).free, 'insufficient actual recovery capacity')
    point.mkdir(mode=0o700);actors.fsync_directory(point.parent)
    data = point / 'data';data.mkdir(mode=0o700)
    for name in sorted(manifest['entries'], key=lambda n: (len(Path(n).parts), n)):
        entry = manifest['entries'][name]
        if entry['kind'] == 'directory':
            (data / name).mkdir(mode=0o700)
    # JSON framing sorts keys; stream file order must match that canonical order.
    for name, entry in sorted(manifest['entries'].items()):
        if entry['kind'] != 'file':
            continue
        digest = hashlib.sha256();remaining = entry['size']
        with (data / name).open('xb') as target:
            os.fchmod(target.fileno(), 0o600)
            while remaining:
                chunk = stream.read(min(1048576, remaining))
                actors.require(chunk, 'truncated etcd member transfer')
                remaining -= len(chunk);digest.update(chunk);target.write(chunk)
            actors.require(digest.hexdigest() == entry['sha256'], 'etcd transfer file checksum differs')
            if os.fstat(target.fileno()).st_gid != entry['gid']:
                os.fchown(target.fileno(), entry['uid'], entry['gid'])
            os.fchmod(target.fileno(), entry['mode']);target.flush();os.fsync(target.fileno())
    actors.require(frame(stream) == {'commit': hashlib.sha256(canonical(header)).hexdigest()} and
                   not stream.read(1), 'etcd transfer final commit missing or trailing bytes')
    for name, entry in sorted(manifest['entries'].items(), key=lambda row: len(Path(row[0]).parts), reverse=True):
        if entry['kind'] == 'directory':
            path = data / name
            if path.stat().st_gid != entry['gid']:
                os.chown(path, entry['uid'], entry['gid'])
            path.chmod(entry['mode']);actors.fsync_directory(path)
    actors.fsync_directory(data)
    received = legacy.member_manifest(data)
    actors.require(legacy.contents(received) == legacy.contents(manifest), 'received etcd member contents differ')
    actors.exclusive_file(point / 'verified.json', canonical(header), 0o600)
    actors.fsync_directory(point)
    return {'accepted': True, 'point': str(point), 'source_manifest_sha256': expected_manifest_sha256,
            'received_manifest_sha256': legacy.manifest_sha256(received),
            'binding_sha256': hashlib.sha256(canonical(binding)).hexdigest(),
            'complete_WAL_and_database': True, 'original_recovery_point_preserved': True}
