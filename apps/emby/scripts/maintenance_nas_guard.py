#!/usr/bin/env python3
"""Pause only Emby's NAS backup schedule after its protected, read-only return."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import sys


NODE_UID = '5d80125d-4228-47dd-b19c-ca86f7d4316c'
MACHINE = 'e5796c3018b6448eae0c69405926317e'
ROOT_UUID = 'c27f6613-788e-4d00-802c-5b84a730a631'
IMAGE = 'lscr.io/linuxserver/emby:latest@sha256:f3827243e5e7a54086714f3fa8a46192b8c81e3da7262443c83eb69b2a5d329a'
NAS_PATHS = {'/backups', '/data/movies', '/data/tv', '/data/music', '/data/movies_custom', '/data/tv_custom'}
POINT = Path('/var/lib/homelab-recovery/maintenance-103/emby-nas-guard-20261028-a')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def command(*args, data=None):
    result = subprocess.run(args, input=data, capture_output=True)
    require(result.returncode == 0, 'NAS guard native command failed: ' + args[0])
    return result.stdout


def task_contract(task, *, accepted=False):
    require(task['Key'] == 'EmbyServerBackup' and task['Name'] == 'Emby Server Backup' and
            re.fullmatch(r'[a-zA-Z0-9-]{1,80}', task['Id']) and task['State'] == 'Idle' and
            isinstance(task['Triggers'], list), 'Emby backup task identity or idle state differs')
    if accepted:
        require(task['Triggers'] == [], 'NAS backup schedule is not paused')
    return {'id': task['Id'], 'key': task['Key'], 'triggers': task['Triggers']}


def runtime_contract(runtime, context):
    status = runtime['status']
    labels = status['labels']
    require(status['state'] == 'CONTAINER_RUNNING' and labels['io.kubernetes.pod.uid'] == context['pod_uid'] and
            labels['io.kubernetes.pod.namespace'] == 'emby' and
            labels['io.kubernetes.container.name'] == 'main', 'Emby runtime identity differs')
    mounts = runtime['info']['runtimeSpec']['mounts']
    nas = [m for m in mounts if m['destination'] in NAS_PATHS]
    require(len(nas) == len(NAS_PATHS) and {m['destination'] for m in nas} == NAS_PATHS and
            all('ro' in m['options'] for m in nas), 'Emby NAS mounts are not all read-only')
    config = [m for m in mounts if m['destination'] == '/config']
    expected = '/var/lib/kubelet/pods/' + context['pod_uid'] + '/volumes/kubernetes.io~csi/' + context['pv'] + '/mount'
    require(len(config) == 1 and config[0]['source'] == expected and 'rw' in config[0]['options'],
            'Emby original writable configuration mount differs')
    pid = runtime['info']['pid']
    require(type(pid) is int and pid > 1, 'Emby runtime PID invalid')
    return pid, Path(expected)


def exclusive_json(path, value):
    with path.open('xb') as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        target.flush()
        os.fsync(target.fileno())
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def select_media(items):
    """Keep private library paths in memory and select only supported local video."""
    for item in items['Items']:
        for source in item.get('MediaSources', []):
            path = source.get('Path', '')
            if (source.get('Protocol') != 'File' or not isinstance(path, str) or
                    '\0' in path or '..' in Path(path).parts or
                    not any(path.startswith(root + '/') for root in NAS_PATHS - {'/backups'})):
                continue
            video = [s for s in source.get('MediaStreams', []) if s.get('Type') == 'Video']
            if video and video[0].get('Codec') == 'h264' and video[0].get('PixelFormat') == 'yuv420p':
                return path
    raise RuntimeError('no supported local video in the bounded library response')


def media_progress(raw):
    values = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
    require(values.get('progress') == 'end' and re.fullmatch(r'\s*[0-9]+', values.get('frame', '')) and
            re.fullmatch(r'[0-9]+', values.get('out_time_us', '')), 'media progress is incomplete')
    frames, duration = int(values['frame']), int(values['out_time_us'])
    require(frames >= 20 and duration >= 1500000, 'media encode did not produce enough frames or duration')
    return {'frames': frames, 'output_microseconds': duration, 'progress': 'end'}


def verify_media(context, request, inspect, pid, root):
    path = select_media(json.loads(request('Items?Recursive=true&IncludeItemTypes=Movie,Episode&'
                                          'Fields=MediaSources,MediaStreams&Limit=50&SortBy=SortName')))
    prefix = ['/usr/local/bin/k3s', 'crictl', 'exec', context['container_id']]
    resolved = command(*prefix, 'readlink', '-f', '--', path).decode().strip()
    require(resolved == path, 'selected media path is not canonical inside the container')
    before = command(*prefix, 'stat', '-Lc', '%f:%d:%i:%s:%Y', '--', path)
    fields = before.decode().strip().split(':')
    require(len(fields) == 5 and stat.S_ISREG(int(fields[0], 16)) and int(fields[3]) > 0,
            'selected media is not a nonempty regular file')
    require(runtime_contract(inspect(), context) == (pid, root), 'Emby runtime changed before media acceptance')
    argv = [*prefix, '/bin/sh', '-c', 'exec timeout -k 5 -s TERM 90 "$@"', 'maintenance103-media',
            'env', 'LD_LIBRARY_PATH=/app/emby/lib:/app/emby/extra/lib',
            '/app/emby/bin/ffmpeg', '-nostdin', '-hide_banner', '-nostats', '-loglevel', 'error',
            '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-threads', '1', '-i', path,
            '-map', '0:v:0', '-t', '2', '-an', '-sn', '-dn', '-vf', 'scale_cuda=1280:720:format=nv12',
            '-c:v', 'h264_nvenc', '-progress', 'pipe:1', '-f', 'null', '-']
    result = subprocess.run(argv, capture_output=True)
    require(result.returncode == 0, 'owned media encode failed; exit ' + str(result.returncode) +
            ', stderr SHA256 ' + hashlib.sha256(result.stderr).hexdigest())
    progress = media_progress(result.stdout)
    require(command(*prefix, 'stat', '-Lc', '%f:%d:%i:%s:%Y', '--', path) == before and
            runtime_contract(inspect(), context) == (pid, root), 'media source or Emby runtime changed')
    return {'accepted': True, 'cuda_decode': True, 'cuda_scale': True, 'nvenc_encode': True,
            'null_output': True, 'child_exit': result.returncode, 'source_metadata_unchanged': True,
            'source_path_sha256': hashlib.sha256(path.encode()).hexdigest(), **progress}


def native(context, *, media=False):
    require(os.geteuid() == 0 and socket.gethostname() == 'sprigatito' and
            Path('/etc/machine-id').read_text().strip() == MACHINE and
            command('findmnt', '-n', '-o', 'UUID', '/').decode().strip() == ROOT_UUID and
            command('rpm', '-E', '%fedora').strip() == b'44', 'Emby return host identity or release differs')

    def inspect():
        return json.loads(command('/usr/local/bin/k3s', 'crictl', 'inspect', context['container_id']))

    pid, root = runtime_contract(inspect(), context)
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'Emby CSI mount ancestry changed')
    # Inspect actual namespace mount flags as well as the CRI desired mounts.
    entries = [line.split() for line in Path('/proc/' + str(pid) + '/mountinfo').read_text().splitlines()]
    for destination in NAS_PATHS:
        matches = [e for e in entries if e[4] == destination]
        require(len(matches) == 1 and 'ro' in matches[0][5].split(',') and
                matches[0][matches[0].index('-') + 1] in ('nfs', 'nfs4'), 'actual NAS mount is not read-only NFS')
    database = root / 'data/authentication.db'
    require(database.is_file() and not database.is_symlink(), 'Emby authentication database changed')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        keys = connection.execute('SELECT AccessToken FROM Tokens_2 WHERE IsActive=1 AND (UserId IS NULL OR UserId=0)').fetchall()
    require(keys and isinstance(keys[0][0], str) and re.fullmatch(r'[a-zA-Z0-9_-]+', keys[0][0]),
            'existing server API key unavailable')
    key = keys[0][0]

    def request(path, *, update=False):
        require(runtime_contract(inspect(), context) == (pid, root), 'Emby runtime changed before API access')
        config = ('silent\nshow-error\nfail\nmax-time=10\nproxy=""\nnoproxy="*"\nurl="http://127.0.0.1:8096/emby/' + path +
                  '"\nheader="X-Emby-Token: ' + key + '"\n')
        if update:
            config += 'request="POST"\nheader="Content-Type: application/json"\ndata="[]"\n'
        return command('nsenter', '--target', str(pid), '--net', '--', 'curl', '--disable', '--config', '-', data=config.encode())

    require(json.loads(request('System/Info'))['Version'] == '4.10.2.0', 'Emby return API version differs')
    tasks = [t for t in json.loads(request('ScheduledTasks')) if t.get('Key') == 'EmbyServerBackup']
    require(len(tasks) == 1, 'Emby backup task absent or duplicate')
    before = task_contract(tasks[0])
    for path in reversed((POINT, *POINT.parents)):
        require(not path.is_symlink(), 'unsafe NAS guard receipt ancestry')
        if not path.exists():
            path.mkdir(mode=0o700)
        require(path.is_dir() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022,
                'unsafe NAS guard receipt owner or permissions')
    intent = POINT / 'intent.json'
    if not intent.exists():
        exclusive_json(intent, {'context': context, 'original': before, 'desired_triggers': []})
        if before['triggers']:
            request('ScheduledTasks/' + before['id'] + '/Triggers', update=True)
    else:
        require(not intent.is_symlink() and intent.stat().st_uid == 0 and
                intent.stat().st_nlink == 1 and intent.stat().st_mode & 0o777 == 0o600, 'unsafe NAS guard intent')
        saved = json.loads(intent.read_bytes())
        require(saved['context'] == context and saved['original']['id'] == before['id'] and
                saved['original']['key'] == before['key'] and saved['desired_triggers'] == [],
                'NAS guard intent differs; observe only')
    after = task_contract(json.loads(request('ScheduledTasks/' + before['id'])), accepted=True)
    result = {'accepted': True, 'task_id': after['id'], 'task_key': after['key'], 'triggers': [],
              'nas_mounts_readonly': len(NAS_PATHS), 'nas_write_or_backup_test': False,
              'intent_sha256': hashlib.sha256(intent.read_bytes()).hexdigest()}
    accepted = POINT / 'accepted.json'
    if not accepted.exists():
        exclusive_json(accepted, result)
    require(not accepted.is_symlink() and json.loads(accepted.read_bytes()) == result, 'NAS guard acceptance differs')
    if media:
        result['media'] = verify_media(context, request, inspect, pid, root)
        task_contract(json.loads(request('ScheduledTasks/' + before['id'])), accepted=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('identity', 'known-hosts', 'kubectl'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--verify-media', action='store_true', help='Verify existing media using CUDA/NVENC and null output')
    args = parser.parse_args()
    repository = Path('/Users/chris/Documents/Github/homelab')
    require(Path.cwd() == repository and command('git', 'branch', '--show-current').strip() == b'master' and
            command('git', 'remote', 'get-url', 'origin').strip() == b'git@git.eaglepass.io:ops/homelab.git',
            'canonical checkout required')
    revision = command('git', 'rev-parse', 'HEAD').decode().strip()
    require(command('git', 'ls-remote', 'origin', 'refs/heads/master').decode().split()[0] == revision and
            command('git', 'show', revision + ':' + str(Path(__file__).relative_to(repository))) == Path(__file__).read_bytes(),
            'publish exact NAS guard before execution')
    sys.path.insert(0, str(repository / 'metal/scripts'))
    import maintenance_production_node as production
    import emby_volume_recovery as recovery
    source = Path(recovery.__file__).read_text().split('\ndef observe(')[0]
    proof = production.remote(args, source + '\nvalue=verified();proof=json.loads((POINT/"restore-accepted.json").read_bytes())\n'
        'require(proof["accepted"] and proof["manifest_sha256"]==summary(value)["manifest_sha256"] and '
        'all(proof["cleanup"].values()) and proof["no_nas_mounts"],"protected Emby restore proof differs")\n'
        'print(json.dumps({"manifest_sha256":proof["manifest_sha256"]}))', '10.0.20.13')

    args_kubectl = args.kubectl

    def read(*arguments):
        return json.loads(command(args_kubectl, *arguments, '-o', 'json'))

    app = read('get', 'application', 'emby', '-n', 'argocd')
    require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == revision,
            'Emby return revision is not reconciled')
    kured = read('get', 'daemonset', 'kured', '-n', 'kured')
    require(kured['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            'homelab.eaglepass.io/maintenance-owner' not in kured['metadata'].get('annotations', {}),
            'node maintenance ownership must finish before the Emby return')
    health = json.loads(command(args_kubectl, 'exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                                'ceph', 'health', '--format', 'json'))
    mapping = json.loads(command(args_kubectl, 'exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                                 'ceph', 'osd', 'dump', '--format', 'json'))
    require(health['status'] == 'HEALTH_OK' and not health.get('checks') and
            mapping['fsid'] == '13c20377-d801-43f9-aebd-59f62df5dad1' and
            {o['osd'] for o in mapping['osds']} == {1, 2, 6, 7, 8} and
            all(o['up'] == o['in'] == 1 and o['weight'] == 1 for o in mapping['osds']),
            'original OSD7 must finish its healthy return first')
    node = read('get', 'node', 'sprigatito')
    require(node['metadata']['uid'] == NODE_UID and node['status']['nodeInfo']['osImage'] == 'Fedora Linux 44 (Forty Four)' and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']), 'Emby return node is not ready on Fedora 44')
    deployment = read('get', 'deployment', 'emby-main', '-n', 'emby')
    require(deployment['spec']['replicas'] == 1 and deployment['status'].get('readyReplicas') == 1 and
            deployment['status']['observedGeneration'] == deployment['metadata']['generation'] and
            deployment['spec']['template']['spec']['containers'][0]['image'] == IMAGE, 'Emby return controller differs')
    cronjobs = read('get', 'cronjobs', '-n', 'emby')['items']
    require(len(cronjobs) == 2 and all(c['spec'].get('suspend') and not c['status'].get('active')
                for c in cronjobs), 'Emby return CronJobs are not held')
    claim = read('get', 'pvc', 'emby-original-data', '-n', 'emby')
    volume = read('get', 'pv', recovery.PV)
    require(claim['metadata']['uid'] == recovery.PVC and claim['status']['phase'] == 'Bound' and
            claim['spec']['volumeName'] == recovery.PV and volume['metadata']['uid'] == recovery.PV_UID and
            volume['spec']['claimRef']['uid'] == recovery.PVC and
            volume['spec']['persistentVolumeReclaimPolicy'] == 'Retain', 'Emby original PVC differs')
    pods = [p for p in read('get', 'pods', '-n', 'emby')['items'] if p['status']['phase'] != 'Succeeded']
    require(len(pods) == 1, 'Emby return has another active Pod')
    pod = pods[0]
    require(not pod['metadata'].get('deletionTimestamp') and pod['spec'].get('nodeName') == 'sprigatito' and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status']['conditions']), 'Emby return Pod is not ready')
    states = pod['status']['containerStatuses']
    require(len(states) == 1 and states[0]['ready'] and states[0]['name'] == 'main' and
            states[0]['containerID'].startswith('containerd://') and
            pod['spec']['containers'][0]['image'] == IMAGE, 'Emby return container differs')
    owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(len(owners) == 1 and owners[0]['kind'] == 'ReplicaSet', 'Emby return Pod lacks its controller')
    replica = read('get', 'replicaset', owners[0]['name'], '-n', 'emby')
    parents = [o for o in replica['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(replica['metadata']['uid'] == owners[0]['uid'] and len(parents) == 1 and
            parents[0]['kind'] == 'Deployment' and parents[0]['uid'] == deployment['metadata']['uid'],
            'Emby return controller ownership differs')
    context = {'pod_uid': pod['metadata']['uid'], 'container_id': states[0]['containerID'].split('://')[1],
               'pv': recovery.PV, 'recovery_manifest_sha256': proof['manifest_sha256']}
    native_source = Path(__file__).read_text().split('\ndef main(')[0]
    result = production.remote(args, native_source + '\nprint(json.dumps(native(' + repr(context) +
                               ',media=' + repr(args.verify_media) + ')))', '10.0.20.20')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
