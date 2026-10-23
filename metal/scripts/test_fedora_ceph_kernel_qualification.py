"""Test verified-package and block-identity refusals without devices or network."""

from pathlib import Path
import ast
import contextlib
import hashlib
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ceph_kernel_runtime as runtime
import fedora_ceph_kernel_qualification as driver
import fedora_ceph_repository as repository


class CephKernelTests(unittest.TestCase):
    def test_foreign_paths_and_native_solver_urls_are_refused(self):
        for value in ('../Packages/a.rpm', '/Packages/a.rpm', 'Packages/../a.rpm',
                      'Packages//a.rpm', 'Packages/a;true.rpm', 'Packages/a%2fb.rpm',
                      'Packages/a?foreign.rpm', 'Packages/a#foreign.rpm', None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                repository.safe_path(value, 'Packages')
        for value in ('Packages/s/SDL3_sound-3.0.0~20260117gitb00e4a3-1.fc44.x86_64.rpm',
                      'Packages/d/DNS-Compliance-Testing-0^20230708git4aea40b-10.fc44.x86_64.rpm'):
            self.assertEqual(repository.safe_path(value, 'Packages'), value)
        relative = 'Packages/c/ceph-common-20.2.4-1.fc44.x86_64.rpm'
        values = {'ceph-updates': {'packages': {relative: 'verified-hash'}}}
        good = 'file://' + driver.GUEST_ROOT + '/ceph-updates/' + relative
        self.assertEqual(repository.selection(good, values, driver.GUEST_ROOT),
                         ('ceph-updates', relative, 'verified-hash'))
        for url in (good.replace('file://', 'https://'), good + '.foreign',
                    good.replace('ceph-updates/', 'ceph-base/'), good.replace('/run/', '/tmp/')):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, 'unverified package URL'):
                repository.selection(url, values, driver.GUEST_ROOT)

    def test_owned_block_mapping_refuses_foreign_or_ambiguous_identity(self):
        good = {'pool': 'qualification', 'name': 'kernel', 'device': '/dev/rbd0'}
        self.assertEqual(runtime.owned_mapping('/dev/rbd0', [good]), '/dev/rbd0')
        for device, rows in (('/dev/sda', [good]), ('/dev/rbd0', []), ('/dev/rbd0', [good, good]),
                             ('/dev/rbd0', [dict(good, pool='production')]),
                             ('/dev/rbd0', [dict(good, name='foreign')]),
                             ('/dev/rbd0', [dict(good, device='/dev/rbd1')])):
            with self.subTest(device=device, rows=rows), self.assertRaisesRegex(RuntimeError, 'owned synthetic'):
                runtime.owned_mapping(device, rows)

    def test_actual_complete_guest_programs_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(driver.Qualification)
            fixture.args = SimpleNamespace(work_dir=Path(directory))
            fixture.root = Path(directory)
            fixture.ssh = []
            fixture.upload = lambda *args: None
            fixture.identity = lambda: {}
            programs = []
            def command(_args, **kwargs):
                if 'data' not in kwargs:
                    return b'{}'
                programs.append(kwargs['data'])
                return b'{"urls":[],"native_signed_install":true}'
            fixture.command = command
            with patch.object(driver.repository, 'mirror', return_value={'files': {}, 'base': 'unused'}), \
                    patch.object(driver.Kernel, 'run', return_value={}):
                fixture.run()
            self.assertGreaterEqual(len(programs), 5)
            for program in programs:
                compile(program, '<actual-complete-Ceph-guest-program>', 'exec')
            self.assertEqual((fixture.root / 'kernel-result.json').read_text(), '{}')
            self.assertEqual(json.loads((fixture.root / 'ceph-package-selection.json').read_text())['urls'], [])
            self.assertTrue(json.loads((fixture.root / 'ceph-install-result.json').read_text())['native_signed_install'])
            install = next(program for program in programs if b'installation=subprocess.run(' in program)
            tree = ast.parse(install)
            start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign) and
                         any(isinstance(target, ast.Name) and target.id == 'installation' for target in node.targets))
            native_program = compile(ast.Module(body=tree.body[start:], type_ignores=[]), '<actual-install-body>', 'exec')
            for code in (0, 1):
                with self.subTest(native_exit=code):
                    calls = []
                    raw = b'original-first-error\n' + b'x' * 70000 + b'\noriginal-final-error'
                    def run(arguments, **kwargs):
                        calls.append(arguments)
                        self.assertEqual(kwargs, {'capture_output': True})
                        return SimpleNamespace(returncode=code, stdout=b'package transaction', stderr=raw)
                    def native(*arguments):
                        return 'ceph version 20.2.4 native' if arguments[0] == 'ceph' else '20.2.4-1.fc44.x86_64'
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        exec(native_program, {'subprocess': SimpleNamespace(run=run), 'targets': driver.TARGETS,
                                              'packages': [], 'hashlib': hashlib, 'json': json, 'native': native})
                    result = json.loads(output.getvalue())
                    self.assertEqual([arg for arg in calls[0] if arg.startswith('--enable-repo=')],
                                     ['--enable-repo=ceph-base', '--enable-repo=ceph-updates'])
                    self.assertEqual(result['native_signed_install'], code == 0)
                    if code:
                        self.assertEqual(result['exit'], code)
                        self.assertEqual(result['diagnostics']['stderr'], {'bytes': len(raw),
                                         'sha256': hashlib.sha256(raw).hexdigest(),
                                         'head': raw[:16384].decode(), 'tail': raw[-16384:].decode()})


    def test_solver_cannot_silently_skip_dvd_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(driver.Qualification)
            fixture.args = SimpleNamespace(work_dir=Path(directory))
            fixture.root = Path(directory)
            fixture.ssh = []
            fixture.upload = lambda *args: None
            fixture.command = lambda *args, **kwargs: json.dumps({'urls': [
                'file:///mnt/qualification-repo/Packages/p/python3-dateutil.rpm']}).encode()
            with patch.object(driver.repository, 'mirror', return_value={'files': {}, 'packages': {}}), \
                    patch.object(driver.Kernel, 'run', return_value={'accepted': True}), \
                    self.assertRaisesRegex(RuntimeError, 'unverified package URL'):
                fixture.run()
            self.assertTrue(json.loads((fixture.root / 'kernel-result.json').read_text())['accepted'])
            self.assertTrue((fixture.root / 'ceph-package-selection.json').is_file())
            self.assertFalse((fixture.root / 'ceph-install-result.json').exists())


if __name__ == '__main__':
    unittest.main()
