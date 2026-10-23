"""Exercise signed-input refusals and compile the actual offline guest programs."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
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

    def test_actual_default_helper_checks_bls_files_layout_vendor_and_saved_entry(self):
        fixture = object.__new__(subject.Qualification)
        fixture.ssh = []
        captured = []
        fixture.command = lambda _args, **kwargs: captured.append(kwargs['data']) or b'{}'
        fixture.guest('print(json.dumps({}))')
        function = next(node for node in ast.parse(captured[0]).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'default_kernel')
        program = compile(ast.Module(body=[function], type_ignores=[]), '<actual-default-helper>', 'exec')
        cases = ('normal', 'btrfs-prefix', 'foreign-display', 'wrong-layout', 'changed-vendor',
                 'modified-rpm', 'duplicate-id', 'unsafe-id', 'wrong-version', 'duplicate-version',
                 'wrong-linux', 'wrong-initrd', 'missing-initrd', 'symlink-kernel', 'wrong-saved')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                kernel = '/boot/vmlinuz-' + subject.VERSION
                initrd = '/boot/initramfs-' + subject.VERSION + '.img'
                entry_id = 'a' * 32 + '-' + subject.VERSION
                entry = root / 'boot/loader/entries' / (entry_id + '.conf')
                entry.parent.mkdir(parents=True)
                text = 'version ' + subject.VERSION + '\nlinux ' + kernel + '\ninitrd ' + initrd + '\n'
                if case == 'duplicate-version':
                    text += 'version ' + subject.VERSION + '\n'
                elif case == 'wrong-linux':
                    text = text.replace('linux ' + kernel, 'linux /boot/foreign')
                elif case == 'wrong-initrd':
                    text = text.replace('initrd ' + initrd, 'initrd /boot/foreign.img')
                elif case == 'wrong-version':
                    text = text.replace('version ' + subject.VERSION, 'version foreign')
                entry.write_text(text)
                for name in (kernel, initrd, '/usr/bin/grubby'):
                    path = root / name.lstrip('/')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'synthetic signed fixture file')
                if case == 'missing-initrd':
                    (root / initrd.lstrip('/')).unlink()
                if case == 'symlink-kernel':
                    path = root / kernel.lstrip('/')
                    path.unlink()
                    path.symlink_to(root / initrd.lstrip('/'))
                prefix = '' if case == 'normal' else '/boot'
                reported = '/boot/foreign' if case == 'foreign-display' else prefix + kernel
                info = ('index=0\nkernel=' + json.dumps(reported) + '\ninitrd=' +
                        json.dumps(prefix + initrd) + '\nid=' + json.dumps(
                            '../foreign' if case == 'unsafe-id' else entry_id) + '\n')
                if case == 'duplicate-id':
                    info += 'id=' + json.dumps(entry_id) + '\n'
                def native(*args):
                    if args == ('grubby', '--info=DEFAULT'):
                        return info
                    if args == ('grubby', '--default-kernel'):
                        return reported
                    if args == ('findmnt', '-n', '-o', 'TARGET,FSTYPE,FSROOT', '-T', '/boot'):
                        return '/boot ext4 /' if case == 'wrong-layout' else '/boot btrfs /boot'
                    if args == ('rpm', '-V', 'grubby'):
                        if case == 'modified-rpm':
                            raise RuntimeError('native vendor verification refused')
                        return ''
                    if args == ('grub2-editenv', '/boot/grub2/grubenv', 'list'):
                        return 'saved_entry=' + ('foreign' if case == 'wrong-saved' else entry_id)
                    raise AssertionError('unexpected native command')
                digest = ('0' * 64 if case == 'changed-vendor' else
                          '8090dcec49248f2cc92d72581d093171f1dbab3b3d0c8d9467364f92a6ac2855')
                namespace = {'pathlib': SimpleNamespace(Path=lambda value: root / value.lstrip('/')),
                             'json': json, 're': re, 'native': native,
                             'hashlib': SimpleNamespace(sha256=lambda _: SimpleNamespace(hexdigest=lambda: digest))}
                exec(program, namespace)
                if case in ('normal', 'btrfs-prefix'):
                    self.assertEqual(namespace['default_kernel']((subject.VERSION,), True), {
                        'version': subject.VERSION, 'reported_kernel': reported, 'entry_id': entry_id})
                else:
                    with self.assertRaises((AssertionError, RuntimeError)):
                        namespace['default_kernel']((subject.VERSION,), True)


if __name__ == '__main__':
    unittest.main()
