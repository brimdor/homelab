#!/usr/bin/env python3
"""Refuse foreign mounts and preserve exact signed native entrypoints."""

import hashlib
import json
from pathlib import Path
import unittest

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
