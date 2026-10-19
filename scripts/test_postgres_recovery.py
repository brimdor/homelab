#!/usr/bin/env python3
"""Exercise recovery input refusal before any database server can start."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'apps/postgres/scripts'
OWNER = 'homelab-postgres-recovery-20261019\n'


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='postgres-recovery-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'source'
        self.target = self.root / 'restore'
        self.bin = self.root / 'bin'
        for path in (self.bundle, self.target, self.bin):
            path.mkdir()
        for path in (self.bundle, self.target):
            (path / '.owner').write_text(OWNER)
        self.keys = [hashlib.sha256(f'db{i}'.encode()).hexdigest() for i in range(6)]
        (self.bundle / 'catalog.tsv').write_text(''.join(
            f'{key}|db{i}\n' for i, key in enumerate(self.keys)))
        (self.bundle / 'cluster.sql').write_text('-- synthetic fixture only\n')
        (self.bundle / 'roles.sha256').write_text('0' * 64 + '\n')
        self.members = ['cluster.sql', 'catalog.tsv', 'roles.sha256']
        for key in self.keys:
            name = f'{key}.schema.sha256'
            (self.bundle / name).write_text('0' * 64 + '\n')
            self.members.append(name)
        stub = self.bin / 'initdb'
        stub.write_text('#!/bin/sh\nprintf reached > "$INIT_MARKER"\nexit 73\n')
        stub.chmod(0o755)
        self.env = dict(os.environ, SOURCE_ROOT=str(self.bundle),
                        RESTORE_ROOT=str(self.target), INIT_MARKER=str(self.root / 'started'),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        EXPECTED_DATABASE_SET_SHA256=hashlib.sha256(
                            ('\n'.join(sorted(self.keys)) + '\n').encode()).hexdigest())
        self.publish()

    def publish(self):
        manifest = ''.join(f'{hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()}  {name}\n'
                           for name in self.members)
        self.set_manifest(manifest)

    def set_manifest(self, manifest):
        (self.bundle / 'manifest.sha256').write_text(manifest)
        digest = hashlib.sha256(manifest.encode()).hexdigest()
        (self.bundle / '.complete').write_text(digest + '\n')
        self.env['EXPECTED_MANIFEST_SHA256'] = digest

    def invoke(self, accepted=False):
        result = subprocess.run(['bash', str(SCRIPTS / 'verify-postgres-recovery.sh')],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'started').exists(), accepted, result.stderr)
        return result

    def test_valid_inputs_reach_initialization(self):
        self.invoke(accepted=True)

    def test_changed_pinned_manifest(self):
        with (self.bundle / 'manifest.sha256').open('a') as stream:
            stream.write('\n')
        self.invoke()

    def test_changed_sql(self):
        (self.bundle / 'cluster.sql').write_text('changed\n')
        self.invoke()

    def test_incomplete_bundle(self):
        (self.bundle / '.complete').unlink()
        self.invoke()

    def test_symlink_input(self):
        original = self.bundle / 'cluster.sql'
        original.rename(self.root / 'original.sql')
        original.symlink_to(self.root / 'original.sql')
        self.invoke()

    def test_existing_data_preserved(self):
        data = self.target / 'data'
        data.mkdir()
        marker = data / 'preserve'
        marker.write_text('original')
        self.invoke()
        self.assertEqual(marker.read_text(), 'original')

    def test_wrong_owner(self):
        (self.target / '.owner').write_text('unknown\n')
        self.invoke()

    def test_path_traversal(self):
        manifest = (self.bundle / 'manifest.sha256').read_text()
        self.set_manifest(manifest.replace('  cluster.sql\n', '  ../cluster.sql\n'))
        self.invoke()

    def test_duplicate_manifest_member(self):
        manifest = (self.bundle / 'manifest.sha256').read_text().splitlines()
        manifest[-1] = manifest[0]
        self.set_manifest('\n'.join(manifest) + '\n')
        self.invoke()

    def test_required_manifest_member_missing(self):
        name = 'a' * 64 + '.schema.sha256'
        (self.bundle / name).write_text('extra')
        self.members[0] = name
        self.publish()
        self.invoke()

    def test_wrong_catalog_identity(self):
        catalog = self.bundle / 'catalog.tsv'
        catalog.write_text(catalog.read_text().replace('|db0\n', '|other\n'))
        self.publish()
        self.invoke()

    def test_source_never_adopts_existing_directory(self):
        env = dict(self.env, RECOVERY_ROOT=str(self.bundle))
        before = {p.name: p.read_bytes() for p in self.bundle.iterdir()}
        result = subprocess.run(['bash', str(SCRIPTS / 'create-postgres-recovery.sh')],
                                env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.bundle.iterdir()})


if __name__ == '__main__':
    unittest.main()
