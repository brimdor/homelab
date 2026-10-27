"""Pinned vendor keys, solver inputs and original GPU runtime remain exact."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_nvidia as gpu


class NvidiaMaintenanceTests(unittest.TestCase):
    def test_owned_repository_retains_exact_key_and_branch_without_cuda_sdk_updates(self):
        key = b'synthetic public key'
        profile = dict(gpu.PROFILES[41], sha256=hashlib.sha256(key).hexdigest())
        url = 'https://developer.download.nvidia.com/compute/cuda/repos/fedora41/x86_64/D42D0685.pub'
        class Response:
            status = 200
            def __enter__(self):return self
            def __exit__(self, *args):return False
            def geturl(self):return url
            def read(self, maximum):return key
        for fault in (None, 'origin', 'key', 'retained-repo'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                path = Path(directory); calls = []
                with patch.dict(gpu.PROFILES, {41: profile}), patch.object(
                        gpu.urllib.request, 'urlopen', return_value=Response()):
                    if fault == 'origin':
                        original = url; url = 'https://foreign.invalid/D42D0685.pub'
                    if fault == 'key':profile['sha256'] = '0' * 64
                    if fault == 'retained-repo':(path / 'nvidia.repo').write_text('foreign')
                    if fault:
                        with self.assertRaises(RuntimeError):gpu.configure(path, 41, lambda *a: calls.append(a))
                    else:
                        result = gpu.configure(path, 41, lambda *a: calls.append(a))
                        self.assertEqual(result['version'], '570.211.01')
                        self.assertIn('includepkgs=*-570.211.01-* nvidia-driver-selinux', (path / 'nvidia.repo').read_text())
                        self.assertIn('gpgcheck=1', (path / 'nvidia.repo').read_text())
                        self.assertEqual(calls, [('rpmkeys', '--import', str(path / 'D42D0685.pub'))])
                        with patch.object(gpu.urllib.request, 'urlopen', side_effect=AssertionError('no refetch')):
                            self.assertEqual(gpu.configure(path, 41, lambda *a: None), result)
                if fault == 'origin':url = original
                profile['sha256'] = hashlib.sha256(key).hexdigest()

    def test_offline_driver_set_rejects_missing_duplicate_foreign_branch_or_distro(self):
        for release, profile in gpu.PROFILES.items():
            metadata = [[name, profile['version'], '1.fc' + str(release)] for name in
                        ('kmod-nvidia-open-dkms', 'nvidia-driver', 'nvidia-driver-cuda', 'nvidia-kmod-common')]
            self.assertEqual(gpu.downloaded(metadata, release)['version'], profile['version'])
            for fault in ('missing', 'duplicate', 'branch', 'distro'):
                bad = [row[:] for row in metadata]
                if fault == 'missing':bad.pop()
                if fault == 'duplicate':bad.append(bad[0][:])
                if fault == 'branch':bad[0][1] = '560.35.05'
                if fault == 'distro':bad[0][2] = '1.fc39'
                with self.subTest(release=release, fault=fault), self.assertRaises(RuntimeError):
                    gpu.downloaded(bad, release)

    def test_runtime_checks_loaded_original_gpu_and_exact_current_kernel_open_modules(self):
        for release, profile in gpu.PROFILES.items():
            version = profile['version']; kernel = 'synthetic-1.fc' + str(release) + '.x86_64'
            answers = {
                ('rpm', '-E', '%fedora'): str(release), ('uname', '-r'): kernel,
                ('dkms', 'status'): 'nvidia/' + version + ', ' + kernel + ', x86_64: installed',
                ('nvidia-smi', '--query-gpu=uuid,pci.bus_id,name,driver_version,memory.total',
                 '--format=csv,noheader,nounits'): gpu.GPU + ', 00000000:01:00.0, NVIDIA GeForce RTX 3090, ' + version + ', 24576',
                ('nvidia-smi', '--query-gpu=uuid,driver_version', '--format=csv,noheader'): gpu.GPU + ', ' + version,
            }
            for name in ('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm'):
                for field, answer in {'version': version, 'vermagic': kernel + ' SMP', 'license': 'Dual MIT/GPL'}.items():
                    answers[('modinfo', '-k', kernel, '-F', field, name)] = answer
            result = gpu.runtime(lambda *args: answers[args], release)
            self.assertTrue(result['native_nvml'])
            self.assertTrue(result['cuda_execution_untested'])
            for command in (('dkms', 'status'), ('modinfo', '-k', kernel, '-F', 'version', 'nvidia'),
                            ('modinfo', '-k', kernel, '-F', 'license', 'nvidia'),
                            ('nvidia-smi', '--query-gpu=uuid,driver_version', '--format=csv,noheader')):
                original = answers[command]; answers[command] = 'foreign'
                with self.subTest(release=release, command=command), self.assertRaises(RuntimeError):
                    gpu.runtime(lambda *args: answers[args], release)
                answers[command] = original


if __name__ == '__main__':
    unittest.main()
