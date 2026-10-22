"""Rehearse the approved role-only recovery on protected copies, never production."""

import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time

import gitea_postgres_control as control
import point_postgres_recovery as logical

common = control.common
retained = control.retained
LABEL = 'io.eaglepass.gitea-postgres-account-copy-103'
BIN = '/opt/bitnami/postgresql/bin/'
DATA = '/bitnami/postgresql/data'
ENV = {'LC_ALL': 'C', 'LANG': 'C', 'PG_COLOR': 'never'}
TMPFS = {'/tmp': 'rw,nosuid,nodev,uid=1001,gid=1001,mode=1777'}
for directory in ('conf', 'tmp', 'secrets'):
    TMPFS['/opt/bitnami/postgresql/' + directory] = 'rw,nosuid,nodev,uid=1001,gid=1001,mode=0700'
NATIVE_ENV = {'BITNAMI_DEBUG': 'false', 'POSTGRESQL_PORT_NUMBER': '5432',
              'POSTGRESQL_VOLUME_DIR': '/bitnami/postgresql', 'PGDATA': DATA,
              'POSTGRES_USER': 'gitea', 'POSTGRES_DATABASE': 'gitea',
              'POSTGRES_PASSWORD_FILE': '/opt/bitnami/postgresql/secrets/password',
              'POSTGRES_POSTGRES_PASSWORD_FILE': '/opt/bitnami/postgresql/secrets/postgres-password',
              'POSTGRESQL_ENABLE_LDAP': 'no', 'POSTGRESQL_ENABLE_TLS': 'no',
              'POSTGRESQL_LOG_HOSTNAME': 'false', 'POSTGRESQL_LOG_CONNECTIONS': 'false',
              'POSTGRESQL_LOG_DISCONNECTIONS': 'false', 'POSTGRESQL_PGAUDIT_LOG_CATALOG': 'off',
              'POSTGRESQL_CLIENT_MIN_MESSAGES': 'error', 'POSTGRESQL_SHARED_PRELOAD_LIBRARIES': 'pgaudit'}
VENDOR_HASHES = {'postgresql/entrypoint.sh': '5fc7a4ba859787e049e36cb56a1c7feae00e7d1c5b360980855b3153ca730868',
                 'postgresql/setup.sh': '84c037ec77279c74b9dde81a685aae6dc4cc8a844a56a04af8f301b992db2d45',
                 'postgresql/run.sh': 'f5c6976e50ce3999ad0dab79c16e995e37ddf6eb070e5573d1e19db478cd8f3f',
                 'postgresql-env.sh': '9ffffeccb6bc0daff1440524e1940ca15eef5dfa4212dfcd40c34614c091d28c',
                 'libpostgresql.sh': '025de015e66349725729e498fe71e6d5a8adb0b10271965e5f39809157869820'}
NSS_LIBRARY = '/opt/bitnami/common/lib/libnss_wrapper.so.0.3.5'
NSS_SHA256 = 'aee52fd8be9d5786b51449cd4e6ba1d6dce94ddfe34cd793bd31b4ea080f36d1'
MISSING_USER = b'postgres: could not look up effective user ID 1001: user does not exist\n'
SINGLE_WRAPPER = '''source /opt/bitnami/scripts/libpostgresql.sh
source /opt/bitnami/scripts/postgresql-env.sh
export TMPDIR=/tmp
postgresql_enable_nss_wrapper
[[ "$LD_PRELOAD" == /opt/bitnami/common/lib/libnss_wrapper.so ]]
[[ "$NSS_WRAPPER_PASSWD" == /tmp/tmp.* && "$NSS_WRAPPER_GROUP" == /tmp/tmp.* ]]
trap 'rm -f -- "$NSS_WRAPPER_PASSWD" "$NSS_WRAPPER_GROUP"' EXIT
"$@"
'''
OPTIONS = ['-c', 'config_file=/tmp/fixture.conf', '-c', 'hba_file=/tmp/source-hba.conf',
           '-c', 'listen_addresses=', '-c', 'unix_socket_directories=/tmp',
           '-c', 'unix_socket_permissions=0700', '-c', 'logging_collector=off',
           '-c', 'log_destination=stderr', '-c', 'log_statement=none',
           '-c', 'log_min_error_statement=panic', '-c', 'log_min_messages=panic',
           '-c', 'log_error_verbosity=verbose',
           '-c', 'shared_preload_libraries=', '-c', 'session_preload_libraries=',
           '-c', 'local_preload_libraries=', '-c', 'autovacuum=off']
