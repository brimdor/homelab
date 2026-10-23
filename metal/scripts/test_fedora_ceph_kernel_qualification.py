"""Test verified-package and block-identity refusals without devices or network."""

from pathlib import Path
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
                return b'{"urls":[]}'
            fixture.command = command
            with patch.object(driver.repository, 'mirror', return_value={'files': {}, 'base': 'unused'}), \
                    patch.object(driver.Kernel, 'run', return_value={}):
                fixture.run()
            self.assertGreaterEqual(len(programs), 5)
            for program in programs:
                compile(program, '<actual-complete-Ceph-guest-program>', 'exec')
            self.assertEqual((fixture.root / 'kernel-result.json').read_text(), '{}')
            self.assertEqual((fixture.root / 'ceph-package-selection.json').read_text(), '{\n  "urls": []\n}')


if __name__ == '__main__':
    unittest.main()
