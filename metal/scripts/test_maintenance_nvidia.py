"""Pinned vendor keys, solver inputs and original GPU runtime remain exact."""

import contextlib
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_nvidia as gpu


class NvidiaMaintenanceTests(unittest.TestCase):
    def test_permanent_repository_is_bound_to_final_owner_and_observes_interruption(self):
        original = ('[cuda-fedora39-x86_64]\nname=cuda-fedora39-x86_64\n'
                    'baseurl=https://developer.download.nvidia.com/compute/cuda/repos/fedora39/x86_64\n'
                    'enabled=1\ngpgcheck=1\n'
                    'gpgkey=https://developer.download.nvidia.com/compute/cuda/repos/fedora39/x86_64/D42D0685.pub\n')
        for fault in (None, 'foreign-owner', 'wrong-phase', 'foreign-repository', 'key', 'symlink', 'imported-key', 'short-key',
                      'interrupted-before-replace', 'interrupted-after-replace', 'tampered-intent', 'released-owner'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); repo = root / 'cuda-fedora.repo'; repo.write_text(original); repo.chmod(0o644)
                owner = {'node': 'arcanine', 'source': 43, 'target': 44,
                         'node_uid': '88aa2572-09df-40b9-8a00-960e9682917c',
                         'owner': 'homelab-maintenance-103-00000000-0000-0000-0000-000000000000'}
                identity = {'machine': 'synthetic', 'root_uuid': 'synthetic-root'}
                recovery = {'source_release': 44, 'identity': identity, 'sha256': 'a' * 64}
                hold = SimpleNamespace(state=root, identity=lambda: identity, serialized=contextlib.nullcontext)
                completed = ['cordon', 'drain', 'prepare_source', 'download_release',
                             'offline_transaction', 'trusted_reconnect', 'verify_infrastructure']
                journal = SimpleNamespace(hold=hold, owners=lambda **kw: {'global': owner},
                                          token=owner['owner'], path=root / 'journal',
                                          read=lambda: {'pending': None, 'completed': completed})
                key = b'synthetic public key'; profile = dict(gpu.PROFILES[44], sha256=hashlib.sha256(key).hexdigest())
                keys = root / ('fedora-repositories-44-' + owner['owner']); keys.mkdir(mode=0o700)
                (keys / profile['key']).write_bytes(key); (keys / profile['key']).chmod(0o600)
                if fault == 'foreign-owner':owner['node'] = 'sprigatito'
                if fault == 'wrong-phase':completed.pop()
                if fault == 'foreign-repository':repo.write_text('foreign')
                if fault == 'key':(keys / profile['key']).write_bytes(b'foreign')
                if fault == 'symlink':repo.unlink(); repo.symlink_to(keys / profile['key'])
                journal.path.mkdir(mode=0o700)
                header = journal.path / '00000000.json'
                header.write_bytes(gpu.canonical({'owners': {'global': owner}})); header.chmod(0o600)
                def native(*argv):
                    if argv == ('rpm', '-E', '%fedora'):return '44'
                    if argv == ('rpmkeys', '--list'):
                        fingerprint = ('0' * 40 if fault == 'imported-key' else
                                       '73cd9b30' if fault == 'short-key' else profile['fingerprint'].lower())
                        return fingerprint + ' NVIDIA synthetic public key'
                    raise AssertionError(argv)
                with patch.object(gpu, 'PERMANENT_REPOSITORY', repo), patch.dict(gpu.PROFILES, {44: profile}):
                    if fault in ('foreign-owner', 'wrong-phase', 'foreign-repository', 'key', 'symlink', 'imported-key', 'short-key'):
                        with self.assertRaises((RuntimeError, AssertionError)):
                            gpu.persist_repository(journal, native, recovery)
                        self.assertFalse(list(root.glob('nvidia-repository-*.json')))
                    elif fault == 'interrupted-before-replace':
                        with patch.object(gpu.os, 'replace', side_effect=OSError('interrupted')):
                            with self.assertRaises(OSError):gpu.persist_repository(journal, native, recovery)
                        self.assertEqual(repo.read_text(), original)
                        with self.assertRaisesRegex(RuntimeError, 'observe only'):
                            gpu.persist_repository(journal, native, recovery)
                    else:
                        accepted = gpu.persist_repository(journal, native, recovery)
                        self.assertEqual(repo.read_bytes(), gpu.PERMANENT_CONTENT)
                        if fault == 'tampered-intent':
                            import json
                            accepted_path = root / ('nvidia-repository-accepted-' + owner['owner'] + '.json')
                            accepted_path.unlink()
                            intent = root / ('nvidia-repository-' + owner['owner'] + '.json')
                            record = json.loads(intent.read_bytes()); record['original'] = 'foreign'
                            intent.write_bytes(gpu.canonical(record))
                            with self.assertRaises(RuntimeError):gpu.persist_repository(journal, native, recovery)
                            self.assertFalse(accepted_path.exists())
                            continue
                        if fault == 'interrupted-after-replace':
                            (root / ('nvidia-repository-accepted-' + owner['owner'] + '.json')).unlink()
                        with patch.object(gpu.os, 'replace', side_effect=AssertionError('never replay')):
                            self.assertEqual(gpu.persist_repository(journal, native, recovery), accepted)
                        self.assertEqual(gpu.permanent_repository(journal, native), accepted)
                        if fault == 'released-owner':
                            journal.owners = lambda **kw: (_ for _ in ()).throw(RuntimeError('owner released'))
                            self.assertEqual(gpu.permanent_repository(journal, native), accepted)
                            with self.assertRaises(RuntimeError):gpu.persist_repository(journal, native, recovery)
                        repo.write_text('foreign')
                        with self.assertRaises(RuntimeError):gpu.permanent_repository(journal, native)

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

    @patch.object(gpu, 'compute', return_value={'result': 42, 'owned_gpu_resources_released': True})
    def test_runtime_checks_loaded_original_gpu_and_exact_current_kernel_open_modules(self, compute):
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
            self.assertEqual(result['cuda_execution']['result'], 42)
            self.assertTrue(result['cuda_execution']['owned_gpu_resources_released'])
            for command in (('dkms', 'status'), ('modinfo', '-k', kernel, '-F', 'version', 'nvidia'),
                            ('modinfo', '-k', kernel, '-F', 'license', 'nvidia'),
                            ('nvidia-smi', '--query-gpu=uuid,driver_version', '--format=csv,noheader')):
                original = answers[command]; answers[command] = 'foreign'
                with self.subTest(release=release, command=command), self.assertRaises(RuntimeError):
                    gpu.runtime(lambda *args: answers[args], release)
                answers[command] = original


if __name__ == '__main__':
    unittest.main()
