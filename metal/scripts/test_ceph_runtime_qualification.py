#!/usr/bin/env python3
"""Reject synthetic runtime identity, mount, capability and block changes."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ceph_runtime_qualification as subject


class RuntimeGuardTests(unittest.TestCase):
    def test_replication_requires_exact_cluster_and_clean_two_copy_state(self):
        value = {'fsid': 'synthetic', 'mgrmap': {'available': True},
                 'pgmap': {'pgs_by_state': [{'state_name': 'active+clean'}]},
                 'health': {'status': 'HEALTH_OK', 'checks': {}}}
        rows = [{'osd': number, 'up': 1, 'in': 1} for number in range(3)]
        self.assertTrue(subject.replica_state(value, rows, {0, 1, 2}, 'synthetic'))
        rows[0].update(up=0, **{'in': 0})
        self.assertTrue(subject.replica_state(value, rows, {1, 2}, 'synthetic'))
        self.assertFalse(subject.replica_state(value, rows, {0, 1, 2}, 'synthetic'))
        rows[0]['in'] = 1
        self.assertFalse(subject.replica_state(value, rows, {1, 2}, 'synthetic'))
        for wrong in ('foreign', None):
            with self.assertRaises(RuntimeError):
                subject.replica_state(value, rows, {1, 2}, wrong)
        with self.assertRaises(RuntimeError):
            subject.replica_state(value, rows[:2], {1, 2}, 'synthetic')
        with self.assertRaises(RuntimeError):
            subject.replica_state(value, rows, {1}, 'synthetic')
        rows[0]['in'] = 0
        changed = copy.deepcopy(value)
        changed['pgmap']['pgs_by_state'][0]['state_name'] = 'active+undersized+degraded'
        self.assertFalse(subject.replica_state(changed, rows, {1, 2}, 'synthetic'))
        changed = copy.deepcopy(value)
        changed['health'] = {'status': 'HEALTH_WARN', 'checks': {'OSD_DOWN': {}}}
        with self.assertRaises(RuntimeError):
            subject.replica_state(changed, rows, {1, 2}, 'synthetic')

    def test_object_requires_two_distinct_live_copies_and_matching_up_set(self):
        value = {'pool': 'qualification', 'objname': 'replica-000', 'acting': [1, 2], 'up': [1, 2]}
        self.assertEqual(subject.replica_placement(value, 'replica-000', {1, 2}), {1, 2})
        for fields in ({'pool': 'foreign'}, {'objname': 'foreign'}, {'acting': [1]},
                       {'acting': [1, 1]}, {'acting': [0, 1]}, {'up': [2, 1]}, {'acting': None}):
            with self.assertRaises(RuntimeError):
                subject.replica_placement(value | fields, 'replica-000', {1, 2})

    def test_distinct_osd_children_do_not_replace_existing_owned_process(self):
        runtime = object.__new__(subject.Runtime)
        runtime.children = {}
        runtime.conf = ['-c', '/work/ceph.conf']
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            children = [Mock(), Mock(), Mock()]
            with patch.object(subject.subprocess, 'Popen', side_effect=children) as spawn:
                for number in range(3):
                    runtime.start('osd', str(number))
                self.assertEqual(runtime.children, dict(zip(('osd', 'osd.1', 'osd.2'), children)))
                with self.assertRaises(RuntimeError):
                    runtime.start('osd', '1')
                self.assertEqual(spawn.call_count, 3)
                for number, call in enumerate(spawn.call_args_list):
                    self.assertEqual(call.args[0], ['ceph-osd', *runtime.conf, '-i', str(number), '-f',
                                                    '--setuser=root', '--setgroup=root'])

    def container(self):
        return {'Config': {'Image': subject.IMAGE, 'Hostname': 'ceph103-fixture-103',
                           'Labels': {'io.eaglepass.maintenance': '103',
                                      'io.eaglepass.recovery-run': 'fixture-103'}},
                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                               'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                               'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                               'Memory': 4 * 1024**3, 'NanoCpus': 2000000000, 'PidsLimit': 512,
                               'Tmpfs': {'/run': 'rw,nosuid,nodev', '/tmp': 'rw,nosuid,nodev'},
                               'RestartPolicy': {'Name': 'no'}},
                'Mounts': [{'Type': 'bind', 'Source': '/owned', 'Destination': '/work', 'RW': True}]}

    def test_exact_image_and_no_production_mount_or_route(self):
        value = self.container()
        subject.require_container(value, Path('/owned'), 'fixture-103', [])
        for change in ({'NetworkMode': 'host'}, {'Privileged': True}, {'CapAdd': ['SYS_ADMIN']},
                       {'PidMode': 'host'}, {'PortBindings': {'3100/tcp': []}}, {'ReadonlyRootfs': False}):
            changed = copy.deepcopy(value)
            changed['HostConfig'].update(change)
            with self.assertRaises(RuntimeError):
                subject.require_container(changed, Path('/owned'), 'fixture-103', [])
        for field in ('Source', 'Destination'):
            changed = copy.deepcopy(value)
            changed['Mounts'][0][field] = '/var/lib/ceph'
            with self.assertRaises(RuntimeError):
                subject.require_container(changed, Path('/owned'), 'fixture-103', [])
        changed = copy.deepcopy(value)
        changed['Config']['Image'] = 'quay.io/ceph/ceph:latest'
        with self.assertRaises(RuntimeError):
            subject.require_container(changed, Path('/owned'), 'fixture-103', [])
        with self.assertRaises(RuntimeError):
            subject.require_container(value, Path('/owned'), 'fixture-103', ['/'])

    def test_sparse_owned_block_identity_and_refuse_link_or_wrong_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'block'
            with path.open('xb') as output:
                output.truncate(subject.BLOCK_BYTES)
            before = subject.block_identity(root)
            self.assertEqual(before['bytes'], subject.BLOCK_BYTES)
            self.assertEqual(before, subject.block_identity(root))
            path.write_bytes(b'wrong size')
            with self.assertRaises(RuntimeError):
                subject.block_identity(root)
            path.unlink()
            path.symlink_to('/etc/hosts')
            with self.assertRaises(RuntimeError):
                subject.block_identity(root)

    def test_internal_entry_refuses_host_and_diagnostic_redacts_key(self):
        with self.assertRaises(RuntimeError):
            subject.Runtime(Path('/not-the-fixture'), 'fixture-103')
        secret = b'key = AQAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJKKKKLLLLMMMMNNNN===='
        self.assertNotIn('AQAABBBB', subject.sanitized(secret))

    def test_rotation_requires_changed_key_and_private_regular_destination(self):
        runtime = object.__new__(subject.Runtime)
        runtime.ceph = Mock(return_value=b'[client.fixture]\nkey = synthetic\n')
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'original'
            original.write_bytes(b'original')
            destination = Path(directory) / 'rotated'
            runtime.command = Mock(side_effect=[Mock(stdout=b'old\n'), Mock(stdout=b'new\n')])
            runtime.rotate_keyring('client.fixture', original, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.read_bytes(), runtime.ceph.return_value)
            runtime.ceph.assert_called_once_with('auth', 'rotate', 'client.fixture', '--key-type=aes256k')
            runtime.command = Mock(side_effect=[Mock(stdout=b'same'), Mock(stdout=b'same')])
            with self.assertRaises(RuntimeError):
                runtime.rotate_keyring('client.fixture', original, destination)
            destination.unlink()
            destination.symlink_to(original)
            runtime.command = Mock(return_value=Mock(stdout=b'old'))
            with self.assertRaises(OSError):
                runtime.rotate_keyring('client.fixture', original, destination)
            self.assertEqual(original.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
