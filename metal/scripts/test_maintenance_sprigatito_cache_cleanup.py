"""Owned vendor cache deletion refuses foreign or changed filesystem objects."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import maintenance_nvidia as gpu
import maintenance_sprigatito_cache_cleanup as cleanup


class CacheCleanupTests(unittest.TestCase):
    def test_only_exact_private_manifest_can_be_removed(self):
        for fault in (None, 'content', 'extra', 'symlink', 'hardlink', 'mode', 'name'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                cache = parent / cleanup.CACHE
                cache.mkdir(mode=0o700)
                (cache / 'repodata').mkdir()
                metadata = cache / 'repodata' / 'repomd.xml'
                metadata.write_bytes(b'synthetic metadata')
                (cache / 'verified.json').write_bytes(b'synthetic receipt')
                expected = {'repodata/repomd.xml': hashlib.sha256(metadata.read_bytes()).hexdigest()}
                original = parent / 'protected-original'
                original.write_bytes(b'recovery material')
                if fault == 'content':
                    metadata.write_bytes(b'changed')
                if fault == 'extra':
                    (cache / 'unknown').write_bytes(b'foreign')
                if fault == 'symlink':
                    metadata.unlink()
                    metadata.symlink_to(original)
                if fault == 'hardlink':
                    import os
                    os.link(metadata, parent / 'other-consumer')
                if fault == 'mode':
                    cache.chmod(0o755)
                if fault == 'name':
                    renamed = parent / 'unrelated-cache'
                    cache.rename(renamed)
                    cache = renamed
                if fault:
                    with self.assertRaises(RuntimeError):
                        cleanup.remove_verified_cache(cache, expected, gpu.local_files)
                    self.assertTrue(cache.exists())
                    self.assertTrue(metadata.exists() if fault != 'name' else (cache / 'repodata/repomd.xml').exists())
                else:
                    self.assertGreater(cleanup.remove_verified_cache(cache, expected, gpu.local_files), 0)
                    self.assertFalse(cache.exists())
                self.assertEqual(original.read_bytes(), b'recovery material')


if __name__ == '__main__':
    unittest.main()
