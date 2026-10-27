"""The monitor archive must never authorize unsafe or live-store copying."""

import copy
import unittest

import maintenance_monitor_recovery as subject
import maintenance_production_node as production


class MonitorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.node = {'metadata': {'name': 'charmander', 'uid': subject.NODE_UID},
                     'spec': {'unschedulable': True}}
        self.status = {'fsid': subject.FSID, 'quorum_names': ['l', 'n'],
                       'health': {'status': 'HEALTH_WARN', 'checks': {'MON_DOWN': {}}},
                       'osdmap': {'num_osds': 5, 'num_up_osds': 5, 'num_in_osds': 5},
                       'pgmap': {'pgs_by_state': [{'state_name': 'active+clean'}]}}

    def test_cold_original_monitor_outage_and_all_embedded_programs(self):
        subject.guard(self.node, [], self.status)
        for source in (subject.READBACK, subject.SOURCE, subject.RECEIVE):
            compile(subject.bindings() + source, 'cold-monitor-native', 'exec')
        self.assertIn("command!='ceph-mon'", subject.SOURCE)
        self.assertIn('fcntl.LOCK_EX|fcntl.LOCK_NB', subject.SOURCE)
        self.assertIn("assert not root.exists()", subject.RECEIVE)

    def test_changed_target_uncordoned_live_monitor_quorum_osd_or_pg_is_refused(self):
        for fault in ('node', 'cordon', 'live', 'identity', 'quorum', 'osd', 'pg', 'health'):
            node, status, pods = copy.deepcopy(self.node), copy.deepcopy(self.status), []
            if fault == 'node': node['metadata']['uid'] = 'another-node'
            if fault == 'cordon': node['spec']['unschedulable'] = False
            if fault == 'live': pods = [{'metadata': {'uid': subject.POD_UID}, 'spec': {}}]
            if fault == 'identity': status['fsid'] = 'another-cluster'
            if fault == 'quorum': status['quorum_names'] = ['h', 'l']
            if fault == 'osd': status['osdmap']['num_up_osds'] = 4
            if fault == 'pg': status['pgmap']['pgs_by_state'][0]['state_name'] = 'active+degraded'
            if fault == 'health': status['health']['checks']['OSD_DOWN'] = {}
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                subject.guard(node, pods, status)

    def test_monitor_protection_gates_actual_package_operations(self):
        import inspect
        source = inspect.getsource(production.main)
        gate = source.index("if NODE == 'charmander' and args.operation in ('source-repositories'")
        dispatch = source.index('print(encoded(run_worker(')
        self.assertLess(gate, dispatch)
        self.assertIn('verify(args)', source[gate:dispatch])

    def test_arcanine_cold_monitor_requires_both_survivors_and_every_osd_up(self):
        profile = subject.profile_for('arcanine')
        node = {'metadata': {'name': 'arcanine', 'uid': profile['node_uid']},
                'spec': {'unschedulable': True}}
        status = copy.deepcopy(self.status)
        status['quorum_names'] = ['l', 'o']
        subject.guard(node, [], status, target='arcanine')
        # Rook may finish failover while the original cold store is protected.
        status['quorum_names'].append('p')
        status['health'] = {'status': 'HEALTH_OK', 'checks': {}}
        subject.guard(node, [], status, target='arcanine')
        for fault in ('original live', 'replacement local', 'old monitor quorum', 'lost survivor', 'down osd'):
            changed, pods = copy.deepcopy(status), []
            if fault == 'original live':pods = [{'metadata': {'uid': profile['pod_uid']}, 'spec': {}}]
            if fault == 'replacement local':pods = [{'metadata': {'uid': 'new', 'labels': {
                'app': 'rook-ceph-mon'}}, 'spec': {'nodeName': 'arcanine'}}]
            if fault == 'old monitor quorum':changed['quorum_names'].append('n')
            if fault == 'lost survivor':changed['quorum_names'] = ['l', 'p']
            if fault == 'down osd':changed['osdmap']['num_up_osds'] = 4
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                subject.guard(node, pods, changed, target='arcanine')

    def test_arcanine_bindings_keep_exact_archive_and_receiver_separate(self):
        scope = {}
        exec(subject.bindings('arcanine'), scope)
        self.assertEqual(scope['MONITOR'], 'n')
        self.assertEqual(scope['NODE'], 'arcanine')
        self.assertEqual(scope['RECEIVER_NODE'], 'charmander')
        self.assertEqual(scope['ROOT'], '/var/lib/homelab-recovery/maintenance-103/arcanine-mon-n-20261027-a')
        self.assertEqual(scope['POD_UID'], 'bc113cbd-a8a8-4b2c-a85f-7da4fe180e83')
        for source in (subject.READBACK, subject.SOURCE, subject.RECEIVE):
            compile(subject.bindings('arcanine') + source, 'arcanine-cold-monitor-native', 'exec')
            self.assertNotIn('mon-h', source)
        self.assertEqual(subject.PROFILES['arcanine']['receiver'], '10.0.20.11')
        self.assertEqual(subject.PROFILES['charmander']['receiver'], '10.0.20.18')
        with self.assertRaisesRegex(RuntimeError, 'unreviewed'):
            subject.bindings('unknown')


if __name__ == '__main__':
    unittest.main()
