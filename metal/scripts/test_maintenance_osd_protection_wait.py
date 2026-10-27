"""Rook's asynchronous protection must finish without replay or weaker Ceph gates."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import maintenance_osd_host as osd
from maintenance_coordination import JOURNAL


class API:
    def __init__(self, node):
        profile = osd.profile_for(node)
        self.owner = {'owner': 'homelab-maintenance-103-00000000-0000-4000-8000-000000000000',
                      'node': node, 'node_uid': profile['node_uid'], 'source': 41, 'target': 43}
        self.ref = {'namespace': 'rook-ceph', 'keep': False, 'uid': 'evicted-pod', 'controller': {
            'kind': 'ReplicaSet', 'name': 'rook-ceph-osd-' + str(profile['osd']) + '-abc123', 'uid': 'replica'}}
        self.ds = {'metadata': {'uid': '4abc4fee-c3be-440e-8945-34bb3fb15ce1',
                               'annotations': {JOURNAL: json.dumps(self.owner)}}}
        self.node = {'metadata': {'uid': profile['node_uid']}, 'spec': {'unschedulable': True}}
        self.replica = {'metadata': {'uid': 'replica', 'ownerReferences': [{
            'kind': 'Deployment', 'controller': True, 'uid': profile['deployment_uid']}]}}
        self.before = {'metadata': {'uid': osd.STATE_UID}, 'data': {'draining-failure-domain': ''}}
        self.after = {'metadata': {'uid': osd.STATE_UID}, 'data': {
            'draining-failure-domain': node, 'set-no-out': 'true'}}
        self.map = {'fsid': osd.FSID, 'crush_node_flags': {node: ['noout']}}
        self.wait_error = None
        self.calls = []

    def call(self, *args):
        self.calls.append(args)
        if args[0] == 'wait':
            if self.wait_error:
                raise self.wait_error
            return copy.deepcopy(self.after)
        if args[0] == 'exec':
            return copy.deepcopy(self.map)
        return copy.deepcopy({'daemonset': self.ds, 'node': self.node,
                              'replicaset': self.replica, 'configmap': self.before}[args[1]])


class ProtectionWaitTests(unittest.TestCase):
    def run_wait(self, api):
        return osd.wait_for_protection(api, api.owner['node'], api.owner, api.ref)

    def test_each_reviewed_host_waits_readonly_then_runs_full_gate(self):
        for node in ('cyndaquil', 'growlithe'):
            with self.subTest(node=node):
                api = API(node)
                with patch.object(osd, 'observe', return_value={'owner': api.owner['owner']}) as full_gate:
                    result = self.run_wait(api)
                full_gate.assert_called_once_with(api, node=node)
                waits = [call for call in api.calls if call[0] == 'wait']
                self.assertEqual(waits, [('wait', 'configmap/rook-ceph-pdbstatemap', '-n', 'rook-ceph',
                                         '--for=jsonpath={.data.set-no-out}=true', '--timeout=60s', '-o', 'json')])
                self.assertTrue(result['actual_noout_verified'])
                self.assertFalse(result['mutation_performed'])
                self.assertFalse(any(call[0] in ('patch', 'create', 'delete') for call in api.calls))

    def test_changed_identity_cordon_controller_or_rook_domain_is_rejected(self):
        cases = [
            lambda a: a.ds['metadata']['annotations'].update({JOURNAL: '{}'}),
            lambda a: a.node['spec'].update(unschedulable=False),
            lambda a: a.ref.update(namespace='foreign'),
            lambda a: a.ref.update(keep=True),
            lambda a: a.replica['metadata'].update(uid='foreign'),
            lambda a: a.replica['metadata']['ownerReferences'][0].update(uid='foreign'),
            lambda a: a.before['data'].update({'draining-failure-domain': 'foreign'}),
            lambda a: a.after['metadata'].update(uid='foreign'),
            lambda a: a.after['data'].update({'draining-failure-domain': 'foreign'}),
            lambda a: a.after['data'].update({'set-no-out': 'false'}),
            lambda a: a.map.update(crush_node_flags={}),
            lambda a: a.map.update(fsid='foreign'),
        ]
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                api = API('growlithe'); change(api)
                with patch.object(osd, 'observe', return_value={'owner': api.owner['owner']}):
                    with self.assertRaises(RuntimeError):
                        self.run_wait(api)

    def test_timeout_or_full_ceph_failure_is_not_retried_or_suppressed(self):
        api = API('growlithe'); api.wait_error = RuntimeError('wait timeout')
        with patch.object(osd, 'observe') as full_gate:
            with self.assertRaisesRegex(RuntimeError, 'wait timeout'):
                self.run_wait(api)
            full_gate.assert_not_called()
        self.assertEqual(sum(call[0] == 'wait' for call in api.calls), 1)
        api = API('growlithe')
        with patch.object(osd, 'observe', side_effect=RuntimeError('unrelated unhealthy PG')):
            with self.assertRaisesRegex(RuntimeError, 'unrelated unhealthy PG'):
                self.run_wait(api)

    def test_native_wait_follows_only_a_new_queued_osd_eviction(self):
        source = (Path(__file__).parent / 'maintenance_production_node.py').read_text()
        self.assertIn("result.get('queued')and expected_node in('cyndaquil','growlithe','arcanine')", source)
        self.assertLess(source.index('result=worker.advance(digest,verify,removed)'),
                        source.index("rpc('await_osd_protection',ref=ref)"))
        self.assertIn("args.operation == 'drain' and NODE in OSD_RECOVERY", source)


if __name__ == '__main__':
    unittest.main()
