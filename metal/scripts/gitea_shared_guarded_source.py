"""Protect complete shared files only under the exact idle Gitea init guard.

Kubernetes ownership and exclusive PVC consumers are independently checked by
the prefetched coordinator. This native observer proves the claimed lock and
readonly CSI binding; recording a source descriptor alone never proves a hold.
"""

import fcntl
import json
from pathlib import Path
import re

import gitea_init_guard as application
import gitea_postgres_guarded_source as postgres


cold, common = postgres.cold, postgres.common
FORMAT = 'guarded-production-gitea-files-103-v1'
CLAIM_UID = '377a65f6-e88e-473e-9bfd-0c4045c15b7e'
PV_UID = '0d94e077-fecb-4bb8-b7b8-8ac43e45a269'
OWNER_UID = '478cb556-8f9e-45c0-9cd9-413c8a33ef3d'
STARTUP = ['/bin/bash', '-eu', '/maintenance-103/gitea-init.sh']
CONTROLLER = ['/bin/bash', '-ceu', application.CLAIM]


def validate_core(core):
    required = {'cluster_uid', 'namespace', 'pod', 'pod_uid', 'controller_uid', 'node',
                'container_id', 'image', 'claim', 'claim_uid', 'pv', 'pv_uid', 'revision'}
    try:
        if (set(core) != required or core['cluster_uid'] != common.CLUSTER_UID or
                core['namespace'] != 'gitea' or core['controller_uid'] != OWNER_UID or
                core['image'] != application.IMAGE or core['claim'] != 'gitea-shared-storage' or
                core['claim_uid'] != CLAIM_UID or core['pv'] != 'pvc-' + CLAIM_UID or core['pv_uid'] != PV_UID or
                not re.fullmatch('gitea-[a-z0-9]+-[a-z0-9]+', core['pod']) or
                not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', core['pod_uid']) or
                not re.fullmatch('[a-z][a-z0-9-]*', core['node']) or
                not re.fullmatch('[a-f0-9]{64}', core['container_id']) or
                not re.fullmatch('[a-f0-9]{40}', core['revision'])):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError('guarded Gitea shared-file source differs') from None
    return core


def validate_source(source):
    try:
        validate_core({k: v for k, v in source.items() if k not in {'volume', 'guard'}})
        volume, guard = source['volume'], source['guard']
        expected = '/var/lib/kubelet/pods/' + source['pod_uid'] + '/volumes/kubernetes.io~csi/' + source['pv'] + '/mount'
        if (set(volume) != {'source', 'device', 'inode'} or volume['source'] != expected or
                set(guard) != {'namespace_pid', 'host_pid', 'start_ticks', 'lock_device', 'lock_inode'} or
                any(type(v) is not int or v <= 0 for k, v in volume.items() if k != 'source') or
                any(type(v) is not int or v <= 0 for v in guard.values())):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        raise RuntimeError('guarded Gitea shared-file binding differs') from None
    return source


def validate(value):
    try:
        if (set(value) != {'format', 'source', 'control', 'tree'} or value['format'] != FORMAT or
                set(value['control']) != {'application_started'} or value['control']['application_started'] is not False):
            raise ValueError()
        validate_source(value['source'])
        cold.retained.validate_tree(value['tree'])
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        raise RuntimeError('guarded Gitea shared-file point differs') from None
    return value


def guard_tasks(tasks, main_pid, namespace_pid):
    holders = [(pid, item) for pid, item in tasks.items() if item[1:] == (namespace_pid, CONTROLLER)]
    waiters = [item for item in tasks.values() if item[2] == ['flock', '-x', '9']]
    if (len(tasks) != 3 or main_pid not in tasks or tasks[main_pid][1:] != (1, STARTUP) or
            len(holders) != 1 or len(waiters) != 1):
        raise RuntimeError('held Gitea initialization task set differs')
    return holders[0]


