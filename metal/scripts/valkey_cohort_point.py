"""Stream native RDBs into a distinct protected, finite-write-exclusion point.

The coordinator owns the six finite WRITE leases and blocked no-op probes.
This observer independently binds the native process and exact Ceph CSI root.
Historical snapshot formats and their non-quiesced provenance remain unchanged.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import base64
import shutil
import stat

import gitea_postgres_guarded_source as native
import valkey_recovery as recovery


common = recovery.common
FORMAT = 'gitea-valkey-write-excluded-103-v1'
CLAIMS = {**recovery.CLAIMS,
          '1': ('ff537397-6401-45d3-9804-f4137b4ccb6f', '760fad77-cc28-4c0e-b18e-d2c2647af752'),
          '2': ('a12c9162-cd13-4d13-8c7a-cda2061a8d4b', 'ce5bca1f-9975-45c1-acc3-a693069db6bf'),
          '4': ('256eb525-52a4-4124-acf4-52c180a75483', '7bf3bcd9-c070-454e-bda8-8e9bfe80c232')}
REPLICAS = {'1': '5', '2': '3', '4': '0'}
SLOTS = {'0': [0, 5460], '3': [10923, 16383], '5': [5461, 10922]}
LEASE_MS = 60000
CORE_KEYS = {'ordinal', 'cluster_uid', 'namespace', 'pod', 'pod_uid', 'controller_uid', 'node',
             'container_id', 'image', 'claim', 'claim_uid', 'pv', 'pv_uid', 'revision'}


def validate_core(value):
    try:
        ordinal = value['ordinal']
        claim, pv = CLAIMS[ordinal]
        if (set(value) != CORE_KEYS or value['cluster_uid'] != common.CLUSTER_UID or
                value['namespace'] != 'gitea' or value['controller_uid'] != recovery.OWNER or
                value['image'] != recovery.IMAGE or value['pod'] != 'gitea-valkey-cluster-' + ordinal or
                value['claim'] != 'valkey-data-' + value['pod'] or value['claim_uid'] != claim or
                value['pv'] != 'pvc-' + claim or value['pv_uid'] != pv or
                not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', value['pod_uid']) or
                not re.fullmatch('[a-f0-9]{64}', value['container_id']) or
                not re.fullmatch('[a-f0-9]{40}', value['revision']) or
                not re.fullmatch('[a-z][a-z0-9-]*', value['node'])):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('native Valkey cohort source differs') from None
    return value


def validate_binding(value):
    try:
        validate_core({k: value[k] for k in CORE_KEYS})
        volume, process = value['volume'], value['process']
        expected = '/var/lib/kubelet/pods/' + value['pod_uid'] + '/volumes/kubernetes.io~csi/' + value['pv'] + '/mount'
        if (set(value) != CORE_KEYS | {'volume', 'process'} or
                set(volume) != {'source', 'device', 'inode'} or volume['source'] != expected or
                set(process) != {'host_pid', 'start_ticks'} or
                any(type(v) is not int or v <= 0 for k, v in volume.items() if k != 'source') or
                any(type(v) is not int or v <= 0 for v in process.values())):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('native Valkey cohort binding differs') from None
    return value


def observe(core):
    validate_core(core)
    common.require_host(core['node'])
    cid = core['container_id']
    runtime = json.loads(common.command([*native.CRI, 'inspect', cid]).stdout)
    status, info = runtime['status'], runtime['info']
    if (status['id'] != cid or status['state'] != 'CONTAINER_RUNNING' or
            status['imageRef'] != recovery.IMAGE or status['metadata']['name'] != 'gitea-valkey-cluster' or
            info['runtimeSpec']['process']['user'] != {'uid': 1001, 'gid': 1001, 'additionalGids': [1001]}):
        raise RuntimeError('native Valkey cohort immutable runtime differs')
    for name, expected in [('namespace', 'gitea'), ('name', core['pod']), ('uid', core['pod_uid'])]:
        if status['labels'].get('io.kubernetes.pod.' + name) != expected:
            raise RuntimeError('native Valkey cohort Pod label differs')
    mounts = [m for m in info['runtimeSpec']['mounts'] if m['destination'] == '/bitnami/valkey/data']
    expected = '/var/lib/kubelet/pods/' + core['pod_uid'] + '/volumes/kubernetes.io~csi/' + core['pv'] + '/mount'
    if len(mounts) != 1 or mounts[0]['source'] != expected or 'rw' not in mounts[0]['options']:
        raise RuntimeError('native Valkey cohort CSI mount differs')
    root, pid = Path(expected), info['pid']
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('native Valkey cohort CSI ancestry differs')
    first, second = root.stat(), (Path('/proc') / str(pid) / 'root/bitnami/valkey/data').stat()
    process, namespace_pid, _command = native.process(pid)
    if ((first.st_dev, first.st_ino) != (second.st_dev, second.st_ino) or namespace_pid != 1 or
            core['pod_uid'].replace('-', '_') not in process['cgroup'] or cid not in process['cgroup'] or
            (Path('/proc') / str(pid) / 'comm').read_text() != 'valkey-server\n'):
        raise RuntimeError('native Valkey cohort process or CSI identity differs')
    return validate_binding({**core, 'volume': {'source': str(root), 'device': first.st_dev, 'inode': first.st_ino},
                             'process': {'host_pid': pid, 'start_ticks': int(process['start_ticks'])}})


def probe(core, observer):
    """Prove a native write-flagged no-op is queued, without changing any key."""
    binding = observe(core)
    program = '''import base64,select,socket,types
v=types.ModuleType('private_resp');exec(base64.b64decode(OBSERVER),v.__dict__)
with socket.create_connection(('127.0.0.1',6379),timeout=75) as connection:
 with connection.makefile('rb') as stream:
  connection.sendall(v.request('PING'))
  if v.response(stream)!=b'PONG':raise RuntimeError('native probe read acknowledgement differs')
  connection.sendall(v.request('EVAL','return 1',0))
  if select.select([connection],[],[],0.2)[0]:raise RuntimeError('native probe write was not excluded')
  print('HOMELAB103:WRITE-BLOCKED',flush=True)
  if v.response(stream)!=1:raise RuntimeError('native probe release differs')
  print('HOMELAB103:WRITE-RELEASED',flush=True)
'''.replace('OBSERVER', repr(base64.b64encode(observer).decode()))
    os.execvp('nsenter', ['nsenter', '--target', str(binding['process']['host_pid']), '--net', '--',
                         'python3', '-I', '-B', '-c', program])


def source_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        first = os.fstat(stream.fileno())
        if (not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_size <= 9 or
                (first.st_uid, first.st_gid, stat.S_IMODE(first.st_mode)) != (1001, 1001, 0o644)):
            raise RuntimeError('native Valkey source RDB metadata differs')
        if not re.fullmatch(rb'REDIS\d{4}', stream.read(9)):
            raise RuntimeError('native Valkey source RDB header differs')
        stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
        last = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(first) != identity(last) or identity(path.lstat()) != identity(first):
        raise RuntimeError('native Valkey source RDB changed during hashing')
    return {'bytes': first.st_size, 'sha256': digest.hexdigest()}, identity(first)


def send(core, output):
    binding = observe(core)
    if core['ordinal'] not in SLOTS:
        raise RuntimeError('only reviewed primary RDBs may be streamed')
    path = Path(binding['volume']['source']) / 'dump.rdb'
    record = source_file(path)
    header = {'format': FORMAT, 'source': binding, 'file': record[0]}
    encoded = common.canonical(header)
    output.write(encoded + b'\n')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest, size = hashlib.sha256(), 0
    with os.fdopen(descriptor, 'rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            output.write(block)
            digest.update(block)
            size += len(block)
    if ({'bytes': size, 'sha256': digest.hexdigest()} != record[0] or
            source_file(path) != record or observe(core) != binding):
        raise RuntimeError('native Valkey RDB stream lost source binding; no commit')
    output.write(common.canonical({'commit': hashlib.sha256(encoded).hexdigest()}) + b'\n')
    output.flush()


def point_path(run_id):
    common.require_host('pikachu')
    common.private_root()
    point = common.ROOT / ('valkey-cohort-' + common.run_identifier(run_id))
    if any(p.is_symlink() for p in (point, *point.parents)):
        raise RuntimeError('Valkey cohort protected ancestry differs')
    return point


def directory(point):
    meta = point.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o700:
        raise RuntimeError('Valkey cohort destination is not protected')


def validate_header(header):
    try:
        validate_binding(header['source'])
        record = header['file']
        if (set(header) != {'format', 'source', 'file'} or header['format'] != FORMAT or
                header['source']['ordinal'] not in SLOTS or set(record) != {'bytes', 'sha256'} or
                type(record['bytes']) is not int or record['bytes'] <= 9 or
                not re.fullmatch('[a-f0-9]{64}', record['sha256'])):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('Valkey cohort frame differs') from None
    return header


def receive(run_id, expected, stream):
    validate_core(expected)
    point = point_path(run_id)
    ordinal = expected['ordinal']
    if ordinal == '0':
        point.mkdir(mode=0o700)
    directory(point)
    header = validate_header(common.read_frame(stream))
    if {k: header['source'][k] for k in CORE_KEYS} != expected:
        raise RuntimeError('Valkey cohort sender differs from expected source')
    record = header['file']
    if record['bytes'] > shutil.disk_usage(point).free:
        raise RuntimeError('insufficient actual capacity for protected Valkey RDB')
    path = point / ('shard-' + ordinal + '.rdb')
    digest, remaining = hashlib.sha256(), record['bytes']
    with path.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        while remaining:
            block = stream.read(min(1048576, remaining))
            if not block:
                raise RuntimeError('truncated Valkey cohort stream; protected partial retained')
            output.write(block)
            digest.update(block)
            remaining -= len(block)
        output.flush()
        os.fsync(output.fileno())
    if (digest.hexdigest() != record['sha256'] or
            common.read_frame(stream) != {'commit': hashlib.sha256(common.canonical(header)).hexdigest()} or stream.read(1)):
        raise RuntimeError('Valkey cohort stream lacks exact final commit; protected partial retained')
    recovery.protected.write_json(point / ('source-' + ordinal + '.json'), header)
    return header


def validate(manifest):
    try:
        if (set(manifest) != {'format', 'cluster_uid', 'owner_uid', 'image', 'sources', 'shards', 'replicas',
                             'slots', 'write_exclusion', 'source_quiesced', 'cross_shard_atomic', 'topology_sha256'} or
                manifest['format'] != FORMAT or manifest['cluster_uid'] != common.CLUSTER_UID or
                manifest['owner_uid'] != recovery.OWNER or manifest['image'] != recovery.IMAGE or
                manifest['replicas'] != REPLICAS or manifest['slots'] != SLOTS or
                manifest['source_quiesced'] is not True or manifest['cross_shard_atomic'] is not False or
                not re.fullmatch('[a-f0-9]{64}', manifest['topology_sha256']) or
                set(manifest['sources']) != set(CLAIMS) or set(manifest['shards']) != set(SLOTS)):
            raise ValueError()
        exclusion = manifest['write_exclusion']
        if (set(exclusion) != {'lease_ms', 'elapsed_ms', 'all_six_probes_blocked'} or
                type(exclusion['lease_ms']) is not int or exclusion['lease_ms'] != LEASE_MS or
                type(exclusion['elapsed_ms']) is not int or not 0 < exclusion['elapsed_ms'] < LEASE_MS or
                exclusion['all_six_probes_blocked'] is not True):
            raise ValueError()
        for ordinal, binding in manifest['sources'].items():
            validate_binding(binding)
            if binding['ordinal'] != ordinal:
                raise ValueError()
        if (len({v['revision'] for v in manifest['sources'].values()}) != 1 or
                len({v['pod_uid'] for v in manifest['sources'].values()}) != 6 or
                len({v['container_id'] for v in manifest['sources'].values()}) != 6):
            raise ValueError()
        for ordinal, header in manifest['shards'].items():
            validate_header(header)
            if header['source'] != manifest['sources'][ordinal]:
                raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError('Valkey write-excluded point contract differs') from None
    return manifest


def verify(run_id, checksum):
    point = point_path(run_id)
    directory(point)
    if {p.name for p in point.iterdir()} != {'verified.json'} | {
            prefix + ordinal + suffix for ordinal in SLOTS for prefix, suffix in (('shard-', '.rdb'), ('source-', '.json'))}:
        raise RuntimeError('Valkey cohort protected file set differs')
    raw = common.source_record('verified.json', point / 'verified.json')[0]
    if raw['sha256'] != checksum:
        raise RuntimeError('Valkey cohort protected manifest hash differs')
    value = validate(json.loads((point / 'verified.json').read_bytes()))
    if hashlib.sha256(common.canonical(value)).hexdigest() != checksum:
        raise RuntimeError('Valkey cohort manifest encoding differs')
    for ordinal, header in value['shards'].items():
        source = point / ('source-' + ordinal + '.json')
        common.source_record(source.name, source)
        if (json.loads(source.read_bytes()) != header or
                recovery.protected.file_digest(point / ('shard-' + ordinal + '.rdb')) != header['file']):
            raise RuntimeError('Valkey cohort protected material changed')
    return point, value


def finalize(run_id, manifest):
    validate(manifest)
    point = point_path(run_id)
    directory(point)
    for ordinal, header in manifest['shards'].items():
        source = point / ('source-' + ordinal + '.json')
        common.source_record(source.name, source)
        if (json.loads(source.read_bytes()) != header or
                recovery.protected.file_digest(point / ('shard-' + ordinal + '.rdb')) != header['file']):
            raise RuntimeError('Valkey cohort received material differs')
    recovery.protected.write_json(point / 'verified.json', manifest)
    checksum = hashlib.sha256(common.canonical(manifest)).hexdigest()
    verify(run_id, checksum)
    return {'point': str(point), 'run_id': run_id, 'manifest_sha256': checksum,
            'source_quiesced': True, 'cross_shard_atomic': False}
