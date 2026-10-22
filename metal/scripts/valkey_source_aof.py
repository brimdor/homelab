"""Copy the six actual multipart AOFs through an existing finite cohort lease.

Source files are read only. Protected original files never enter caller scratch.
Acceptance links every source to the RDB point from the same exclusion interval.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

import valkey_cohort_point as cohort

common = cohort.common
FORMAT = 'gitea-valkey-source-aof-103-v1'
MANIFEST = 'appendonly.aof.manifest'


def parse_manifest(raw):
    if len(raw) > 4096 or not raw.endswith(b'\n'):
        raise RuntimeError('source AOF manifest framing differs')
    names, kinds = [], []
    for line in raw.splitlines():
        match = re.fullmatch(rb'file (appendonly\.aof\.([1-9][0-9]*)\.(base\.rdb|incr\.aof)) seq ([1-9][0-9]*) type ([bi])', line)
        if (not match or match[2] != match[4] or
                (match[3], match[5]) not in ((b'base.rdb', b'b'), (b'incr.aof', b'i'))):
            raise RuntimeError('source AOF manifest entry differs')
        names.append(match[1].decode('ascii'))
        kinds.append(match[5])
    if len(names) != 2 or len(set(names)) != 2 or sorted(kinds) != [b'b', b'i']:
        raise RuntimeError('source AOF requires the observed single base/incremental pair')
    return set(names) | {MANIFEST}


def identity(meta):
    return (meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)


def source_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        first = os.fstat(stream.fileno())
        if (not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_size < 0 or
                (first.st_uid, first.st_gid) != (1001, 1001) or stat.S_IMODE(first.st_mode) not in (0o644, 0o664)):
            raise RuntimeError('source AOF file metadata differs')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
        last = os.fstat(stream.fileno())
    if identity(first) != identity(last) or identity(path.lstat()) != identity(first):
        raise RuntimeError('source AOF file changed during readonly hashing')
    return {'bytes': first.st_size, 'sha256': digest.hexdigest(), 'source_mode': stat.S_IMODE(first.st_mode)}, identity(first)


def source_directory(binding):
    root = Path(binding['volume']['source']) / 'appendonlydir'
    meta = root.lstat()
    if (not stat.S_ISDIR(meta.st_mode) or meta.st_nlink != 2 or
            (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) != (1001, 1001, 0o2775)):
        raise RuntimeError('source AOF directory metadata differs')
    descriptor = os.open(root / MANIFEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        meta_file = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta_file.st_mode) or meta_file.st_nlink != 1 or
                (meta_file.st_uid, meta_file.st_gid) != (1001, 1001) or
                stat.S_IMODE(meta_file.st_mode) not in (0o644, 0o664) or not 0 < meta_file.st_size <= 4096):
            raise RuntimeError('source AOF manifest metadata differs')
        names = parse_manifest(stream.read(4097))
    if {p.name for p in root.iterdir()} != names:
        raise RuntimeError('source AOF directory has an unexpected active file set')
    return root, names, identity(meta)


def send(core, output):
    binding = cohort.observe(core)
    root, names, directory_identity = source_directory(binding)
    records = {name: source_file(root / name) for name in sorted(names)}
    header = {'format': FORMAT, 'source': binding, 'files': {name: value[0] for name, value in records.items()}}
    encoded = common.canonical(header)
    output.write(encoded + b'\n')
    for name in sorted(names):
        descriptor = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
        digest, size = hashlib.sha256(), 0
        with os.fdopen(descriptor, 'rb') as stream:
            if identity(os.fstat(stream.fileno())) != records[name][1]:
                raise RuntimeError('source AOF identity changed before streaming')
            for block in iter(lambda: stream.read(1048576), b''):
                output.write(block)
                digest.update(block)
                size += len(block)
            if identity(os.fstat(stream.fileno())) != records[name][1]:
                raise RuntimeError('source AOF identity changed during streaming')
        if (size != records[name][0]['bytes'] or digest.hexdigest() != records[name][0]['sha256'] or
                source_file(root / name) != records[name]):
            raise RuntimeError('source AOF bytes changed during streaming')
    if ({name: source_file(root / name) for name in sorted(names)} != records or
            source_directory(binding) != (root, names, directory_identity) or cohort.observe(core) != binding):
        raise RuntimeError('source AOF lost exact native binding; no commit')
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def validate_header(header):
    try:
        cohort.validate_binding(header['source'])
        files = header['files']
        if (set(header) != {'format', 'source', 'files'} or header['format'] != FORMAT or
                not isinstance(files, dict) or len(files) != 3 or MANIFEST not in files):
            raise ValueError()
        for name, record in files.items():
            if (name != MANIFEST and not re.fullmatch(r'appendonly\.aof\.[1-9][0-9]*\.(base\.rdb|incr\.aof)', name)):
                raise ValueError()
            if (set(record) != {'bytes', 'sha256', 'source_mode'} or type(record['bytes']) is not int or
                    record['bytes'] < 0 or type(record['source_mode']) is not int or record['source_mode'] not in (0o644, 0o664) or
                    not re.fullmatch('[a-f0-9]{64}', record['sha256'])):
                raise ValueError()
            if (name == MANIFEST and not 0 < record['bytes'] <= 4096) or (name.endswith('.base.rdb') and record['bytes'] <= 9):
                raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('protected source AOF frame differs') from None
    return header


def point_path(run_id):
    common.require_host('pikachu')
    common.private_root()
    point = common.ROOT / ('valkey-source-aof-' + common.run_identifier(run_id))
    if any(p.is_symlink() for p in (point, *point.parents)):
        raise RuntimeError('protected source AOF ancestry differs')
    return point


def receive(run_id, expected, stream):
    cohort.validate_core(expected)
    point = point_path(run_id)
    if expected['ordinal'] == '0':
        point.mkdir(mode=0o700)
    cohort.directory(point)
    header = validate_header(common.read_frame(stream))
    if {k: header['source'][k] for k in cohort.CORE_KEYS} != expected:
        raise RuntimeError('source AOF sender differs from expected native source')
    if sum(v['bytes'] for v in header['files'].values()) > shutil.disk_usage(point).free:
        raise RuntimeError('insufficient actual protected source AOF capacity')
    directory = point / ('node-' + expected['ordinal'])
    directory.mkdir(mode=0o700)
    for name, record in sorted(header['files'].items()):
        remaining, digest = record['bytes'], hashlib.sha256()
        with (directory / name).open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            while remaining:
                block = stream.read(min(1048576, remaining))
                if not block:
                    raise RuntimeError('truncated source AOF; protected partial retained')
                output.write(block)
                digest.update(block)
                remaining -= len(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != record['sha256']:
            raise RuntimeError('source AOF checksum differs; protected partial retained')
    if (parse_manifest((directory / MANIFEST).read_bytes()) != set(header['files']) or
            common.read_frame(stream) != {'commit': hashlib.sha256(common.canonical(header)).hexdigest()} or stream.read(1)):
        raise RuntimeError('source AOF stream lacks exact manifest/final commit')
    cohort.recovery.protected.write_json(directory / 'source.json', header)
    return header


def validate(value):
    try:
        if (set(value) != {'format', 'run_id', 'rdb_manifest_sha256', 'nodes'} or value['format'] != FORMAT or
                set(value['nodes']) != set(cohort.CLAIMS) or
                not re.fullmatch('[a-f0-9]{64}', value['rdb_manifest_sha256'])):
            raise ValueError()
        _point, rdb = cohort.verify(value['run_id'], value['rdb_manifest_sha256'])
        for ordinal, header in value['nodes'].items():
            validate_header(header)
            if header['source'] != rdb['sources'][ordinal]:
                raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('source AOF cohort differs from its same-interval RDB point') from None
    return value


def verify(run_id, checksum):
    point = point_path(run_id)
    cohort.directory(point)
    if {p.name for p in point.iterdir()} != {'verified.json'} | {'node-' + n for n in cohort.CLAIMS}:
        raise RuntimeError('protected source AOF point file set differs')
    record = common.source_record('verified.json', point / 'verified.json')[0]
    if record['sha256'] != checksum:
        raise RuntimeError('protected source AOF manifest checksum differs')
    value = validate(json.loads((point / 'verified.json').read_bytes()))
    if value['run_id'] != run_id or hashlib.sha256(common.canonical(value)).hexdigest() != checksum:
        raise RuntimeError('protected source AOF manifest encoding differs')
    for ordinal, header in value['nodes'].items():
        directory = point / ('node-' + ordinal)
        cohort.directory(directory)
        if {p.name for p in directory.iterdir()} != set(header['files']) | {'source.json'}:
            raise RuntimeError('protected native AOF file set differs')
        common.source_record('source.json', directory / 'source.json')
        if json.loads((directory / 'source.json').read_bytes()) != header:
            raise RuntimeError('protected native AOF header differs')
        for name, expected in header['files'].items():
            if cohort.recovery.protected.protected_file(directory / name).st_nlink != 1:
                raise RuntimeError('protected native AOF acquired another link')
            if cohort.recovery.protected.file_digest(directory / name) != {k: expected[k] for k in ('bytes', 'sha256')}:
                raise RuntimeError('protected native AOF original changed')
        if parse_manifest((directory / MANIFEST).read_bytes()) != set(header['files']):
            raise RuntimeError('protected native AOF manifest membership differs')
    return point, value


def finalize(run_id, rdb_manifest_sha256, nodes):
    value = validate({'format': FORMAT, 'run_id': run_id, 'rdb_manifest_sha256': rdb_manifest_sha256, 'nodes': nodes})
    point = point_path(run_id)
    cohort.directory(point)
    cohort.recovery.protected.write_json(point / 'verified.json', value)
    checksum = hashlib.sha256(common.canonical(value)).hexdigest()
    verify(run_id, checksum)
    return {'point': str(point), 'run_id': run_id, 'manifest_sha256': checksum,
            'rdb_manifest_sha256': rdb_manifest_sha256, 'six_actual_source_aofs': True}
