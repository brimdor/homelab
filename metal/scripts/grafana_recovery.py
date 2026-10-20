#!/usr/bin/env python3
"""Protect the reviewed Grafana emptyDirs and restore only in a disconnected copy."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
import struct
import time
import urllib.parse
import urllib.request

import etcd_recovery as common
import prometheus_recovery as shared

POD = '72d42a94-085c-47ee-a761-93489209b813'
CONTAINER = '6dbf4c9532d47f43ce56bee698d2232b550409ace24431f7d6c02573c2a309cf'
PID = 16923
IMAGE = 'docker.io/grafana/grafana@sha256:2175aaa91c96733d86d31cf270d5310b278654b03f5718c59de12a865380a31f'
LABEL = 'io.eaglepass.grafana-recovery-103'
ROOT = Path('/var/lib/kubelet/pods') / POD / 'volumes/kubernetes.io~empty-dir'
VOLUMES = {'data': ('storage', '/var/lib/grafana'), 'search': ('search', '/var/lib/grafana-search'),
           'dashboards': ('sc-dashboard-volume', '/tmp/dashboards'),
           'datasources': ('sc-datasources-volume', '/etc/grafana/provisioning/datasources')}
CONFIG = {'grafana.ini': '/etc/grafana/grafana.ini',
          'provider.yaml': '/etc/grafana/provisioning/dashboards/sc-dashboardproviders.yaml'}
ENTRYPOINT = ['/usr/share/grafana/bin/grafana']
SERVER_ARGS = ['server', '--homepath=/usr/share/grafana', '--config=/etc/grafana/grafana.ini']
ENVIRONMENT = {'GF_LOG_MODE': 'console', 'GF_PATHS_CONFIG': '/etc/grafana/grafana.ini',
               'GF_PATHS_HOME': '/usr/share/grafana', 'GF_PATHS_DATA': '/var/lib/grafana', 'GF_PATHS_LOGS': '/tmp/logs',
               'GF_PATHS_PLUGINS': '/var/lib/grafana/plugins', 'GF_PATHS_PROVISIONING': '/etc/grafana/provisioning',
               'GF_UNIFIED_STORAGE_INDEX_PATH': '/var/lib/grafana-search',
               'GF_ANALYTICS_REPORTING_ENABLED': 'false', 'GF_ANALYTICS_CHECK_FOR_UPDATES': 'false',
               'GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES': 'false', 'GF_PLUGINS_PREINSTALL_DISABLED': 'true',
               'GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED': 'true', 'GF_AUTH_GENERIC_OAUTH_ENABLED': 'false',
               'GF_UNIFIED_ALERTING_ENABLED': 'false', 'GF_RECORDING_RULES_ENABLED': 'false',
               'GF_SERVER_HTTP_ADDR': '127.0.0.1', 'GF_SERVER_HTTP_PORT': '3000'}


def digest(value):
    return hashlib.sha256(common.canonical(value)).hexdigest()


def typed(value):
    if value is None: return ['null']
    if isinstance(value, int): return ['integer', str(value)]
    if isinstance(value, float): return ['real', struct.pack('>d', value).hex()]
    if isinstance(value, str): return ['text', value]
    if isinstance(value, bytes): return ['blob', value.hex()]
    raise RuntimeError('unsupported native SQLite value')


def fingerprint(path):
    # Capture permits DELETE journaling with no sidecars and a stopped sole writer only.
    for suffix in ('-journal', '-wal', '-shm'):
        if Path(str(path) + suffix).exists():
            raise RuntimeError('SQLite sidecar requires a separately qualified recovery contract')
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('native SQLite source is not a regular file')
    quote = lambda name: '"' + name.replace('"', '""') + '"'
    database = sqlite3.connect('file:' + urllib.parse.quote(str(path)) + '?mode=ro&immutable=1', uri=True, timeout=0)
    try:
        if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or database.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('native SQLite integrity or foreign keys failed')
        schema = database.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name,tbl_name').fetchall()
        tables = database.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        metadata = [(name, database.execute('PRAGMA ' + name).fetchone()) for name in ('user_version', 'application_id', 'encoding')]
        contents = []; rows = 0
        for (name,) in tables:
            columns = database.execute('PRAGMA table_xinfo(' + quote(name) + ')').fetchall()
            info = next(row for row in database.execute('PRAGMA table_list') if row[0] == 'main' and row[1] == name)
            alias = next((key for key in ('rowid', 'oid', '_rowid_') if key not in {c[1].lower() for c in columns}), None)
            if info[4] == 0 and alias is None: raise RuntimeError('SQLite rowid is shadowed by every alias')
            prefix = quote(alias) + ',' if info[4] == 0 and alias else ''
            records = sorted(digest([typed(v) for v in row]) for row in database.execute('SELECT ' + prefix + '* FROM ' + quote(name)))
            rows += len(records); contents.append([name, [[typed(v) for v in row] for row in columns], records])
        if not tables: raise RuntimeError('empty SQLite database is not a recovery point')
        return {'tables': len(tables), 'rows': rows, 'schema_sha256': digest([[typed(v) for v in row] for row in schema]),
                'data_sha256': digest(contents), 'metadata_sha256': digest([[name, [typed(v) for v in values]] for name, values in metadata])}
    finally:
        database.close()


def tree(root):
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError('recovery tree has an unsafe ancestry')
    result = {'directories': [], 'files': {}}
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            if not stat.S_ISDIR(path.lstat().st_mode): raise RuntimeError('recovery directory is not regular')
            result['directories'].append(str(path.relative_to(root)))
        for name in files:
            path = Path(parent) / name; before = shared.file_identity(path)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as source:
                checksum = hashlib.file_digest(source, 'sha256').hexdigest()
            if shared.file_identity(path) != before: raise RuntimeError('file changed during inventory')
            result['files'][str(path.relative_to(root))] = {'bytes': before[2], 'sha256': checksum}
    result['directories'].sort()
    return result


def copy_tree(source, target, skip=()):
    if not source.is_dir() or any(p.is_symlink() for p in (source, *source.parents)):
        raise RuntimeError('copy source has an unsafe ancestry')
    target.mkdir(mode=0o700)
    for parent, directories, files in os.walk(source, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            if not stat.S_ISDIR(path.lstat().st_mode): raise RuntimeError('source directory is not regular')
            (target / path.relative_to(source)).mkdir(mode=0o700)
        for name in files:
            path = Path(parent) / name
            if str(path.relative_to(source)) not in skip:
                shared.copy_file(path, target / path.relative_to(source), shared.file_identity(path))


def source_identity():
    common.require_host('pikachu')
    runtime = json.loads(common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', CONTAINER]).stdout)
    status = runtime['status']; labels = status['labels']
    if (status['state'] != 'CONTAINER_RUNNING' or status['imageRef'].split('@')[-1] != IMAGE.split('@')[-1] or
            labels.get('io.kubernetes.pod.uid') != POD or labels.get('io.kubernetes.pod.namespace') != 'grafana' or
            labels.get('io.kubernetes.container.name') != 'grafana' or runtime['info']['pid'] != PID or
            runtime['info']['runtimeSpec']['process']['user'] != {'uid': 472, 'gid': 472, 'additionalGids': [0, 472]}):
        raise RuntimeError('reviewed Grafana runtime changed')
    process = shared.process_identity(PID)
    if process['exe'] != '/usr/share/grafana/bin/grafana' or POD.replace('-', '_') not in process['cgroup']:
        raise RuntimeError('reviewed Grafana process changed')
    tasks = common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', CONTAINER]).stdout.decode().splitlines()[1:]
    if [int(line.split()[0]) for line in tasks if line.strip()] != [PID]:
        raise RuntimeError('Grafana has an unreviewed additional writer process')
    root = Path('/proc') / str(PID) / 'root'; mounts = {}
    for name, (volume, target) in VOLUMES.items():
        path = ROOT / volume
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise RuntimeError('reviewed emptyDir ancestry changed')
        a, b = path.stat(), (root / target.lstrip('/')).stat()
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino): raise RuntimeError('reviewed emptyDir mount changed')
        mounts[name] = {'device': a.st_dev, 'inode': a.st_ino}
    return {'pod_uid': POD, 'container_id': CONTAINER, 'image': IMAGE, 'process': process, 'mounts': mounts}


def write_json(path, value):
    with path.open('xb') as output:
        os.fchmod(output.fileno(), 0o600); output.write(common.canonical(value)); output.flush(); os.fsync(output.fileno())


def capture(run_id):
    common.private_root(); before = source_identity()
    expected_bytes = sum(shared.file_identity(Path(parent) / name)[2]
                         for volume, _ in VOLUMES.values() for parent, _, names in os.walk(ROOT / volume)
                         for name in names)
    if shutil.disk_usage(common.ROOT).free <= expected_bytes:
        raise RuntimeError('actual recovery capacity cannot hold the source files')
    point = common.ROOT / ('grafana-' + common.run_identifier(run_id)); point.mkdir(mode=0o700)
    root = Path('/proc') / str(PID) / 'root'
    ini = configparser.ConfigParser(interpolation=None); ini.read(root / 'etc/grafana/grafana.ini')
    environment = dict(item.split(b'=', 1) for item in (Path('/proc') / str(PID) / 'environ').read_bytes().split(b'\0') if b'=' in item)
    if (any(k.startswith(b'GF_SECURITY_ENCRYPTION') for k in environment) or b'GF_SECURITY_SECRET_KEY' in environment or
            (ini.has_section('security') and any(key in ini['security'] for key in ('secret_key', 'encryption_provider')))):
        raise RuntimeError('reviewed default Grafana encryption contract changed')
    config = point / 'config'; config.mkdir(mode=0o700)
    for name, path in CONFIG.items():
        original = root / path.lstrip('/')
        shared.copy_file(original, config / name, shared.file_identity(original))
    # Stage static plugins before pausing; the complete stopped-source comparison still covers every file.
    for name, (volume, _) in VOLUMES.items():
        copy_tree(ROOT / volume, point / name, skip=('grafana.db',) if name == 'data' else ())
    marker = point / 'watchdog-fired'
    with shared.frozen(before['process'], marker) as pause:
        if source_identity() != before: raise RuntimeError('Grafana source changed before capture')
        snapshot = fingerprint(ROOT / 'storage/grafana.db')
        database = ROOT / 'storage/grafana.db'
        shared.copy_file(database, point / 'data/grafana.db', shared.file_identity(database))
        inventories = {name: tree(ROOT / volume) for name, (volume, _) in VOLUMES.items()}
        if inventories != {name: tree(point / name) for name in VOLUMES}:
            raise RuntimeError('complete stopped-source copy differs')
        if fingerprint(point / 'data/grafana.db') != snapshot: raise RuntimeError('protected SQLite fingerprint differs')
        for name, path in CONFIG.items():
            original = root / path.lstrip('/')
            if hashlib.sha256(original.read_bytes()).hexdigest() != hashlib.sha256((config / name).read_bytes()).hexdigest():
                raise RuntimeError('source configuration changed during capture')
        if source_identity() != before: raise RuntimeError('Grafana source changed during capture')
    if source_identity() != before or marker.exists(): raise RuntimeError('Grafana source did not resume unchanged')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'source': before, 'trees': inventories,
                'config': tree(config), 'snapshot': snapshot, 'pause': pause, 'created_at_ns': time.time_ns(),
                'default_image_encryption': True}
    write_json(point / 'verified.json', manifest)
    checksum = hashlib.sha256((point / 'verified.json').read_bytes()).hexdigest()
    verify(point, checksum)
    return {'point': str(point), 'manifest_sha256': checksum, 'snapshot': snapshot, 'pause': pause,
            'files': sum(len(v['files']) for v in inventories.values()),
            'bytes': sum(v['bytes'] for t in inventories.values() for v in t['files'].values()),
            'original_process_resumed': True}


def verify(point, checksum):
    common.source_record('verified.json', point / 'verified.json')
    raw = (point / 'verified.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum: raise RuntimeError('exact protected manifest changed')
    manifest = json.loads(raw)
    if (manifest['format'] != 1 or manifest['cluster_uid'] != common.CLUSTER_UID or manifest['source']['pod_uid'] != POD or
            manifest['source']['image'] != IMAGE or set(manifest['trees']) != set(VOLUMES) or
            not manifest['default_image_encryption'] or set(p.name for p in point.iterdir()) != {*VOLUMES, 'config', 'verified.json'}):
        raise RuntimeError('protected Grafana source or file set changed')
    if any(p.is_symlink() for p in (point, *point.parents)) or stat.S_IMODE(point.stat().st_mode) != 0o700:
        raise RuntimeError('protected point ancestry or permissions changed')
    for name in [*VOLUMES, 'config']:
        actual = tree(point / name); expected = manifest['config'] if name == 'config' else manifest['trees'][name]
        if actual != expected: raise RuntimeError('protected file hashes changed')
        for relative in ['', *actual['directories']]:
            directory = point / name / relative
            if directory.stat().st_uid != os.geteuid() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise RuntimeError('protected directory ownership or permissions changed')
        for relative in actual['files']:
            p = point / name / relative
            if p.stat().st_uid != os.geteuid() or stat.S_IMODE(p.stat().st_mode) != 0o600:
                raise RuntimeError('protected file ownership changed')
    if fingerprint(point / 'data/grafana.db') != manifest['snapshot']: raise RuntimeError('protected database changed')
    return manifest


def require_container(value, scratch):
    host = value['HostConfig']
    environment = dict(item.split('=', 1) for item in value['Config'].get('Env', []) if '=' in item)
    bind_mounts = [m for m in value['Mounts'] if m['Type'] == 'bind']
    other_mounts = [m for m in value['Mounts'] if m['Type'] != 'bind']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 256, 'Memory': 1073741824, 'NanoCpus': 1000000000}
    mounts = {(str(scratch / name), target, True) for name, (_, target) in VOLUMES.items()}
    mounts |= {(str(scratch / 'config/grafana.ini'), CONFIG['grafana.ini'], False),
               (str(scratch / 'config/provider.yaml'), CONFIG['provider.yaml'], False)}
    if (value['Config']['Image'] != IMAGE or value['Config']['User'] != '472:472' or
            value['Config'].get('Entrypoint') != ENTRYPOINT or value['Config'].get('Cmd') != SERVER_ARGS or
            {k: v for k, v in environment.items() if k.startswith('GF_')} != ENVIRONMENT or
            host.get('Tmpfs') != {'/tmp': 'rw,nosuid,nodev'} or
            value['Config'].get('Labels', {}).get(LABEL) != scratch.name or
            any(host.get(k) != v for k, v in expected.items()) or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            len(bind_mounts) != len(mounts) or len(other_mounts) > 1 or
            any(m['Type'] != 'tmpfs' or m.get('Source', '') != '' or m['Destination'] != '/tmp' or not m['RW'] for m in other_mounts) or
            {(m['Source'], m['Destination'], m['RW']) for m in bind_mounts} != mounts):
        raise RuntimeError('Grafana restore isolation changed')


def restore(point, checksum):
    manifest = verify(point, checksum)
    if shutil.disk_usage(common.ROOT).free <= sum(v['bytes'] for t in manifest['trees'].values() for v in t['files'].values()):
        raise RuntimeError('actual restore capacity cannot hold the protected copy')
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip(): raise RuntimeError('owned Grafana restore already active')
    before_images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    import tempfile
    scratch = Path(tempfile.mkdtemp(prefix='grafana-restore-', dir=common.ROOT)); scratch.chmod(0o700)
    container = image_id = None; result = {'accepted': False, 'manifest_sha256': checksum}
    try:
        for name in [*VOLUMES, 'config']: copy_tree(point / name, scratch / name)
        if fingerprint(scratch / 'data/grafana.db') != manifest['snapshot']: raise RuntimeError('restore copy differs')
        common.docker('pull', IMAGE); image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]; image_id = image['Id']
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or image['Config'].get('Volumes') or
                not any(d.split('@')[-1] == IMAGE.split('@')[-1] and d.split('@')[0] in ('grafana/grafana', 'docker.io/grafana/grafana') for d in image.get('RepoDigests', []))):
            raise RuntimeError('exact Grafana image contract changed')
        for parent, _, files in os.walk(scratch):
            os.chown(parent, 472, 472)
            for name in files: os.chown(Path(parent) / name, 472, 472)
        args = ['create', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--ipc=private', '--user=472:472', '--pids-limit=256', '--memory=1g', '--cpus=1',
                '--label=' + LABEL + '=' + scratch.name, '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/usr/share/grafana/bin/grafana']
        for name, (_, target) in VOLUMES.items(): args.append('--mount=type=bind,source=' + str(scratch / name) + ',target=' + target)
        for name, target in CONFIG.items(): args.append('--mount=type=bind,source=' + str(scratch / 'config' / name) + ',target=' + target + ',readonly')
        for name, value in ENVIRONMENT.items(): args.extend(['--env', name + '=' + value])
        container = common.docker(*args, IMAGE, *SERVER_ARGS).stdout.decode().strip()
        require_container(common.inspect(container), scratch); common.docker('start', container)
        state = common.inspect(container); require_container(state, scratch); pid = str(state['State']['Pid'])
        common.require_network(json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'link']).stdout),
                               json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'route']).stdout))
        if common.command(['nsenter', '-t', pid, '-n', 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('isolated Grafana has a production route')
        readiness_deadline = time.monotonic() + 600
        while True:
            state = common.inspect(container)
            if not state['State']['Running']: raise RuntimeError('native Grafana restore exited')
            code = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health',timeout=5))))"
            response = common.command(['nsenter', '-t', pid, '-n', 'python3', '-B', '-c', code], check=False)
            if response.returncode == 0:
                health = json.loads(response.stdout)
                if health.get('database') != 'ok' or health.get('version') != '12.3.1': raise RuntimeError('native Grafana database/version health differs')
                break
            if time.monotonic() >= readiness_deadline: raise RuntimeError('native Grafana restore readiness exceeded 600 seconds')
            time.sleep(1)
        require_container(common.inspect(container), scratch); common.docker('stop', '--time=30', container)
        if common.inspect(container)['State']['Running']: raise RuntimeError('native Grafana restore did not stop')
        stopped_snapshot = fingerprint(scratch / 'data/grafana.db')
        result.update(accepted=True, snapshot=manifest['snapshot'], native_version=health['version'], native_database_health='ok',
                      stopped_restore_snapshot=stopped_snapshot, native_shutdown_completed=True,
                      network_none=True, production_routes_absent=True, original_unmounted=True,
                      sso_datasources_alert_delivery_unqualified=True)
    finally:
        if container:
            require_container(common.inspect(container), scratch); common.docker('rm', '--force', '--volumes', container)
            if common.docker('inspect', container, check=False).returncode == 0: raise RuntimeError('owned Grafana restore container remains')
        if image_id and image_id not in before_images:
            if common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip(): raise RuntimeError('new image has another consumer; retained')
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', IMAGE, check=False).returncode == 0: raise RuntimeError('new unused Grafana image remains')
        shutil.rmtree(scratch); verify(point, checksum)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'owned_container_absent': True,
                             'protected_hashes_unchanged': True, 'new_unused_image_removed': bool(image_id and image_id not in before_images)}
        print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('mode', choices=('capture', 'restore'))
    parser.add_argument('--run-id', type=common.run_identifier, required=True); parser.add_argument('--manifest'); args = parser.parse_args()
    os.umask(0o077)
    def cancel(_number, _frame): raise RuntimeError('owned Grafana recovery interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, cancel)
    common.require_host('pikachu'); common.private_root()
    if args.mode == 'capture': print(json.dumps(capture(args.run_id)), flush=True)
    else:
        if not re.fullmatch('[a-f0-9]{64}', args.manifest or ''): parser.error('restore requires exact manifest hash')
        restore(common.ROOT / ('grafana-' + args.run_id), args.manifest)


if __name__ == '__main__': main()
