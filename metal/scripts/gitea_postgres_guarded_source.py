"""Capture only the exact cold Gitea CSI volume while its native guard owns startup.

The prefetched caller separately verifies Kubernetes owners, all application
writers stopped, and the applied canonical revision. This module never runs SQL.
"""

import fcntl
import hashlib
import json
from pathlib import Path
import re
import stat

import gitea_postgres_cold_point as cold
import gitea_postgres_startup_guard as startup
from maintenance_actor_hold import exclusive_file


common = cold.common
recovery = startup.recovery
CRI = ['/usr/local/bin/k3s', 'crictl', '--runtime-endpoint',
       'unix:///run/k3s/containerd/containerd.sock']
CONTROLLER = ['/bin/bash', '-ceu', startup.CLAIM, 'maintenance-103-controller',
              '/bin/bash', '-ceu', recovery.SINGLE_WRAPPER, 'maintenance-103-single',
              recovery.BIN + 'postgres', '--single', '-D', recovery.DATA,
              *recovery.OPTIONS, 'postgres']
STARTUP = ['/bin/bash', '-eu', '/maintenance-103/startup.sh',
           '/opt/bitnami/scripts/postgresql/entrypoint.sh', '/opt/bitnami/scripts/postgresql/run.sh']
READINESS = ['pg_isready', '-U', 'gitea', '-d', 'dbname=gitea', '-h', '127.0.0.1', '-p', '5432']
READINESS_SHELL = ['/bin/sh', '-c', '-e',
                   'exec pg_isready -U "gitea" -d "dbname=gitea" -h 127.0.0.1 -p 5432\n'
                   '[ -f /opt/bitnami/postgresql/tmp/.initialized ] || [ -f /bitnami/postgresql/.initialized ]\n']


def guard_tasks(tasks, main_pid, namespace_pid):
    # Readiness remains enabled: admit only its exact existing read-only command.
    idle = {pid: item for pid, item in tasks.items()
            if item[2] not in (READINESS, [recovery.BIN + 'pg_isready', *READINESS[1:]], READINESS_SHELL)}
    if len(idle) != 3 or main_pid not in idle or idle[main_pid][1:] != (1, STARTUP):
        raise RuntimeError('held PostgreSQL startup task set differs')
    holders = [(pid, item) for pid, item in idle.items() if item[1] == namespace_pid and item[2] == CONTROLLER]
    waiters = [item for item in idle.values() if item[2] == ['flock', '--exclusive', '9']]
    if len(holders) != 1 or len(waiters) != 1:
        raise RuntimeError('held PostgreSQL controller or blocked ordinary startup missing')
    return holders[0]


def private(path, directory=False):
    value = path.lstat()
    if (any(p.is_symlink() for p in (path, *path.parents)) or value.st_uid != 1001 or
            stat.S_IMODE(value.st_mode) != (0o700 if directory else 0o600) or
            not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)) or
            (not directory and value.st_nlink != 1)):
        raise RuntimeError('held PostgreSQL guard ownership or mode differs')
    return value


