"""Qualify the exact maintained PG16 image on two protected copies, never production."""

import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

import gitea_postgres_account_recovery as legacy
import gitea_postgres_cold_point as cold

common = legacy.common
retained = legacy.retained
IMAGE = cold.control.MAINTAINED_IMAGE
LABEL = 'io.eaglepass.gitea-postgres-maintained-copy-103'
BIN = '/usr/lib/postgresql/16/bin/'
FILES = {'pgaudit.so': '332e2bcb4844cdab7c9fe93478c07c47c49dda118c4c81202ca995e97824baa8', 'pgaudit.control': 'ecf9b47d762337da85607cd4fd315f29135e04773795df8fabc8d4146206c69c', 'pgaudit--16.1.sql': '9d4d2d3358c308e1ae704bb6f59c410be36f6eab6f9a9ff0c459b8406d6f06f3', 'pgaudit--16.0--16.1.sql': '9181507e2853956a8dc502501780fa772ec162daa72f83ef0615d46232461cdc', 'pgaudit-copyright': '58ee977a7f19c3b8cd14fae42c59fa2153beb32bff0e1d2fb68c968377fdd5eb', 'postgresql.conf': '3cc4dfef0ab7dd37a0055bd450a9027080e0082b622bfcd7771d43fddd426ce7', 'pg_hba.conf': '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05', 'postgres-startup.sh': '2f51a58b32939053ce72ec91c25df30ddc4e74a24ad6629a6e33f8828e3fd7f1'}
TARGETS = {'postgres-startup.sh': '/configuration/postgres-startup.sh',
           'postgresql.conf': '/configuration/postgresql.conf', 'pg_hba.conf': '/configuration/pg_hba.conf',
           'pgaudit.so': '/usr/lib/postgresql/16/lib/pgaudit.so',
           'pgaudit.control': '/usr/share/postgresql/16/extension/pgaudit.control',
           'pgaudit--16.1.sql': '/usr/share/postgresql/16/extension/pgaudit--16.1.sql',
           'pgaudit--16.0--16.1.sql': '/usr/share/postgresql/16/extension/pgaudit--16.0--16.1.sql',
           'pgaudit-copyright': '/configuration/pgaudit-copyright'}
TMPFS = {'/tmp': 'rw,nosuid,nodev,uid=1001,gid=1001,mode=1777',
         '/opt/bitnami/postgresql/tmp': 'rw,nosuid,nodev,uid=1001,gid=1001,mode=0700'}


def validate_payload(value):
    try:
        if set(value) != set(FILES):
            raise ValueError()
        decoded = {name: base64.b64decode(raw, validate=True) for name, raw in value.items()}
        if any(hashlib.sha256(raw).hexdigest() != FILES[name] for name, raw in decoded.items()):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise RuntimeError('maintained PostgreSQL public runtime payload differs') from None
    return decoded


def candidate_mounts(work, volumes, artifacts, *, client=False):
    mounted = {name: (str(work / ('image-volume-' + str(n))), True) for n, name in enumerate(volumes)}
    if not client:
        mounted['/bitnami/postgresql'] = (str(work / 'copy'), True)
        mounted.update({target: (str(artifacts / name), False) for name, target in TARGETS.items()})
    return mounted