CATALOG = """SELECT jsonb_build_object(
'roles',(SELECT jsonb_agg(to_jsonb(r) ORDER BY oid) FROM pg_authid r),
'members',(SELECT jsonb_agg(to_jsonb(r) ORDER BY oid) FROM pg_auth_members r),
'settings',(SELECT jsonb_agg(to_jsonb(r) ORDER BY setdatabase,setrole) FROM pg_db_role_setting r),
'databases',(SELECT jsonb_agg(to_jsonb(r)-'datfrozenxid'-'datminmxid' ORDER BY oid) FROM pg_database r),
'tablespaces',(SELECT jsonb_agg(to_jsonb(r) ORDER BY oid) FROM pg_tablespace r),
'parameters',(SELECT jsonb_agg(to_jsonb(r) ORDER BY oid) FROM pg_parameter_acl r),
'prepared',(SELECT count(*) FROM pg_prepared_xacts),
'slots',(SELECT count(*) FROM pg_replication_slots))"""


def catalog_sql():
    # Standalone mode treats each newline as a command boundary without -j.
    return "COPY (SELECT 'HOMELAB103:' || encode(convert_to((" + CATALOG.replace('\n', ' ') + ")::text,'UTF8'),'hex')) TO STDOUT;\n"


def parse_catalog(raw):
    records = re.findall(rb'HOMELAB103:([0-9a-f]+)\r?\n', raw)
    try:
        if len(records) != 1 or re.search(rb'\b(?:ERROR|FATAL|PANIC):', raw):
            raise ValueError()
        value = json.loads(bytes.fromhex(records[0].decode()))
        if set(value) != {'roles', 'members', 'settings', 'databases', 'tablespaces', 'parameters', 'prepared', 'slots'}:
            raise ValueError()
        roles = value['roles']
        if (sum(r['rolname'] == 'postgres' for r in roles) != 1 or
                sum(r['rolname'] == 'gitea' for r in roles) != 1 or value['prepared'] or value['slots'] or
                {d['datname'] for d in value['databases']} != {'gitea', 'postgres', 'template0', 'template1'} or
                {t['spcname'] for t in value['tablespaces']} != {'pg_default', 'pg_global'}):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('copied PostgreSQL catalog contract differs; raw output discarded') from None


def role_transaction(password, mode):
    if not isinstance(password, str) or not password or '\0' in password:
        raise RuntimeError('existing declared password is invalid')
    if mode not in {'rollback', 'failed', 'interrupted', 'commit'}:
        raise RuntimeError('unreviewed copied transaction mode')
    verifier = 'md5' + hashlib.md5((password + 'postgres').encode()).hexdigest()
    sql = "BEGIN;\nALTER ROLE postgres PASSWORD '" + verifier + "';\n"
    if mode == 'rollback':
        sql += 'ROLLBACK;\n'
    elif mode == 'failed':
        sql += 'SELECT 1/0;\nCOMMIT;\n'
    elif mode == 'commit':
        sql += 'COMMIT;\n'
    return sql.encode()


def require_role_only(before, after, password):
    expected = json.loads(json.dumps(before))
    role = next(r for r in expected['roles'] if r['rolname'] == 'postgres')
    role['rolpassword'] = 'md5' + hashlib.md5((password + 'postgres').encode()).hexdigest()
    if after != expected:
        raise RuntimeError('copied recovery changed more than the existing postgres password')


def mounts(work, volumes):
    return {name: str(work / ('copy' if name == '/bitnami/postgresql' else 'volume-' + str(n)))
            for n, name in enumerate(volumes)}


def arguments(work, volumes, run_id):
    args = ['create', '--network=none', '--read-only', '--log-driver=none', '--no-healthcheck',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=1001:1001',
            '--workdir=/tmp', '--pids-limit=128', '--memory=1g', '--cpus=1',
            '--label=' + LABEL + '=' + run_id]
    for target, options in TMPFS.items():
        args.append('--tmpfs=' + target + ':' + options)
    for key, value in ENV.items():
        args.extend(['--env', key + '=' + value])
    for target, source in mounts(work, volumes).items():
        args.extend(['--mount', 'type=bind,source=' + source + ',target=' + target])
    return [*args, '--entrypoint=/bin/sh', control.IMAGE, '-c', 'exec sleep 2147483647']


