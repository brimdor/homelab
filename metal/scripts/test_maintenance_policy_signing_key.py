"""Restore the pinned public signing key once; reject changed trust material."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import maintenance_host_security as security


class PolicySigningKeyTests(unittest.TestCase):
    def exercise(self, directory, present=False, imported=True, fail_import=False):
        calls = []
        trusted = present

        def native(*argv):
            nonlocal trusted
            calls.append(argv)
            if argv == ('rpmkeys', '--list'):
                return security.SIGNING_FINGERPRINT + ' Existing public key\n' if trusted else ''
            self.assertEqual(argv, ('rpmkeys', '--import', str(Path(directory) / 'rancher-public.key')))
            if fail_import:
                raise RuntimeError('native import failed')
            trusted = imported
            return ''

        def exclusive_file(path, value, mode):
            with path.open('xb') as target:
                target.write(value)
            path.chmod(mode)

        hold = SimpleNamespace(safe=lambda path: None, exclusive_file=exclusive_file)
        return native, hold, calls

    def test_missing_trust_imports_once_and_second_call_observes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            native, hold, calls = self.exercise(directory)
            security.ensure_policy_signing_key(native, Path(directory), hold)
            security.ensure_policy_signing_key(native, Path(directory), hold)
            self.assertEqual(sum(c[:2] == ('rpmkeys', '--import') for c in calls), 1)
            self.assertEqual((Path(directory) / 'rancher-public.key').read_bytes(), security.POLICY_SIGNING_KEY)

    def test_existing_full_fingerprint_needs_no_import(self):
        with tempfile.TemporaryDirectory() as directory:
            native, hold, calls = self.exercise(directory, present=True)
            security.ensure_policy_signing_key(native, Path(directory), hold)
            self.assertFalse(any(c[:2] == ('rpmkeys', '--import') for c in calls))

    def test_changed_asset_stops_before_any_keyring_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'rancher-public.key').write_bytes(b'changed')
            native, hold, calls = self.exercise(directory)
            with self.assertRaisesRegex(AssertionError, 'policy signing key asset differs'):
                security.ensure_policy_signing_key(native, Path(directory), hold)
            self.assertEqual(calls, [])

    def test_failed_import_or_missing_readback_never_passes(self):
        for failure in (True, False):
            with self.subTest(import_failure=failure), tempfile.TemporaryDirectory() as directory:
                native, hold, _ = self.exercise(directory, imported=False, fail_import=failure)
                with self.assertRaises(RuntimeError if failure else AssertionError):
                    security.ensure_policy_signing_key(native, Path(directory), hold)


if __name__ == '__main__':
    unittest.main()
