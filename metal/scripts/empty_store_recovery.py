"""Recover reviewed empty Ceph stores; never repair source data."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

import etcd_recovery as common
import prometheus_recovery as process
import grafana_recovery as files
import sporecast_recovery as transfer


PROFILES = globals().get('PROFILE_DATA') or json.loads(
    Path(__file__).parents[1].joinpath('maintenance/empty-stores-103.json').read_text())


def shared_consumers(namespace, pods, jobs, cronjobs):
    """Require suspended exact schedulers and prove every historical writer exited."""
    profile = PROFILES[namespace]
    expected = profile['required_suspended_cronjobs']
    if {c['metadata']['name'] for c in cronjobs} != set(expected):
        raise RuntimeError('shared-store scheduler set changed')
    for cron in cronjobs:
        record = expected[cron['metadata']['name']]
        spec = dict(cron['spec'])
        if (cron['metadata']['uid'] != record['uid'] or cron['metadata'].get('deletionTimestamp') or
                spec.get('suspend') is not True or cron.get('status', {}).get('active')):
            raise RuntimeError('shared-store scheduler is not held')
        spec['suspend'] = False
        if hashlib.sha256(common.canonical(spec)).hexdigest() != record['spec_sha256']:
            raise RuntimeError('shared-store scheduler configuration changed')
    uses = lambda spec: any(v.get('persistentVolumeClaim', {}).get('claimName') == profile['claim']
                            for v in spec.get('volumes', []))
    complete = {}
    for job in jobs:
        if not uses(job['spec']['template']['spec']):
            continue
        meta, status = job['metadata'], job.get('status', {})
        owners = [o for o in meta.get('ownerReferences', []) if o.get('controller') is True]
        if (not meta.get('uid') or meta.get('deletionTimestamp') or len(owners) != 1 or
                owners[0].get('kind') != 'CronJob' or owners[0].get('apiVersion') != 'batch/v1' or
                owners[0].get('name') not in expected or
                owners[0].get('uid') != expected[owners[0]['name']]['uid'] or
                status.get('active', 0) or status.get('terminating', 0) or status.get('failed', 0) or
                status.get('succeeded', 0) < 1 or
                not any(c.get('type') == 'Complete' and c.get('status') == 'True' for c in status.get('conditions', [])) or
                any(c.get('type') in ('Failed', 'FailureTarget') and c.get('status') == 'True' for c in status.get('conditions', []))):
            raise RuntimeError('shared-store Job is not proven complete')
        complete[meta['uid']] = meta['name']
    found = []
    for pod in pods:
        if not uses(pod['spec']):
            continue
        meta, status = pod['metadata'], pod['status']
        if meta.get('deletionTimestamp') or not meta.get('uid'):
            raise RuntimeError('shared-store consumer is deleting or unidentified')
        if meta['uid'] == profile['pod_uid']:
            if status.get('phase') != 'Running' or not status.get('containerStatuses') or not all(
                    c.get('ready') is True for c in status['containerStatuses']):
                raise RuntimeError('shared-store web consumer is not ready')
        else:
            owners = [o for o in meta.get('ownerReferences', []) if o.get('controller') is True]
            containers = status.get('containerStatuses', [])
            if (len(owners) != 1 or owners[0].get('kind') != 'Job' or owners[0].get('apiVersion') != 'batch/v1' or
                    not owners[0].get('uid') or complete.get(owners[0]['uid']) != owners[0].get('name') or
                    status.get('phase') != 'Succeeded' or pod['spec'].get('restartPolicy') not in ('Never', 'OnFailure') or
                    not containers or {c['name'] for c in containers} != {c['name'] for c in pod['spec']['containers']} or
                    any(c.get('state', {}).get('terminated', {}).get('exitCode') != 0 for c in containers)):
                raise RuntimeError('shared-store Pod completion is unproven')
        initial = status.get('initContainerStatuses', [])
        if ({c['name'] for c in initial} != {c['name'] for c in pod['spec'].get('initContainers', [])} or
                any(c.get('state', {}).get('terminated', {}).get('exitCode') != 0 for c in initial)):
            raise RuntimeError('shared-store init completion is unproven')
        found.append(meta['uid'])
    if profile['pod_uid'] not in found or len(found) != len(set(found)):
        raise RuntimeError('shared-store web consumer missing or duplicated')
    return sorted(found)


def metadata(path):
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode):
        raise RuntimeError('empty store has a file, symlink or special entry')
    return {'mode': stat.S_IMODE(value.st_mode), 'uid': value.st_uid, 'gid': value.st_gid,
            'mtime_ns': value.st_mtime_ns,
            'xattrs': {name: os.getxattr(path, name, follow_symlinks=False).hex()
                       for name in sorted(os.listxattr(path, follow_symlinks=False))}}


def tree(root):
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('unsafe empty-store ancestry')
    result = {'': metadata(root)}
    device = root.stat().st_dev
    for parent, directories, names in os.walk(root, followlinks=False):
        if names:
            raise RuntimeError('store is no longer empty')
        for name in directories:
            path = Path(parent) / name
            if path.lstat().st_dev != device:
                raise RuntimeError('empty store crosses a device')
            result[str(path.relative_to(root))] = metadata(path)
    return dict(sorted(result.items()))


def source_identity(namespace):
    p = PROFILES[namespace]
    common.require_host(p['node'])
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', p['container_id']]).stdout)
    status, info = runtime['status'], runtime['info']
    labels, spec = status['labels'], info['runtimeSpec']
    if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'] != p['image_ref'] or info['pid'] != p['pid'] or
            labels.get('io.kubernetes.pod.uid') != p['pod_uid'] or labels.get('io.kubernetes.pod.namespace') != namespace or
            labels.get('io.kubernetes.container.name') != p['container'] or spec['process']['user'] != p['process_user']):
        raise RuntimeError('reviewed empty-store runtime changed')
    tasks = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', p['container_id']]).stdout.decode()
    if [line.split()[0] for line in tasks.splitlines()[1:] if line.strip()] != [str(p['pid'])] or len(p['tasks']) != 1:
        raise RuntimeError('empty store has an unreviewed writer process')
    identity = process.process_identity(p['pid'])
    expected = p['tasks'][str(p['pid'])]
    if ({k: identity[k] for k in ('exe', 'start_ticks', 'cgroup')} != {k: expected[k] for k in ('exe', 'start_ticks', 'cgroup')} or
            (Path('/proc') / str(p['pid'])).stat().st_uid != expected['uid']):
        raise RuntimeError('empty-store process identity changed')
    volume = p['volumes'][0]
    path = Path(volume['source'])
    root = Path('/proc') / str(p['pid']) / 'root' / volume['destination'].lstrip('/')
    if any(q.is_symlink() for q in (path, *path.parents)):
        raise RuntimeError('unsafe empty-store CSI ancestry')
    mounts = [m for m in spec['mounts'] if m['destination'] == volume['destination']]
    a, b = path.stat(), root.stat()
    if (len(mounts) != 1 or mounts[0]['source'] != str(path) or
            (a.st_dev, a.st_ino) != (volume['device'], volume['inode']) or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
        raise RuntimeError('empty-store CSI identity changed')
    return identity


def validate(value, namespace):
    if (not isinstance(value, dict) or set(value) != {'format', 'cluster_uid', 'profile', 'directories', 'pause', 'resumed'} or
            type(value['format']) is not int or value['format'] != 1 or value['cluster_uid'] != common.CLUSTER_UID or
            value['profile'] != PROFILES[namespace] or value['resumed'] is not True or
            not isinstance(value['pause'], dict) or set(value['pause']) != {'stopped_seconds'} or
            type(value['pause']['stopped_seconds']) not in (int, float) or not 0 < value['pause']['stopped_seconds'] < 10 or
            not isinstance(value['directories'], dict) or '' not in value['directories']):
        raise RuntimeError('empty-store manifest identity changed')
    directories = value['directories']
    for name, record in directories.items():
        if name:
            path = transfer.safe_name(name)
            if any(str(parent) not in directories for parent in path.parents if str(parent) != '.'):
                raise RuntimeError('empty-store directory parent missing')
        if (not isinstance(record, dict) or set(record) != {'mode', 'uid', 'gid', 'mtime_ns', 'xattrs'} or
                any(type(record[k]) is not int or record[k] < 0 for k in ('mode', 'uid', 'gid', 'mtime_ns')) or
                record['mode'] > 0o7777 or not isinstance(record['xattrs'], dict)):
            raise RuntimeError('invalid empty-store directory metadata')
        for key, data in record['xattrs'].items():
            if not isinstance(key, str) or not key or '\0' in key or not isinstance(data, str):
                raise RuntimeError('invalid empty-store extended attribute')
            try:
                if bytes.fromhex(data).hex() != data:
                    raise ValueError()
            except ValueError:
                raise RuntimeError('invalid empty-store extended attribute') from None
    return value


def send(namespace, output):
    identity = source_identity(namespace)
    path = Path(PROFILES[namespace]['volumes'][0]['source'])
    with tempfile.TemporaryDirectory(prefix='homelab-empty-store-103-', dir='/run') as temporary:
        marker = Path(temporary) / 'watchdog-fired'
        with process.frozen(identity, marker) as pause:
            if source_identity(namespace) != identity:
                raise RuntimeError('source changed before empty-store capture')
            directories = tree(path)
            if directories != tree(path) or source_identity(namespace) != identity:
                raise RuntimeError('empty store changed during capture')
        if marker.exists() or source_identity(namespace) != identity:
            raise RuntimeError('empty-store source did not resume unchanged')
    value = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'profile': PROFILES[namespace],
             'directories': directories, 'pause': pause, 'resumed': True}
    raw = common.canonical(validate(value, namespace))
    if len(raw) >= 65536:
        raise RuntimeError('empty-store manifest exceeds frame contract')
    output.write(raw + b'\n' + common.canonical({'commit': hashlib.sha256(raw).hexdigest()}) + b'\n')
    output.flush()


def verify(point, checksum, namespace):
    if any(p.is_symlink() for p in (point, *point.parents)) or stat.S_IMODE(point.stat().st_mode) != 0o700 or point.stat().st_uid != os.geteuid():
        raise RuntimeError('unsafe protected empty-store point')
    common.source_record('verified.json', point / 'verified.json')
    raw = (point / 'verified.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise RuntimeError('protected empty-store manifest changed')
    return validate(json.loads(raw), namespace)


def receive(source, point, namespace):
    value = validate(common.read_frame(source), namespace)
    raw = common.canonical(value)
    checksum = hashlib.sha256(raw).hexdigest()
    if common.read_frame(source) != {'commit': checksum} or source.read(1):
        raise RuntimeError('empty-store commit missing or trailing bytes')
    if any(p.is_symlink() for p in (point, *point.parents)):
        raise RuntimeError('unsafe protected empty-store ancestry')
    point.mkdir(mode=0o700)
    files.write_json(point / 'verified.json', value)
    for directory in (point, point.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    verify(point, checksum, namespace)
    return {'point': str(point), 'manifest_sha256': checksum, 'directories': len(value['directories']), 'files': 0, 'bytes': 0, 'pause': value['pause']}


def restore_metadata(root, directories):
    for name in sorted(directories, key=lambda name: len(Path(name).parts), reverse=True):
        path, record = root / name, directories[name]
        os.chown(path, record['uid'], record['gid'], follow_symlinks=False)
        os.chmod(path, record['mode'], follow_symlinks=False)
        for key in os.listxattr(path, follow_symlinks=False):
            if key not in record['xattrs']:
                os.removexattr(path, key, follow_symlinks=False)
        for key, value in record['xattrs'].items():
            os.setxattr(path, key, bytes.fromhex(value), follow_symlinks=False)
        os.utime(path, ns=(record['mtime_ns'], record['mtime_ns']), follow_symlinks=False)


def copied_write(root, user):
    program = "import os;os.setgroups(GROUPS);os.setgid(GID);os.setuid(UID);p='.maintenance103-copied-write';f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(f,b'synthetic');os.close(f);os.unlink(p)"
    program = program.replace('GROUPS', repr(user['additionalGids'])).replace('GID', repr(user['gid'])).replace('UID', repr(user['uid']))
    response = subprocess.run(['python3', '-B', '-c', program], cwd=root, capture_output=True)
    if response.returncode:
        raise RuntimeError('copied empty-store application user write failed')


def restore(point, checksum, namespace):
    value = verify(point, checksum, namespace)
    scratch = Path(tempfile.mkdtemp(prefix=namespace + '-empty-restore-', dir=point.parent))
    result = {'accepted': False, 'namespace': namespace, 'manifest_sha256': checksum}
    try:
        directories = value['directories']
        for name in sorted(directories, key=lambda name: len(Path(name).parts)):
            if name:
                (scratch / name).mkdir(mode=0o700)
        restore_metadata(scratch, directories)
        if tree(scratch) != directories:
            raise RuntimeError('copied empty-store metadata differs')
        copied_write(scratch, PROFILES[namespace]['process_user'])
        restore_metadata(scratch, directories)
        if tree(scratch) != directories:
            raise RuntimeError('copied empty-store metadata differs after write probe')
        verify(point, checksum, namespace)
        result.update(accepted=True, exact_directory_metadata=True, app_uid_gid_copied_write=True,
                      files=0, bytes=0, directories=len(directories), native_app_and_joint_database_checkpoint_unqualified=True)
    finally:
        # Restored directory permissions may deny traversal; change only owned scratch.
        allocated = scratch.stat().st_blocks * 512
        for parent, children, _names in os.walk(scratch, topdown=True):
            os.chmod(parent, 0o700)
            for child in children:
                allocated += (Path(parent) / child).stat().st_blocks * 512
                os.chmod(Path(parent) / child, 0o700)
        shutil.rmtree(scratch)
        verify(point, checksum, namespace)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'protected_manifest_unchanged': True,
                             'allocated_bytes_removed': allocated}
    return result
