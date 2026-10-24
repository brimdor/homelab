#!/usr/bin/env python3
"""Refuse foreign mounts and preserve exact signed native entrypoints."""

import hashlib
import io
import json
import os
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import ceph_kernel_runtime as kernel
import cephfs_kernel_runtime as runtime
import fedora_cephfs_kernel_qualification as driver


class CephFSTests(unittest.TestCase):
    def test_ambiguous_helper_requires_fresh_exact_monitor_rejection(self):
        result = SimpleNamespace(returncode=32, stderr=runtime.MDS_UNREACHABLE)
        evidence = runtime.require_retired_mount_refusal(result, None, 1)
        self.assertEqual(evidence, {'helper_exit': 32, 'direct_permission_refusal': False,
                                   'ambiguous_mds_message': True, 'fresh_monitor_key_refusals': 1})
        for count in (0, -1, True, 1.0, None):
            with self.subTest(count=count), self.assertRaises(RuntimeError):
                runtime.require_retired_mount_refusal(result, None, count)
        for code, mount, message in (
                (0, None, runtime.MDS_UNREACHABLE),
                (32, {'owned': True}, runtime.MDS_UNREACHABLE),
                (110, None, runtime.MDS_UNREACHABLE),
                (32, None, b'mount error 110 = Connection timed out\n'),
                (32, None, runtime.MDS_UNREACHABLE + b'foreign\n')):
            with self.subTest(code=code, mount=mount), self.assertRaises(RuntimeError):
                runtime.require_retired_mount_refusal(SimpleNamespace(returncode=code, stderr=message), mount, 1)

    def test_authentication_evidence_requires_fresh_owned_unchanged_regular_log(self):
        rejection = b'prefix cephx server client.filesystem:  unexpected key: PRIVATE_SENTINEL\n'
        foreign = b'prefix cephx server client.foreign:  unexpected key: PRIVATE_SENTINEL\n'
        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(runtime.Runtime)
            fixture.root = Path(directory)
            log = fixture.root / 'mon.log'
            log.write_bytes(rejection + foreign)
            before = fixture.auth_log_position()
            self.assertEqual(fixture.fresh_auth_refusals(before), 0)
            with log.open('ab') as output:
                output.write(foreign + rejection + b'client.filesystem: challenge_error PRIVATE_SENTINEL\n')
            self.assertEqual(fixture.fresh_auth_refusals(before), 1)
            self.assertEqual(fixture.fresh_auth_refusals(fixture.auth_log_position()), 0)
            with patch.object(runtime.os, 'geteuid', return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(RuntimeError, 'foreign'):
                    fixture.auth_log_position()
                with self.assertRaisesRegex(RuntimeError, 'replaced or truncated'):
                    fixture.fresh_auth_refusals(before)
            after = fixture.auth_log_position()
            log.write_bytes(b'')
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                fixture.fresh_auth_refusals(after)
            log.rename(fixture.root / 'old.log')
            log.write_bytes(rejection * 10)
            with self.assertRaisesRegex(RuntimeError, 'replaced'):
                fixture.fresh_auth_refusals(before)
            log.unlink()
            log.symlink_to(fixture.root / 'old.log')
            with self.assertRaisesRegex(RuntimeError, 'foreign'):
                fixture.auth_log_position()
            with self.assertRaises(OSError):
                fixture.fresh_auth_refusals(before)
            log.unlink()
            log.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'foreign'):
                fixture.auth_log_position()

    def test_later_failure_preserves_completed_public_profiles_and_reaps_children(self):
        completed = {'modern_rados': {'accepted': True, 'payload_sha256': 'public-hash'},
                     'kernel_rbd': {'accepted': True, 'client_rotation': True}}
        fixture = SimpleNamespace(stage='cephfs', children={'mon': object()},
                                  run=lambda: completed['modern_rados'],
                                  kernel_io=lambda: completed['kernel_rbd'])
        stopped = []
        fixture.stop = stopped.append
        def fail():
            raise RuntimeError('PRIVATE_SENTINEL')
        fixture.cephfs_io = fail
        output = io.StringIO()
        with patch.object(runtime, 'Runtime', return_value=fixture), \
                patch.object(runtime.signal, 'signal'), \
                patch.object(runtime, 'manager_diagnostic', return_value={'checks': []}), \
                patch('sys.stdout', output), self.assertRaises(RuntimeError):
            runtime.main()
        failure = json.loads(output.getvalue())
        self.assertFalse(failure['accepted'])
        self.assertEqual(failure['completed_profiles'], completed)
        self.assertEqual(failure['error_type'], 'RuntimeError')
        self.assertNotIn('PRIVATE_SENTINEL', output.getvalue())
        self.assertEqual(stopped, ['mon'])

    def test_retired_mount_refusal_keeps_gate_and_records_only_typed_failure(self):
        for message in (b'mount error 13 = Permission denied\n',
                        b'mount error 1 = Operation not permitted\n'):
            runtime.require_retired_mount_refusal(SimpleNamespace(returncode=32, stderr=message), None)
        for code, mount, message in (
                (0, None, b'mount error 13 = Permission denied\n'),
                (32, {'owned': True}, b'mount error 13 = Permission denied\n'),
                (32, None, b'mount error 110 = Connection timed out\n'),
                (32, None, b'mount error 129 = Key was rejected by service\n'),
                (32, None, b'PRIVATE_SENTINEL\nsecret=' + b'A' * 64 + b'\n')):
            with self.subTest(code=code, mount=mount, message=message):
                with self.assertRaises(RuntimeError) as failure:
                    runtime.require_retired_mount_refusal(SimpleNamespace(returncode=code, stderr=message), mount)
                evidence = json.loads(str(failure.exception).partition(': ')[2])
                self.assertEqual(evidence['exit_code'], code)
                self.assertEqual(evidence['mount_present'], mount is not None)
                self.assertEqual(evidence['stderr_sha256'], hashlib.sha256(message).hexdigest())
                self.assertNotIn('PRIVATE_SENTINEL', str(failure.exception))
                self.assertNotIn('AAAA', str(failure.exception))
                if b'110' in message:
                    self.assertEqual(evidence['mount_errors'], [['110', 'Connection timed out']])

    def test_exact_mount_identity_and_encrypted_transport_required(self):
        fsid = '00000000-1111-2222-3333-444444444444'
        target = runtime.MOUNTS[0]
        row = {'target': str(target), 'source': 'filesystem@' + fsid + '.qualificationfs=/',
               'fstype': 'ceph', 'options': 'rw,noshare,ms_mode=secure', 'maj:min': '0:55'}
        self.assertEqual(runtime.owned_mount({'filesystems': [row]}, target, fsid)['device'], '0:55')
        for key, value in (('target', '/production'), ('source', '10.0.40.3:/forbidden'),
                           ('source', row['source'].replace(fsid, 'foreign')),
                           ('source', row['source'].replace('qualificationfs', 'production')),
                           ('fstype', 'nfs'), ('maj:min', ''), ('options', 'rw,ms_mode=crc'),
                           ('options', 'ro,ms_mode=secure')):
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                runtime.owned_mount({'filesystems': [{**row, key: value}]}, target, fsid)
        for rows in ([], [row, row]):
            with self.assertRaises(RuntimeError):
                runtime.owned_mount({'filesystems': rows}, target, fsid)

    def test_native_modern_mds_and_client_metadata_cannot_be_missing_or_legacy(self):
        rows = [{'entity': {'type_str': kind, 'id': identity}, 'auth': {'key': {'type_str': 'aes256k'}}}
                for kind, identity in (('mds', 'a'), ('client', 'filesystem'))]
        self.assertEqual(runtime.filesystem_key_types({'data': {'secrets': rows}}),
                         {'mds.a': 'aes256k', 'client.filesystem': 'aes256k'})
        for bad in ([], rows[:1], rows + rows[:1],
                    [rows[0], {**rows[1], 'auth': {'key': {'type_str': 'aes'}}}]):
            with self.assertRaises(RuntimeError):
                runtime.filesystem_key_types({'data': {'secrets': bad}})

    def test_exact_sources_preserve_native_root_and_matching_signed_mds(self):
        fixture = object.__new__(driver.Qualification)
        fixture.ssh = []
        uploads = []
        fixture.upload = lambda source, target, digest: uploads.append((source, target, digest))
        calls = []
        def command(args):
            calls.append(args)
            return b'{"native":true}'
        fixture.command = command
        value, files = fixture.native_runtime()
        self.assertTrue(value['native'])
        self.assertEqual(calls, [['sudo python3 -B /run/qualification-cephfs-runtime.py']])
        self.assertEqual({target for _, target, _ in uploads}, {
            '/work/ceph_kernel_runtime.py', '/work/ceph_runtime_qualification.py', '/work/etcd_recovery.py',
            '/run/qualification-cephfs-runtime.py'})
        for source, _target, digest in uploads:
            self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(files[source.name], digest)
        self.assertEqual(driver.Qualification.targets, [*driver.TARGETS, 'ceph-mds-2:20.2.4-1.fc44.x86_64'])
        compile(runtime.CORPUS, '<actual-native-complete-corpus-program>', 'exec')
        self.assertIn('os.fsync', runtime.CORPUS)
        self.assertIn('path.read_bytes()==expected', runtime.CORPUS)

    def test_only_owned_manager_receives_independent_sqlite_configuration(self):
        fixture = object.__new__(kernel.Runtime)
        with patch.dict(kernel.os.environ, {'CEPH_ARGS': 'parent-value'}):
            with patch.object(kernel.ModernRuntime, 'start') as start:
                fixture.start('mgr', 'a')
                start.assert_called_once_with('mgr', 'a', env=kernel.os.environ | {
                    'CEPH_CONF': '/work/ceph.conf', 'CEPH_KEYRING': '/work/mgr/keyring',
                    'CEPH_ARGS': '--name=mgr.a --debug-cephsqlite=10/10'})
                self.assertEqual(kernel.os.environ['CEPH_ARGS'], 'parent-value')
                start.reset_mock()
                fixture.start('osd', '0')
                start.assert_called_once_with('osd', '0', env=None)
                with self.assertRaisesRegex(RuntimeError, 'foreign synthetic manager'):
                    fixture.start('mgr', 'foreign')

    def vendor_classes(self, root):
        directory = root / 'classes'
        directory.mkdir()
        for name in ('lock', 'rbd', 'cephfs'):
            target = directory / ('libcls_' + name + '.so.1.0.0')
            target.write_bytes(('synthetic-' + name).encode())
            (directory / ('libcls_' + name + '.so')).symlink_to(target.name)
        return directory

    def test_native_class_configuration_requires_vendor_files_and_exact_rpm_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = self.vendor_classes(root)
            fixture = object.__new__(kernel.Runtime)
            calls = []
            def command(arguments):
                calls.append(arguments)
                return SimpleNamespace(stdout=b'ceph-base 20.2.4-1.fc44.x86_64')
            fixture.command = command
            with patch.object(kernel, 'CLASS_DIRECTORY', directory):
                self.assertEqual(fixture.class_configuration(), 'osd class dir = ' + str(directory) + '\n')
                evidence = fixture.class_directory_evidence
                self.assertEqual([item['class'] for item in evidence['libraries']], ['lock', 'rbd', 'cephfs'])
                self.assertEqual(len(calls), 3)
                for item, call in zip(evidence['libraries'], calls):
                    self.assertEqual(call, ['rpm', '-qf', '--qf', '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}',
                                            item['resolved_path']])
                    self.assertEqual(item['sha256'], hashlib.sha256(Path(item['resolved_path']).read_bytes()).hexdigest())
                fixture.command = lambda args: SimpleNamespace(stdout=b'foreign 1-1.x86_64')
                with self.assertRaisesRegex(RuntimeError, 'RPM identity'):
                    fixture.class_configuration()
                fixture.command = command
                link = directory / 'libcls_lock.so'
                link.unlink()
                with self.assertRaises(FileNotFoundError):
                    fixture.class_configuration()
                foreign = root / 'foreign.so'
                foreign.write_bytes(b'foreign')
                link.symlink_to(foreign)
                with self.assertRaisesRegex(RuntimeError, 'escaped'):
                    fixture.class_configuration()
                link.unlink()
                link.mkdir()
                with self.assertRaisesRegex(RuntimeError, 'not a file'):
                    fixture.class_configuration()
            redirected = root / 'redirected'
            redirected.symlink_to(directory, target_is_directory=True)
            for path in (root / 'absent', redirected):
                with patch.object(kernel, 'CLASS_DIRECTORY', path), self.assertRaisesRegex(RuntimeError, 'absent or redirected'):
                    fixture.class_configuration()

    def test_actual_shared_bootstrap_config_only_changes_native_class_path(self):
        class BootstrapReached(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = self.vendor_classes(root)
            for native in (False, True):
                fixture = object.__new__(kernel.Runtime if native else kernel.ModernRuntime)
                fixture.root = root / ('native' if native else 'container')
                fixture.root.mkdir()
                def command(arguments):
                    if arguments == ['ceph', '--version']:
                        return SimpleNamespace(stdout=b'ceph version 20.2.4 synthetic')
                    if arguments[0] == 'rpm':
                        return SimpleNamespace(stdout=b'ceph-base 20.2.4-1.fc44.x86_64')
                    raise BootstrapReached()
                fixture.command = command
                with patch.object(kernel, 'CLASS_DIRECTORY', directory), self.assertRaises(BootstrapReached):
                    fixture.run()
                config = (fixture.root / 'ceph.conf').read_text()
                self.assertEqual('osd class dir = ' + str(directory) + '\n' in config, native)
                self.assertEqual(config.count('osd class dir'), int(native))
                self.assertNotIn('osd class load list', config)
                self.assertNotIn('osd class default list', config)
                self.assertIn('auth allow insecure global id reclaim = false', config)

    def test_sqlite_diagnostics_exclude_credentials_and_unrelated_log_lines(self):
        raw = (b'cephsqlite: Open: cannot open striper: (13) Permission denied\n'
               b'cephsqlite: read: read failed: (5) Input/output error\n'
               b'cephsqlite: secret=PRIVATE_SENTINEL\n'
               b'arbitrary unrelated PRIVATE_SENTINEL\n'
               b'cephsqlite: opaque AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n')
        messages = kernel.sqlite_messages(raw)
        self.assertEqual(len(messages), 3)
        self.assertIn('(13) Permission denied', messages[0])
        self.assertIn('(5) Input/output error', messages[1])
        self.assertNotIn('PRIVATE_SENTINEL', str(messages))
        self.assertNotIn('AAAAAAAA', str(messages))
        self.assertEqual(len(kernel.sqlite_messages(b'cephsqlite: error\n' * 100)), 48)

    def test_native_manager_diagnostic_scopes_logs_pools_and_avc_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mgr.log').write_text('cephsqlite: Open: cannot create ioctx: (2) No such file or directory\n')
            (root / 'osd.log').write_text('prefix _load_class could not stat class /usr/lib64/rados-classes/libcls_lock.so: (2) No such file\n')
            calls = []
            pool = {'pool_name': '.mgr', 'pool_id': 1, 'size': 1, 'min_size': 1, 'pg_num': 1,
                    'foreign': 'PRIVATE_SENTINEL'}
            def command(arguments, **kwargs):
                calls.append((arguments, kwargs))
                if arguments[0] == 'ceph':
                    self.assertEqual(arguments[:5], ['ceph', '--admin-daemon', str(root / 'osd.0.asok'), 'config', 'get'])
                    name = arguments[-1]
                    value = '/usr/lib64/rados-classes' if name == 'osd_class_dir' else 'lock rbd'
                    return SimpleNamespace(returncode=0, stdout=json.dumps({name: value}).encode())
                row = {'MESSAGE': 'avc: denied { read open } for pid=42 comm="ceph-mgr" '
                       'scontext=system_u:system_r:unconfined_t:s0 '
                       'tcontext=system_u:object_r:var_t:s0 tclass=file permissive=0 name="PRIVATE_SENTINEL"'}
                return SimpleNamespace(returncode=0, stdout=json.dumps(row).encode())
            fixture = SimpleNamespace(root=root, command=command,
                                      ceph=lambda *args: json.dumps([pool]).encode())
            value = kernel.manager_native_diagnostic(fixture)
            self.assertEqual(value['pool_policies'][0]['name'], '.mgr')
            self.assertEqual(value['pool_policies'][0]['pool_id'], 1)
            self.assertEqual(value['kernel_avc_denials'][0]['permissions'], ['read', 'open'])
            self.assertEqual(value['kernel_avc_denials'][0]['comm'], 'ceph-mgr')
            self.assertIn('(2) No such file', value['logs'][0]['sqlite_messages'][0])
            self.assertIn('libcls_lock.so', value['osd_class_logs'][0]['class_messages'][0])
            self.assertEqual(value['osd_class_config'], [
                {'name': name, 'exit_code': 0, 'value': '/usr/lib64/rados-classes' if name == 'osd_class_dir' else 'lock rbd'}
                for name in ('osd_class_dir', 'osd_class_load_list', 'osd_class_default_list')])
            self.assertNotIn('PRIVATE_SENTINEL', str(value))
            self.assertIn('--grep=avc:.*denied', calls[0][0])
            for bad in ({key: value for key, value in pool.items() if key != 'pool_id'},
                        {**pool, 'pool_id': 'PRIVATE_SENTINEL'}):
                fixture.ceph = lambda *args: json.dumps({'status': 'HEALTH_ERR', 'checks': {}} if args[0] == 'health' else [bad]).encode()
                partial = kernel.manager_diagnostic(fixture)
                self.assertIn(partial['native_diagnostic_error'], ('KeyError', 'RuntimeError'))
                self.assertIn('(2) No such file', partial['native']['logs'][0]['sqlite_messages'][0])
                self.assertEqual(partial['native']['kernel_avc_denials'][0]['permissions'], ['read', 'open'])
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(partial))
            fixture.ceph = lambda *args: json.dumps([pool]).encode()
            pool['pool_name'] = 'production'
            with self.assertRaisesRegex(RuntimeError, 'foreign native diagnostic pool'):
                kernel.manager_native_diagnostic(fixture)
            (root / 'mgr.log').unlink()
            (root / 'mgr.log').symlink_to(root / 'foreign')
            with self.assertRaisesRegex(RuntimeError, 'foreign synthetic manager log'):
                kernel.manager_native_diagnostic(fixture)

    def test_class_diagnostics_preserve_native_loader_errors_and_refuse_foreign_evidence(self):
        raw = (b'prefix _load_class lock from /usr/lib64/rados-classes/libcls_lock.so\n'
               b'prefix _load_class could not open class /usr/lib64/rados-classes/libcls_lock.so (dlopen failed): missing dependency\n'
               b'class rbd open got (2) No such file\n'
               b'class lock method missing token=PRIVATE_SENTINEL\n'
               b'unrelated PRIVATE_SENTINEL\n'
               b'class lock open AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n')
        messages = kernel.class_messages(raw)
        self.assertEqual(len(messages), 4)
        self.assertIn('missing dependency', messages[1])
        self.assertNotIn('PRIVATE_SENTINEL', str(messages))
        self.assertNotIn('AAAAAAAA', str(messages))
        self.assertEqual(len(kernel.class_messages(b'class lock open error\n' * 100)), 32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'osd.0.native.log').write_bytes(raw)
            def command(arguments, **kwargs):
                if arguments[0] == 'journalctl':
                    return SimpleNamespace(returncode=1, stdout=b'')
                return SimpleNamespace(returncode=0, stdout=b'{"foreign":"PRIVATE_SENTINEL"}')
            fixture = SimpleNamespace(root=root, command=command, ceph=lambda *args:
                                      b'{"status":"HEALTH_ERR","checks":{}}')
            value = kernel.manager_diagnostic(fixture)
            self.assertEqual(value['native_diagnostic_error'], 'RuntimeError')
            self.assertIn('missing dependency', value['native']['osd_class_logs'][0]['class_messages'][1])
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(value))
            (root / 'osd.log').symlink_to(root / 'foreign')
            with self.assertRaisesRegex(RuntimeError, 'foreign synthetic OSD log'):
                kernel.manager_native_diagnostic(fixture)

    def test_pending_manager_failure_retains_only_sanitized_public_health(self):
        secret = 'A' * 64
        finding = {'severity': 'HEALTH_ERR', 'summary': {'message': 'Module failed ' + secret},
                   'detail': [{'message': 'module dependency unavailable'}]}
        class Fixture:
            def ceph(self, *arguments):
                self.arguments = arguments
                return json.dumps({'status': 'HEALTH_ERR', 'checks': {'MGR_MODULE_ERROR': finding},
                                   'auth': secret}).encode()
        fixture = Fixture()
        value = kernel.manager_diagnostic(fixture)
        self.assertEqual(fixture.arguments, ('health', 'detail', '--format=json'))
        self.assertEqual(value['checks'], ['MGR_MODULE_ERROR'])
        self.assertNotIn(secret, json.dumps(value))
        self.assertNotIn('auth', value)
        self.assertEqual(value['manager_module_error']['details'], ['module dependency unavailable'])


if __name__ == '__main__':
    unittest.main()
