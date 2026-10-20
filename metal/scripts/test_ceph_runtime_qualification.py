#!/usr/bin/env python3
"""Reject synthetic runtime identity, mount, capability and block changes."""

import copy
from pathlib import Path
import tempfile
import unittest

import ceph_runtime_qualification as subject


class RuntimeGuardTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
