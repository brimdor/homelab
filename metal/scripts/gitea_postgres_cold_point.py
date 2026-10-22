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


def validate(value):
    try:
        if (set(value) != {'format', 'original_manifest_sha256', 'control', 'tree'} or
                value['format'] != FORMAT or value['original_manifest_sha256'] != control.CHECKSUM or
                value['control']['cluster_state'] != 'shut down' or
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


def capture(source, point, state):
    """Caller must first prove the exact source is its owned clean stopped copy."""
    if (any(p.is_symlink() for p in (source, *source.parents, point.parent, *point.parent.parents)) or
            not source.is_dir() or point.exists() or source == point or source in point.parents or
            point in source.parents):
        raise RuntimeError('clean PostgreSQL copy-point source or destination differs')
    tree, payloads = retained.snapshot(source)
    value = validate({'format': FORMAT, 'original_manifest_sha256': control.CHECKSUM,
                      'control': state, 'tree': tree})
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
