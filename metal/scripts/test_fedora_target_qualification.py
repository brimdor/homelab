#!/usr/bin/env python3
"""Guard fixture storage/media identity and the only allowed QEMU network path."""

import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest

import fedora_target_qualification as subject


class GuardTests(unittest.TestCase):
    def test_private_root_and_exact_owned_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            subject.require_root(root)
            media = root / 'media'
            media.write_bytes(b'synthetic signed-input stand-in')
            sha = hashlib.sha256(media.read_bytes()).hexdigest()
            subject.require_media(root, media, sha)
            for path, digest in ((media, '0' * 64), (Path('/etc/hosts'), sha)):
                with self.assertRaises(RuntimeError):
                    subject.require_media(root, path, digest)
            linked = root / 'link'
            linked.symlink_to(media)
            with self.assertRaises(RuntimeError):
                subject.require_media(root, linked, sha)
            root.chmod(0o755)
            with self.assertRaises(RuntimeError):
                subject.require_root(root)
            with self.assertRaises(RuntimeError):
                subject.require_root(Path.cwd())

    def test_disconnected_emulation_and_no_host_data_share(self):
        args = argparse.Namespace(qemu='qemu-system-x86_64', server_image=Path('/owned/server.iso'))
        argv = subject.qemu_arguments(args, Path('/owned/disk.qcow2'), Path('/owned/seed.iso'),
                                      12345, Path('/owned/serial.log'))
        self.assertIn('tcg,thread=multi', argv)
        self.assertEqual(argv[argv.index('-netdev') + 1],
                         'user,id=fixture,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:12345-:22')
        self.assertNotIn('-virtfs', argv)
        self.assertNotIn('-fsdev', argv)
        self.assertNotIn('-device vfio-pci', ' '.join(argv))
        self.assertIn('if=none,id=repo,format=raw,readonly=on,file=/owned/server.iso', argv)
        self.assertIn('if=none,id=seed,format=raw,readonly=on,file=/owned/seed.iso', argv)


if __name__ == '__main__':
    unittest.main()
