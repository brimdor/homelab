"""Reject source drift and retain independent BLAKE2 behavior coverage."""

import hashlib
import unittest
from unittest.mock import patch

import maintenance_python_blake2 as repair


class Blake2RepairTests(unittest.TestCase):
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
