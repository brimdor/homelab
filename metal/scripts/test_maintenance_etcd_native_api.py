"""Existing-trust cycle reads refuse mutations and retain no native scratch."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import maintenance_etcd_native_api as api


class NativeReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name);self.credential = self.root / 'existing-kubeconfig'
        self.credential.write_bytes(b'synthetic credential');self.credential.chmod(0o600)
        self.config = {'clusters': [{'cluster': {'certificate-authority-data': 'REDACTED'}}],
                       'users': [{'user': {'client-certificate-data': 'REDACTED', 'client-key-data': 'REDACTED'}}],
                       'contexts': [{}]}
        self.calls = []

    def native(self, *argv):
        self.calls.append(argv)
        self.assertIn('--kubeconfig=' + str(self.credential), argv)
        self.assertIn('--server=https://10.0.20.12:6443', argv)
        self.assertTrue(any(a.startswith('--cache-dir=' + str(self.root)) for a in argv))
        self.assertNotIn('--insecure-skip-tls-verify', argv)
        if 'config' in argv:
            return json.dumps(self.config)
        self.assertEqual(argv[-3:-1], ('get', '--raw'))
        return json.dumps({'kind': 'DaemonSet'} if argv[-1] == api.RESOURCES[0] else {'items': [argv[-1]]})

    def reader(self, endpoint='https://10.0.20.12:6443', native=None):
        with patch.object(api, 'record', return_value={'sha256': api.SHA256['v1.33.10+k3s1']}):
            return api.Reader('charmander', endpoint, native or self.native,
                              self.credential, self.root / 'source-k3s', self.root)

    def test_exact_three_reads_reuse_existing_certificate_and_remove_scratch(self):
        original = self.credential.read_bytes();reader = self.reader()
        try:
            self.assertEqual(reader.snapshot(), ({'kind': 'DaemonSet'}, [api.RESOURCES[1]], [api.RESOURCES[2]]))
            self.assertEqual(len(self.calls), 4)
            self.assertEqual(self.credential.read_bytes(), original)
        finally:reader.close()
        self.assertFalse(reader.scratch.exists());self.assertTrue(self.credential.exists())

    def test_fixed_registry_read_does_not_expand_ownership_snapshot_or_allow_other_reads(self):
        reader = self.reader()
        try:
            self.assertEqual(reader.query('get', '--raw', api.REGISTRY_PODS), {'items': [api.REGISTRY_PODS]})
            self.assertEqual(len(reader.snapshot()), 3)
            for path in ('/api/v1/pods', '/api/v1/namespaces/zot/secrets', api.REGISTRY_PODS + '?watch=true'):
                with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'only original ownership'):
                    reader.query('get', '--raw', path)
        finally:reader.close()
        self.assertFalse(reader.scratch.exists())

    def test_foreign_insecure_or_own_endpoint_refuses_before_process_and_scratch(self):
        native = Mock()
        for endpoint in ('http://10.0.20.12:6443', 'https://10.0.20.11:6443',
                         'https://10.0.20.12:6443/extra', 'https://foreign:6443'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(RuntimeError, 'surviving HTTPS'):
                self.reader(endpoint, native)
        native.assert_not_called();self.assertEqual(list(self.root.iterdir()), [self.credential])

    def test_insecure_proxy_exec_or_missing_CA_refuses_and_cleans_scratch(self):
        original = copy.deepcopy(self.config)
        variants = []
        for field, value in (('insecure-skip-tls-verify', True), ('proxy-url', 'http://foreign'),
                             ('certificate-authority-data', '')):
            v = copy.deepcopy(original);v['clusters'][0]['cluster'][field] = value;variants.append(v)
        v = copy.deepcopy(original);v['users'][0]['user']['exec'] = {'command': 'foreign'};variants.append(v)
        for value in variants:
            self.config = value
            with self.subTest(config=value), self.assertRaisesRegex(RuntimeError, 'verified CA'):
                self.reader()
            self.assertEqual(list(self.root.iterdir()), [self.credential])

    def test_changed_or_unsafe_credential_stops_before_another_request(self):
        reader = self.reader()
        try:
            self.credential.write_bytes(b'changed synthetic credential')
            with self.assertRaisesRegex(RuntimeError, 'kubeconfig changed'):reader.snapshot()
            self.assertEqual(len(self.calls), 1)
        finally:reader.close()
        self.credential.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'unsafe original'):self.reader()
        self.assertEqual(len(self.calls), 1)

    def test_mutations_other_reads_and_source_checksum_changes_are_refused(self):
        reader = self.reader()
        try:
            for args in (('patch', 'node', 'charmander'), ('get', '--raw', '/api/v1/secrets'), ()):
                with self.subTest(args=args), self.assertRaisesRegex(RuntimeError, 'only original ownership'):
                    reader.query(*args)
            self.assertEqual(len(self.calls), 1)
        finally:reader.close()
        with patch.object(api, 'record', return_value={'sha256': '0' * 64}), self.assertRaisesRegex(RuntimeError, 'SOURCE'):
            api.Reader('charmander', 'https://10.0.20.12:6443', self.native,
                       self.credential, self.root / 'source-k3s', self.root)
        self.assertEqual(list(self.root.iterdir()), [self.credential])

    def test_native_request_failure_has_verified_constructor_cleanup(self):
        with self.assertRaisesRegex(RuntimeError, 'native request failed'):
            self.reader(native=Mock(side_effect=RuntimeError('native request failed')))
        self.assertEqual(list(self.root.iterdir()), [self.credential])


if __name__ == '__main__':
    unittest.main()
