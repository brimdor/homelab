#!/usr/bin/env python3
"""Refuse foreign NFS evidence and exercise actual generated fixture programs."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_nfs_kernel_qualification as driver
import nfs_kernel_runtime as runtime


class NativeNFSTests(unittest.TestCase):
    def test_mount_requires_exact_source_protocol_and_remote_lock_cache_contract(self):
        for version in ('3', '4.1'):
            row = {'target': str(runtime.MOUNTS[0]),
                   'source': runtime.CLIENTS[0][3] + ':/' if version == '4.1' else '127.0.0.1:' + str(runtime.EXPORT),
                   'fstype': 'nfs4' if version == '4.1' else 'nfs', 'maj:min': '0:101',
                   'options': 'rw,vers=' + version + ',' + runtime.OPTIONS}
            self.assertEqual(runtime.require_mount(row, version), '0:101')
            for key, value in (('target', '/production'), ('source', '10.0.40.3:/forbidden'), ('fstype', 'ext4'),
                               ('maj:min', ''), ('options', row['options'].replace('hard', 'soft')),
                               ('options', row['options'].replace('nosharecache', 'sharecache')),
                               ('options', row['options'].replace('local_lock=none', 'local_lock=all')),
                               ('options', row['options'] + ',nolock'),
                               ('options', row['options'].replace('vers=' + version, 'vers=4.2'))):
                with self.subTest(version=version, key=key, value=value), self.assertRaises(RuntimeError):
                    runtime.require_mount({**row, key: value}, version)

    def test_network_clients_have_unique_identifiers_and_no_external_routes(self):
        calls = []
        def command(*arguments):
            calls.append(arguments)
            self.assertEqual(arguments[0], 'nsenter')
            client = next(c for c in runtime.CLIENTS if arguments[1] == '--net=/run/netns/' + c[0])
            if arguments[2] == runtime.sys.executable:
                self.assertEqual(arguments[-1], 'qualification-nfs103-' + client[0][-1])
                compile(arguments[-2], '<actual-network-identity-program>', 'exec')
                return json.dumps({'identifier': arguments[-1], 'namespace': 'net:[' + client[4] + ']'})
            if arguments[4:] == ('route',):
                return json.dumps([{'dev': client[2], 'prefsrc': client[4],
                                    'dst': '198.18.103.0/30' if client[0].endswith('a') else '198.18.103.4/30'}])
            if arguments[4:] == ('link',):
                return json.dumps([{'ifname': 'lo'}, {'ifname': client[2]}])
            return ''
        def all_commands(*arguments):
            return command(*arguments) if arguments[0] == 'nsenter' else ''
        with patch.object(runtime.Path, 'exists', return_value=False), \
                patch.object(runtime, 'command', side_effect=all_commands):
            records = runtime.prepare_clients()
        self.assertEqual(len({row['identifier'] for row in records}), 2)
        self.assertEqual(len({row['namespace'] for row in records}), 2)
        self.assertFalse(any('default' in row['routes'] for row in records))
        self.assertIn('127.0.0.1' + runtime.EXPORT_OPTIONS, runtime.export_configuration())
        self.assertNotIn('*', runtime.export_configuration())
        with patch.object(runtime.Path, 'exists', return_value=True), \
                patch.object(runtime, 'command') as native:
            with self.assertRaisesRegex(RuntimeError, 'preexisting'):
                runtime.prepare_clients()
            native.assert_not_called()

    def test_full_corpus_refuses_duplicate_missing_changed_or_unterminated_records(self):
        lines = sorted(runtime.corpus('4.1'))
        valid = ('\n'.join(lines) + '\n').encode()
        self.assertEqual(runtime.verify_corpus(valid, '4.1'), hashlib.sha256(valid).hexdigest())
        for bad in (valid[:-1], valid + b'foreign\n', ('\n'.join(lines[:-1]) + '\n').encode(),
                    valid.replace(lines[0].encode(), lines[1].encode()), valid.replace(b'4.1:', b'3:')):
            with self.assertRaisesRegex(RuntimeError, 'corpus mismatch'):
                runtime.verify_corpus(bad, '4.1')

    def test_actual_complete_guest_install_program_and_driver_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(driver.Qualification)
            fixture.root = Path(directory)
            fixture.ssh = []
            fixture.upload = lambda *args: None
            fixture.identity = lambda: {'boot': 'before'}
            fixture.reboot = lambda expected, previous: {'boot': 'after'}
            programs = []
            phases = []
            def command(_args, **kwargs):
                if 'data' in kwargs:
                    programs.append(kwargs['data'])
                    return b'{"signed_offline_install":true}'
                phase = _args[-1].split()[-1]
                phases.append(phase)
                return json.dumps({'accepted': True} if phase != 'cleanup' else {'mounts_absent': True}).encode()
            fixture.command = command
            with patch.object(driver.Kernel, 'run', return_value={'accepted': True}):
                result = fixture.run()
            self.assertTrue(result['accepted'])
            self.assertEqual(phases, ['prepare', 'exercise', 'verify', 'cleanup'])
            self.assertEqual(len(programs), 1)
            compile(programs[0], '<complete-native-NFS-install>', 'exec')
            self.assertIn(b"'--setopt=gpgcheck=True'", programs[0])
            self.assertIn(b"'--enable-repo=qualification'", programs[0])
            self.assertEqual(result['before']['boot'], 'before')
            self.assertEqual(result['after']['boot'], 'after')

    def test_actual_uid1000_programs_compile_and_use_native_remote_locks(self):
        programs = []
        class Child:
            returncode = 0
            stdout = SimpleNamespace(readline=lambda: b'LOCKED\n')
            def communicate(self, **_kwargs):
                return b'', b''
            def poll(self):
                return 0
        def popen(arguments, **kwargs):
            self.assertEqual((kwargs['user'], kwargs['group'], kwargs['extra_groups']), (1000, 1000, []))
            programs.append(arguments[3])
            return Child()
        def run_user(program, *_args):
            programs.append(program)
        with patch.object(runtime.subprocess, 'Popen', side_effect=popen), \
                patch.object(runtime, 'run_user', side_effect=run_user):
            runtime.lock_and_write('4.1')
        self.assertEqual(len(programs), 4)
        for source in programs:
            compile(source, '<actual-UID1000-operation>', 'exec')
        self.assertIn('LOCK_NB', programs[1])
        self.assertIn('os.fsync', programs[2])


if __name__ == '__main__':
    unittest.main()
