"""Exercise actual generated archive paths for agent and server roles."""
import ast
import shlex
import types
import unittest
from unittest import mock

import maintenance_production_node as production


class CaptureProgram(Exception):
    pass


class RecoveryRoleTests(unittest.TestCase):
    def setUp(self):
        self.previous = {name: getattr(production, name) for name in (
            'NODE', 'ADDRESS', 'UID', 'MAC', 'IDENTITY', 'BACKUPS',
            'RECEIVER', 'RECEIVER_ADDRESS', 'RECEIVER_IDENTITY')}

    def tearDown(self):
        for name, value in self.previous.items():
            setattr(production, name, value)

    def archive_paths(self, node, exists, directory=True, symlink=False):
        production.select_node(node)
        captured = []

        def capture(argv, **kwargs):
            captured.append(shlex.split(argv[-1])[-1])
            raise CaptureProgram()

        args = types.SimpleNamespace(identity='unused', known_hosts='unused')
        with mock.patch.object(production, 'remote', return_value=None), \
                mock.patch('maintenance_control_plane.recovery', return_value={}), \
                mock.patch.object(production.subprocess, 'Popen', side_effect=capture):
            with self.assertRaises(CaptureProgram):
                production.recovery(args, 39, capture=True)
        program = ast.parse(captured[0])
        start = next(i for i, statement in enumerate(program.body) if isinstance(statement, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'command'
                             for target in statement.targets))
        # Execute the generated path selection, excluding identity probes and tar itself.
        fragment = ast.Module(body=program.body[start:-1], type_ignores=[])
        server = types.SimpleNamespace(exists=lambda: exists, is_dir=lambda: directory,
                                       is_symlink=lambda: symlink)
        scope = {'pathlib': types.SimpleNamespace(Path=lambda path: server)}
        exec(compile(fragment, '<archive-paths>', 'exec'), scope)
        return scope['command']

    def test_agent_without_server_retains_boot_identity_and_osd_metadata(self):
        paths = self.archive_paths('cyndaquil', False)
        self.assertNotIn('var/lib/rancher/k3s/server', paths)
        for required in ('etc', 'boot', 'boot/efi', 'usr/local/bin/k3s', 'var/lib/rancher/k3s/agent',
                         'var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_1c69c51e-b0da-42ee-bd34-581361740a02'):
            self.assertIn(required, paths)
        self.assertTrue(production.BACKUPS[39].endswith('-20261027-b'))

    def test_growlithe_retains_its_existing_agent_state_and_exact_nvme_metadata(self):
        paths = self.archive_paths('growlithe', True)
        self.assertIn('var/lib/rancher/k3s/server', paths)
        self.assertIn('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_e7ccd0a2-4d7a-41bb-aac9-5464abe2ba85', paths)
        self.assertNotIn('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_1c69c51e-b0da-42ee-bd34-581361740a02', paths)
        self.assertEqual(production.RECEIVER_ADDRESS, '10.0.20.11')
        self.assertTrue(production.BACKUPS[39].endswith('growlithe-fedora39-config-20261027-a'))

    def test_arcanine_preserves_both_metadata_directories_without_reading_block_devices(self):
        paths = self.archive_paths('arcanine', True)
        self.assertEqual(production.RECEIVER_ADDRESS, '10.0.20.11')
        for prefix, block in production.OSD_RECOVERY['arcanine']:
            self.assertIn(prefix, paths)
            self.assertNotIn(block, paths)
        self.assertNotIn('--dereference', paths)
        self.assertEqual(production.UID, '88aa2572-09df-40b9-8a00-960e9682917c')

    def test_generated_metadata_readback_refuses_foreign_block_and_missing_members(self):
        import io
        import tarfile
        import tempfile
        import textwrap
        from pathlib import Path
        for node in ('cyndaquil', 'growlithe', 'arcanine'):
            production.select_node(node)
            class ReadbackCaptured(Exception):
                pass
            programs = []
            def capture(args, program, address):
                programs.append(program)
                raise ReadbackCaptured()
            with mock.patch.object(production, 'remote', side_effect=capture):
                with self.assertRaises(ReadbackCaptured):
                    production.recovery(None, 39)
            program = programs[0]
            start = program.index(' osd_recovery=')
            end = program.index(' print(json.dumps(value))', start)
            snippet = textwrap.dedent(program[start:end])
            pairs = production.OSD_RECOVERY[node] if node == 'arcanine' else (production.OSD_RECOVERY[node],)
            names = ('ceph_fsid', 'fsid', 'keyring', 'ready', 'require_osd_release', 'type', 'whoami')
            for fault in (None, 'foreign-block', 'missing-member', 'missing-osd', 'duplicate-member'):
                with self.subTest(node=node, fault=fault), tempfile.TemporaryDirectory() as directory:
                    archive = Path(directory) / 'synthetic.tar'
                    with tarfile.open(archive, 'w') as target:
                        for index, (prefix, block) in enumerate(pairs):
                            if fault == 'missing-osd' and index == len(pairs) - 1:continue
                            entry = tarfile.TarInfo(prefix);entry.type = tarfile.DIRTYPE;target.addfile(entry)
                            entry = tarfile.TarInfo(prefix + '/block');entry.type = tarfile.SYMTYPE
                            entry.linkname = '/dev/foreign' if fault == 'foreign-block' else block;target.addfile(entry)
                            for name in names:
                                if fault == 'missing-member' and name == 'whoami':continue
                                entry = tarfile.TarInfo(prefix + '/' + name);entry.size = 1;target.addfile(entry, io.BytesIO(b'x'))
                            if fault == 'duplicate-member':target.addfile(entry, io.BytesIO(b'x'))
                    scope = {'value': {'node': node}, 'archive': archive, 'tarfile': tarfile}
                    if fault is None:exec(snippet, scope)
                    else:
                        with self.assertRaises(AssertionError):exec(snippet, scope)

    def test_retained_store_is_verified_before_growlithe_configuration_capture(self):
        import inspect
        source = inspect.getsource(production.main)
        guard = source.index("if NODE == 'growlithe' and owner is None:")
        capture = source.index('recovery_manifest = recovery(args,')
        self.assertLess(guard, capture)
        self.assertIn('verify(args, node=NODE)', source[guard:capture])

    def test_existing_agent_server_state_is_preserved(self):
        self.assertIn('var/lib/rancher/k3s/server', self.archive_paths('cyndaquil', True))

    def test_server_role_requires_server_and_retains_separate_etcd_contract(self):
        with self.assertRaisesRegex(AssertionError, 'control-plane recovery'):
            self.archive_paths('charmander', False)
        paths = self.archive_paths('charmander', True)
        self.assertIn('var/lib/rancher/k3s/server', paths)
        self.assertIn('--exclude=var/lib/rancher/k3s/server/db', paths)
        self.assertIn('var/lib/homelab-recovery/maintenance-103', paths)

    def test_symlink_or_non_directory_server_is_refused(self):
        for options in ({'exists': True, 'directory': False}, {'exists': False, 'symlink': True}):
            with self.subTest(options=options), self.assertRaises(AssertionError):
                self.archive_paths('cyndaquil', **options)


if __name__ == '__main__':
    unittest.main()