def create_candidate(work, volumes, artifacts, run_id, image_id, *, server=None):
    mounted = candidate_mounts(work, volumes, artifacts, client=server is not None)
    for name in volumes:
        path = Path(mounted[name][0]); path.mkdir(mode=0o755)
    network = 'container:' + server if server else 'none'
    args = ['create', '--network=' + network, '--read-only', '--log-driver=none', '--no-healthcheck',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=1001:1001',
            '--workdir=/tmp', '--pids-limit=128', '--memory=1g', '--cpus=1', '--label=' + LABEL + '=' + run_id]
    for target, options in TMPFS.items():
        args.append('--tmpfs=' + target + ':' + options)
    for key, value in legacy.ENV.items():
        args.extend(['--env', key + '=' + value])
    for target, (path, writable) in mounted.items():
        args.extend(['--mount', 'type=bind,source=' + path + ',target=' + target + ('' if writable else ',readonly')])
    container = common.docker(*args, '--entrypoint=/bin/sh', IMAGE, '-c', 'exec sleep 2147483647').stdout.decode().strip()
    if not re.fullmatch('[a-f0-9]{64}', container):
        raise RuntimeError('maintained-copy container identity missing')
    try:
        require_candidate(container, mounted, network, run_id, image_id)
        common.docker('start', container)
        require_candidate(container, mounted, network, run_id, image_id)
        pid = common.inspect(container)['State']['Pid']
        net = ['nsenter', '-t', str(pid), '-n', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
            sum((json.loads(common.command([*net, 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
                 for family in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('maintained copy can route to production')
        return container, mounted, network
    except BaseException:
        common.docker('rm', '-f', container)
        raise


def require_candidate(container, mounted, network, run_id, image_id):
    value = common.inspect(container); config, host = value['Config'], value['HostConfig']
    expected = {'NetworkMode': network, 'ReadonlyRootfs': True, 'Privileged': False,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}}}
    actual = value['Mounts']
    environment = dict(item.split('=', 1) for item in config.get('Env', []))
    if (config['Image'] != IMAGE or value['Image'] != image_id or config['User'] != '1001:1001' or
            config['Entrypoint'] != ['/bin/sh'] or config['Cmd'] != ['-c', 'exec sleep 2147483647'] or
            config.get('WorkingDir') != '/tmp' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Healthcheck', {}).get('Test') != ['NONE'] or
            any(environment.get(k) != v for k, v in legacy.ENV.items()) or
            any(k in environment for k in ('PGPASSWORD', 'POSTGRES_PASSWORD')) or
            any(host.get(k) != v for k, v in expected.items()) or host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd')) or
            len(actual) != len(mounted) or any(m.get('Type') != 'bind' for m in actual) or
            {m['Destination']: (m['Source'], m['RW']) for m in actual} != mounted):
        raise RuntimeError('maintained-copy native isolation differs')


def client(container, password, role, binary, *args):
    if not isinstance(password, str) or not password or any(c in password for c in '\n\r\0'):
        raise RuntimeError('existing copied credential differs')
    return legacy.execute(container, '/bin/sh', '-c',
        'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"', 'credential-stdin',
        BIN + binary, '-h', '127.0.0.1', '-U', role, *args, input=(password + '\n').encode()).stdout


def fingerprints(container, credentials):
    result = {}
    for role, key in (('postgres', 'admin'), ('gitea', 'app')):
        for database in ('gitea', 'postgres', 'template1'):
            answer = client(container, credentials[key], role, 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1', '-d', database,
                '-c', 'SELECT current_user,current_database(),pg_is_in_recovery()')
            if answer != (role + '|' + database + '|f\n').encode():
                raise RuntimeError('copied existing-role ordinary authentication differs')
    catalog = json.loads(client(container, credentials['admin'], 'postgres', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
        '-d', 'postgres', '-c', legacy.CATALOG))
    for database in ('gitea', 'postgres', 'template1'):
        raw = client(container, credentials['admin'], 'postgres', 'pg_dump', '--no-comments', '--dbname=' + database)
        result[database] = hashlib.sha256(legacy.logical.normalized_dump(raw)).hexdigest()
    return result, catalog


def candidate_start(container):
    legacy.execute(container, '/bin/sh', '-ceu',
        '"$@" > /tmp/maintained-start.log 2>&1 &', 'maintained-start', '/bin/bash', '/configuration/postgres-startup.sh')
    end = time.monotonic() + 60
    while legacy.execute(container, BIN + 'pg_isready', '-h', '127.0.0.1', '-p', '5432', allow_error=True).returncode:
        if time.monotonic() > end:
            raw = legacy.execute(container, '/bin/cat', '/tmp/maintained-start.log').stdout
            raise RuntimeError('maintained copied startup failed; classes=' + ','.join(legacy.error_classes(raw)))
        time.sleep(.1)
    version = legacy.execute(container, BIN + 'postgres', '--version').stdout
    if not re.fullmatch(rb'postgres \(PostgreSQL\) 16\.15[^\n]*\n', version):
        raise RuntimeError('maintained native PostgreSQL version differs')
    maps = legacy.execute(container, '/bin/sh', '-ceu',
        'IFS= read -r pid < /bitnami/postgresql/data/postmaster.pid; case "$pid" in ""|*[!0-9]*) exit 1;; esac; cat "/proc/$pid/maps"').stdout
    if b'/usr/lib/postgresql/16/lib/pgaudit.so' not in maps:
        raise RuntimeError('maintained copied server did not load pgAudit')


def candidate_stop(container):
    legacy.execute(container, BIN + 'pg_ctl', '-D', legacy.DATA, '-m', 'fast', '-w', 'stop')
    legacy.execute(container, '/usr/bin/test', '!', '-e', legacy.DATA + '/postmaster.pid')
    control = cold.control.parse_control(legacy.execute(container, BIN + 'pg_controldata', legacy.DATA).stdout)
    if control['cluster_state'] != 'shut down':
        raise RuntimeError('maintained copied server did not stop cleanly')
    return control


def inspect_metadata(client_id, credentials, version):
    sql = """SELECT jsonb_build_object(
'v',current_setting('server_version_num')::int,
'preload',current_setting('shared_preload_libraries'),
'audit',current_setting('pgaudit.log'),'audit_catalog',current_setting('pgaudit.log_catalog'),
'fsync',current_setting('fsync'),'wal',current_setting('wal_level'),
'data',current_setting('data_directory'),'socket',current_setting('unix_socket_directories'),
'collation',(SELECT bool_and(datcollate='en_US.UTF-8' AND datctype='en_US.UTF-8' AND
 datlocprovider='c' AND pg_database_collation_actual_version(oid)='2.36' AND
 (datcollversion='2.36' OR datname='template0' AND datcollversion IS NULL)) FROM pg_database),
'extensions',(SELECT jsonb_agg(jsonb_build_object('name',extname,'version',extversion) ORDER BY extname) FROM pg_extension),
'partition_self_fk',(SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
 WHERE c.contype='f' AND c.confrelid=c.conrelid AND t.relkind='p'),
'special_indexes',(SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
 JOIN pg_am a ON a.oid=c.relam WHERE a.amname IN ('brin','gist','gin')),
'slots',(SELECT count(*) FROM pg_replication_slots),'prepared',(SELECT count(*) FROM pg_prepared_xacts),
'subscriptions',(SELECT count(*) FROM pg_subscription));"""
    values = []
    for database in ('gitea', 'postgres', 'template1'):
        value = json.loads(client(client_id, credentials['admin'], 'postgres', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
            '-d', database, '-c', sql))
        expected = {'v': version, 'preload': 'pgaudit', 'audit': 'none', 'audit_catalog': 'off',
                    'fsync': 'on', 'wal': 'replica', 'data': legacy.DATA, 'socket': '/tmp',
                    'collation': True, 'extensions': [{'name': 'plpgsql', 'version': '1.0'}],
                    'partition_self_fk': 0, 'special_indexes': 0, 'slots': 0, 'prepared': 0, 'subscriptions': 0}
        if value != expected:
            raise RuntimeError('native copied compatibility/settings/migration conditions differ')
        values.append(value)
    return values


def run(point, checksum, credentials, hba, run_id, payload):
    common.run_identifier(run_id); common.require_host('pikachu'); common.private_root()
    if (point.parent != common.ROOT or not point.name.startswith('gitea-postgres-guarded-') or
            set(credentials) != {'admin', 'app'} or hashlib.sha256(hba).hexdigest() != FILES['pg_hba.conf']):
        raise RuntimeError('maintained qualification requires exact protected existing-account source')
    artifacts = validate_payload(payload)
    if artifacts['pg_hba.conf'] != hba:
        raise RuntimeError('existing HBA bytes differ from maintained profile')
    manifest = cold.verify(point, checksum)
    if manifest['format'] not in (cold.GUARDED_FORMAT, cold.MAINTAINED_FORMAT):
        raise RuntimeError('maintained qualification requires actual clean production provenance')
    for label in (LABEL, legacy.LABEL):
        if common.docker('ps', '-aq', '--filter=label=' + label).stdout.strip():
            raise RuntimeError('another owned PostgreSQL qualification is active')
    retained.require_capacity(common.ROOT, manifest['tree'], 2)
    previous_images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    work = Path(tempfile.mkdtemp(prefix='gitea-postgres-maintained-copy-', dir=common.ROOT)); work.chmod(0o700)
    images = {}; owned = {}; summaries = []
    result = {'accepted': False, 'manifest_sha256': checksum, 'production_mutated': False}
    def remove(container):
        item = owned[container]
        if item['kind'] == 'candidate':
            require_candidate(container, item['mounted'], item['network'], run_id, images[IMAGE]['Id'])
        else:
            legacy.require_container(common.inspect(container), item['work'], item['volumes'], run_id,
                                     images[cold.control.IMAGE]['Id'])
        common.docker('rm', '-f', container)
        if common.docker('inspect', container, check=False).returncode == 0:
            raise RuntimeError('owned compatibility container remains')
        del owned[container]
    def new_candidate(child, *, server=None):
        volumes = sorted((images[IMAGE]['Config'].get('Volumes') or {}).keys())
        container, mounted, network = create_candidate(child, volumes, work / 'artifacts', run_id,
                                                       images[IMAGE]['Id'], server=server)
        owned[container] = {'kind': 'candidate', 'mounted': mounted, 'network': network}
        return container
    def new_legacy(child):
        volumes = sorted((images[cold.control.IMAGE]['Config'].get('Volumes') or {}).keys())
        for source in legacy.mounts(child, volumes).values():
            if source != str(child / 'copy'):
                Path(source).mkdir(mode=0o755, exist_ok=True)
        container = common.docker(*legacy.arguments(child, volumes, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('legacy comparison container identity missing')
        owned[container] = {'kind': 'legacy', 'work': child, 'volumes': volumes}
        legacy.require_container(common.inspect(container), child, volumes, run_id, images[cold.control.IMAGE]['Id'])
        common.docker('start', container)
        legacy.require_container(common.inspect(container), child, volumes, run_id, images[cold.control.IMAGE]['Id'])
        return container
    def evaluate(server, child, expected_version):
        child.mkdir(mode=0o700)
        client_id = new_candidate(child, server=server)
        try:
            output, catalog = fingerprints(client_id, credentials)
            metadata = inspect_metadata(client_id, credentials, expected_version)
            return output, catalog, metadata
        finally:
            remove(client_id)
    try:
        (work / 'artifacts').mkdir(mode=0o755)
        for name, raw in artifacts.items():
            path = work / 'artifacts' / name; path.write_bytes(raw); path.chmod(0o444)
        for image in (cold.control.IMAGE, IMAGE):
            common.docker('pull', image)
            value = json.loads(common.docker('image', 'inspect', image).stdout)[0]
            volumes = set((value['Config'].get('Volumes') or {}).keys())
            required = {'/var/lib/postgresql/data'} if image == IMAGE else {
                '/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d'}
            images[image] = value
            if (value['Architecture'] != 'amd64' or value['Os'] != 'linux' or volumes != required or
                    not {image, image.removeprefix('docker.io/')}.intersection(value.get('RepoDigests', []))):
                raise RuntimeError('exact compatibility image architecture/digest/volumes differ')
        for number in range(2):
            if cold.verify(point, checksum) != manifest:
                raise RuntimeError('protected actual PostgreSQL point changed')
            child = work / ('copy-' + str(number)); child.mkdir(mode=0o700)
            retained.materialize(point, child / 'copy', manifest)
            server = new_legacy(child)
            legacy.prepare_standalone_directory(lambda *args: legacy.execute(server, *args))
            legacy.normal_start(server, credentials, hba)
            baseline, catalog, metadata = evaluate(server, child / 'baseline-client', 160006)
            legacy.stop(server); remove(server)
            server = new_candidate(child)
            candidate_start(server)
            actual, new_catalog, new_metadata = evaluate(server, child / 'candidate-client', 160015)
            audit_work = child / 'audit-client'; audit_work.mkdir(mode=0o700)
            audit_client = new_candidate(audit_work, server=server)
            try:
                client(audit_client, credentials['admin'], 'postgres', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
                    '-d', 'postgres', '-c', "SET pgaudit.log='read'; SELECT 'maintenance103-public-audit-marker';")
            finally:
                remove(audit_client)
            audit_log = legacy.execute(server, '/bin/cat', '/tmp/maintained-start.log').stdout
            if not any(b'AUDIT:' in line and b'maintenance103-public-audit-marker' in line
                       for line in audit_log.splitlines()):
                raise RuntimeError('maintained copied pgAudit behavior did not produce its public marker')
            if (actual, new_catalog) != (baseline, catalog):
                raise RuntimeError('maintained server changed complete logical data/schema or authorization catalog')
            candidate_stop(server); candidate_start(server)
            restarted, restarted_catalog, _ = evaluate(server, child / 'restart-client', 160015)
            if (restarted, restarted_catalog) != (baseline, catalog):
                raise RuntimeError('maintained native restart lost logical data/schema or changed authorization')
            candidate_stop(server); remove(server)
            server = new_legacy(child)
            legacy.normal_start(server, credentials, hba)
            rollback, rollback_catalog, _ = evaluate(server, child / 'rollback-client', 160006)
            if (rollback, rollback_catalog) != (baseline, catalog):
                raise RuntimeError('legacy rollback on the same copied PGDATA differs')
            legacy.stop(server); remove(server)
            summaries.append({'normal_authentication_six_paths': True, 'full_dump_sha256': baseline,
                'administrator_authentication': True, 'full_logical_data_equal': True,
                'unchanged_hba': True, 'clean_shutdown': True,
                'catalog_sha256': hashlib.sha256(common.canonical(catalog)).hexdigest(),
                'maintained_version': '16.15', 'legacy_version': '16.6', 'collation_2_36_equal': True,
                'maintained_restart_equal': True, 'same_copy_legacy_rollback_equal': True,
                'pgdata_and_hba_preserved': True, 'native_pgaudit_loaded': True, 'native_audit_behavior_passed': True})
        if summaries[0]['full_dump_sha256'] != summaries[1]['full_dump_sha256'] or summaries[0]['catalog_sha256'] != summaries[1]['catalog_sha256']:
            raise RuntimeError('independent actual-copy compatibility results disagree')
        result.update(accepted=True, independent_copies=2, copies=summaries)
    finally:
        cleanup_errors = []
        for container in list(owned):
            try:
                remove(container)
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            raise RuntimeError('owned compatibility cleanup incomplete; scratch preserved; classes=' + ','.join(cleanup_errors))
        if owned or any(common.docker('ps', '-aq', '--filter=label=' + label).stdout.strip()
                        for label in (LABEL, legacy.LABEL)):
            raise RuntimeError('owned compatibility workload remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in work.rglob('*'))
        shutil.rmtree(work)
        removed = []
        for image, value in images.items():
            if value['Id'] not in previous_images and not common.docker('ps', '-aq', '--filter=ancestor=' + value['Id']).stdout.strip():
                common.docker('image', 'rm', image)
                if common.docker('image', 'inspect', value['Id'], check=False).returncode == 0:
                    raise RuntimeError('new unused compatibility image remains')
                removed.append(image)
        if cold.verify(point, checksum) != manifest:
            raise RuntimeError('protected original changed during qualification')
        result['cleanup'] = {'scratch_absent': not work.exists(), 'containers_absent': True,
            'allocated_bytes_removed': allocated, 'new_unused_images_removed': removed, 'protected_original_unchanged': True}
    return result
