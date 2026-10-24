"""Guard public vendor paths and exercise the actual package guest programs."""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import fedora_nvidia_package_qualification as driver
import nvidia_package_repository as vendor


class NvidiaPackageTests(unittest.TestCase):
    def test_actual_storage_and_upload_diagnostic_programs_execute_with_shared_header(self):
        mount = {'source': '/dev/vda3[/var]', 'fstype': 'btrfs', 'maj:min': '0:34'}
        root_mount = {**mount, 'source': '/dev/vda3[/root]'}
        repository = unittest.mock.MagicMock()
        repository.__str__.return_value = driver.GUEST_ROOT
        repository.parents = ()
        repository.is_symlink.return_value = False
        repository.stat.return_value = SimpleNamespace(st_uid=0, st_mode=0o40700)
        programs = []

        def path(value):
            if value == '/etc/os-release':
                return SimpleNamespace(read_text=lambda: 'VERSION_ID=44')
            if value == '/sys/fs/selinux/enforce':
                return SimpleNamespace(read_text=lambda: '1')
            return repository

        def native(arguments, **kwargs):
            value = ''
            if arguments[0] == 'findmnt':
                value = json.dumps({'filesystems': [root_mount if arguments[3] == '/' else mount]})
            if arguments[0] == 'rpm':
                value = 'python3-libdnf5 synthetic signed identity'
            return SimpleNamespace(returncode=0, stdout=value.encode())

        def command(arguments, data):
            programs.append(data)
            output = io.StringIO()
            with patch('pathlib.Path', side_effect=path), \
                    patch.object(os, 'statvfs', return_value=SimpleNamespace(f_bavail=1024, f_blocks=2048, f_frsize=4096)), \
                    patch.object(subprocess, 'check_output', return_value=b'qualification-fedora44'), \
                    patch.object(subprocess, 'run', side_effect=native), redirect_stdout(output):
                exec(compile(data, '<actual-storage-guest-program>', 'exec'), {})
            return output.getvalue().encode()

        class StorageAccepted(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            fixture = object.__new__(driver.Qualification)
            fixture.args = SimpleNamespace(work_dir=Path(directory))
            fixture.root = Path(directory)
            fixture.ssh = []
            def first(arguments, data):
                value = json.loads(command(arguments, data))
                self.assertEqual(value['mount'], [mount])
                self.assertEqual(value['root_mount'], [root_mount])
                self.assertEqual(value['available_bytes'], 4194304)
                raise StorageAccepted()
            fixture.command = first
            metadata = {'files': {}, 'base': 'unused'}
            with patch.object(driver.Kernel, 'run', return_value={'accepted': True}), \
                    patch.object(driver.fedora_repository, 'mirror', return_value=metadata), \
                    patch.object(driver.vendor, 'mirror', return_value=metadata), self.assertRaises(StorageAccepted):
                fixture.run()
            fixture.command = command
            fixture.upload = unittest.mock.Mock(side_effect=RuntimeError('owned upload failed'))
            source = fixture.root / 'public.rpm'
            source.write_bytes(b'public')
            with self.assertRaisesRegex(RuntimeError, '^owned upload failed$'):
                fixture.transfer(source, driver.GUEST_ROOT + '/nvidia-vendor/public.rpm', 'a' * 64)
            evidence = json.loads((fixture.root / 'gpu-package-upload-failure.json').read_text())
            self.assertEqual(evidence['filesystem']['available_bytes'], 4194304)
            self.assertNotIn('diagnostic_error_type', evidence)
            self.assertEqual(len(programs), 3)

    def test_repository_disk_allows_real_btrfs_subvolumes_and_refuses_foreign_storage(self):
        root = {'source': '/dev/vda3[/root]', 'fstype': 'btrfs', 'maj:min': '0:34'}
        mount = {**root, 'source': '/dev/vda3[/var]'}
        driver.verify_repository_disk([mount], [root])
        driver.verify_repository_disk([{**mount, 'source': '/dev/vda3', 'fstype': 'ext4'}],
                                      [{**root, 'source': '/dev/vda3', 'fstype': 'ext4'}])
        for rows in ([], [mount, mount], [{}], [None], [{**mount, 'source': None}],
                     [{**mount, 'source': '/dev/vda4[/var]'}],
                     [{**mount, 'source': '/dev/vdb3[/var]'}],
                     [{**mount, 'source': '/dev/vda3[/var]\nforeign'}],
                     [{**mount, 'fstype': 'tmpfs'}], [{**mount, 'maj:min': '0:35'}]):
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                driver.verify_repository_disk(rows, [root])
        for roots in ([], [root, root], [{**root, 'fstype': 'nfs4'}],
                      [{**root, 'maj:min': 'malformed'}], [{**root, 'source': 'foreign'}]):
            with self.subTest(roots=roots), self.assertRaises(RuntimeError):
                driver.verify_repository_disk([mount], roots)

    def test_failed_upload_retains_public_storage_evidence_without_masking_failure(self):
        for diagnostic in ({'available_bytes': 0, 'mount': [{'fstype': 'ext4'}]}, RuntimeError('query failed')):
            with self.subTest(diagnostic=diagnostic), tempfile.TemporaryDirectory() as directory:
                fixture = object.__new__(driver.Qualification)
                fixture.root = Path(directory)
                source = fixture.root / 'public.rpm'
                source.write_bytes(b'public-package')
                fixture.guest = unittest.mock.Mock(side_effect=[{}, diagnostic])
                fixture.upload = unittest.mock.Mock(side_effect=RuntimeError('owned upload failed'))
                destination = driver.GUEST_ROOT + '/nvidia-vendor/public.rpm'
                with self.assertRaisesRegex(RuntimeError, '^owned upload failed$'):
                    fixture.transfer(source, destination, 'a' * 64)
                evidence = json.loads((fixture.root / 'gpu-package-upload-failure.json').read_text())
                self.assertEqual(evidence['destination'], destination)
                self.assertEqual(evidence['source_bytes'], len(b'public-package'))
                if isinstance(diagnostic, Exception):
                    self.assertEqual(evidence['diagnostic_error_type'], 'RuntimeError')
                else:
                    self.assertEqual(evidence['filesystem'], diagnostic)

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
