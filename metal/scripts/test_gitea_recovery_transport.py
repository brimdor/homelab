"""Exercise actual child framing and preserve fixed SSH trust boundaries."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import gitea_recovery_transport as transport


class TransportTests(unittest.TestCase):
    def test_complete_prefetched_bundle_loads_before_runtime_refusal(self):
        root = Path(__file__).resolve().parents[2]
        bundle = object.__new__(transport.Bundle)
        bundle.sources = {name: (root / 'metal/scripts' / (name + '.py')).read_text()
                          for name in transport.MODULES}
        bundle.profiles = json.loads((root / 'metal/maintenance/gitea-postgres-files-103.json').read_text())
        child = subprocess.run([sys.executable, '-I', '-B', '-c', transport.BOOT],
                               input=bundle.request('observe', {'core': {}, 'namespace_pid': 2}),
                               capture_output=True)
        self.assertEqual(child.returncode, 70)
        self.assertEqual(json.loads(child.stderr), {
            'accepted': False, 'error_type': 'RuntimeError',
            'error': 'unreviewed held PostgreSQL runtime request'})
        self.assertEqual(child.stdout, b'')

    def test_long_lease_task_crosses_actual_native_frame_before_any_host_contact(self):
        root = Path(__file__).resolve().parents[2]
        bundle = object.__new__(transport.Bundle)
        bundle.sources = {name: (root / 'metal/scripts' / (name + '.py')).read_text()
                          for name in transport.MODULES}
        bundle.profiles = json.loads((root / 'metal/maintenance/gitea-postgres-files-103.json').read_text())
        bundle.sources['valkey_long_lease_qualification'] = (
            "def run(run_id,observer):\n assert run_id=='synthetic-lease'\n"
            " assert observer.startswith(b'\"\"\"')\n return {'synthetic_dispatch':True}\n")
        child = subprocess.run([sys.executable, '-I', '-B', '-c', transport.BOOT],
            input=bundle.request('valkey_lease_qualify', {'run_id': 'synthetic-lease'}), capture_output=True)
        self.assertEqual((child.returncode, child.stderr), (0, b''))
        self.assertEqual(json.loads(child.stdout), {'synthetic_dispatch': True})

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
