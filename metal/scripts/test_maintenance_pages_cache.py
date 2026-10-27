#!/usr/bin/env python3
"""Reject a recovery request after its maintenance or scheduled Pod changes."""

import copy
import json
import unittest

import maintenance_pages_cache as recovery


class RecoveryGuardTest(unittest.TestCase):
    def setUp(self):
        self.items = {
            ('daemonset', 'kured'): {'metadata': {
                'uid': '4abc4fee-c3be-440e-8945-34bb3fb15ce1', 'annotations': {
                    recovery.LOCK: json.dumps({'nodeID': recovery.OWNER}),
                    recovery.JOURNAL: json.dumps({'owner': recovery.OWNER, 'node': 'totodile'}),
                }}},
            ('deployment', 'pages-canary'): {'metadata': {
                'uid': '0ff8ede9-76f9-4b25-b303-3bedf46e4793'}, 'spec': {'template': {'spec': {
                    'containers': [{'name': 'pages-canary', 'image': recovery.VALUES['IMAGE'],
                                    'imagePullPolicy': 'IfNotPresent'}]}}}},
            ('pod', 'pages-canary-5b5b56cd7f-bx7n6'): {'metadata': {
                'uid': 'e5ac29b5-40f3-488b-b5e3-942b58c8b659'}, 'spec': {'nodeName': 'growlithe'}},
        }
        for name, uid, cordoned in (
            ('totodile', '83e0e536-e94a-45a1-8dfb-1cedac1e9bd7', True),
            ('growlithe', '50f95b8f-4117-4c1e-84bc-266c5b23bffb', False),
        ):
            self.items[('node', name)] = {'metadata': {'uid': uid},
                'spec': {'unschedulable': cordoned},
                'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}

    def get(self, verb, kind, name, *unused):
        self.assertEqual(verb, 'get')
        return copy.deepcopy(self.items[(kind, name)])

    def test_original_scheduled_recovery(self):
        recovery.check_state(self.get)
        self.assertFalse(recovery.VALUES['RECOVERY'].startswith('/var/lib/homelab-recovery/'))

    def test_reject_replaced_pod_or_moved_receiver(self):
        key = ('pod', 'pages-canary-5b5b56cd7f-bx7n6')
        original = copy.deepcopy(self.items[key])
        for field, value in (('uid', 'replacement'), ('nodeName', 'pikachu')):
            self.items[key] = copy.deepcopy(original)
            self.items[key]['metadata' if field == 'uid' else 'spec'][field] = value
            with self.assertRaises(RuntimeError):
                recovery.check_state(self.get)

    def test_reject_released_owner_or_registry_required_policy(self):
        self.items[('daemonset', 'kured')]['metadata']['annotations'][recovery.LOCK] = json.dumps(
            {'nodeID': 'foreign-owner'})
        with self.assertRaises(RuntimeError):
            recovery.check_state(self.get)
        self.setUp()
        self.items[('deployment', 'pages-canary')]['spec']['template']['spec']['containers'][0][
            'imagePullPolicy'] = 'Always'
        with self.assertRaises(RuntimeError):
            recovery.check_state(self.get)


if __name__ == '__main__':
    unittest.main()
