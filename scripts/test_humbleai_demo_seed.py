#!/usr/bin/env python3
"""Exercise no-overwrite and corrupt-input refusals with disposable synthetic data."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('demo_seed', Path(__file__).resolve().parents[1] / 'apps/humbleai-demo/scripts/seed-data.py')
SEED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEED)


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='humbleai-seed-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.database = self.root / 'original.sqlite'
        with sqlite3.connect(self.database) as db:
            db.executescript("CREATE TABLE fixture(id INTEGER PRIMARY KEY, value BLOB); INSERT INTO fixture VALUES(1,x'000102');")
        self.manifest = self.root / 'verified.json'
        self.target = self.root / 'target'; self.target.mkdir()
        self.proof = {'format': 1, 'cluster_uid': '7ff226e0-565a-4610-8a3e-97e7e87355a3',
                      'source': {'namespace': 'humbleai-demo', 'container': 'main',
                                 'pod_uid': 'fae3621d-e4da-41a8-8087-e1768c066053', 'node': 'growlithe',
                                 'data_storage': 'container-layer', 'database': '/app/server/data/humbleai.db',
                                 'image': 'registry.eaglepass.io/humbleai@sha256:fcf08c14538753af9539a66d2c3551e07445c664970a392da4928b80cb9fe542'},
                      'encryption_key': {'uid': '8d3d65c0-e6da-4dc8-9ad6-1b0ddc20e595', 'secret': 'secrets',
                                         'field': 'openai-encryption-key', 'environment': 'OPENAI_ENCRYPTION_KEY',
                                         'bytes': 32, 'sha256': 'a' * 64},
                      'capture': {'bytes': self.database.stat().st_size, 'sha256': SEED.digest(self.database),
                                  'snapshot': {'schema_sha256': '34ea8a6d7cbe469a4b5d67dc3bf1a03223e823b64814379950df02b6085c68a2'}}}

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.proof))
        return SEED.digest(self.manifest)

    def run_seed(self):
        return SEED.seed(self.database, self.manifest, self.target, self.write_manifest())

    def test_seed_is_exact_private_and_never_overwrites(self):
        original = self.database.read_bytes()
        self.assertTrue(self.run_seed()['accepted'])
        destination = self.target / 'humbleai.db'
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.database.read_bytes(), original)
        with self.assertRaisesRegex(RuntimeError, 'not empty'):
            self.run_seed()
        self.assertEqual(destination.read_bytes(), original)

    def test_manifest_and_database_hashes_are_mandatory(self):
        expected = self.write_manifest()
        self.manifest.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'manifest hash differs'):
            SEED.seed(self.database, self.manifest, self.target, expected)
        self.database.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'hash or size differs'):
            self.run_seed()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_wrong_source_and_key_never_touch_target(self):
        for group, field in [('source', 'pod_uid'), ('encryption_key', 'uid')]:
            before = self.proof[group][field]; self.proof[group][field] = 'wrong'
            with self.assertRaisesRegex(RuntimeError, 'identity differs'):
                self.run_seed()
            self.proof[group][field] = before
        self.assertEqual(list(self.target.iterdir()), [])

    def test_existing_partial_and_nonempty_lost_found_are_preserved(self):
        partial = self.target / '.humbleai-final-seed.partial'; partial.write_bytes(b'owned-by-someone-else')
        with self.assertRaisesRegex(RuntimeError, 'not empty'):
            self.run_seed()
        self.assertEqual(partial.read_bytes(), b'owned-by-someone-else'); partial.unlink()
        lost = self.target / 'lost+found'; lost.mkdir(); (lost / 'original').write_bytes(b'keep')
        with self.assertRaisesRegex(RuntimeError, 'not empty'):
            self.run_seed()
        self.assertEqual((lost / 'original').read_bytes(), b'keep')

    def test_symlink_input_is_refused(self):
        real = self.root / 'real.sqlite'; self.database.rename(real); self.database.symlink_to(real)
        with self.assertRaisesRegex(RuntimeError, 'regular file'):
            self.run_seed()

    def test_corrupt_sqlite_never_becomes_destination(self):
        self.database.write_bytes(b'not-a-database')
        self.proof['capture'].update(bytes=self.database.stat().st_size, sha256=SEED.digest(self.database))
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_seed()
        self.assertEqual(list(self.target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
