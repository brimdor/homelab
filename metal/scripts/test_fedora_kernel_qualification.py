"""Exercise signed-input refusals and compile the actual offline guest programs."""

import argparse
import ast
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_kernel_qualification as subject


class KernelQualificationTests(unittest.TestCase):
    def test_input_guard_rejects_changed_or_external_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / 'kernel.rpm'
            path.write_bytes(b'synthetic package')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            args = argparse.Namespace(work_dir=root, kernel_dir=root)
            with patch.object(subject, 'PACKAGES', {'kernel.rpm': digest}), patch.object(
                    subject.fedora.Qualification, '__init__', return_value=None):
                subject.Qualification(args)
                path.write_bytes(b'changed package')
                with self.assertRaisesRegex(RuntimeError, 'hash differs'):
                    subject.Qualification(args)
                path.unlink()
                path.symlink_to('/etc/hosts')
                with self.assertRaisesRegex(RuntimeError, 'regular files'):
                    subject.Qualification(args)

    def test_actual_guest_programs_compile(self):
        tree = ast.parse(Path(subject.__file__).read_text())
        bodies = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and '\n' in node.value and
                  ('native(' in node.value or 'def native(' in node.value)]
        self.assertGreaterEqual(len(bodies), 6)
        for body in bodies:
            compile(body, '<actual-kernel-guest-fragment>', 'exec')
        fixture = object.__new__(subject.Qualification)
        fixture.ssh = []
        captured = []
        fixture.command = lambda _args, **kwargs: captured.append(kwargs['data']) or b'{}'
        fixture.guest('print(json.dumps({}))')
        compile(captured[0], '<actual-kernel-complete-guest>', 'exec')

    def test_boot_identity_gate_accepts_only_expected_changed_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(subject.Qualification)
            fixture.root = Path(directory)
            fixture.args = SimpleNamespace(collection_dir=Path(directory), ansible_playbook=Path('/never-executed'))
            fixture.command = lambda *args, **kwargs: b''
            fixture.guest = lambda *args: {}
            before = {'machine': 'machine', 'root_uuid': 'root', 'architecture': 'x86_64',
                      'boot': 'old', 'kernel': 'old-kernel'}
            good = dict(before, boot='new', kernel=subject.VERSION)
            for current in (good, dict(good, boot='old'), dict(good, root_uuid='foreign'),
                            dict(good, kernel='wrong-kernel')):
                fixture.identity = lambda: current
                with self.subTest(current=current):
                    if current == good:
                        self.assertEqual(fixture.reboot(subject.VERSION, before), current)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'boot or preserved identity'):
                            fixture.reboot(subject.VERSION, before)


if __name__ == '__main__':
    unittest.main()
