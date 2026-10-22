"""Refuse broader mutations, credential leakage and disconnected-copy escape."""

import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import gitea_postgres_account_recovery as recovery


def catalog():
    return {'roles': [{'oid': 10, 'rolname': 'postgres', 'rolpassword': 'old', 'rolsuper': True},
                      {'oid': 20, 'rolname': 'gitea', 'rolpassword': 'application', 'rolsuper': False}],
            'members': None, 'settings': None, 'parameters': None, 'prepared': 0, 'slots': 0,
            'databases': [{'datname': n} for n in ('gitea', 'postgres', 'template0', 'template1')],
            'tablespaces': [{'spcname': n} for n in ('pg_default', 'pg_global')]}


class RecoveryContract(unittest.TestCase):
    def test_only_existing_postgres_password_can_change(self):
        before = catalog()
        after = copy.deepcopy(before)
        after['roles'][0]['rolpassword'] = 'md5' + hashlib.md5(b'fixturepostgres').hexdigest()
        recovery.require_role_only(before, after, 'fixture')
        for change in (lambda v: v['roles'][1].update(rolpassword='changed'),
                       lambda v: v['roles'][0].update(oid=11),
                       lambda v: v['roles'][0].update(rolsuper=False),
                       lambda v: v.update(members=[{'roleid': 10, 'member': 20}]),
                       lambda v: v['databases'].append({'datname': 'foreign'})):
            modified = copy.deepcopy(after)
            change(modified)
            with self.assertRaises(RuntimeError):
                recovery.require_role_only(before, modified, 'fixture')
        self.assertEqual(before, catalog())

    def test_sql_never_contains_raw_password_or_alternate_role(self):
        secret = "private'\\\n;ALTER ROLE gitea SUPERUSER;--"
        for mode in ('rollback', 'failed', 'interrupted', 'commit'):
            sql = recovery.role_transaction(secret, mode)
            self.assertNotIn(secret.encode(), sql)
            self.assertEqual(sql.count(b'ALTER ROLE postgres PASSWORD'), 1)
            self.assertNotIn(b'ALTER ROLE gitea', sql)
            if mode == 'interrupted':
                self.assertNotIn(b'COMMIT', sql)
        for password, mode in (('', 'commit'), ('x\0y', 'commit'), ('x', 'arbitrary')):
            with self.assertRaises(RuntimeError):
                recovery.role_transaction(password, mode)

    def test_native_catalog_rejects_errors_duplicates_and_uncovered_features(self):
        self.assertEqual(recovery.catalog_sql().count('\n'), 1)
        def encoded(v):
            return b'backend> HOMELAB103:' + json.dumps(v).encode().hex().encode() + b'\nbackend> '
        raw = encoded(catalog())
        self.assertEqual(recovery.parse_catalog(raw), catalog())
        for bad in (b'', raw + raw, raw + b'ERROR: private-data', b'HOMELAB103:ff\n'):
            with self.assertRaises(RuntimeError) as caught:
                recovery.parse_catalog(bad)
            self.assertNotIn('private-data', str(caught.exception))
        for field, value in (('slots', 1), ('prepared', 1), ('roles', []), ('tablespaces', [])):
            modified = catalog()
            modified[field] = value
            with self.assertRaises(RuntimeError):
                recovery.parse_catalog(encoded(modified))

    def container(self):
        work = Path('/protected/owned-copy')
        volumes = ['/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d']
        value = {'Image': 'sha256:owned', 'Config': {'Image': recovery.control.IMAGE, 'User': '1001:1001',
                 'Entrypoint': ['/bin/sh'], 'Cmd': ['-c', 'exec sleep 2147483647'], 'WorkingDir': '/tmp',
                 'Labels': {recovery.LABEL: 'fixture'}, 'Healthcheck': {'Test': ['NONE']},
                 'Env': [k + '=' + v for k, v in recovery.ENV.items()]},
                 'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                 'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824, 'NanoCpus': 1000000000,
                 'Tmpfs': recovery.TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}}, 'RestartPolicy': {'Name': 'no'}},
                 'Mounts': [{'Type': 'bind', 'RW': True, 'Destination': target, 'Source': source}
                            for target, source in recovery.mounts(work, volumes).items()]}
        return work, volumes, value

    def test_logging_network_root_foreign_mount_and_credentials_refused(self):
        work, volumes, original = self.container()
        recovery.require_container(original, work, volumes, 'fixture', 'sha256:owned')
        for change in (lambda v: v['HostConfig'].update(NetworkMode='host'),
                       lambda v: v['HostConfig'].update(LogConfig={'Type': 'journald', 'Config': {}}),
                       lambda v: v['Config'].update(User='0:0'),
                       lambda v: v['Config']['Env'].append('PGPASSWORD=private'),
                       lambda v: v['Mounts'][0].update(Source='/original/live-volume'),
                       lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN'])):
            modified = copy.deepcopy(original)
            change(modified)
            with self.assertRaises(RuntimeError):
                recovery.require_container(modified, work, volumes, 'fixture', 'sha256:owned')

    def test_native_failure_never_exports_output_or_persists_diagnostics(self):
        response = SimpleNamespace(returncode=1, stdout=b'private-credential', stderr=b'ERROR: private-record')
        with patch.object(recovery.common, 'require_no_logging'), \
                patch.object(recovery.subprocess, 'run', return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                recovery.execute('owned', '/native', input=b'private-sql')
        self.assertNotIn('private', str(caught.exception))

    def test_client_password_uses_stdin_without_shell_interpolation(self):
        with patch.object(recovery, 'execute', return_value=SimpleNamespace(stdout=b'accepted')) as execute:
            self.assertEqual(recovery.client('owned', "secret'$(bad)", 'gitea', 'psql', '-X'), b'accepted')
        args, kwargs = execute.call_args
        self.assertNotIn("secret'$(bad)", str(args))
        self.assertEqual(kwargs['input'], b"secret'$(bad)\n")
        with self.assertRaises(RuntimeError):
            recovery.client('owned', 'secret\nextra', 'gitea', 'psql')

    def test_start_failure_projects_only_fixed_classes_and_hashes(self):
        raw = b'FATAL: could not access the server configuration file "private-value": Permission denied'
        def execute(_container, *args, **_kwargs):
            if args[0].endswith('pg_ctl'):
                raise RuntimeError('fixed start failure')
            return SimpleNamespace(stdout=raw)
        with patch.object(recovery, 'execute', side_effect=execute):
            with self.assertRaises(RuntimeError) as caught:
                recovery.start('owned')
        self.assertIn('file_access', str(caught.exception))
        self.assertIn('missing_config', str(caught.exception))
        self.assertNotIn('private-value', str(caught.exception))

    def test_single_uses_existing_vendor_uid_resolution_and_stdin_only(self):
        with patch.object(recovery, 'execute', return_value=SimpleNamespace(stdout=b'', stderr=b'')) as execute:
            recovery.single('owned', b'secret-verifier-in-stdin')
        args, kwargs = execute.call_args
        self.assertIn('postgresql_enable_nss_wrapper', args[3])
        self.assertIn('trap', args[3])
        self.assertNotIn('secret-verifier', str(args))
        self.assertEqual(kwargs['input'], b'secret-verifier-in-stdin')

    def test_harmless_failure_requires_native_error_and_clean_exit(self):
        for output in ('stdout', 'stderr'):
            response = SimpleNamespace(stdout=b'', stderr=b'', returncode=0)
            setattr(response, output, b'ERROR:  22012: division by zero\n')
            with patch.object(recovery, 'execute', return_value=response) as execute:
                recovery.single('owned', b'fixture', expected_failure=True)
            self.assertIn('log_min_messages=error', execute.call_args.args)
        for response in (SimpleNamespace(stdout=b'', stderr=b'', returncode=0),
                         SimpleNamespace(stdout=b'ERROR: division by zero\n', stderr=b'', returncode=1),
                         SimpleNamespace(stdout=b'ERROR: division by zero\nFATAL: failure', stderr=b'', returncode=0)):
            with patch.object(recovery, 'execute', return_value=response), self.assertRaises(RuntimeError):
                recovery.single('owned', b'fixture', expected_failure=True)

    def test_native_entrypoint_uses_original_environment_and_tmpfs_credentials(self):
        hba = b'reviewed md5 fixture'
        def execute(_container, *args, **_kwargs):
            output = b''
            if args == ('/bin/cat', '/opt/bitnami/postgresql/conf/pg_hba.conf'):
                output = hba
            elif args == ('/bin/cat', recovery.DATA + '/postmaster.opts'):
                output = (recovery.BIN + 'postgres -D ' + recovery.DATA +
                          ' --config-file=/opt/bitnami/postgresql/conf/postgresql.conf'
                          ' --external_pid_file=/opt/bitnami/postgresql/tmp/postgresql.pid'
                          ' --hba_file=/opt/bitnami/postgresql/conf/pg_hba.conf').encode()
            elif args[0] == '/bin/sh' and '/proc/' in args[-1]:
                output = b'/opt/bitnami/postgresql/lib/pgaudit.so'
            return SimpleNamespace(returncode=0, stdout=output, stderr=b'')
        with patch.dict(recovery.VENDOR_HASHES, {}, clear=True), \
                patch.object(recovery, 'execute', side_effect=execute) as native, \
                patch.object(recovery, 'client', return_value=b'gitea|gitea|f\n') as client:
            recovery.normal_start('owned', {'app': 'private-app', 'admin': 'private-admin'}, hba)
        self.assertNotIn('private-app', str([c.args for c in native.call_args_list]))
        self.assertNotIn('private-admin', str([c.args for c in native.call_args_list]))
        self.assertEqual(native.call_args_list[1].kwargs['input'], b'private-app\nprivate-admin\n')
        startup = native.call_args_list[2].args
        self.assertIn('/opt/bitnami/scripts/postgresql/entrypoint.sh', startup)
        self.assertIn('/opt/bitnami/scripts/postgresql/run.sh', startup)
        self.assertIn('POSTGRESQL_SHARED_PRELOAD_LIBRARIES=pgaudit', startup)
        self.assertEqual(client.call_args.args[-1], 'SELECT current_user,current_database(),pg_is_in_recovery()')
        for name in ('conf', 'tmp', 'secrets'):
            self.assertIn('/opt/bitnami/postgresql/' + name, recovery.TMPFS)

    def test_native_startup_refuses_hba_drift_and_unproven_negative_fixture(self):
        def execute(_container, *args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=b'changed', stderr=b'')
        with patch.dict(recovery.VENDOR_HASHES, {}, clear=True), \
                patch.object(recovery, 'execute', side_effect=execute):
            for failed in (False, True):
                with self.assertRaises(RuntimeError):
                    recovery.normal_start('owned', {'app': 'fixture', 'admin': 'fixture'}, b'original', failed)

    def test_native_startup_refuses_changed_vendor_code_before_credentials(self):
        with patch.object(recovery, 'execute', return_value=SimpleNamespace(stdout=b'changed')) as execute:
            with self.assertRaises(RuntimeError):
                recovery.normal_start('owned', {'app': 'private', 'admin': 'private'}, b'hba')
        self.assertEqual(execute.call_count, 2)
        self.assertTrue(all('input' not in c.kwargs for c in execute.call_args_list))

    def test_native_negative_fixture_requires_postgres_port_error(self):
        diagnostic = b'FATAL: invalid value for parameter "port": "invalid-port-fixture"\n'
        def execute(_container, *args, **_kwargs):
            return SimpleNamespace(returncode=int(args[0] == '/usr/bin/env'),
                                   stdout=b'', stderr=diagnostic if args[0] == '/usr/bin/env' else b'')
        with patch.dict(recovery.VENDOR_HASHES, {}, clear=True), \
                patch.object(recovery, 'execute', side_effect=execute):
            recovery.normal_start('owned', {'app': 'fixture', 'admin': 'fixture'}, b'hba', True)

    def test_cold_capture_refuses_live_paths_running_state_pid_and_unknown_layout(self):
        work = recovery.common.ROOT / 'gitea-postgres-account-copy-fixture' / '0'
        state = {'cluster_state': 'shut down'}
        tree = {'data/PG_VERSION': {'kind': 'file', 'sha256':
                'e6c21e8d260fe71882debdb339d2402a2ca7648529bc2303f48649bce0380017'},
                'data/global/pg_control': {'kind': 'file', 'bytes': 8192}}
        recovery.require_cold_copy(work, state, tree)
        for path in (Path('/var/lib/kubelet/live'), recovery.common.ROOT / 'original-point' / '0',
                     work.parent / 'unreviewed'):
            with self.assertRaises(RuntimeError):
                recovery.require_cold_copy(path, state, tree)
        for phase in ('in production', 'in crash recovery', 'shut down in recovery', None):
            with self.assertRaises(RuntimeError):
                recovery.require_cold_copy(work, {'cluster_state': phase}, tree)
        for change in (lambda t: t.update({'data/postmaster.pid': {'kind': 'file'}}),
                       lambda t: t['data/PG_VERSION'].update(sha256='changed'),
                       lambda t: t['data/global/pg_control'].update(bytes=0),
                       lambda t: t.update({'foreign': {'kind': 'symlink'}})):
            modified = copy.deepcopy(tree);change(modified)
            with self.assertRaises(RuntimeError):
                recovery.require_cold_copy(work, state, modified)


if __name__ == '__main__':
    unittest.main()
