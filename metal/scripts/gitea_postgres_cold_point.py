"""Write and verify complete clean PostgreSQL copy points without starting a server."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat

import gitea_postgres_control as control


retained = control.retained
common = control.common
FORMAT = 'isolated-clean-copy-103-v2'
GUARDED_FORMAT = 'guarded-production-postgresql-103-v1'


def validate_source(value):
    """Record the exact production binding; the caller proves its live guard."""
    required = {'cluster_uid', 'namespace', 'pod', 'pod_uid', 'controller_uid', 'node',
                'container_id', 'image', 'claim', 'claim_uid', 'pv', 'pv_uid',
                'revision', 'hba_sha256', 'volume', 'guard'}
    try:
        if (set(value) != required or value['cluster_uid'] != common.CLUSTER_UID or
                value['namespace'] != 'gitea' or value['pod'] != 'gitea-postgresql-0' or
                value['controller_uid'] != '80aac4a0-46ec-4564-84db-d99c440780e9' or
                value['image'] != control.IMAGE or value['claim'] != 'data-gitea-postgresql-0' or
                value['claim_uid'] != '4d6d356d-ec5d-4f2e-961e-090eae9e0c21' or
                value['pv'] != 'pvc-' + value['claim_uid'] or
                value['pv_uid'] != '5cadac3d-dd99-4e3e-8551-4d165826cf44' or
                value['hba_sha256'] != '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05' or
                not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', value['pod_uid']) or
                not re.fullmatch('[a-z][a-z0-9-]*', value['node']) or
                not re.fullmatch('[a-f0-9]{64}', value['container_id']) or
                not re.fullmatch('[a-f0-9]{40}', value['revision'])):
            raise ValueError()
        volume, guard = value['volume'], value['guard']
        expected = '/var/lib/kubelet/pods/' + value['pod_uid'] + '/volumes/kubernetes.io~csi/' + value['pv'] + '/mount'
        if (set(volume) != {'source', 'device', 'inode'} or volume['source'] != expected or
                set(guard) != {'namespace_pid', 'host_pid', 'start_ticks', 'lock_device', 'lock_inode'} or
                any(type(v) is not int or v <= 0 for k, v in volume.items() if k != 'source') or
                any(type(v) is not int or v <= 0 for v in guard.values())):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError('guarded production PostgreSQL source binding differs') from None
    return value


def validate(value):
    try:
        if value['format'] == FORMAT:
            if (set(value) != {'format', 'original_manifest_sha256', 'control', 'tree'} or
                    value['original_manifest_sha256'] != control.CHECKSUM):
                raise ValueError()
        elif value['format'] == GUARDED_FORMAT:
            if set(value) != {'format', 'source', 'control', 'tree'}:
                raise ValueError()
            validate_source(value['source'])
        else:
            raise ValueError()
        if (value['control']['cluster_state'] != 'shut down' or
                value['control']['control_version'] != 1300 or value['control']['catalog_version'] != 202307071):
            raise ValueError()
        state = value['control']
        if (set(state) != {'control_version', 'catalog_version', 'cluster_state', 'data_page_checksum_version',
                          'system_identifier_sha256', 'checkpoint_sha256', 'complete_control_output_sha256'} or
                type(state['data_page_checksum_version']) is not int or state['data_page_checksum_version'] not in (0, 1) or
                any(not re.fullmatch('[0-9a-f]{64}', state[k]) for k in
                    ('system_identifier_sha256', 'checkpoint_sha256', 'complete_control_output_sha256'))):
            raise ValueError()
        tree = value['tree']
        if not isinstance(tree, dict) or tree['']['kind'] != 'directory' or 'data/postmaster.pid' in tree:
            raise ValueError()
        for name, record in tree.items():
            if name:
                retained.transfer.safe_name(name)
                parent = str(Path(name).parent)
                if tree['' if parent == '.' else parent]['kind'] != 'directory':
                    raise ValueError()
            if (record['kind'] not in {'file', 'directory'} or
                    any(type(record[k]) is not int or record[k] < 0 for k in ('mode', 'uid', 'gid', 'mtime_ns')) or
                    record['mode'] > 0o7777 or not isinstance(record['xattrs'], dict)):
                raise ValueError()
            for key, encoded in record['xattrs'].items():
                if not isinstance(key, str) or not key or '\0' in key or bytes.fromhex(encoded).hex() != encoded:
                    raise ValueError()
            fields = {'kind', 'mode', 'uid', 'gid', 'mtime_ns', 'xattrs'}
            if record['kind'] == 'file':
                fields |= {'bytes', 'sha256'}
                if (type(record['bytes']) is not int or record['bytes'] < 0 or
                        not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
                    raise ValueError()
            if set(record) != fields:
                raise ValueError()
        if (tree['data/PG_VERSION']['sha256'] !=
                'e6c21e8d260fe71882debdb339d2402a2ca7648529bc2303f48649bce0380017' or
                tree['data/global/pg_control']['bytes'] != 8192):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        raise RuntimeError('clean PostgreSQL copy-point manifest differs') from None
    return value


def require_directory(path):
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir() or
            path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) != 0o700):
        raise RuntimeError('clean PostgreSQL copy-point directory differs')


def verify(point, checksum):
    require_directory(point)
    require_directory(point / 'data')
    path = point / 'verified.json'
    if path.lstat().st_nlink != 1:
        raise RuntimeError('clean PostgreSQL copy-point manifest is linked')
    record, identity = common.source_record('verified.json', path)
    raw = path.read_bytes()
    if (record['sha256'] != checksum or hashlib.sha256(raw).hexdigest() != checksum or
            common.source_record('verified.json', path) != (record, identity)):
        raise RuntimeError('clean PostgreSQL copy-point manifest checksum differs')
    value = validate(json.loads(raw))
    expected = {}
    for number, (_, metadata) in enumerate(sorted(value['tree'].items())):
        if metadata['kind'] == 'file':
            expected[str(number)] = {'bytes': metadata['bytes'], 'sha256': metadata['sha256']}
            path = point / 'data' / str(number)
            properties = path.lstat()
            if (not stat.S_ISREG(properties.st_mode) or properties.st_nlink != 1 or
                    properties.st_uid != os.geteuid() or stat.S_IMODE(properties.st_mode) != 0o600):
                raise RuntimeError('clean PostgreSQL copy-point payload properties differ')
    if retained.files.tree(point / 'data') != {'directories': [], 'files': expected}:
        raise RuntimeError('clean PostgreSQL copy-point payload set or checksum differs')
    if sorted(p.name for p in point.iterdir()) != ['data', 'verified.json']:
        raise RuntimeError('clean PostgreSQL copy-point contains an unexpected item')
    return value


def capture(source, point, state, *, source_binding=None):
    """Caller proves an owned stopped copy or the exact held production runtime.

    Recording a binding alone does not establish quiescence or authorize SQL.
    """
    if (any(p.is_symlink() for p in (source, *source.parents, point.parent, *point.parent.parents)) or
            not source.is_dir() or point.exists() or source == point or source in point.parents or
            point in source.parents):
        raise RuntimeError('clean PostgreSQL copy-point source or destination differs')
    tree, payloads = retained.snapshot(source)
    provenance = ({'format': FORMAT, 'original_manifest_sha256': control.CHECKSUM}
                  if source_binding is None else {'format': GUARDED_FORMAT, 'source': source_binding})
    value = validate({**provenance, 'control': state, 'tree': tree})
    retained.require_capacity(point.parent, tree, 3)
    point.mkdir(mode=0o700)
    (point / 'data').mkdir(mode=0o700)
    for number, (name, metadata) in enumerate(sorted(tree.items())):
        if metadata['kind'] != 'file':
            continue
        with (point / 'data' / str(number)).open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payloads[name])
            output.flush()
            os.fsync(output.fileno())
    del payloads
    retained.files.write_json(point / 'verified.json', value)
    for directory in (point / 'data', point, point.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    checksum = hashlib.sha256(common.canonical(value)).hexdigest()
    if verify(point, checksum) != value or retained.snapshot(source)[0] != tree:
        raise RuntimeError('clean PostgreSQL copy-point source changed during capture')
    return value, checksum


def send(point, checksum, output, *, confirm_source=None):
    """Stream an already verified protected point; commit only unchanged bytes."""
    value = verify(point, checksum)
    encoded = common.canonical(value)
    output.write(common.canonical({'manifest_bytes': len(encoded), 'sha256': checksum}) + b'\n')
    output.write(encoded)
    for number, (_, metadata) in enumerate(sorted(value['tree'].items())):
        if metadata['kind'] == 'file':
            with (point / 'data' / str(number)).open('rb') as source:
                for chunk in iter(lambda: source.read(1048576), b''):
                    output.write(chunk)
    if verify(point, checksum) != value:
        raise RuntimeError('protected PostgreSQL point changed during transfer')
    if confirm_source is not None and confirm_source() is not True:
        raise RuntimeError('guarded PostgreSQL source changed before transfer commit')
    output.write(common.canonical({'commit': checksum}) + b'\n')
    output.flush()


def receive(source, point):
    """Reject partial streams and retain real recovery material on failure."""
    header = common.read_frame(source)
    if (set(header) != {'manifest_bytes', 'sha256'} or type(header['manifest_bytes']) is not int or
            not 0 < header['manifest_bytes'] < retained.available_memory() or
            not isinstance(header['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', header['sha256'])):
        raise RuntimeError('PostgreSQL point transfer header differs')
    encoded = source.read(header['manifest_bytes'])
    if len(encoded) != header['manifest_bytes'] or hashlib.sha256(encoded).hexdigest() != header['sha256']:
        raise RuntimeError('PostgreSQL point transfer manifest changed or truncated')
    value = validate(json.loads(encoded))
    require_directory(point.parent)
    retained.require_capacity(point.parent, value['tree'], 3)
    point.mkdir(mode=0o700)
    (point / 'data').mkdir(mode=0o700)
    for number, (_, record) in enumerate(sorted(value['tree'].items())):
        if record['kind'] != 'file':
            continue
        remaining, digest = record['bytes'], hashlib.sha256()
        with (point / 'data' / str(number)).open('xb') as target:
            os.fchmod(target.fileno(), 0o600)
            while remaining:
                chunk = source.read(min(1048576, remaining))
                if not chunk:
                    raise RuntimeError('PostgreSQL point transfer truncated; protected partial retained')
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            target.flush()
            os.fsync(target.fileno())
        if digest.hexdigest() != record['sha256']:
            raise RuntimeError('PostgreSQL point payload checksum differs; protected partial retained')
    if common.read_frame(source) != {'commit': header['sha256']} or source.read(1):
        raise RuntimeError('PostgreSQL point transfer commit or EOF differs')
    retained.files.write_json(point / 'verified.json', value)
    for directory in (point / 'data', point, point.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if verify(point, header['sha256']) != value:
        raise RuntimeError('received PostgreSQL point differs')
    return value, header['sha256']
