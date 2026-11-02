"""Check the public read boundary before applying it to the protected backend."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def policy(filename):
    lines = (ROOT / 'templates' / filename).read_text().splitlines()
    return yaml.safe_load('\n'.join(lines[1:-1]).replace('{{ .Release.Namespace }}', 'zot'))['spec']


class BackendPolicyTests(unittest.TestCase):
    def setUp(self):
        self.backend = policy('backend-isolation.yaml')
        self.rules = self.backend['ingress'][0]['toPorts'][0]['rules']['http']

    def allowed(self, method, path):
        return any(re.fullmatch(rule['method'], method) and re.fullmatch(rule['path'], path)
                   for rule in self.rules)

    def test_anonymous_pulls_preserve_nested_repositories_and_queries(self):
        for path in ['/v2', '/v2/', '/v2/ops/app/manifests/tag',
                     '/v2/ops/app/manifests/sha256:abcd', '/v2/app/blobs/sha256:abcd',
                     '/v2/app/referrers/sha256:abcd?artifactType=application%2Fjson',
                     '/v2/ops/app/tags/list?n=10&last=old']:
            for method in ['GET', 'HEAD']:
                with self.subTest(method=method, path=path):
                    self.assertTrue(self.allowed(method, path))
        for path in ['/livez', '/readyz', '/startupz']:
            self.assertTrue(self.allowed('GET', path))
            self.assertFalse(self.allowed('POST', path))

    def test_catalog_admin_upload_sessions_and_mutations_are_not_public_reads(self):
        for path in ['/v2/_catalog', '/v2/_catalog?n=10', '/v2/_zot/ext/mgmt',
                     '/v2/app/blobs/uploads/', '/v2/app/blobs/uploads/session',
                     '/v2/app/blobs/uploads/session?digest=sha256:abcd',
                     '/v2/app/manifests/tag/extra', '/v2/app/tags/list/extra', '/']:
            for method in ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']:
                with self.subTest(method=method, path=path):
                    self.assertFalse(self.allowed(method, path))
        for method in ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']:
            self.assertFalse(self.allowed(method, '/v2/app/manifests/tag'))

    def test_only_exact_proxy_identity_gets_backend_access_beyond_public_reads(self):
        self.assertEqual(self.backend['endpointSelector']['matchLabels'],
                         {'app.kubernetes.io/name': 'zot', 'app.kubernetes.io/instance': 'zot'})
        self.assertEqual(self.backend['enableDefaultDeny'], {'ingress': True, 'egress': False})
        self.assertEqual(len(self.backend['ingress']), 2)
        self.assertEqual(self.backend['ingress'][0]['fromEntities'], ['all'])
        trusted = self.backend['ingress'][1]
        self.assertEqual(trusted['fromEndpoints'], [{'matchLabels': {
            'k8s:io.kubernetes.pod.namespace': 'zot', 'app.kubernetes.io/name': 'zot-auth',
            'app.kubernetes.io/instance': 'zot'}}])
        self.assertEqual(trusted['toPorts'], [{'ports': [{'port': '5000', 'protocol': 'TCP'}]}])
        self.assertNotIn('egress', self.backend)
        self.assertNotIn('ingressDeny', self.backend)

    def test_mock_qualifies_the_same_public_paths_and_trusted_identity(self):
        mock = policy('auth-policy-qualification.yaml')
        mock_rules = mock['ingress'][0]['toPorts'][0]['rules']['http']
        self.assertEqual(mock_rules[:-1], self.rules)
        self.assertEqual(mock_rules[-1], {'method': '^GET$', 'path': '^/healthz$'})
        self.assertEqual(mock['ingress'][1]['fromEndpoints'],
                         self.backend['ingress'][1]['fromEndpoints'])


if __name__ == '__main__':
    unittest.main()
