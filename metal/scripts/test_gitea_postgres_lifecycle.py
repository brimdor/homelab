"""Verify once-only intent and strict uncertain-outcome observation."""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import gitea_postgres_lifecycle as lifecycle
from test_gitea_postgres_account_recovery import catalog


class LifecycleTests(unittest.TestCase):
    def test_intent_is_exclusive_and_has_no_credential_field(self):
        binding = {'image': lifecycle.recovery.control.IMAGE,
                   'source_manifest_sha256': lifecycle.recovery.control.CHECKSUM,
                   'hba_sha256': '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05',
                   'catalog_sha256': 'b' * 64}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            digest = lifecycle.begin(directory, 'committed-unacknowledged', binding)
            self.assertEqual(len(digest), 64)
            path = directory / 'committed-unacknowledged-intent.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                lifecycle.begin(directory, 'committed-unacknowledged', binding)
            self.assertEqual(path.read_bytes(), original)
            for changed in (binding | {'password': 'private'}, binding | {'image': 'foreign'},
                            binding | {'source_manifest_sha256': 'c' * 64}, binding | {'hba_sha256': 'a' * 64},
                            binding | {'catalog_sha256': 'z' * 64}):
                with self.assertRaises(RuntimeError):
                    lifecycle.begin(directory, 'success', changed)

    def test_uncertain_commit_requires_the_exact_role_only_change(self):
        before = catalog()
        after = copy.deepcopy(before)
        after['roles'][0]['rolpassword'] = 'md5' + hashlib.md5(b'fixturepostgres').hexdigest()
        self.assertEqual(lifecycle.observed_outcome(before, after, 'fixture', 'committed-unacknowledged'), 'committed')
        self.assertEqual(lifecycle.observed_outcome(before, before, 'fixture', 'interrupted-before'), 'unchanged')
        for changed, mode in ((before, 'success'), (after, 'failed'), (after, 'interrupted-before')):
            with self.assertRaises(RuntimeError):
                lifecycle.observed_outcome(before, changed, 'fixture', mode)
        after['roles'][1]['rolsuper'] = True
        with self.assertRaises(RuntimeError):
            lifecycle.observed_outcome(before, after, 'fixture', 'committed-unacknowledged')

    def test_live_and_original_paths_refused_before_any_native_operation(self):
        for work in (Path('/var/lib/kubelet/production'), lifecycle.recovery.control.POINT / '0'):
            with self.assertRaises(RuntimeError), lifecycle.recovery.prepared_copy(work, [], 'fixture', 'image', b'hba'):
                self.fail('unowned source accepted')


if __name__ == '__main__':
    unittest.main()
