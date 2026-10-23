#!/usr/bin/env python3
"""Refuse foreign mounts and preserve exact signed native entrypoints."""

import hashlib
import json
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import ceph_kernel_runtime as kernel
import cephfs_kernel_runtime as runtime
import fedora_cephfs_kernel_qualification as driver


class CephFSTests(unittest.TestCase):
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
