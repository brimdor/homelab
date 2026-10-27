"""Verify the original architecture and receiver guard before image recovery."""

import unittest
from unittest import mock

import maintenance_growlithe_images as images


class GrowlitheImageTests(unittest.TestCase):
    def test_existing_handler_requires_enabled_exact_interpreter_and_fixed_flag(self):
        good = 'enabled\ninterpreter /usr/bin/qemu-aarch64-static\nflags: F\n'
        self.assertTrue(images.handler_ready(good))
        for bad in (good.replace('enabled', 'disabled'), good.replace('flags: F', 'flags: '),
                    good.replace('/usr/bin/qemu-aarch64-static', '/tmp/foreign')):
            self.assertFalse(images.handler_ready(bad))

    def test_stream_uses_original_arm64_graph_and_exact_native_receivers(self):
        with mock.patch.object(images, 'stream', return_value={'verified': True}) as transfer:
            self.assertEqual(images.preserve(None), {'verified': True})
        _, source_host, source, receiver, target_host = transfer.call_args.args
        self.assertEqual((source_host, target_host), ('10.0.20.18', '10.0.20.16'))
        self.assertIn("'linux/arm64'", source)
        self.assertNotIn("'linux/amd64'", source)
        self.assertIn(images.VALUES['CONFIG'], source)
        self.assertIn('handler_ready(', receiver)
        self.assertIn('len(blobs)==BLOB_COUNT', receiver)
        self.assertIn("assert not root.exists()", receiver)
        compile(source, '<source>', 'exec')
        compile(receiver, '<receiver>', 'exec')

    def test_registration_retains_declared_registry_alias_and_nonreplay_guard(self):
        with mock.patch.object(images, 'remote') as native:
            images.register(None)
        _, program, address = native.call_args.args
        self.assertEqual(address, '10.0.20.16')
        self.assertIn(images.VALUES['ALIAS'], program)
        self.assertIn("elif intent.exists():", program)
        self.assertIn("assert not rows(alias)", program)
        self.assertIn("io.cri-containerd.pinned=pinned", program)
        compile(program, '<register>', 'exec')

    def test_nibble_keeps_its_amd64_graph_and_charmander_receiver(self):
        with mock.patch.object(images, 'stream') as transfer:
            images.preserve_nibble(None)
        _, address, source, receiver, target = transfer.call_args.args
        self.assertEqual((address, target), ('10.0.20.17', '10.0.20.11'))
        self.assertIn(images.NIBBLE['SOURCE_ARCHIVE_SHA256'], source)
        self.assertIn("hashlib.file_digest(source,'sha256')", source)
        self.assertIn("'st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'", source)
        self.assertNotIn("'linux/arm64'", source)
        self.assertIn(images.NIBBLE['CONFIG'], source)
        self.assertNotIn('handler_ready(', receiver)
        self.assertIn(images.NIBBLE['TARGET_ROOT'], receiver)
        self.assertIn('BLOB_COUNT=14', receiver)
        compile(source, '<nibble-source>', 'exec')
        compile(receiver, '<nibble-receiver>', 'exec')
        with mock.patch.object(images, 'remote') as native:
            images.register_nibble(None)
        self.assertIn(images.NIBBLE['ALIAS'], native.call_args.args[1])
        self.assertEqual(native.call_args.args[2], target)


if __name__ == '__main__':
    unittest.main()
