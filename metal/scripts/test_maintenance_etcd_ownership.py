"""Only the exact owned SOURCE may lose its heartbeat during the private cycle."""

import copy
import unittest

import maintenance_etcd_ownership as scoped
from test_maintenance_coordination import API


class OwnedCycleTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        node, pod = self.api.nodes[0], self.api.pods[0]
        self.api.nodes = [];self.api.pods = []
        for name in scoped.ORDER:
            n = copy.deepcopy(node);n['metadata'].update(name=name, uid=name + '-uid')
            n['spec'] = {'unschedulable': name == 'charmander'}
            p = copy.deepcopy(pod);p['metadata'].update(name='kured-' + name, uid='pod-' + name)
            p['spec']['nodeName'] = name
            p['status']['containerStatuses'][0].update(containerID='containerd://' + name,
                restartCount=0, state={'running': {'startedAt': '2026-10-30T00:00:00Z'}})
            self.api.nodes.append(n);self.api.pods.append(p)
        self.api.ds['status'].update(desiredNumberScheduled=9, currentNumberScheduled=9,
            updatedNumberScheduled=9, numberReady=9, numberAvailable=9)
        self.controller = self.api.controller()
        self.owner = self.controller.acquire('charmander', 'v1.33.10+k3s1', 'v1.33.13+k3s2', 'a' * 40, component='k3s')
        self.baseline = scoped.capture(self.controller, self.owner['owner'])
        self.original = copy.deepcopy(self.api.snapshot())

    def lost_source_heartbeat(self):
        for condition in self.api.nodes[0]['status']['conditions']:condition['status'] = 'Unknown'
        self.api.pods[0]['status']['containerStatuses'][0]['ready'] = False
        self.api.ds['status'].update(numberReady=8, numberAvailable=8, numberUnavailable=1)

    def test_exact_source_heartbeat_loss_is_read_only_and_does_not_weaken_normal_owner(self):
        self.lost_source_heartbeat()
        writes = self.api.writes;snapshot = copy.deepcopy(self.api.snapshot())
        self.assertTrue(scoped.observe(self.controller, self.baseline))
        self.assertEqual(self.api.snapshot(), snapshot);self.assertEqual(self.api.writes, writes)
        with self.assertRaisesRegex(RuntimeError, 'node health'):self.controller.resume(self.owner['owner'])

    def test_another_node_or_kured_container_failure_is_not_allowed(self):
        for fault in ('node', 'container', 'cordon', 'pressure', 'source_pressure'):
            self.api.ds, self.api.pods, self.api.nodes = copy.deepcopy(self.original)
            self.lost_source_heartbeat()
            if fault == 'node':self.api.nodes[1]['status']['conditions'][0]['status'] = 'Unknown'
            if fault == 'container':self.api.pods[1]['status']['containerStatuses'][0]['ready'] = False
            if fault == 'cordon':self.api.nodes[1]['spec']['unschedulable'] = True
            if fault == 'pressure':self.api.nodes[1]['status']['conditions'][1]['status'] = 'True'
            if fault == 'source_pressure':self.api.nodes[0]['status']['conditions'][1]['status'] = 'True'
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):scoped.observe(self.controller, self.baseline)

    def test_changed_lock_uid_generation_spec_or_original_process_is_refused(self):
        for fault in ('lock', 'node_uid', 'pod_uid', 'generation', 'spec', 'container', 'restart', 'started', 'source_cordon'):
            self.api.ds, self.api.pods, self.api.nodes = copy.deepcopy(self.original)
            self.lost_source_heartbeat()
            if fault == 'lock':self.api.ds['metadata']['annotations'].clear()
            if fault == 'node_uid':self.api.nodes[0]['metadata']['uid'] = 'foreign'
            if fault == 'pod_uid':self.api.pods[0]['metadata']['uid'] = 'foreign'
            if fault == 'generation':self.api.ds['metadata']['generation'] += 1
            if fault == 'spec':self.api.ds['spec']['changed'] = True
            if fault == 'container':self.api.pods[0]['status']['containerStatuses'][0]['containerID'] = 'foreign'
            if fault == 'restart':self.api.pods[0]['status']['containerStatuses'][0]['restartCount'] = 1
            if fault == 'started':self.api.pods[0]['status']['containerStatuses'][0]['state']['running']['startedAt'] = 'changed'
            if fault == 'source_cordon':self.api.nodes[0]['spec']['unschedulable'] = False
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):scoped.observe(self.controller, self.baseline)

    def test_source_cycle_cannot_hide_a_larger_kured_outage_or_capture_unhealthy_baseline(self):
        for field in ('numberReady', 'numberAvailable', 'currentNumberScheduled', 'updatedNumberScheduled'):
            self.api.ds, self.api.pods, self.api.nodes = copy.deepcopy(self.original)
            self.lost_source_heartbeat();self.api.ds['status'][field] = 7
            with self.subTest(field=field), self.assertRaises(RuntimeError):scoped.observe(self.controller, self.baseline)
        self.api.ds, self.api.pods, self.api.nodes = copy.deepcopy(self.original)
        self.lost_source_heartbeat()
        with self.assertRaises(RuntimeError):scoped.capture(self.controller, self.owner['owner'])


if __name__ == '__main__':
    unittest.main()