def process(pid):
    root = Path('/proc') / str(pid)
    identity = cold.retained.process.process_identity(pid)
    status = dict(line.split(':', 1) for line in (root / 'status').read_text().splitlines() if ':' in line)
    namespace = [int(v) for v in status['NSpid'].split()]
    if (root.stat().st_uid != 1001 or not namespace or namespace[0] != pid or
            set(int(v) for v in status['Uid'].split()) != {1001}):
        raise RuntimeError('held PostgreSQL process identity differs')
    command = (root / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    return identity, namespace[-1], [v.decode() for v in command]


def parse_sync_control(raw):
    # The installed crictl ExecSync printer adds two newlines to native stdout.
    if not raw.endswith(b'\n\n\n'):
        raise RuntimeError('native CRI synchronous output framing differs')
    return cold.control.parse_control(raw[:-2])


def observe(core, namespace_pid):
    """Return a binding only when all native tasks are the reviewed idle guard."""
    if (not isinstance(core, dict) or core.get('namespace') != 'gitea' or
            core.get('pod') != 'gitea-postgresql-0' or core.get('image') != cold.control.IMAGE or
            core.get('pv') != 'pvc-4d6d356d-ec5d-4f2e-961e-090eae9e0c21' or
            not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', core.get('pod_uid', '')) or
            not re.fullmatch('[a-f0-9]{64}', core.get('container_id', '')) or
            type(namespace_pid) is not int or namespace_pid <= 1):
        raise RuntimeError('unreviewed held PostgreSQL runtime request')
    common.require_host(core['node'])
    cid = core['container_id']
    value = json.loads(common.command([*CRI, 'inspect', cid]).stdout)
    status, info = value['status'], value['info']
    if (status['id'] != cid or status['state'] != 'CONTAINER_RUNNING' or
            status['imageRef'] != cold.control.IMAGE or status['metadata']['name'] != 'postgresql' or
            info['runtimeSpec']['process']['args'] != STARTUP or
            info['runtimeSpec']['process']['user'] != {'uid': 1001, 'gid': 1001, 'additionalGids': [1001]}):
        raise RuntimeError('held PostgreSQL immutable runtime differs')
    labels = status['labels']
    for name, expected in [('namespace', 'gitea'), ('name', core['pod']), ('uid', core['pod_uid'])]:
        if labels.get('io.kubernetes.pod.' + name) != expected:
            raise RuntimeError('held PostgreSQL runtime Pod binding differs')
    mounts = info['runtimeSpec']['mounts']
    data_mount = [m for m in mounts if m['destination'] == '/bitnami/postgresql']
    temp_mount = [m for m in mounts if m['destination'] == '/opt/bitnami/postgresql/tmp']
    expected_source = '/var/lib/kubelet/pods/' + core['pod_uid'] + '/volumes/kubernetes.io~csi/' + core['pv'] + '/mount'
    if (len(data_mount) != 1 or data_mount[0]['source'] != expected_source or
            len(temp_mount) != 1 or not temp_mount[0]['source'].startswith(
                '/var/lib/kubelet/pods/' + core['pod_uid'] + '/volume-subpaths/empty-dir/postgresql/')):
        raise RuntimeError('held PostgreSQL CSI or runtime mount differs')
    root = Path(expected_source)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('held PostgreSQL CSI ancestry differs')
    mounted = Path('/proc') / str(info['pid']) / 'root/bitnami/postgresql'
    a, b = root.stat(), mounted.stat()
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino) or (root / 'data/postmaster.pid').exists():
        raise RuntimeError('held PostgreSQL volume differs or postmaster exists')
    guard = Path(temp_mount[0]['source']) / 'maintenance-103'
    private(guard, directory=True)
    for name in ('lock', 'phase', 'claimed'):
        private(guard / name)
    if ((guard / 'phase').read_bytes() != b'waiting\n' or (guard / 'native-child').exists() or
            not re.fullmatch(rb'[0-9]+\n', (guard / 'claimed').read_bytes())):
        raise RuntimeError('held PostgreSQL window is not an idle claimed startup')
    raw = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode()
    pids = {int(line.split()[0]) for line in raw.splitlines()[1:] if line.strip()}
    tasks = {pid: process(pid) for pid in pids}
    if any(core['pod_uid'].replace('-', '_') not in item[0]['cgroup'] or cid not in item[0]['cgroup']
           for item in tasks.values()):
        raise RuntimeError('held PostgreSQL task escaped the exact Pod/runtime cgroup')
    host_pid, holder = guard_tasks(tasks, info['pid'], namespace_pid)
    lock = (guard / 'lock').stat()
    descriptor = (Path('/proc') / str(host_pid) / 'fd/9').stat()
    if (lock.st_dev, lock.st_ino) != (descriptor.st_dev, descriptor.st_ino):
        raise RuntimeError('held PostgreSQL native descriptor lost its lock binding')
    with (guard / 'lock').open('rb') as contender:
        try:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(contender, fcntl.LOCK_UN)
            raise RuntimeError('held PostgreSQL startup lock is not owned')
    binding = cold.validate_source({**core,
        'volume': {'source': str(root), 'device': a.st_dev, 'inode': a.st_ino},
        'guard': {'namespace_pid': namespace_pid, 'host_pid': host_pid,
                  'start_ticks': int(holder[0]['start_ticks']),
                  'lock_device': lock.st_dev, 'lock_inode': lock.st_ino}})
    state = parse_sync_control(common.command(
        [*CRI, 'exec', '--sync', cid, '/usr/bin/env', 'LC_ALL=C', cold.control.ENTRY, recovery.DATA]).stdout)
    if state['cluster_state'] != 'shut down':
        raise RuntimeError('held PostgreSQL data is not cleanly shut down')
    return binding, state


def capture(core, namespace_pid, run_id):
    common.run_identifier(run_id)
    before, state = observe(core, namespace_pid)
    common.private_root()
    point = common.ROOT / ('gitea-postgres-guarded-' + run_id)
    value, checksum = cold.capture(Path(before['volume']['source']), point, state, source_binding=before)
    if observe(core, namespace_pid) != (before, state):
        raise RuntimeError('held PostgreSQL source changed; protected point retained, not accepted')
    return {'point': str(point), 'manifest_sha256': checksum, 'source': value['source'], 'control': state}


def send(point, checksum, expected, output):
    value = cold.verify(point, checksum)
    if value['format'] != cold.GUARDED_FORMAT or value['source'] != expected:
        raise RuntimeError('guarded PostgreSQL transfer point binding differs')
    core = {k: v for k, v in expected.items() if k not in {'volume', 'guard'}}
    check = lambda: observe(core, expected['guard']['namespace_pid']) == (expected, value['control'])
    if not check():
        raise RuntimeError('guarded PostgreSQL source changed before transfer')
    cold.send(point, checksum, output, confirm_source=check)


def intent(point, checksum, expected, catalog_sha256, secret_uid, application_uid):
    """Exclusive durable task intent: an uncertain native child is never replayed."""
    common.require_host('pikachu')
    common.private_root()
    value = cold.verify(point, checksum)
    if (value['format'] != cold.GUARDED_FORMAT or value['source'] != expected or
            not re.fullmatch('[a-f0-9]{64}', catalog_sha256) or
            any(not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uid)
                for uid in (secret_uid, application_uid))):
        raise RuntimeError('production role intent binding differs')
    record = {'version': 1, 'task': 'maintenance-103-existing-postgres-role-only',
              'source': expected, 'point_sha256': checksum, 'catalog_sha256': catalog_sha256,
              'credential_secret_uid': secret_uid, 'held_application_pod_uid': application_uid}
    raw = common.canonical(record)
    exclusive_file(common.ROOT / 'gitea-postgres-role-103-intent.json', raw, 0o600)
    return {'intent_sha256': hashlib.sha256(raw).hexdigest(), 'exclusive_creation': True}
