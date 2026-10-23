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
    def test_imported_key_requires_exact_single_full_native_fingerprint(self):
        fingerprint = vendor.KEY_FINGERPRINT
        for value in (fingerprint + ' NVIDIA public key\n', fingerprint.upper() + ' NVIDIA public key\n'):
            driver.verify_key_listing(value, fingerprint)
        for value in ('', '\n', fingerprint, fingerprint[-8:] + ' NVIDIA public key',
                      '0' * 40 + ' foreign key', 'prefix' + fingerprint + ' NVIDIA public key',
                      (fingerprint + ' NVIDIA public key\n') * 2):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                driver.verify_key_listing(value, fingerprint)
        with self.assertRaises(RuntimeError):
            driver.verify_key_listing(fingerprint + ' NVIDIA public key', fingerprint[-8:])

    def test_native_rpm6_and_legacy_signature_formats_keep_verification_and_signer_guards(self):
        current = 'Header OpenPGP V4 RSA/SHA512 signature, key ID 2b6cf03373cd9b30: OK\nHeader SHA256 digest: OK'
        legacy = 'Header V4 RSA/SHA256 Signature, key ID 73cd9b30: OK'
        for text in (current, legacy, current.replace('key ID 2b6cf033', 'key fingerprint: 991343d72b6cf033')):
            driver.verify_signature_output(text, vendor=True)
        driver.verify_signature_output(current.replace('73cd9b30', '31645531'))
        for text in ('Header SHA256 digest: OK', current.replace(': OK', ': NOKEY'),
                     current.replace(': OK', ': BAD'), current.replace(': OK', ': NOTTRUSTED'),
                     current.replace('73cd9b30', '31645531'), current + '\n' + legacy.replace(': OK', ': BAD')):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                driver.verify_signature_output(text, vendor=True)

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
