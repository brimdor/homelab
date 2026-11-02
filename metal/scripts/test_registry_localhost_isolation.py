"""Ensure host preservation never bypasses registry L7 rules or adds default deny."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def selected(selector, labels):
    if not all(labels.get(key) == value for key, value in selector.get('matchLabels', {}).items()):
        return False
    for expression in selector.get('matchExpressions', []):
        key, operator = expression['key'], expression['operator']
        if operator == 'Exists' and key not in labels:
            return False
        if operator == 'NotIn' and labels.get(key) in expression['values']:
            return False
    return True


class HostPreservationTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'roles/cilium/templates/registry-localhost-host-access.yaml'
        self.rules = yaml.safe_load(path.read_text())['specs']

    def test_host_preservation_excludes_both_registry_security_boundaries(self):
        namespace = 'k8s:io.kubernetes.pod.namespace'
        name = 'k8s:app.kubernetes.io/name'
        for labels, expected in [
                ({namespace: 'zot', name: 'zot'}, False),
                ({namespace: 'zot', name: 'zot-auth'}, False),
                ({namespace: 'zot', name: 'other'}, True),
                ({namespace: 'zot'}, True),
                ({namespace: 'other', name: 'zot'}, True),
                ({namespace: 'kube-system', name: 'coredns'}, True),
                ({'reserved:host': ''}, False)]:
            with self.subTest(labels=labels):
                self.assertEqual(any(selected(rule['endpointSelector'], labels) for rule in self.rules), expected)

    def test_rules_preserve_only_host_ingress_without_default_deny(self):
        for rule in self.rules:
            self.assertEqual(rule['enableDefaultDeny'], {'ingress': False, 'egress': False})
            self.assertEqual(rule['ingress'], [{'fromEntities': ['host']}])
            self.assertNotIn('egress', rule)
            self.assertNotIn('ingressDeny', rule)
            self.assertNotIn('nodeSelector', rule)


if __name__ == '__main__':
    unittest.main()
