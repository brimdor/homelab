"""Reject invalid control metadata, unsafe execution and raw failure retention."""

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gitea_postgres_control as control


SYNTHETIC = b'''pg_control version number:            1300
Catalog version number:               202307071
Database system identifier:           123456789
Database cluster state:               in production
Latest checkpoint location:           0/12345678
Latest checkpoint's REDO location:    0/12340000
Latest checkpoint's REDO WAL file:    000000010000000000000012
Database block size:                  8192
WAL block size:                       8192
Bytes per WAL segment:                16777216
Data page checksum version:           0
'''


class ControlContract(unittest.TestCase):
    def test_reviewed_metadata_hashes_identifiers_and_refuses_invalid_fields(self):
        value = control.parse_control(SYNTHETIC)
        self.assertEqual(value['cluster_state'], 'in production')
        self.assertEqual(value['data_page_checksum_version'], 0)
        self.assertNotIn('123456789', str(value))
        for old, new in ((b'1300', b'9999'), (b'202307071', b'202307070'),
                         (b'in production', b'unknown'), (b'8192', b'4096'),
                         (b'16777216', b'1024'), (b'123456789', b'not-numeric'),
                         (b'0/12340000', b'invalid'), (b'000000010000000000000012', b'invalid'),
                         (b'version:           0', b'version:           9')):
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                control.parse_control(SYNTHETIC.replace(old, new))
        for bad in (b'', SYNTHETIC + b'WARNING: Calculated CRC checksum mismatch\n', SYNTHETIC + b'bad line\n', SYNTHETIC + b'Catalog version number: 202307071\n',
                    SYNTHETIC.replace(b'Catalog version number:', b'Unknown version:'), SYNTHETIC + b'\xff'):
            with self.assertRaises(RuntimeError):
                control.parse_control(bad)

    def container(self, scratch):
        return {'Image': 'sha256:owned', 'Config': {
            'Image': control.IMAGE, 'User': '1001:1001', 'Entrypoint': [control.ENTRY],
            'Cmd': ['/recovered/data'], 'WorkingDir': '/tmp', 'Healthcheck': {'Test': ['NONE']},
            'Labels': {control.LABEL: 'synthetic'},
            'Env': [key + '=' + value for key, value in control.ENV.items()]},
            'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                           'PidMode': '', 'IpcMode': 'private', 'UTSMode': '', 'UsernsMode': '',
                           'PidsLimit': 64, 'Memory': 536870912, 'NanoCpus': 1000000000,
                           'Tmpfs': control.TMPFS, 'LogConfig': {'Type': 'none', 'Config': {}},
                           'RestartPolicy': {'Name': 'no'}},
            'Mounts': [{'Type': 'bind', 'RW': False, 'Source': source, 'Destination': target}
                       for target, source in control.mounts(scratch, ['/bitnami/postgresql']).items()],
            'State': {'Running': False, 'ExitCode': 1, 'OOMKilled': False}}

    def test_isolation_refuses_logging_mutable_data_credentials_and_server_entry(self):
        root = Path('/synthetic')
        value = self.container(root)
        control.require_container(value, root, ['/bitnami/postgresql'], 'synthetic', 'sha256:owned')
        for change in (lambda v: v['HostConfig'].update(LogConfig={'Type': 'journald', 'Config': {}}),
                       lambda v: v['HostConfig'].update(NetworkMode='host'),
                       lambda v: v['HostConfig'].update(Privileged=True),
                       lambda v: v['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                       lambda v: v['Config'].update(User='0:0'),
                       lambda v: v['Config'].update(Entrypoint=['/opt/bitnami/postgresql/bin/postgres']),
                       lambda v: v['Config'].update(Healthcheck={'Test': ['CMD', 'server']}),
                       lambda v: v['Mounts'][0].update(RW=True),
                       lambda v: v['Mounts'][0].update(Source='/original'),
                       lambda v: v['Mounts'].append({'Type': 'bind', 'RW': False, 'Source': '/secrets'})):
            changed = copy.deepcopy(value)
            change(changed)
            with self.assertRaises(RuntimeError):
                control.require_container(changed, root, ['/bitnami/postgresql'], 'synthetic', 'sha256:owned')

    def test_failed_native_output_is_discarded_and_exact_container_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.container(root)
            calls = []
            def docker(*args, **_kwargs):
                calls.append(args)
                if args[0] == 'create':
                    return SimpleNamespace(stdout=('a' * 64).encode())
                if args[0] == 'start':
                    return SimpleNamespace(returncode=1, stdout=b'synthetic-private-output', stderr=b'CRC warning')
                return SimpleNamespace(returncode=1 if args[0] == 'inspect' else 0)
            with patch.object(control.common, 'docker', side_effect=docker), \
                    patch.object(control.common, 'inspect', return_value=value):
                with self.assertRaises(RuntimeError) as caught:
                    control.operation(root, ['/bitnami/postgresql'], 'synthetic', 'sha256:owned')
            self.assertNotIn('synthetic-private-output', str(caught.exception))
            self.assertNotIn('CRC warning', str(caught.exception))
            self.assertEqual(list(root.iterdir()), [])
            self.assertIn(('rm', '-f', 'a' * 64), calls)


if __name__ == '__main__':
    unittest.main()
