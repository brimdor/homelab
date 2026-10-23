"""Guard public vendor paths and exercise the actual package guest programs."""

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_nvidia_package_qualification as driver
import nvidia_package_repository as vendor


class NvidiaPackageTests(unittest.TestCase):
    def test_only_exact_repository_paths_and_metadata_bound_solver_urls(self):
        for path in ('nvidia-open-615.71.10-1.fc44.noarch.rpm', vendor.KEY):
            self.assertEqual(vendor.safe_path(path), path)
        self.assertEqual(vendor.safe_path('repodata/hash-primary.xml.gz', True), 'repodata/hash-primary.xml.gz')
        for path in ('../nvidia.rpm', '/nvidia.rpm', 'foreign/nvidia.rpm', 'nvidia.rpm?query',
                     'repodata/../foreign', 'repodata//primary.xml', '73CD9B30.pub/foreign'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                vendor.safe_path(path, path.startswith('repodata/'))
        value = {'packages': {'nvidia.rpm': 'a' * 64}}
        prefix = 'file:///run/fixture/nvidia-vendor/'
        self.assertEqual(vendor.selection(prefix + 'nvidia.rpm', value, '/run/fixture'), ('nvidia.rpm', 'a' * 64))
        for url in ('https://foreign/nvidia.rpm', prefix + 'unknown.rpm', prefix + '../nvidia.rpm'):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                vendor.selection(url, value, '/run/fixture')

    def test_metadata_rejects_duplicate_and_unsupported_package_checksums(self):
        def package(checksum='sha256', arch='x86_64'):
            return ('<package><arch>' + arch + '</arch><location href="nvidia.rpm"/>'
                    '<checksum type="' + checksum + '">' + 'a' * 64 + '</checksum></package>')

        members = package()
        checksum_type = 'sha256'

        def fetch(relative, destination, expected=None):
            if relative == vendor.KEY:
                raw = b'public-test-key'
            elif relative.endswith('repomd.xml'):
                raw = ('<repomd xmlns="http://linux.duke.edu/metadata/repo"><data type="primary">'
                       '<location href="repodata/hash-primary.xml.gz"/><checksum type="' + checksum_type + '">' +
                       'b' * 64 + '</checksum></data></repomd>').encode()
            else:
                raw = gzip.compress(('<metadata xmlns="http://linux.duke.edu/metadata/common">' +
                                     members + '</metadata>').encode())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()

        for body, kind, refusal in ((package(), 'sha256', False), (package() * 2, 'sha256', True),
                                    (package('sha1'), 'sha256', True), (package(), 'sha1', True),
                                    (package(arch='i686'), 'sha256', False)):
            members, checksum_type = body, kind
            with tempfile.TemporaryDirectory() as directory, patch.object(vendor, 'fetch', side_effect=fetch):
                if refusal:
                    with self.assertRaises(RuntimeError):
                        vendor.mirror(Path(directory))
                else:
                    actual = vendor.mirror(Path(directory))
                    self.assertEqual(bool(actual['packages']), 'i686' not in body)

    def test_complete_guest_programs_compile_and_failed_acceptance_is_retained(self):
        for failure in ('none', 'install', 'before', 'after'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = object.__new__(driver.Qualification)
                fixture.args = SimpleNamespace(work_dir=root)
                fixture.root = root
                fixture.ssh = []
                fixture.upload = lambda *args: None
                fixture.identity = lambda: {'boot': 'before'}
                fixture.reboot = lambda *args: {'boot': 'after'}
                programs = []

                def command(_arguments, **kwargs):
                    programs.append(kwargs['data'])
                    return json.dumps({'urls': [], 'native_signed_install': failure != 'install'}).encode()

                fixture.command = command
                state = {'accepted': failure != 'before', 'packages': {'nvidia-open': '615.71.10'},
                         'modules': {'nvidia': 'expected'}, 'firmware': {'gsp': 'expected'}, 'dkms_status': 'installed'}
                after = {**state, 'modules': {'nvidia': 'changed'}} if failure == 'after' else state
                fixture.inspect_runtime = unittest.mock.Mock(side_effect=[state, after])
                metadata = {'files': {}, 'base': 'unused'}
                with patch.object(driver.Kernel, 'run', return_value={'accepted': True}), \
                        patch.object(driver.fedora_repository, 'mirror', return_value=metadata), \
                        patch.object(driver.vendor, 'mirror', return_value=metadata):
                    if failure == 'none':
                        self.assertTrue(fixture.run()['accepted'])
                    else:
                        with self.assertRaises(RuntimeError):
                            fixture.run()
                        self.assertTrue((root / 'gpu-package-before-reboot.json').is_file())
                        if failure == 'after':
                            self.assertEqual(json.loads((root / 'gpu-package-after-reboot.json').read_text())['modules'],
                                             {'nvidia': 'changed'})
                for program in programs:
                    compile(program, '<actual-package-guest-program>', 'exec')


if __name__ == '__main__':
    unittest.main()
