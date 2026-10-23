"""Reject unsafe source and mismatched native compiler inputs without a GPU."""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_nvidia_kernel_qualification as driver
import nvidia_kernel_build as build


class NvidiaBuildTests(unittest.TestCase):
    def test_source_inventory_refuses_links_traversal_duplicates_and_missing_entries(self):
        members = [tarfile.TarInfo(build.SOURCE_ROOT + '/Makefile')]
        members += [tarfile.TarInfo(build.SOURCE_ROOT + '/file' + str(i)) for i in range(4641)]
        self.assertEqual(build.source_members(SimpleNamespace(getmembers=lambda: members)), members)
        for bad in ('../foreign', '/foreign', build.SOURCE_ROOT + '/../foreign',
                    'foreign/file', build.SOURCE_ROOT + '//file'):
            with self.subTest(path=bad), self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: [tarfile.TarInfo(bad)]))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            member = tarfile.TarInfo(build.SOURCE_ROOT + '/special')
            member.type = kind
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: [member]))
        for items in (members[:-1], members + [members[0]]):
            with self.assertRaises(RuntimeError):
                build.source_members(SimpleNamespace(getmembers=lambda: items))

    def test_exact_kernel_compiler_version_is_required(self):
        build.compiler_matches('CONFIG_GCC_VERSION=160201\n', '16.2.1')
        for config, compiler in [('CONFIG_GCC_VERSION=160201\n', '16.2.0'),
                                 ('CONFIG_GCC_VERSION=160201\n', '16.2'),
                                 ('', '16.2.1'), ('CONFIG_GCC_VERSION=160201\n' * 2, '16.2.1')]:
            with self.subTest(config=config, compiler=compiler), self.assertRaises(RuntimeError):
                build.compiler_matches(config, compiler)

    def test_actual_complete_guest_programs_compile_and_refuse_unaccepted_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.tar.gz'
            archive.write_bytes(b'synthetic-public-source')
            fixture = object.__new__(driver.Qualification)
            fixture.args = SimpleNamespace(work_dir=root, source_archive=archive)
            fixture.root = root
            fixture.ssh = []
            fixture.upload = lambda *args: None
            fixture.identity = lambda: {}
            programs = []
            accepted = True

            def command(_arguments, **kwargs):
                if 'data' in kwargs:
                    programs.append(kwargs['data'])
                    return b'{"urls":[],"native_signed_install":true}'
                return json.dumps({'accepted': accepted}).encode()

            fixture.command = command
            with patch.object(driver.repository, 'mirror', return_value={'files': {}, 'base': 'unused'}), \
                    patch.object(driver.Kernel, 'run', return_value={'accepted': True}), \
                    patch.object(driver.tarfile, 'open'), patch.object(build, 'source_members'), \
                    patch.object(build, 'SOURCE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
                self.assertTrue(fixture.run()['accepted'])
                for program in programs:
                    compile(program, '<actual-NVIDIA-guest-program>', 'exec')
                (root / 'nvidia-repositories').rmdir()
                accepted = False
                with self.assertRaisesRegex(RuntimeError, 'module build failed'):
                    fixture.run()
                self.assertFalse(json.loads((root / 'nvidia-build-result.json').read_text())['accepted'])


if __name__ == '__main__':
    unittest.main()
