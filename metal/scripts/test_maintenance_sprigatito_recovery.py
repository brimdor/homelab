import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

import maintenance_sprigatito_recovery as recovery


class ConfigurationRestoreTests(unittest.TestCase):
    def archive(self, root, entries):
        path = root / 'configuration.tar'
        with tarfile.open(path, 'w') as target:
            for name, kind, value in entries:
                member = tarfile.TarInfo(name)
                member.uid, member.gid, member.mode = os.getuid(), os.getgid(), 0o600
                member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(value)
                    target.addfile(member, io.BytesIO(value))
                else:
                    member.linkname = value
                    target.addfile(member)
        return path

    def test_restores_payload_without_following_absolute_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root, [('etc/identity', tarfile.REGTYPE, b'original'),
                                         ('osd/block', tarfile.SYMTYPE, '/dev/sda3'),
                                         ('etc/copy', tarfile.LNKTYPE, 'etc/identity')])
            result = recovery.reconstruct(archive, root)
            self.assertEqual(result['regular_files'], 1)
            self.assertEqual(result['links'], 2)
            self.assertEqual(result['payload_bytes'], 8)
            self.assertEqual(list(root.iterdir()), [archive])

    def test_refuses_traversal_and_link_descendants_and_cleans_up(self):
        cases = [[('../escape', tarfile.REGTYPE, b'unsafe')],
                 [('/absolute', tarfile.REGTYPE, b'unsafe')],
                 [('etc', tarfile.SYMTYPE, '/tmp'), ('etc/escape', tarfile.REGTYPE, b'unsafe')],
                 [('etc/identity', tarfile.REGTYPE, b'safe'), ('copy', tarfile.LNKTYPE, '../outside')]]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = self.archive(root, entries)
                with self.assertRaises(RuntimeError):
                    recovery.reconstruct(archive, root)
                self.assertEqual(list(root.iterdir()), [archive])


if __name__ == '__main__':
    unittest.main()
