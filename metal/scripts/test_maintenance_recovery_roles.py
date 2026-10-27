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
