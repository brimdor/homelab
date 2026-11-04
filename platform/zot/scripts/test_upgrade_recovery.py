from pathlib import Path
import tempfile
import unittest
from unittest import mock

import upgrade_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # Native Linux qualification checks real xattrs; local fixtures contain none.
        patch = mock.patch.object(recovery.os, 'listxattr', return_value=[], create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_full_clone_matches_and_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            source.mkdir(mode=0o700)
            (source / 'nested').mkdir()
            (source / 'nested/blob').write_bytes(b'original registry bytes')
            expected = recovery.tree(source)
            destination = Path(temporary) / 'restored'
            # Local account owns the fixture; Linux capture uses root for real ownership.
            original = recovery.os.chown
            recovery.os.chown = lambda path, uid, gid: None
            try:
                recovery.clone(source, destination)
            finally:
                recovery.os.chown = original
            self.assertEqual(recovery.tree(destination), expected)
            (destination / 'nested/blob').write_bytes(b'corrupt registry bytes')
            self.assertNotEqual(recovery.tree(destination), expected)
            with self.assertRaisesRegex(RuntimeError, 'preserve existing'):
                recovery.clone(source, destination)

    def test_links_never_enter_the_recovery_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'unsafe').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(RuntimeError, 'symlinks'):
                recovery.tree(root)


if __name__ == '__main__':
    unittest.main()
