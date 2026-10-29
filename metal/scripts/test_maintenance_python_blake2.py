"""Reject source drift and retain independent BLAKE2 behavior coverage."""

import hashlib
import base64
from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_python_blake2 as repair


class Blake2RepairTests(unittest.TestCase):
    def test_transfer_refuses_corrupt_or_unqualified_artifact_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'candidate.so'
            artifact = b'exact qualified artifact'
            with patch.object(repair, 'CANDIDATE_SHA', hashlib.sha256(artifact).hexdigest()):
                for encoded in ('invalid!', base64.b64encode(artifact + b'drift')):
                    with self.assertRaises((ValueError, RuntimeError)):
                        repair.transferred_candidate(encoded, target)
                    self.assertFalse(target.exists())
                self.assertEqual(repair.transferred_candidate(base64.b64encode(artifact), target), target)
                self.assertEqual(target.read_bytes(), artifact)

    def test_atomic_install_and_failed_acceptance_restore_bytes_and_metadata(self):
        for accepted in (True, False):
            # macOS Python lacks os xattr calls; Linux repeats this test with real xattrs.
            attributes = nullcontext() if hasattr(os, 'listxattr') else patch.object(
                os, 'listxattr', return_value=[], create=True)
            with self.subTest(accepted=accepted), attributes, tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                target, candidate = root / 'installed.so', root / 'candidate.so'
                target.write_bytes(b'original vendor extension')
                candidate.write_bytes(b'qualified repaired extension')
                target.chmod(0o644)
                if hasattr(os, 'setxattr'):
                    os.setxattr(target, 'user.maintenance103', b'preserved')
                original_metadata = repair.metadata(target)
                original_sha = hashlib.sha256(target.read_bytes()).hexdigest()
                candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                def verify():
                    self.assertEqual(target.read_bytes(), candidate.read_bytes())
                    if not accepted:
                        raise RuntimeError('injected acceptance failure')
                with patch.object(repair, 'ORIGINAL_SHA', original_sha), patch.object(
                        repair, 'CANDIDATE_SHA', candidate_sha):
                    if accepted:
                        repair.install(target, candidate, root / 'recovery', verify, 'a' * 40)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'injected acceptance failure'):
                            repair.install(target, candidate, root / 'recovery', verify, 'a' * 40)
                self.assertEqual(repair.metadata(target), original_metadata)
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),
                                 candidate_sha if accepted else original_sha)
                self.assertEqual(repair.metadata(root / 'recovery/original.so'), original_metadata)
                self.assertEqual(hashlib.sha256((root / 'recovery/original.so').read_bytes()).hexdigest(), original_sha)
                self.assertEqual(list(root.glob('.maintenance103-blake2-*')), [])

    def test_patch_requires_exact_source_and_one_dispatch_block(self):
        source = ('prefix\n' + repair.PATCH_FROM + '\nsuffix\n').encode()
        with patch.object(repair, 'MODULE_SHA', hashlib.sha256(source).hexdigest()):
            result = repair.patched(source)
            self.assertIn(b'__builtin_cpu_supports("avx2")', result)
            self.assertEqual(result.count(repair.PATCH_FROM.encode()), 1)
            for changed in (source + b'drift', source.replace(b'prefix', b'change')):
                with self.assertRaisesRegex(RuntimeError, 'exact official'):
                    repair.patched(changed)
        doubled = source + source
        with patch.object(repair, 'MODULE_SHA', hashlib.sha256(doubled).hexdigest()):
            with self.assertRaisesRegex(RuntimeError, 'exact official'):
                repair.patched(doubled)

    def test_reference_vectors_include_rfc_empty_input_and_both_widths(self):
        values = repair.vectors()
        self.assertEqual(len(values), 72)
        self.assertEqual(values[0], '786a02f742015903c6c6fd852552d272912f4740e15847618a86e217f71f5419'
                         'd25e1031afee585313896444934eb04b903a685b1448b755d56f701afe9be2ce')
        self.assertEqual(values[36], '69217a3079908094e11121d042354a7c1f55b6482ca1a51e1b250dfd1ed0eef9')


if __name__ == '__main__':
    unittest.main()
