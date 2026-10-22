"""Exercise actual child framing and preserve fixed SSH trust boundaries."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import gitea_recovery_transport as transport


class TransportTests(unittest.TestCase):
    def test_successful_binary_sender_exit_is_not_caught_as_failure(self):
        sources = {'etcd_recovery': '', 'gitea_postgres_cold_point': '',
                   'gitea_postgres_guarded_source': 'def send(point,checksum,expected,output):\n output.write(b"synthetic-frame");output.flush()\n',
                   'gitea_postgres_fresh_restore': ''}
        request = {'sources': sources, 'profiles': {}, 'task': 'send',
                   'args': {'point': '/synthetic', 'checksum': 'a' * 64, 'expected': {}}}
        child = subprocess.run([sys.executable, '-B', '-c', transport.BOOT],
                               input=json.dumps(request).encode() + b'\n', capture_output=True)
        self.assertEqual((child.returncode, child.stdout, child.stderr), (0, b'synthetic-frame', b''))

    def test_ssh_preserves_existing_key_and_strict_trust_without_secret_arguments(self):
        bundle = object.__new__(transport.Bundle)
        bundle.nodes = {'pikachu': '10.0.20.14'}
        command = bundle.command('pikachu')
        self.assertIn('IdentitiesOnly=yes', command)
        self.assertIn('StrictHostKeyChecking=yes', command)
        self.assertIn('UpdateHostKeys=no', command)
        self.assertIn('root@10.0.20.14', command)
        with self.assertRaises(RuntimeError):
            bundle.command('foreign')

    def test_exact_prefetch_refuses_a_different_candidate(self):
        with patch.object(Path, 'read_bytes', return_value=b'current'), \
                patch.object(transport.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'other', b'')):
            with self.assertRaises(RuntimeError):
                transport.Bundle.exact(Path('/source'), 'a' * 40, 'metal/scripts/fixture.py')

    def test_transport_error_never_exports_unstructured_native_output(self):
        with self.assertRaises(RuntimeError) as error:
            transport.Bundle.response(subprocess.CompletedProcess([], 1, b'private-data', b'private-secret'))
        self.assertNotIn('private', str(error.exception))


if __name__ == '__main__':
    unittest.main()