def require_container(value, work, volumes, run_id, image_id):
    config, host = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}}}
    environment = dict(item.split('=', 1) for item in config.get('Env', []))
    actual = value['Mounts']
    if (config['Image'] != control.IMAGE or value['Image'] != image_id or config['User'] != '1001:1001' or
            config['Entrypoint'] != ['/bin/sh'] or config['Cmd'] != ['-c', 'exec sleep 2147483647'] or
            config.get('WorkingDir') != '/tmp' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Healthcheck', {}).get('Test') != ['NONE'] or
            any(environment.get(k) != v for k, v in ENV.items()) or
            any(k in environment for k in ('PGPASSWORD', 'POSTGRES_PASSWORD')) or
            any(host.get(k) != v for k, v in expected.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd')) or
            len(actual) != len(mounts(work, volumes)) or
            any(m.get('Type') != 'bind' or not m['RW'] for m in actual) or
            {m['Destination']: m['Source'] for m in actual} != mounts(work, volumes)):
        raise RuntimeError('copied PostgreSQL account-recovery isolation differs')


def execute(container, *args, input=None, allow_error=False):
    common.require_no_logging(container)
    response = subprocess.run(['docker', 'exec', '-i', container, *args], input=input, capture_output=True)
    if not allow_error and (response.returncode or re.search(rb'\b(?:ERROR|FATAL|PANIC):', response.stderr)):
        raise RuntimeError('copied PostgreSQL native command failed; command=' + Path(args[0]).name +
                           '; classes=' + ','.join(error_classes(response.stderr)) + '; exit=' + str(response.returncode) +
                           '; sqlstates=' + ','.join(code.decode() for code in re.findall(
                               rb'\b(?:ERROR|FATAL|PANIC):\s+([0-9A-Z]{5}):', response.stderr)) +
                           '; raw output discarded; stdout_bytes=' + str(len(response.stdout)) +
                           '; stderr_bytes=' + str(len(response.stderr)))
    return response


def error_classes(raw):
    patterns = {'file_access': rb'(?:Permission denied|could not (?:open|access|create|read) (?:file|directory))',
                'invalid_checkpoint': rb'(?:could not locate a valid checkpoint|invalid primary checkpoint record)',
                'missing_config': rb'(?:configuration file .* does not exist|could not access the server configuration file)',
                'shared_memory': rb'(?:could not (?:create|resize|map) shared memory|No space left on device)',
                'missing_library': rb'(?:could not (?:access|load) (?:file|library)|error while loading shared libraries)',
                'server_start': rb'could not start server', 'authentication': rb'password authentication failed',
                'role_permission': rb'permission denied (?:for|to)', 'missing_relation': rb'relation .* does not exist',
                'lock_file': rb'lock file .* already exists', 'config_parameter': rb'(?:unrecognized configuration parameter|invalid value for parameter)',
                'sql_syntax': rb'syntax error', 'division_by_zero': rb'division by zero'}
    return [k for k, p in patterns.items() if re.search(p, raw)] or ['unclassified']


def single(container, sql, expected_failure=False):
    # No shell, credential environment, command argument, persisted SQL, or native log file.
    execute(container, '/usr/bin/test', '!', '-e', DATA + '/postmaster.pid')
    options = [*OPTIONS, *(['-c', 'log_min_messages=error'] if expected_failure else [])]
    response = execute(container, '/bin/bash', '-ceu', SINGLE_WRAPPER, 'native-single-user',
                       BIN + 'postgres', '--single', '-D', DATA, *options, 'postgres',
                       input=sql, allow_error=expected_failure)
    diagnostics = response.stdout + response.stderr
    if expected_failure and (response.returncode or len(re.findall(rb'ERROR:\s+(?:22012:\s+)?division by zero', diagnostics)) != 1 or
                             re.search(rb'\b(?:FATAL|PANIC):', diagnostics)):
        raise RuntimeError('copied harmless-failure rehearsal differs; raw output discarded')
    return response


def client(container, password, role, binary, *args, host='/tmp'):
    # The password travels only on attached stdin into the child environment.
    if '\n' in password or '\r' in password:
        raise RuntimeError('newline in declared credential refused')
    script = 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"'
    return execute(container, '/bin/sh', '-c', script, 'credential-stdin', BIN + binary,
                   '-h', host, '-U', role, *args, input=(password + '\n').encode()).stdout


def normal_start(container, credentials, hba, expected_failure=False):
    """Exercise the original image entrypoint on copies with native tmpfs mounts."""
    execute(container, '/usr/bin/test', '!', '-e', DATA + '/postmaster.pid')
    for path, checksum in VENDOR_HASHES.items():
        if hashlib.sha256(execute(container, '/bin/cat', '/opt/bitnami/scripts/' + path).stdout).hexdigest() != checksum:
            raise RuntimeError('reviewed vendor startup source changed')
    if any(not isinstance(p, str) or not p or any(c in p for c in '\n\r\0') for p in credentials.values()):
        raise RuntimeError('existing copied startup credential format differs')
    script = '''umask 077
IFS= read -r app_password
IFS= read -r admin_password
printf '%s' "$app_password" > /opt/bitnami/postgresql/secrets/password
printf '%s' "$admin_password" > /opt/bitnami/postgresql/secrets/postgres-password
'''
    execute(container, '/bin/sh', '-ceu', script,
            input=(credentials['app'] + '\n' + credentials['admin'] + '\n').encode())
    environment = dict(NATIVE_ENV)
    if expected_failure:
        environment['POSTGRESQL_PORT_NUMBER'] = 'invalid-port-fixture'
    native = ['/usr/bin/env', *[k + '=' + v for k, v in environment.items()],
              '/opt/bitnami/scripts/postgresql/entrypoint.sh', '/opt/bitnami/scripts/postgresql/run.sh']
    if expected_failure:
        response = execute(container, *native, allow_error=True)
        diagnostics = response.stdout + response.stderr
        if response.returncode != 1 or b'POSTGRESQL_PORT_NUMBER' not in diagnostics:
            raise RuntimeError('copied vendor invalid-port refusal differs; raw output discarded')
        execute(container, '/usr/bin/test', '!', '-e', DATA + '/postmaster.pid')
        return
    # All child output stays in container tmpfs; Docker/CRI/journald logging remains disabled.
    execute(container, '/bin/sh', '-ceu', '"$@" > /tmp/vendor-start.log 2>&1 &', 'native-start', *native)
    deadline = time.monotonic() + 60
    while execute(container, BIN + 'pg_isready', '-h', '127.0.0.1', '-p', '5432',
                  '-U', 'gitea', '-d', 'gitea', allow_error=True).returncode:
        if time.monotonic() >= deadline:
            raw = execute(container, '/bin/cat', '/tmp/vendor-start.log').stdout
            raise RuntimeError('copied vendor startup not ready; classes=' + ','.join(error_classes(raw)) +
                               '; raw output discarded')
        time.sleep(0.1)
    if execute(container, '/bin/cat', '/opt/bitnami/postgresql/conf/pg_hba.conf').stdout != hba:
        raise RuntimeError('ordinary copied startup changed source HBA')
    options = shlex.split(execute(container, '/bin/cat', DATA + '/postmaster.opts').stdout.decode())
    if options != [BIN + 'postgres', '-D', DATA,
                   '--config-file=/opt/bitnami/postgresql/conf/postgresql.conf',
                   '--external_pid_file=/opt/bitnami/postgresql/tmp/postgresql.pid',
                   '--hba_file=/opt/bitnami/postgresql/conf/pg_hba.conf']:
        raise RuntimeError('ordinary copied postmaster arguments differ')
    maps = execute(container, '/bin/sh', '-ceu', '''IFS= read -r server_pid < /bitnami/postgresql/data/postmaster.pid
case "$server_pid" in ''|*[!0-9]*) exit 1;; esac
cat "/proc/$server_pid/maps"
''').stdout
    if b'/opt/bitnami/postgresql/lib/pgaudit.so' not in maps:
        raise RuntimeError('ordinary copied postmaster did not load pgaudit')
    # Application authentication must succeed without granting protected-settings privileges.
    result = client(container, credentials['app'], 'gitea', 'psql', '-XAtq', '-d', 'gitea', '-c',
                    'SELECT current_user,current_database(),pg_is_in_recovery()', host='127.0.0.1')
    if result != b'gitea|gitea|f\n':
        raise RuntimeError('ordinary copied TCP application authentication or native configuration differs')


def start(container):
    # Server output is captured in anonymous tmpfs, never CRI/journald or retained evidence.
    options = ' '.join("'" + a.replace("'", "'\\''") + "'" for a in OPTIONS)
    try:
        execute(container, BIN + 'pg_ctl', '-D', DATA, '-l', '/tmp/server.log', '-o', options, '-w', 'start')
    except RuntimeError as error:
        raw = execute(container, '/bin/cat', '/tmp/server.log', allow_error=True).stdout
        raise RuntimeError(str(error) + '; server_log_classes=' + ','.join(error_classes(raw)) +
                           '; server_log_bytes=' + str(len(raw)) + '; server_log_sha256=' + hashlib.sha256(raw).hexdigest()) from None


def stop(container):
    execute(container, BIN + 'pg_ctl', '-D', DATA, '-m', 'fast', '-w', 'stop')
    execute(container, '/usr/bin/test', '!', '-e', DATA + '/postmaster.pid')
    state = control.parse_control(execute(container, BIN + 'pg_controldata', DATA).stdout)
    if state['cluster_state'] != 'shut down':
        raise RuntimeError('copied PostgreSQL did not shut down cleanly')
    return state


def dumps(container, password, role):
    result = {}
    for database in ('gitea', 'postgres', 'template1'):
        raw = client(container, password, role, 'pg_dump', '--no-comments', '--dbname=' + database)
        result[database] = logical.normalized_dump(raw)
    return result


def operation(work, volumes, run_id, image_id, credentials, hba):
    container = None
    try:
        container = common.docker(*arguments(work, volumes, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('copied PostgreSQL container identity missing')
        require_container(common.inspect(container), work, volumes, run_id, image_id)
        common.docker('start', container)
        value = common.inspect(container)
        require_container(value, work, volumes, run_id, image_id)
        net = ['nsenter', '-t', str(value['State']['Pid']), '-n', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
                               sum((json.loads(common.command([*net, 'ip', f, '-j', 'route', 'show', 'table', 'all']).stdout)
                                    for f in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('copied PostgreSQL can route to production')
        execute(container, '/bin/sh', '-c', 'umask 077; cat > /tmp/source-hba.conf; : > /tmp/fixture.conf', input=hba)
        uid = execute(container, '/usr/bin/getent', 'passwd', '1001', allow_error=True)
        if uid.returncode != 2 or uid.stdout or uid.stderr:
            raise RuntimeError('reviewed original image UID lookup contract changed')
        if hashlib.sha256(execute(container, '/bin/cat', NSS_LIBRARY).stdout).hexdigest() != NSS_SHA256:
            raise RuntimeError('reviewed native image NSS wrapper library changed')
        # This stale lock belongs only to an exact copied historical point, never a live volume.
        pid = work / 'copy/data/postmaster.pid'
        if not pid.is_file() or pid.is_symlink():
            raise RuntimeError('reviewed historical copied lock missing')
        pid.unlink()
        normal_start(container, credentials, hba)
        before_dump = dumps(container, credentials['app'], 'gitea')
        stop(container)
        failed_uid = execute(container, BIN + 'postgres', '--single', '-D', DATA, *OPTIONS, 'postgres',
                             input=b'', allow_error=True)
        if failed_uid.returncode != 1 or failed_uid.stdout or failed_uid.stderr != MISSING_USER:
            raise RuntimeError('unwrapped standalone UID failure differs from exact upstream source')
        baseline = parse_catalog(single(container, catalog_sql().encode()).stdout)
        normal_start(container, credentials, hba, expected_failure=True)
        if parse_catalog(single(container, catalog_sql().encode()).stdout) != baseline:
            raise RuntimeError('copied vendor startup refusal changed authorization')
        for mode in ('rollback', 'failed', 'interrupted'):
            single(container, role_transaction(credentials['admin'], mode), expected_failure=mode == 'failed')
            if parse_catalog(single(container, catalog_sql().encode()).stdout) != baseline:
                raise RuntimeError('copied aborted transaction changed authorization')
            normal_start(container, credentials, hba)
            if dumps(container, credentials['app'], 'gitea') != before_dump:
                raise RuntimeError('copied aborted recovery changed logical data')
            stop(container)
            if parse_catalog(single(container, catalog_sql().encode()).stdout) != baseline:
                raise RuntimeError('ordinary copied startup changed authorization')
        single(container, role_transaction(credentials['admin'], 'commit'))
        after = parse_catalog(single(container, catalog_sql().encode()).stdout)
        require_role_only(baseline, after, credentials['admin'])
        normal_start(container, credentials, hba)
        if client(container, credentials['admin'], 'postgres', 'psql', '-XAtq', '-d', 'postgres', '-c',
                  'SELECT current_user', host='127.0.0.1') != b'postgres\n':
            raise RuntimeError('normal copied administrator authentication differs')
        after_dump = dumps(container, credentials['admin'], 'postgres')
        if after_dump != before_dump or dumps(container, credentials['app'], 'gitea') != before_dump:
            raise RuntimeError('copied recovery changed full logical schema/records/sequences')
        state = stop(container)
        require_role_only(baseline, parse_catalog(single(container, catalog_sql().encode()).stdout), credentials['admin'])
        if execute(container, '/bin/cat', '/tmp/source-hba.conf').stdout != hba:
            raise RuntimeError('copied HBA changed')
        require_container(common.inspect(container), work, volumes, run_id, image_id)
        return {'full_dump_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in before_dump.items()},
                'catalog_without_postgres_password_sha256': hashlib.sha256(common.canonical(
                    {**baseline, 'roles': [{k: v for k, v in r.items() if k != 'rolpassword'} for r in baseline['roles']]})).hexdigest(),
                'role_only': True, 'rollback_unchanged': True, 'failed_transaction_unchanged': True,
                'interrupted_transaction_unchanged': True,
                'admin_and_application_normal_md5_auth': True, 'source_hba_unchanged': True,
                'native_vendor_nss_wrapper_same_uid_gid': True,
                'original_vendor_entrypoint_setup_run': True, 'native_pgaudit_loaded': True,
                'ordinary_tcp_application_authentication': True,
                'invalid_port_startup_refusal_and_ordinary_fallback': True,
                'native_crash_recovery_and_clean_shutdown': True, 'control': state}
    finally:
        if container:
            require_container(common.inspect(container), work, volumes, run_id, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned copied PostgreSQL container remains')


def qualify(run_id, credentials, hba):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    if set(credentials) != {'admin', 'app'} or hashlib.sha256(hba).hexdigest() != '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05':
        raise RuntimeError('existing credential fields or reviewed md5 HBA changed')
    value = retained.verify(control.POINT, control.CHECKSUM, 'gitea')
    if any(r['kind'] == 'symlink' for r in value['tree'].values()):
        raise RuntimeError('unreviewed copied PostgreSQL symlink')
    retained.require_capacity(common.ROOT, value['tree'], 2)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned copied recovery already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-postgres-account-copy-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'production_mutated': False, 'manifest_sha256': control.CHECKSUM, 'copies': []}
    try:
        common.docker('pull', control.IMAGE)
        image = json.loads(common.docker('image', 'inspect', control.IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {control.IMAGE, control.IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', [])) or
                set(volumes) != {'/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d'}):
            raise RuntimeError('exact original PostgreSQL image differs')
        for number in range(2):
            work = scratch / str(number)
            work.mkdir(mode=0o700)
            retained.materialize(control.POINT, work / 'copy', value)
            for source in mounts(work, volumes).values():
                if source != str(work / 'copy'):
                    Path(source).mkdir(mode=0o755)
            result['copies'].append(operation(work, volumes, run_id, image_id, credentials, hba))
        if result['copies'][0]['full_dump_sha256'] != result['copies'][1]['full_dump_sha256']:
            raise RuntimeError('independent copied database fingerprints differ')
        result.update(accepted=True, independent_copies=2, image=control.IMAGE,
                      production_cold_capture_and_startup_unqualified=True)
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
            raise RuntimeError('owned copied recovery remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', control.IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused copied PostgreSQL image remains')
        retained.verify(control.POINT, control.CHECKSUM, 'gitea')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'protected_original_unchanged': True, 'allocated_bytes_removed': allocated}
        retained.files.write_json(control.POINT / ('account-copy-' + run_id + '.json'), result)
    return result
