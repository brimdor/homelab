"""Reject a qualification container that can reach production or expose credentials."""

from copy import deepcopy
from pathlib import Path
import unittest

from qualify_auth_proxy import IMAGE, LABEL, isolated


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/var/tmp/owned-qualification')
        self.value = {
            'Config': {'Image': IMAGE, 'User': '101:101', 'Labels': {LABEL: 'owned'}},
            'HostConfig': {
                'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                'LogConfig': {'Type': 'none'}, 'IpcMode': 'private',
                'PidsLimit': 64, 'Memory': 134217728, 'NanoCpus': 500000000,
                'Tmpfs': {'/tmp': 'rw,nosuid,nodev,uid=101,gid=101,mode=0700,size=16777216'},
            },
            'Mounts': [
                {'Type': 'bind', 'Mode': 'ro,Z', 'RW': False,
                 'Source': str(self.root / directory), 'Destination': target}
                for directory, target in [('config', '/etc/nginx-auth'), ('users', '/etc/nginx-auth-users')]
            ],
        }

    def test_owned_isolated_container(self):
        isolated(self.value, self.root, 'owned')

    def test_rejects_network_privilege_logs_and_missing_limits(self):
        changes = {
            'NetworkMode': 'host', 'ReadonlyRootfs': False, 'Privileged': True,
            'CapDrop': [], 'SecurityOpt': [], 'LogConfig': {'Type': 'json-file'},
            'PortBindings': {'8080/tcp': [{'HostPort': '8080'}]},
            'Devices': [{'PathOnHost': '/dev/sda'}], 'PidMode': 'host',
            'IpcMode': 'host', 'PidsLimit': 0, 'Memory': 0, 'NanoCpus': 0, 'Tmpfs': {},
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                candidate = deepcopy(self.value)
                candidate['HostConfig'][key] = value
                with self.assertRaises(RuntimeError):
                    isolated(candidate, self.root, 'owned')

    def test_rejects_foreign_identity_or_mount(self):
        for key, value in [('Image', 'nginx:latest'), ('User', '0:0'), ('Labels', {LABEL: 'foreign'})]:
            with self.subTest(key=key):
                candidate = deepcopy(self.value)
                candidate['Config'][key] = value
                with self.assertRaises(RuntimeError):
                    isolated(candidate, self.root, 'owned')
        for key, value in [('Source', '/mnt/production'), ('RW', True), ('Mode', 'ro,z')]:
            with self.subTest(key=key):
                candidate = deepcopy(self.value)
                candidate['Mounts'][0][key] = value
                with self.assertRaises(RuntimeError):
                    isolated(candidate, self.root, 'owned')


if __name__ == '__main__':
    unittest.main()
