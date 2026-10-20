#!/usr/bin/env python3
"""Protect Outline's reviewed PostgreSQL18 database without changing its writers."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zlib

import etcd_recovery as common
import mariadb_recovery as protected
import point_postgres_recovery as postgres

IMAGE = 'docker.io/library/postgres@sha256:47855c76129d1383e7efc66a1a776e33c9171b3450e95deb822119e02eaab592'
IDENTITY = ['b46072f5-1edd-4b93-8dc0-27bc2f89cf37', 'c361fc29-fa98-425e-8551-df21704e2c87',
            '36cb3442-3bf9-4ccd-a7be-4edd211f361a', '409b7753-b5c5-424b-8709-643290566685']
CONTAINER = 'a79db0b9828837c44b4a95b628db5439be3861a0fa30481d7ecc606edba95dca'
SECRET_UID = 'f18ca58e-61d7-4a22-8ae9-ca2d7d709bcb'
HANDLE_SHA256 = 'ea8ddaabcfccef059cbb2a7da0a44cd5e00dee177daacba9b2cb5831503c5ec3'
LABEL = 'io.eaglepass.outline-postgres-recovery-103'
MOUNT = '/var/lib/postgresql'
FEATURES = {'version': '18.4 (Debian 18.4-1.pgdg12+1)', 'database': 'outline', 'role': 'outline',
            'encoding': 'UTF8', 'locale': ['en_US.utf8', 'en_US.utf8', 'c'], 'user_tables': 42,
            'foreign_tables': 0, 'large_objects': 0, 'extensions': ['pg_trgm', 'plpgsql', 'unaccent', 'uuid-ossp'],
            'custom_tablespaces': 0, 'databases': ['outline', 'postgres'], 'roles': ['outline'],
            'prepared_transactions': 0, 'subscriptions': 0, 'replication_slots': 0}


def source_identity():
    def get(*args):
        return json.loads(common.command([os.environ.get('KUBECTL', 'kubectl'), 'get', *args, '-o=json']).stdout)
    if get('namespace', 'kube-system')['metadata']['uid'] != common.CLUSTER_UID: raise RuntimeError('wrong source cluster')
    pod = get('pod', 'outline-postgres-0', '-n', 'outline'); containers = pod['spec']['containers']
    statuses = pod['status'].get('containerStatuses', [])
    if (len(containers) != 1 or containers[0]['name'] != 'main' or len(statuses) != 1 or
            not statuses[0]['ready'] or statuses[0]['restartCount'] != 0 or statuses[0]['imageID'] != IMAGE or
            statuses[0]['containerID'] != 'containerd://' + CONTAINER or pod['spec']['nodeName'] != 'pikachu' or
            pod['metadata'].get('deletionTimestamp')): raise RuntimeError('reviewed source runtime changed')
    expected = {'POSTGRES_USER': 'postgres-user', 'POSTGRES_PASSWORD': 'postgres-password', 'POSTGRES_DB': 'postgres-db'}
    refs = {e['name']: e.get('valueFrom', {}).get('secretKeyRef') for e in containers[0].get('env', []) if e['name'] in expected}
    if refs != {k: {'key': v, 'name': 'secrets'} for k, v in expected.items()}:
        raise RuntimeError('declared source credential references changed')
    if get('secret', 'secrets', '-n', 'outline')['metadata']['uid'] != SECRET_UID:
        raise RuntimeError('declared source credential identity changed')
    mounts = [m for m in containers[0]['volumeMounts'] if m['mountPath'] == MOUNT]
    if len(mounts) != 1: raise RuntimeError('database mount changed')
    volume = next(v for v in pod['spec']['volumes'] if v['name'] == mounts[0]['name'])
    if volume.get('persistentVolumeClaim') != {'claimName': 'outline'}: raise RuntimeError('database claim changed')
    claim = get('pvc', 'outline', '-n', 'outline'); pv = get('pv', claim['spec']['volumeName'])
    owners = [o for o in pod['metadata']['ownerReferences'] if o.get('controller') and o['kind'] == 'StatefulSet']
    identity = [pod['metadata']['uid'], owners[0]['uid'] if len(owners) == 1 else None, claim['metadata']['uid'], pv['metadata']['uid']]
    if (identity != IDENTITY or claim['status']['phase'] != 'Bound' or claim['spec']['storageClassName'] != 'standard-rwo' or
            pv['spec'].get('csi', {}).get('driver') != 'rook-ceph.rbd.csi.ceph.com' or
            postgres.digest(pv['spec']['csi']['volumeHandle'].encode()) != HANDLE_SHA256 or
            claim['metadata'].get('deletionTimestamp') or pv['metadata'].get('deletionTimestamp')):
        raise RuntimeError('reviewed database storage ownership changed')
    return identity


def source_client(*args, database='outline'):
    return [os.environ.get('KUBECTL', 'kubectl'), 'exec', '-i', '-n', 'outline', 'outline-postgres-0', '-c', 'main', '--',
            'sh', '-ceu', 'export PGPASSWORD="$POSTGRES_PASSWORD" PGUSER="$POSTGRES_USER" PGDATABASE=' + shlex.quote(database) +
            ' PGOPTIONS="-c default_transaction_read_only=on -c lock_timeout=10s -c timezone=UTC"; exec ' + shlex.join(args) + ' -h 127.0.0.1']


def source_metadata():
    def sql(query, database='outline'):
        return common.command(source_client('psql', '-X', '-Atq', '-v', 'ON_ERROR_STOP=1', '-c', query, database=database)).stdout
    features = json.loads(sql(postgres.FEATURE_SQL))
    if features != FEATURES: raise RuntimeError('reviewed PostgreSQL features changed')
    for database in ('postgres', 'template1'):
        if sql(postgres.EMPTY_SQL, database).splitlines() != [b'0', b'0']:
            raise RuntimeError('another database contains uncovered application data')
    schema = common.command(source_client('pg_dump', '--schema-only', '--no-comments')).stdout
    return {'features': features, 'schema_sha256': postgres.digest(postgres.normalized_dump(schema)),
            'roles_sha256': sql(postgres.ROLE_SQL).decode().strip()}


def point_path(run_id):
    common.require_host('pikachu'); common.private_root()
    point = common.ROOT / ('outline-postgres-' + common.run_identifier(run_id))
    if any(p.is_symlink() for p in (point, *point.parents)): raise RuntimeError('unsafe protected point ancestry')
    return point


def remote(mode, run_id, *extra):
    code = 'import base64,sys,types; '
    for name in ('etcd_recovery', 'mariadb_recovery', 'point_postgres_recovery'):
        encoded = base64.b64encode(Path(__file__).with_name(name + '.py').read_bytes()).decode()
        code += 'm=types.ModuleType(' + repr(name) + ');sys.modules[' + repr(name) + ']=m;exec(base64.b64decode(' + repr(encoded) + '),m.__dict__);'
    code += 'exec(base64.b64decode(' + repr(base64.b64encode(Path(__file__).read_bytes()).decode()) + '))'
    return [*common.SSH[:-1], '-o', 'ControlMaster=no', common.SSH[-1],
            shlex.join(['python3', '-B', '-c', postgres.compressed_program(code), mode, '--run-id', run_id, *extra])]


def receive(run_id, name):
    if name not in ('globals.sql', 'database.dump'): raise RuntimeError('unreviewed archive filename')
    point = point_path(run_id)
    if name == 'globals.sql': point.mkdir(mode=0o700)
    if point.stat().st_uid != 0 or stat.S_IMODE(point.stat().st_mode) != 0o700: raise RuntimeError('unprotected point')
    with (point / name).open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        for block in iter(lambda: sys.stdin.buffer.read(1048576), b''):
            if shutil.disk_usage(point).free < len(block): raise RuntimeError('actual capacity exhausted; protected partial retained')
            output.write(block)
        output.flush(); os.fsync(output.fileno())
    value = protected.file_digest(point / name)
    if not value['bytes']: raise RuntimeError('empty export; protected partial retained')
    return value


def require_manifest(value):
    if (value.get('format') != 1 or value.get('cluster_uid') != common.CLUSTER_UID or value.get('image') != IMAGE or
            value.get('identity') != IDENTITY or value.get('before') != value.get('after') or
            value.get('before', {}).get('features') != FEATURES or value.get('role_passwords_omitted') is not True or
            any(not re.fullmatch('[a-f0-9]{64}', value.get('before', {}).get(k, '')) for k in ('schema_sha256', 'roles_sha256')) or
            value.get('writers_quiesced') is not False or set(value.get('files', {})) != {'globals.sql', 'database.dump'} or
            any(type(v.get('bytes')) is not int or v['bytes'] <= 0 or not re.fullmatch('[a-f0-9]{64}', v.get('sha256', '')) for v in value['files'].values())):
        raise RuntimeError('protected source/export contract changed')


def verify(point, checksum):
    protected.protected_file(point / 'verified.json'); raw = (point / 'verified.json').read_bytes(); value = json.loads(raw)
    if postgres.digest(raw) != checksum: raise RuntimeError('exact protected manifest changed')
    require_manifest(value)
    if point.stat().st_uid != 0 or stat.S_IMODE(point.stat().st_mode) != 0o700: raise RuntimeError('unprotected point')
    if any(protected.file_digest(point / n) != v for n, v in value['files'].items()): raise RuntimeError('protected archive changed')
    return value


def capture(run_id):
    identity = source_identity(); before = source_metadata(); files = {}
    for name, args in (('globals.sql', ('pg_dumpall', '--globals-only', '--no-role-passwords', '--no-tablespaces')),
                       ('database.dump', ('pg_dump', '--format=custom', '--create', '--lock-wait-timeout=10s'))):
        producer = receiver = None
        try:
            producer = subprocess.Popen(source_client(*args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            receiver = subprocess.Popen(remote('receive', run_id, '--file', name), stdin=producer.stdout,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            producer.stdout.close(); output, _ = receiver.communicate(); _, errors = producer.communicate()
            if producer.returncode or receiver.returncode or errors: raise RuntimeError('export failed or warned; protected partial retained')
            files[name] = json.loads(output)
        finally:
            for child in (receiver, producer):
                if child is not None and child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
    if source_identity() != identity: raise RuntimeError('source identity changed during export')
    manifest = {'format': 1, 'cluster_uid': common.CLUSTER_UID, 'image': IMAGE, 'identity': identity, 'before': before,
                'after': source_metadata(), 'files': files, 'role_passwords_omitted': True, 'writers_quiesced': False}
    require_manifest(manifest)
    return json.loads(common.command(remote('finalize', run_id, '--manifest', json.dumps(manifest))).stdout)


def require_container(value, scratch, run_id):
    host = value['HostConfig']; config = value['Config']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'PidsLimit': 128, 'Memory': 1073741824, 'NanoCpus': 1000000000, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'}}
    if (config['Image'] != IMAGE or config['User'] != '999:999' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Entrypoint') != ['/bin/sh'] or config.get('Cmd') != ['-c', 'exec sleep 2147483647'] or
            any(h in e for e in config.get('Env', []) for h in ('POSTGRES_PASSWORD=', 'PGPASSWORD=')) or
            any(host.get(k) != v for k, v in expected.items()) or host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            len(value['Mounts']) != 1 or value['Mounts'][0].get('Type') != 'bind' or
            value['Mounts'][0].get('Source') != str(scratch / 'data') or value['Mounts'][0].get('Destination') != MOUNT or
            value['Mounts'][0].get('RW') is not True): raise RuntimeError('native restore isolation changed')


def restore(run_id, checksum):
    point = point_path(run_id); manifest = verify(point, checksum)
    if shutil.disk_usage(common.ROOT).free <= sum(v['bytes'] for v in manifest['files'].values()):
        raise RuntimeError('actual restore capacity cannot hold the protected archives')
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip(): raise RuntimeError('owned restore already active')
    before_images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='outline-restore-', dir=common.ROOT)); scratch.chmod(0o700)
    container = image_id = None; result = {'accepted': False, 'manifest_sha256': checksum}
    try:
        data = scratch / 'data'; data.mkdir(mode=0o700); os.chown(data, 999, 999)
        for name in manifest['files']:
            shutil.copyfile(point / name, data / name); (data / name).chmod(0o600); os.chown(data / name, 999, 999)
            if protected.file_digest(point / name) != manifest['files'][name]: raise RuntimeError('protected source changed during copy')
            if hashlib.sha256((data / name).read_bytes()).hexdigest() != manifest['files'][name]['sha256']:
                raise RuntimeError('scratch archive differs')
        common.docker('pull', IMAGE); image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]; image_id = image['Id']
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or set(image['Config'].get('Volumes') or {}) != {MOUNT} or
                IMAGE not in {protected.canonical_reference(r) for r in image.get('RepoDigests', [])}):
            raise RuntimeError('exact native image contract changed')
        container = common.docker('create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=999:999',
                                  '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=128', '--cpus=1', '--memory=1g',
                                  '--label=' + LABEL + '=' + run_id, '--tmpfs=/tmp:rw,nosuid,nodev',
                                  '--mount=type=bind,source=' + str(data) + ',target=' + MOUNT, '--entrypoint=/bin/sh', IMAGE,
                                  '-c', 'exec sleep 2147483647').stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container): raise RuntimeError('invalid owned container identity')
        require_container(common.inspect(container), scratch, run_id); common.docker('start', container)
        state = common.inspect(container); require_container(state, scratch, run_id)
        net = ['nsenter', '-t', str(state['State']['Pid']), '-n', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
                               sum((json.loads(common.command([*net, 'ip', f, '-j', 'route', 'show', 'table', 'all']).stdout) for f in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('restore can route to production')
        def execute(*args, input=None):
            response = subprocess.run(['docker', 'exec', '-i', container, *args], input=input, capture_output=True)
            if response.returncode:
                protected.write_json(point / ('diagnostic-' + str(time.time_ns()) + '.json'),
                                     {'command': args[0], 'exit': response.returncode, 'stdout': response.stdout.decode(errors='replace'),
                                      'stderr': response.stderr.decode(errors='replace')})
                raise RuntimeError('native command failed: ' + args[0] + '; classes=' + ','.join(postgres.error_class(response.stderr)))
            return response.stdout
        if execute('postgres', '--version').strip() != b'postgres (PostgreSQL) 18.4 (Debian 18.4-1.pgdg12+1)':
            raise RuntimeError('native executable version changed')
        pgdata = MOUNT + '/restored'
        execute('initdb', '-D', pgdata, '--username=' + postgres.ADMIN, '--auth-local=trust', '--auth-host=reject',
                '--encoding=UTF8', '--locale=en_US.utf8', '--data-checksums')
        execute('pg_ctl', '-D', pgdata, '-l', '/tmp/recovery.log', '-o',
                "-c listen_addresses='' -c unix_socket_directories=/tmp -c unix_socket_permissions=0700", '-w', 'start')
        execute('createdb', '-h', '/tmp', '-U', postgres.ADMIN, postgres.CONTROL)
        execute('psql', '-X', '-h', '/tmp', '-U', postgres.ADMIN, '-d', postgres.CONTROL, '-v', 'ON_ERROR_STOP=1', '-f', MOUNT + '/globals.sql')
        execute('pg_restore', '-h', '/tmp', '-U', postgres.ADMIN, '--exit-on-error', '--create', '-d', postgres.CONTROL, MOUNT + '/database.dump')
        schema = execute('pg_dump', '-h', '/tmp', '-U', postgres.ADMIN, '-d', 'outline', '--schema-only', '--no-comments')
        if postgres.digest(postgres.normalized_dump(schema)) != manifest['before']['schema_sha256']:
            raise RuntimeError('complete native schema differs')
        def sql(query):
            return execute('psql', '-X', '-h', '/tmp', '-U', postgres.ADMIN, '-d', 'outline', '-Atq', '-v', 'ON_ERROR_STOP=1', input=query.encode())
        if sql(postgres.ROLE_SQL).decode().strip() != manifest['before']['roles_sha256']:
            raise RuntimeError('password-free authorization differs')
        archived = execute('pg_restore', '--data-only', '--no-comments', '--file=-', MOUNT + '/database.dump')
        restored = execute('pg_dump', '-h', '/tmp', '-U', postgres.ADMIN, '-d', 'outline', '--data-only', '--no-comments')
        comparison = postgres.data_diagnostic(archived, restored)
        if not all(comparison[k] for k in ('copy_multiset_equal', 'session_settings_equal', 'sequence_commands_equal')):
            raise RuntimeError('complete native logical records differ')
        counts = [int(n) for n in sql(postgres.ROW_SQL).splitlines()]
        if len(counts) != FEATURES['user_tables']: raise RuntimeError('native relation count differs')
        features = json.loads(sql(postgres.FEATURE_SQL))
        if any(features[k] != FEATURES[k] for k in ('version', 'database', 'encoding', 'locale', 'user_tables', 'extensions',
                                                   'foreign_tables', 'large_objects', 'custom_tablespaces', 'prepared_transactions', 'subscriptions', 'replication_slots')):
            raise RuntimeError('native extensions/locale/features differ')
        require_container(common.inspect(container), scratch, run_id)
        execute('pg_ctl', '-D', pgdata, '-w', '-m', 'fast', 'stop'); execute('test', '!', '-e', pgdata + '/postmaster.pid')
        execute('pg_checksums', '--check', '-D', pgdata); verify(point, checksum)
        result.update(accepted=True, native_version=FEATURES['version'], image=IMAGE, relations=len(counts), rows=sum(counts),
                      schema_matches=True, password_free_authorization_matches=True, data_diagnostic=comparison,
                      extensions_locale_match=True, clean_shutdown=True, offline_checksums_valid=True,
                      production_network_unroutable=True, source_writers_quiesced=False, original_unmounted=True)
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id); common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0: raise RuntimeError('owned restore container remains')
        removed = False
        if image_id and image_id not in before_images:
            if common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip(): raise RuntimeError('new image has another consumer; retained')
            common.docker('image', 'rm', IMAGE); removed = common.docker('image', 'inspect', IMAGE, check=False).returncode != 0
            if not removed: raise RuntimeError('new unused image remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch); verify(point, checksum)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'owned_container_absent': True,
                             'new_unused_image_removed': removed, 'protected_hashes_unchanged': True, 'allocated_bytes_removed': allocated}
        protected.write_json(point / ('restore-' + str(time.time_ns()) + '.json'), result)
        print(json.dumps(result), flush=True)
    return result


def main():
    os.umask(0o077)
    def cancel(_number, _frame): raise InterruptedError('owned Outline recovery interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, cancel)
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('mode', choices=('capture', 'receive', 'finalize', 'restore'))
    parser.add_argument('--run-id', type=common.run_identifier, required=True); parser.add_argument('--file'); parser.add_argument('--manifest'); args = parser.parse_args()
    if args.mode == 'capture': result = capture(args.run_id)
    elif args.mode == 'receive': result = receive(args.run_id, args.file)
    elif args.mode == 'finalize':
        value = json.loads(args.manifest); require_manifest(value); point = point_path(args.run_id)
        if any(protected.file_digest(point / n) != v for n, v in value['files'].items()): raise RuntimeError('export hash changed')
        protected.write_json(point / 'verified.json', value)
        result = {'point': str(point), 'manifest_sha256': postgres.digest(common.canonical(value)), 'files': value['files']}
    else:
        if not re.fullmatch('[a-f0-9]{64}', args.manifest or ''): parser.error('restore requires exact manifest SHA256')
        return 0 if restore(args.run_id, args.manifest)['accepted'] else 1
    print(json.dumps(result), flush=True); return 0


if __name__ == '__main__': raise SystemExit(main())