def observe(core, namespace_pid):
    validate_core(core)
    if type(namespace_pid) is not int or namespace_pid <= 1:
        raise RuntimeError('held Gitea controller PID differs')
    common.require_host(core['node'])
    cid = core['container_id']
    runtime = json.loads(common.command([*postgres.CRI, 'inspect', cid]).stdout)
    status, info = runtime['status'], runtime['info']
    if (status['id'] != cid or status['state'] != 'CONTAINER_RUNNING' or
            status['imageRef'] != application.IMAGE or status['metadata']['name'] != 'maintenance-103-init' or
            info['runtimeSpec']['process']['args'] != STARTUP or
            info['runtimeSpec']['process']['user'] != {'uid': 1000, 'gid': 1000, 'additionalGids': [1000]}):
        raise RuntimeError('held Gitea immutable initialization runtime differs')
    for name, expected in [('namespace', 'gitea'), ('name', core['pod']), ('uid', core['pod_uid'])]:
        if status['labels'].get('io.kubernetes.pod.' + name) != expected:
            raise RuntimeError('held Gitea initialization Pod binding differs')
    mounts = info['runtimeSpec']['mounts']
    data = [m for m in mounts if m['destination'] == '/data']
    temp = [m for m in mounts if m['destination'] == '/tmp']
    prefix = '/var/lib/kubelet/pods/' + core['pod_uid']
    expected_source = prefix + '/volumes/kubernetes.io~csi/' + core['pv'] + '/mount'
    if (len(data) != 1 or data[0]['source'] != expected_source or 'ro' not in data[0]['options'] or
            len(temp) != 1 or temp[0]['source'] != prefix + '/volumes/kubernetes.io~empty-dir/temp'):
        raise RuntimeError('held Gitea readonly CSI or temporary mount differs')
    root = Path(expected_source)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('held Gitea CSI ancestry differs')
    a, b = root.stat(), (Path('/proc') / str(info['pid']) / 'root/data').stat()
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        raise RuntimeError('held Gitea native CSI identity differs')
    guard = Path(temp[0]['source']) / 'maintenance-103-gitea'
    postgres.private(guard, directory=True, uid=1000)
    for name in ('lock', 'phase', 'claimed'):
        postgres.private(guard / name, uid=1000)
    if ((guard / 'phase').read_bytes() != b'waiting\n' or
            not re.fullmatch(rb'[0-9]+\n', (guard / 'claimed').read_bytes())):
        raise RuntimeError('held Gitea initialization is not an idle claimed window')
    raw = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode()
    pids = {int(line.split()[0]) for line in raw.splitlines()[1:] if line.strip()}
    tasks = {pid: postgres.process(pid, uid=1000) for pid in pids}
    if any(core['pod_uid'].replace('-', '_') not in item[0]['cgroup'] or cid not in item[0]['cgroup']
           for item in tasks.values()):
        raise RuntimeError('held Gitea task escaped its exact Pod/runtime cgroup')
    host_pid, holder = guard_tasks(tasks, info['pid'], namespace_pid)
    lock = (guard / 'lock').stat()
    descriptor = (Path('/proc') / str(host_pid) / 'fd/9').stat()
    if (lock.st_dev, lock.st_ino) != (descriptor.st_dev, descriptor.st_ino):
        raise RuntimeError('held Gitea native descriptor lost its lock binding')
    with (guard / 'lock').open('rb') as contender:
        try:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(contender, fcntl.LOCK_UN)
            raise RuntimeError('held Gitea initialization lock is not owned')
    binding = {**core, 'volume': {'source': str(root), 'device': a.st_dev, 'inode': a.st_ino},
               'guard': {'namespace_pid': namespace_pid, 'host_pid': host_pid,
                         'start_ticks': int(holder[0]['start_ticks']),
                         'lock_device': lock.st_dev, 'lock_inode': lock.st_ino}}
    return validate_source(binding)


def capture(core, namespace_pid, run_id):
    common.run_identifier(run_id)
    before = observe(core, namespace_pid)
    common.private_root()
    point = common.ROOT / ('gitea-shared-guarded-' + run_id)
    value, checksum = cold.capture(Path(before['volume']['source']), point, {'application_started': False},
                                   source_binding=before, validator=validate, source_format=FORMAT)
    if observe(core, namespace_pid) != before:
        raise RuntimeError('held Gitea source changed; protected point retained, not accepted')
    return {'point': str(point), 'manifest_sha256': checksum, 'source': value['source']}


def send(point, checksum, expected, output):
    value = cold.verify(point, checksum, validator=validate)
    if value['source'] != expected:
        raise RuntimeError('guarded Gitea shared-file transfer binding differs')
    core = {k: v for k, v in expected.items() if k not in {'volume', 'guard'}}
    check = lambda: observe(core, expected['guard']['namespace_pid']) == expected
    if not check():
        raise RuntimeError('guarded Gitea source changed before transfer')
    cold.send(point, checksum, output, confirm_source=check, validator=validate)
