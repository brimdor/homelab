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


if __name__ == '__main__':
    unittest.main()
