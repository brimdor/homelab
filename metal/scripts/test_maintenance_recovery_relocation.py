"""Synthetic regressions for protected historical recovery relocation."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_recovery_relocation as relocation


class RecoveryRelocationTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(os, 'listxattr'):
            # macOS Python lacks this Linux API; native transfer verifies real xattrs.
            missing = patch.object(relocation.os, 'listxattr', return_value=[], create=True)
            missing.start(); self.addCleanup(missing.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.payload = self.root / 'payload'
        self.payload.write_bytes(b'synthetic recovery only')
        self.payload.chmod(0o600)

    def test_inventory_detects_changed_bytes(self):
        original = relocation.inventory(self.root)
        self.assertEqual(original['payload']['bytes'], 23)
        self.payload.write_bytes(b'changed synthetic data')
        self.assertNotEqual(relocation.inventory(self.root), original)

    def test_links_and_public_permissions_refused(self):
        os.link(self.payload, self.root / 'hardlink')
        with self.assertRaisesRegex(RuntimeError, 'link or special'):
            relocation.inventory(self.root)
        (self.root / 'hardlink').unlink()
        os.symlink(self.payload, self.root / 'symlink')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            relocation.inventory(self.root)
        (self.root / 'symlink').unlink()
        self.payload.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'root-private'):
            relocation.inventory(self.root)

    def test_invalid_receiver_receipt_cannot_remove_source(self):
        with patch.object(relocation, 'native'), patch.object(relocation, 'ROOT', self.root):
            with self.assertRaisesRegex(RuntimeError, 'independent complete receiver'):
                relocation.retire_source({'name': next(iter(relocation.POINTS))}, {'accepted': False})
        self.assertTrue(self.payload.exists())


if __name__ == '__main__':
    unittest.main()
