#!/usr/bin/env python3
"""Cold Emby recovery: protected full-volume copy and disconnected reconstruction."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path('/var/lib/homelab-recovery/maintenance-103')
POINT = ROOT / 'emby-volume-cold-20261028-a'
IMAGE = 'lscr.io/linuxserver/emby@sha256:f3827243e5e7a54086714f3fa8a46192b8c81e3da7262443c83eb69b2a5d329a'
PVC = '9ef38f61-9f53-447b-abfa-3b5cdf361901'
PV = 'pvc-5e4a5182-6f37-4cc3-8cfe-31281f8baa24'
PV_UID = 'd924f299-0570-49e7-a5e5-9286bd4c8986'
HOSTS = {
    'bulbasaur': ('f61201c3e2ba4b8cbd31e09f77da2ad0', '2c59d1d1-d2d8-420e-b3a5-d87eb0437823'),
    'squirtle': ('90c7f1d7caea486d9dc9bdbb4ec5ae21', 'eea5afa0-dbb6-43f5-abe6-f1be801fb03a'),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def command(*args, check=True):
    result = subprocess.run(args, capture_output=True)
    require(not check or result.returncode == 0, 'native recovery command failed: ' + args[0])
    return result


def host(name):
    machine, uuid = HOSTS[name]
    require(os.geteuid() == 0 and socket.gethostname() == name and
            Path('/etc/machine-id').read_text().strip() == machine and
            command('findmnt', '-n', '-o', 'UUID', '/').stdout.decode().strip() == uuid,
            'protected recovery host identity changed')
    require(ROOT.is_dir() and not any(p.is_symlink() for p in (ROOT, *ROOT.parents)) and
            ROOT.stat().st_uid == 0 and not ROOT.stat().st_mode & 0o022,
            'unsafe protected recovery root')


def safe_name(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'unsafe recovery member')
    return path


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def tree(root):
    result = {}
    paths = [root]
    for parent, directories, names in os.walk(root, followlinks=False):
        paths.extend(Path(parent) / name for name in directories + names)
    device = root.stat().st_dev
    for path in sorted(paths):
        name = str(path.relative_to(root))
        if name == '.':
            name = ''
        else:
            safe_name(name)
        info = path.lstat()
        require(info.st_dev == device, 'recovery tree crosses a device')
        if stat.S_ISDIR(info.st_mode):
            kind = 'directory'
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            kind = 'file'
        elif stat.S_ISLNK(info.st_mode):
            kind = 'symlink'
        else:
            raise RuntimeError('unreviewed hardlink or special recovery file')
        record = {'kind': kind, 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid,
                  'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns,
                  'xattrs': {key: os.getxattr(path, key, follow_symlinks=False).hex()
                             for key in sorted(os.listxattr(path, follow_symlinks=False))}}
        if kind == 'file':
            record.update(bytes=info.st_size, sha256=digest_file(path))
        elif kind == 'symlink':
            record['target'] = os.readlink(path)
        result[name] = record
    validate_tree(result)
    return result


def validate_tree(records):
    require(records.get('', {}).get('kind') == 'directory', 'missing recovery root')
    for name, record in records.items():
        if name:
            path = safe_name(name)
            require(all(records.get(str(p) if str(p) != '.' else '', {}).get('kind') == 'directory'
                        for p in path.parents), 'recovery entry beneath a link or absent directory')
        require(record['kind'] in ('file', 'directory', 'symlink'), 'invalid recovery type')


def write_json(path, value):
    with path.open('xb') as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(canonical(value))
        target.flush()
        os.fsync(target.fileno())


def mount(context):
    runtime = json.loads(command('/usr/local/bin/k3s', 'crictl', 'inspect', context['container_id']).stdout)
    labels = runtime['status']['labels']
    require(runtime['status']['state'] == 'CONTAINER_RUNNING' and
            labels['io.kubernetes.pod.uid'] == context['pod_uid'] and
            labels['io.kubernetes.pod.namespace'] == 'emby' and
            labels['io.kubernetes.container.name'] == 'readonly-volume', 'recovery container changed')
    mounts = [m for m in runtime['info']['runtimeSpec']['mounts'] if m['destination'] == '/config']
    require(len(mounts) == 1 and 'ro' in mounts[0]['options'], 'recovery mount is not read-only')
    root = Path('/var/lib/kubelet/pods') / context['pod_uid'] / 'volumes/kubernetes.io~csi' / PV / 'mount'
    require(mounts[0]['source'] == str(root) and root.is_dir() and
            not any(p.is_symlink() for p in (root, *root.parents)), 'recovery CSI source changed')
    visible = Path('/proc') / str(runtime['info']['pid']) / 'root/config'
    require((visible.stat().st_dev, visible.stat().st_ino) == (root.stat().st_dev, root.stat().st_ino) and
            os.statvfs(visible).f_flag & os.ST_RDONLY, 'recovery volume is not enforced read-only')
    return root


def backup(context):
    host('bulbasaur')
    if (POINT / 'verified.json').exists():
        value = verified()
        require(value['context'] == context, 'accepted recovery belongs to another cold mount')
        return summary(value)
    require(not POINT.exists(), 'preserve nonempty prior recovery point; observe before retry')
    root = mount(context)
    records = tree(root)
    size = sum(r.get('bytes', 0) for r in records.values())
    usage = shutil.disk_usage(ROOT)
    require(usage.free - size - len(records) * 8192 > usage.total // 5, 'protected capture capacity guard')
    POINT.mkdir(mode=0o700)
    partial = POINT / 'volume.partial'
    with partial.open('xb') as target:
        os.fchmod(target.fileno(), 0o600)
        result = subprocess.run(['tar', '--format=pax', '--numeric-owner', '--acls', '--xattrs',
                                 '--xattrs-include=*', '--selinux', '--one-file-system', '-cpf', '-', '-C', str(root), '.'],
                                stdout=target, stderr=subprocess.PIPE)
        target.flush()
        os.fsync(target.fileno())
    require(result.returncode == 0, 'cold volume tar failed; protected partial retained')
    require(mount(context) == root and tree(root) == records, 'cold volume changed during capture')
    value = {'format': 1, 'pvc_uid': PVC, 'pv_uid': PV_UID, 'image': IMAGE,
             'context': context, 'tree': records, 'archive_bytes': partial.stat().st_size,
             'archive_sha256': digest_file(partial)}
    # Validate every archived byte before the protected point is accepted.
    check_archive(partial, records)
    os.link(partial, POINT / 'volume.tar')
    partial.unlink()
    write_json(POINT / 'manifest.json', value)
    result = summary(value)
    write_json(POINT / 'verified.json', result)
    descriptor = os.open(POINT, os.O_DIRECTORY)
    os.fsync(descriptor)
    os.close(descriptor)
    return result


def archive_name(name):
    if name in ('.', './'):
        return ''
    if name.startswith('./'):
        name = name[2:]
    return str(safe_name(name.rstrip('/')))


def check_archive(path, records):
    seen = set()
    with tarfile.open(path) as archive:
        for member in archive:
            name = archive_name(member.name)
            require(name in records and name not in seen, 'unexpected or duplicate archive member')
            record = records[name]
            seen.add(name)
            require((member.uid, member.gid, member.mode) == (record['uid'], record['gid'], record['mode']),
                    'archive metadata mismatch')
            if record['kind'] == 'file':
                require(member.isfile() and member.size == record['bytes'], 'archive file type/size mismatch')
                digest = hashlib.sha256()
                with archive.extractfile(member) as source:
                    for chunk in iter(lambda: source.read(1048576), b''):
                        digest.update(chunk)
                require(digest.hexdigest() == record['sha256'], 'archive file checksum mismatch')
            elif record['kind'] == 'directory':
                require(member.isdir(), 'archive directory mismatch')
            else:
                require(member.issym() and member.linkname == record['target'], 'archive link mismatch')
    require(seen == set(records), 'archive missing retained entries')


def summary(value):
    return {'manifest_sha256': hashlib.sha256(canonical(value)).hexdigest(),
            'archive_sha256': value['archive_sha256'], 'archive_bytes': value['archive_bytes'],
            'entries': len(value['tree']),
            'payload_bytes': sum(r.get('bytes', 0) for r in value['tree'].values()),
            'pvc_uid': PVC, 'pv_uid': PV_UID, 'image': IMAGE, 'nas_touched': False}


def verified():
    host('bulbasaur')
    require(not POINT.is_symlink() and stat.S_IMODE(POINT.stat().st_mode) == 0o700, 'unsafe protected point')
    value = json.loads((POINT / 'manifest.json').read_bytes())
    require(summary(value) == json.loads((POINT / 'verified.json').read_bytes()) and
            value['pvc_uid'] == PVC and value['pv_uid'] == PV_UID and value['image'] == IMAGE and
            (POINT / 'volume.tar').stat().st_size == value['archive_bytes'] and
            digest_file(POINT / 'volume.tar') == value['archive_sha256'], 'protected point changed')
    validate_tree(value['tree'])
    return value


def send():
    value = verified()
    sys.stdout.buffer.write(canonical(value) + b'\n')
    with (POINT / 'volume.tar').open('rb') as source:
        shutil.copyfileobj(source, sys.stdout.buffer, 1048576)
    sys.stdout.buffer.flush()


def databases(root):
    result = {}
    for name in ('activitylog.db', 'authentication.db', 'library.db', 'users.db'):
        path = root / 'data' / name
        require(path.is_file() and not path.is_symlink(), 'required Emby database missing')
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
            require(database.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Emby SQLite integrity failed')
            schema = database.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
            counts = {}
            for table in ('MediaItems', 'LocalUsersv2', 'Tokens_2'):
                if any(row[1] == table for row in schema):
                    counts[table] = database.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
            result[name] = {'schema_sha256': hashlib.sha256(canonical(schema)).hexdigest(), 'counts': counts}
    return result


def compare_reconstruction(actual, expected, destination_label):
    """Preserve source metadata; account only for a verified new host label."""
    require(bool(destination_label), 'missing enforcing destination label')
    require(set(actual) == set(expected), 'reconstructed Emby entries differ')
    added = 0
    for name, original in expected.items():
        restored = dict(actual[name])
        attributes = dict(restored['xattrs'])
        if 'security.selinux' not in original['xattrs']:
            require(attributes.pop('security.selinux', None) == destination_label,
                    'reconstructed destination SELinux label differs')
            added += 1
        restored['xattrs'] = attributes
        require(restored == original, 'full reconstructed Emby content or source metadata differs')
    return {'source_content_and_metadata_equal': True, 'destination_selinux_labels_added': added,
            'destination_selinux_label_sha256': hashlib.sha256(bytes.fromhex(destination_label)).hexdigest()}


def restore():
    host('squirtle')
    def interrupted(signum, frame):
        raise RuntimeError('owned restore interrupted; cleaning native resources')
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    header = sys.stdin.buffer.readline(64 * 1024 * 1024)
    require(header.endswith(b'\n'), 'incomplete recovery manifest')
    value = json.loads(header)
    require(value['pvc_uid'] == PVC and value['pv_uid'] == PV_UID and value['image'] == IMAGE, 'restore identity changed')
    records = value['tree']
    validate_tree(records)
    usage = shutil.disk_usage(ROOT)
    require(usage.free - sum(r.get('bytes', 0) for r in records.values()) - 2 * 1024**3 > usage.total // 5,
            'isolated restore capacity guard')
    scratch = Path(tempfile.mkdtemp(prefix='emby-volume-restore-', dir=ROOT))
    scratch.chmod(0o700)
    root = scratch / 'data'
    root.mkdir(mode=0o700)
    container = image_id = None
    old_images = set(command('docker', 'image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    result = {'accepted': False, **summary(value)}
    try:
        require(command('getenforce').stdout.strip() == b'Enforcing', 'restore host is not enforcing')
        command('matchpathcon', '-V', str(root))
        destination_label = os.getxattr(root, 'security.selinux', follow_symlinks=False).hex()
        # A trusted, validated source archive is streamed without a second disk copy.
        extraction_errors = (scratch / 'extract.stderr').open('xb')
        os.fchmod(extraction_errors.fileno(), 0o600)
        child = subprocess.Popen(['tar', '--extract', '--file=-', '--directory=' + str(root),
                                  '--numeric-owner', '--same-owner', '--same-permissions', '--acls', '--xattrs',
                                  '--xattrs-include=*', '--no-selinux'],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=extraction_errors)
        digest = hashlib.sha256()
        remaining = value['archive_bytes']
        try:
            while remaining:
                chunk = sys.stdin.buffer.read(min(1048576, remaining))
                require(chunk, 'truncated restore stream')
                digest.update(chunk)
                child.stdin.write(chunk)
                remaining -= len(chunk)
            child.stdin.close()
            child.wait()
            require(child.returncode == 0 and digest.hexdigest() == value['archive_sha256'] and
                    not sys.stdin.buffer.read(1), 'restored tar stream failed checksum or extraction')
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            extraction_errors.close()
        # Compare all retained content and metadata before any application writes.
        # tar's RHT.security.selinux can describe a synthetic source mount label
        # even when that inode has no security.selinux xattr. Restore only the
        # actual source attributes recorded in the complete manifest.
        for name, record in records.items():
            if 'security.selinux' in record['xattrs']:
                os.setxattr(root / name, 'security.selinux', bytes.fromhex(record['xattrs']['security.selinux']),
                            follow_symlinks=False)
        metadata = compare_reconstruction(tree(root), records, destination_label)
        before = databases(root)
        command('docker', 'pull', IMAGE)
        description = json.loads(command('docker', 'image', 'inspect', IMAGE).stdout)[0]
        image_id = description['Id']
        label = 'homelab.eaglepass.io/emby-recovery=20261028-a'
        require(not command('docker', 'ps', '-aq', '--filter=label=' + label).stdout.strip(), 'owned restore already exists')
        arguments = ['docker', 'create', '--log-driver=none', '--network=none', '--read-only', '--cap-drop=ALL', '--user=99:100',
                     '--security-opt=no-new-privileges:true', '--ipc=private',
                     '--pids-limit=256', '--memory=4g', '--cpus=1', '--label=' + label,
                     '--tmpfs=/tmp:rw,nosuid,nodev,uid=99,gid=100,mode=1777', '--env=HOME=/tmp',
                     '--volume=' + str(root) + ':/config:Z',
                     '--entrypoint=/app/emby/system/EmbyServer', IMAGE, '-programdata', '/config',
                     '-ffdetect', '/app/emby/bin/ffdetect', '-ffmpeg', '/app/emby/bin/ffmpeg',
                     '-ffprobe', '/app/emby/bin/ffprobe', '-restartexitcode', '3']
        container = command(*arguments).stdout.decode().strip()
        inspected = json.loads(command('docker', 'inspect', container).stdout)[0]
        require(inspected['HostConfig']['NetworkMode'] == 'none' and
                inspected['HostConfig']['LogConfig'] == {'Type': 'none', 'Config': {}} and
                inspected['HostConfig']['SecurityOpt'] == ['no-new-privileges:true'] and
                inspected['HostConfig']['ReadonlyRootfs'] is True and
                inspected['HostConfig']['Privileged'] is False and
                inspected['HostConfig']['CapDrop'] == ['ALL'] and inspected['Config']['User'] == '99:100' and
                len(inspected['Mounts']) == 1 and inspected['Mounts'][0]['Type'] == 'bind' and
                inspected['Mounts'][0]['Source'] == str(root) and inspected['Mounts'][0]['Destination'] == '/config',
                'restore isolation changed')
        command('docker', 'start', container)
        deadline = time.monotonic() + 240
        while True:
            ping = command('docker', 'exec', container, 'curl', '--silent', '--fail', '--max-time', '3',
                           'http://127.0.0.1:8096/emby/System/Info/Public', check=False)
            if ping.returncode == 0:
                info = json.loads(ping.stdout)
                require(info['Version'] == '4.10.2.0', 'restored Emby version differs')
                break
            require(time.monotonic() < deadline, 'restored Emby API did not become ready')
            require(json.loads(command('docker', 'inspect', container).stdout)[0]['State']['Running'],
                    'restored Emby stopped')
            time.sleep(1)
        devices = command('docker', 'exec', container, 'cat', '/proc/net/dev').stdout.decode()
        require({line.split(':')[0].strip() for line in devices.splitlines() if ':' in line} == {'lo'},
                'restore has an external network interface')
        with sqlite3.connect((root / 'data/authentication.db').as_uri() + '?mode=ro', uri=True) as database:
            keys = database.execute('SELECT AccessToken FROM Tokens_2 WHERE IsActive=1 AND (UserId IS NULL OR UserId=0)').fetchall()
        require(keys, 'restored server API key missing')
        key = keys[0][0]
        require(isinstance(key, str) and key and all(c.isalnum() or c in '-_' for c in key), 'invalid server key encoding')
        request = ('silent\nshow-error\nfail\nmax-time=5\nurl="http://127.0.0.1:8096/emby/System/Info"\n'
                   'header="X-Emby-Token: ' + key + '"\n').encode()
        authenticated = subprocess.run(['docker', 'exec', '-i', container, 'curl', '--config', '-'],
                                       input=request, capture_output=True)
        require(authenticated.returncode == 0 and json.loads(authenticated.stdout)['Version'] == '4.10.2.0',
                'restored authenticated Emby API failed')
        command('docker', 'stop', '--time=40', container)
        state = json.loads(command('docker', 'inspect', container).stdout)[0]['State']
        require(not state['Running'] and not state['OOMKilled'] and state['ExitCode'] == 0, 'restored Emby did not stop cleanly')
        after = databases(root)
        require(before == after, 'restored Emby changed database schemas or protected record counts')
        result.update(accepted=True, reconstruction=metadata, databases=after, native_api_status=200, authenticated_api_status=200, version=info['Version'],
                      network='none', no_nas_mounts=True, clean_exit=0)
    finally:
        if container:
            command('docker', 'rm', '-f', container)
            require(command('docker', 'inspect', container, check=False).returncode != 0, 'owned restore container remains')
        shutil.rmtree(scratch)
        require(not scratch.exists(), 'owned restore scratch remains')
        if image_id and image_id not in old_images:
            require(not command('docker', 'ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip(), 'new restore image acquired another consumer')
            command('docker', 'image', 'rm', IMAGE)
            require(command('docker', 'image', 'inspect', image_id, check=False).returncode != 0, 'new unused restore image remains')
        result['cleanup'] = {'container_absent': True, 'scratch_absent': True}
    return result

def observe(args):
    def read(*arguments):
        return json.loads(command(args.kubectl, *arguments, '-o', 'json').stdout)
    app = read('get', 'application', 'emby', '-n', 'argocd')
    revision = command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
    require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == revision,
            'published cold hold is not reconciled')
    deployment = read('get', 'deployment', 'emby-main', '-n', 'emby')
    require(deployment['spec']['replicas'] == 0 and not deployment['status'].get('replicas', 0) and
            deployment['status']['observedGeneration'] == deployment['metadata']['generation'], 'Emby writer not stopped')
    cronjobs = read('get', 'cronjobs', '-n', 'emby')['items']
    require(len(cronjobs) == 2 and all(c['spec'].get('suspend') and not c['status'].get('active') for c in cronjobs),
            'Emby scheduled writers not stopped')
    claim = read('get', 'pvc', 'emby-original-data', '-n', 'emby')
    volume = read('get', 'pv', PV)
    require(claim['metadata']['uid'] == PVC and claim['status']['phase'] == 'Bound' and
            claim['spec']['volumeName'] == PV and volume['metadata']['uid'] == PV_UID and
            volume['spec']['claimRef']['uid'] == PVC and volume['spec']['persistentVolumeReclaimPolicy'] == 'Retain' and
            volume['spec']['csi']['driver'] == 'rook-ceph.rbd.csi.ceph.com', 'protected volume identity changed')
    pods = read('get', 'pods', '-n', 'emby')['items']
    current = [p for p in pods if p['metadata']['name'] == 'emby-maintenance103-recovery']
    require(len(current) == 1, 'recovery pod missing or duplicate')
    pod = current[0]
    require(not pod['metadata'].get('deletionTimestamp') and pod['spec']['nodeName'] == 'bulbasaur' and
            pod['spec']['automountServiceAccountToken'] is False and len(pod['spec']['volumes']) == 1 and
            pod['spec']['volumes'][0]['persistentVolumeClaim'] == {'claimName': 'emby-original-data', 'readOnly': True} and
            pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'] is True and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status']['conditions']),
            'recovery pod is not isolated and ready')
    for other in pods:
        if other['metadata']['uid'] == pod['metadata']['uid']:
            continue
        require(other['status']['phase'] == 'Succeeded' and all(
            c.get('state', {}).get('terminated', {}).get('exitCode') == 0
            for c in other['status'].get('containerStatuses', [])), 'another Emby writer remains')
    network = read('get', 'networkpolicy', 'emby-maintenance103-recovery', '-n', 'emby')
    require(network['spec']['podSelector'] == {'matchLabels': {'homelab.eaglepass.io/recovery': 'emby-maintenance103'}} and
            set(network['spec']['policyTypes']) == {'Ingress', 'Egress'} and
            not network['spec'].get('ingress') and not network['spec'].get('egress'), 'recovery network isolation changed')
    statuses = pod['status']['containerStatuses']
    require(len(statuses) == 1 and statuses[0]['ready'] and statuses[0]['restartCount'] == 0 and
            statuses[0]['containerID'].startswith('containerd://'), 'recovery container changed')
    return {'pod_uid': pod['metadata']['uid'], 'container_id': statuses[0]['containerID'].split('://')[1]}


def main():
    import argparse
    import shlex
    import maintenance_production_node as production
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['observe', 'backup', 'restore'])
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--kubectl', required=True)
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab') and
            command('git', 'branch', '--show-current').stdout.decode().strip() == 'master' and
            command('git', 'remote', 'get-url', 'origin').stdout.decode().strip() == 'git@git.eaglepass.io:ops/homelab.git',
            'canonical recovery checkout required')
    revision = command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
    require(command('git', 'ls-remote', 'origin', 'refs/heads/master').stdout.decode().split()[0] == revision,
            'recovery implementation must reach canonical master')
    path = Path(__file__).relative_to(Path.cwd())
    require(path.read_bytes() == command('git', 'show', revision + ':' + str(path)).stdout,
            'unpublished recovery implementation')
    context = observe(args)
    source = path.read_text().split('\ndef observe(')[0]
    if args.operation == 'observe':
        result = context
    elif args.operation == 'backup':
        result = production.remote(args, source + '\nprint(json.dumps(backup(' + repr(context) + ')))', '10.0.20.13')
    else:
        def bulk_ssh(address):
            options = production.ssh(args, address)
            return options[:1] + ['-C'] + options[1:]
        sender = subprocess.Popen(bulk_ssh('10.0.20.13') +
                                  ['python3 -B -c ' + shlex.quote(source + '\nsend()')],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receiver = subprocess.Popen(bulk_ssh('10.0.20.12') +
                                    ['python3 -B -c ' + shlex.quote(source + '\nprint(json.dumps(restore()))')],
                                    stdin=sender.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sender.stdout.close()
        try:
            output, error = receiver.communicate()
            sender.wait()
            require(sender.returncode == receiver.returncode == 0, 'protected restore failed: ' + error.decode()[-1500:])
            result = json.loads(output)
            require(result['accepted'], 'isolated Emby restore not accepted')
            result = production.remote(args, source + '\nvalue=verified();result=' + repr(result) + '\n' +
                'require(summary(value)["archive_sha256"]==result["archive_sha256"],"protected point changed")\n' +
                'write_json(POINT/"restore-accepted.json",result)\nprint(json.dumps(result))', '10.0.20.13')
        finally:
            for child in (sender, receiver):
                if child.poll() is None:
                    child.terminate()
                child.wait()
    require(observe(args) == context, 'cold source identity changed during recovery')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
