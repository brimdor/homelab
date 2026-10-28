"""Bulbasaur's control-plane recovery and protected registry boundaries."""
import copy
import importlib
import unittest
from unittest.mock import patch

import maintenance_production_node as production
import maintenance_control_plane as control
import maintenance_host_security as security
import maintenance_monitor_recovery as monitor


class BulbasaurTests(unittest.TestCase):
    def setUp(self):
        importlib.reload(production)
        self.addCleanup(importlib.reload, production)

    def test_all_hops_bind_consistent_etcd_to_the_exact_master_and_receiver(self):
        production.select_node('bulbasaur')
        self.assertEqual(production.UID, 'b921073c-822a-4b74-80ed-563fec33d6ab')
        self.assertEqual(production.IDENTITY['root_uuid'], '2c59d1d1-d2d8-420e-b3a5-d87eb0437823')
        for release in (39, 41, 43, 44):
            point = {'manifest_sha256': 'a' * 64}
            manifest = {'identity': production.IDENTITY, 'node_uid': production.UID,
                        'source_release': release, 'control_plane_recovery': point}
            with patch.object(control, 'recovery', return_value=point) as snapshot, \
                    patch.object(production, 'remote', return_value=manifest) as remote:
                self.assertEqual(production.recovery(None, release), manifest)
            snapshot.assert_called_once_with(None, release, False, node='bulbasaur')
            self.assertEqual(remote.call_args.args[2], '10.0.20.11')
            self.assertTrue(production.BACKUPS[release].endswith('-20261028-a'))
            changed = dict(manifest, control_plane_recovery={})
            with patch.object(control, 'recovery', return_value=point), \
                    patch.object(production, 'remote', return_value=changed), self.assertRaises(RuntimeError):
                production.recovery(None, release)

    def test_cold_monitor_requires_both_survivors_and_refuses_any_live_local_monitor(self):
        profile = monitor.profile_for('bulbasaur')
        self.assertEqual(profile['monitor'], 'l')
        self.assertEqual(profile['receiver'], '10.0.20.11')
        node = {'metadata': {'name': 'bulbasaur', 'uid': profile['node_uid']}, 'spec': {'unschedulable': True}}
        status = {'fsid': monitor.FSID, 'quorum_names': ['o', 'p'],
                  'health': {'status': 'HEALTH_WARN', 'checks': {'MON_DOWN': {}}},
                  'osdmap': {'num_osds': 5, 'num_up_osds': 5, 'num_in_osds': 5},
                  'pgmap': {'pgs_by_state': [{'state_name': 'active+clean'}]}}
        monitor.guard(node, [], status, target='bulbasaur')
        for fault in ('survivor', 'live', 'local'):
            changed, pods = copy.deepcopy(status), []
            if fault == 'survivor': changed['quorum_names'] = ['p']
            if fault == 'live': pods = [{'metadata': {'uid': profile['pod_uid']}, 'spec': {}}]
            if fault == 'local': pods = [{'metadata': {'uid': 'replacement', 'labels': {'app': 'rook-ceph-mon'}},
                                          'spec': {'nodeName': 'bulbasaur'}}]
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                monitor.guard(node, pods, changed, target='bulbasaur')
        for source in (monitor.SOURCE, monitor.READBACK, monitor.RECEIVE):
            compile(monitor.bindings('bulbasaur') + source, 'bulbasaur-monitor', 'exec')

    def test_registry_guard_rejects_movement_restarts_identity_and_storage_changes(self):
        pod = {'metadata': {'uid': 'ee41a015-dec7-47d4-89ac-54ed8100d7fc'},
               'spec': {'nodeName': 'charmander'}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
               'containerStatuses': [{'name': 'zot', 'ready': True, 'restartCount': 0,
               'containerID': 'containerd://c64893596b9e9f4444cf89a84dfd0c8de029bad82f637a0a777f149092d42078'}]}}
        claim = {'metadata': {'uid': '728fbc24-a589-483f-8833-855c863b4f04'}, 'status': {'phase': 'Bound'},
                 'spec': {'volumeName': 'pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6'}}
        volume = {'metadata': {'uid': '81d390a2-71fd-48ac-ac2f-49df07bda484', 'name': claim['spec']['volumeName']},
                  'spec': {'claimRef': {'uid': claim['metadata']['uid']}, 'persistentVolumeReclaimPolicy': 'Retain',
                  'nfs': {'server': '10.0.40.3', 'path': '/mnt/user/heartlib/zot-zot-nfs-pvc-pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6'}}}
        for fault in (None, 'movement', 'restart', 'pod', 'container', 'storage', 'deletion'):
            p, c, v = copy.deepcopy((pod, claim, volume))
            if fault == 'movement': p['spec']['nodeName'] = 'bulbasaur'
            if fault == 'restart': p['status']['containerStatuses'][0]['restartCount'] = 1
            if fault == 'pod': p['metadata']['uid'] = 'new'
            if fault == 'container': p['status']['containerStatuses'][0]['containerID'] = 'new'
            if fault == 'storage': v['spec']['nfs']['path'] = '/different'
            if fault == 'deletion': p['metadata']['deletionTimestamp'] = 'now'
            api = unittest.mock.Mock()
            api.call.side_effect = lambda *args: {'items': [p]} if args[1] == 'pods' else c if args[1] == 'pvc' else v
            if fault is None:
                self.assertEqual(production.protected_registry(api)['restarts'], 0)
            else:
                with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                    production.protected_registry(api)

    def test_kubelet_default_is_enabled_without_overwriting_existing_arguments(self):
        self.assertIn('seccomp-default=true', security.k3s_security_config('snapshotter: stargz\n', 'bulbasaur'))
        with self.assertRaisesRegex(AssertionError, 'review existing kubelet arguments'):
            security.k3s_security_config('kubelet-arg:\n  - existing=true\n', 'bulbasaur')


if __name__ == '__main__':
    unittest.main()
