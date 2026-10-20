"""Inspect historical PostgreSQL control metadata without starting a server."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import pointguide_files_recovery as retained


common = retained.common
IMAGE = 'docker.io/bitnamilegacy/postgresql@sha256:233f361c5819c180b600d110d7da953bea6f1a00764752643ffb7b78ba85c628'
POINT = common.ROOT / 'gitea-postgres-complete-files-20261020-183719'
CHECKSUM = 'b38f04da4fa7e574b1d77a4f082d73edb308c559718b67caccb434d10617b46e'
LABEL = 'io.eaglepass.gitea-postgres-control'
ENTRY = '/opt/bitnami/postgresql/bin/pg_controldata'
ENV = {'LC_ALL': 'C', 'LANG': 'C', 'PG_COLOR': 'never'}
TMPFS = {'/tmp': 'rw,nosuid,nodev,uid=1001,gid=1001,mode=1777'}


def parse_control(raw):
    try:
        fields = {}
        for line in raw.decode('ascii').splitlines():
            key, separator, value = line.partition(':')
            if not separator or key in fields or key in {'WARNING', 'ERROR', 'FATAL', 'PANIC'}:
                raise ValueError()
            fields[key] = value.strip()
        fixed = {'pg_control version number': '1300', 'Catalog version number': '202307071',
                 'Database block size': '8192', 'WAL block size': '8192',
                 'Bytes per WAL segment': '16777216'}
        if any(fields.get(key) != value for key, value in fixed.items()):
            raise ValueError()
        if fields['Database cluster state'] not in {'in production', 'shut down', 'shut down in recovery',
                                                   'in crash recovery', 'in archive recovery'}:
            raise ValueError()
        if fields['Data page checksum version'] not in {'0', '1'}:
            raise ValueError()
        if not re.fullmatch('[0-9]+', fields['Database system identifier']):
            raise ValueError()
        for key in ('Latest checkpoint location', "Latest checkpoint's REDO location"):
            if not re.fullmatch('[0-9A-F]+/[0-9A-F]+', fields[key]):
                raise ValueError()
        if not re.fullmatch('[0-9A-F]{24}', fields["Latest checkpoint's REDO WAL file"]):
            raise ValueError()
    except (ValueError, KeyError, UnicodeError):
        raise RuntimeError('native PostgreSQL control metadata differs') from None
    checkpoint = {key: value for key, value in fields.items() if 'checkpoint' in key.lower()}
    return {'control_version': 1300, 'catalog_version': 202307071,
            'cluster_state': fields['Database cluster state'],
            'data_page_checksum_version': int(fields['Data page checksum version']),
            'system_identifier_sha256': hashlib.sha256(fields['Database system identifier'].encode()).hexdigest(),
            'checkpoint_sha256': hashlib.sha256(common.canonical(checkpoint)).hexdigest(),
            'complete_control_output_sha256': hashlib.sha256(raw).hexdigest()}


def mounts(scratch, volumes):
    return {'/recovered': str(scratch / 'copy'),
            **{name: str(scratch / ('volume-' + str(n))) for n, name in enumerate(volumes)}}


def arguments(scratch, volumes, run_id):
    args = ['create', '--network=none', '--read-only', '--log-driver=none', '--no-healthcheck',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=1001:1001',
            '--workdir=/tmp', '--pids-limit=64', '--memory=512m', '--cpus=1',
            '--label=' + LABEL + '=' + run_id, '--tmpfs=/tmp:' + TMPFS['/tmp']]
    for key, value in ENV.items():
        args.extend(['--env', key + '=' + value])
    for destination, source in mounts(scratch, volumes).items():
        args.extend(['--mount', 'type=bind,source=' + source + ',target=' + destination + ',readonly'])
    return [*args, '--entrypoint=' + ENTRY, IMAGE, '/recovered/data']


def require_container(value, scratch, volumes, run_id, image_id):
    config, host = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 64, 'Memory': 536870912,
                'NanoCpus': 1000000000, 'Tmpfs': TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}}}
    environment = dict(item.split('=', 1) for item in config.get('Env', []))
    actual = value['Mounts']
    if (config['Image'] != IMAGE or value['Image'] != image_id or config['User'] != '1001:1001' or
            config['Entrypoint'] != [ENTRY] or config['Cmd'] != ['/recovered/data'] or
            config.get('WorkingDir') != '/tmp' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Healthcheck', {}).get('Test') != ['NONE'] or
            any(environment.get(key) != item for key, item in ENV.items()) or
            any(host.get(key) != item for key, item in expected.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(key) for key in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd')) or
            len(actual) != len(mounts(scratch, volumes)) or
            any(item.get('Type') != 'bind' or item['RW'] for item in actual) or
            {item['Destination']: item['Source'] for item in actual} != mounts(scratch, volumes)):
        raise RuntimeError('native PostgreSQL copied-control isolation differs')


def operation(scratch, volumes, run_id, image_id):
    container = None
    try:
        container = common.docker(*arguments(scratch, volumes, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('native PostgreSQL container identity missing')
        require_container(common.inspect(container), scratch, volumes, run_id, image_id)
        response = common.docker('start', '--attach', container, check=False)
        value = common.inspect(container)
        require_container(value, scratch, volumes, run_id, image_id)
        state = value['State']
        if response.returncode or state['Running'] or state['ExitCode'] or state.get('OOMKilled') or response.stderr:
            raise RuntimeError('native PostgreSQL control check failed: ' + json.dumps({
                'exit': state['ExitCode'], 'transport': response.returncode, 'oom': state.get('OOMKilled'),
                'output_bytes': len(response.stdout) + len(response.stderr), 'raw_output_discarded': True}))
        return parse_control(response.stdout)
    finally:
        if container:
            require_container(common.inspect(container), scratch, volumes, run_id, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned PostgreSQL control container remains')


def restore(run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    value = retained.verify(POINT, CHECKSUM, 'gitea')
    if (value['tree'].get('data/PG_VERSION', {}).get('sha256') !=
            'e6c21e8d260fe71882debdb339d2402a2ca7648529bc2303f48649bce0380017' or
            value['tree'].get('data/global/pg_control', {}).get('bytes') != 8192 or
            any(record['kind'] == 'symlink' for record in value['tree'].values())):
        raise RuntimeError('protected PostgreSQL control layout differs')
    retained.require_capacity(common.ROOT, value['tree'], 2)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned PostgreSQL control recovery already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-postgres-control-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'manifest_sha256': CHECKSUM, 'image': IMAGE, 'copies': []}
    try:
        common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {IMAGE, IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', [])) or
                set(volumes) != {'/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d'}):
            raise RuntimeError('exact native PostgreSQL image or declared volumes differ')
        retained.require_capacity(common.ROOT, value['tree'], 2)
        for number in range(2):
            work = scratch / str(number)
            work.mkdir(mode=0o700)
            retained.materialize(POINT, work / 'copy', value)
            for source in mounts(work, volumes).values():
                if source != str(work / 'copy'):
                    Path(source).mkdir(mode=0o755)
            result['copies'].append(operation(work, volumes, run_id, image_id))
            if retained.snapshot(work / 'copy')[0] != value['tree']:
                raise RuntimeError('native control reader changed copied bytes or metadata')
        if result['copies'][0] != result['copies'][1]:
            raise RuntimeError('independent PostgreSQL control fingerprints differ')
        result.update(accepted=True, independent_copies=2, read_only=True, network='none',
                      server_and_sql_not_started=True, consistent_backup_and_data_integrity_unqualified=True)
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
            raise RuntimeError('owned PostgreSQL control container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused PostgreSQL control image remains')
        retained.verify(POINT, CHECKSUM, 'gitea')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'protected_original_unchanged': True, 'allocated_bytes_removed': allocated}
        retained.files.write_json(POINT / ('control-native-' + run_id + '.json'), result)
    return result
