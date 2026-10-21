#!/usr/bin/env python3
"""Reject unsafe runtime evidence without running a daemon or using a credential."""

import base64
import copy
import json
import struct
import unittest
from unittest.mock import Mock, patch

import rook_runtime_qualification as subject
from test_rook_native_candidate import inventory


def warning_case():
    stages = [{'name': name, 'generation': generation, 'health': 'HEALTH_OK',
               'objects_verified': 64, 'three_copy_placement_verified': True,
               'resource_uids': ['ceph-uid', 'pool-uid'], 'observed_at': when}
              for name, generation, when in (
                  ('initial', 1, '2026-10-21T19:07:00Z'),
                  ('operator-restart', 1, '2026-10-21T19:08:00Z'),
                  ('daemon-generation-two', 2, '2026-10-21T19:10:00Z'),
                  ('operator-1.21.0', 2, '2026-10-21T19:12:00Z'))]
    events = []
    def event(uid, reason, message, obj, when, reporter, source=None, legacy=False):
        return subject.warning_record({
            'metadata': {'uid': uid}, 'reason': reason, 'message': message,
            'involvedObject': obj, 'reportingComponent': reporter, 'source': source or {},
            'count': 1 if legacy else None, 'firstTimestamp': when if legacy else None,
            'lastTimestamp': when if legacy else None, 'eventTime': None if legacy else when})
    events.append(event('gc-warning', 'InvalidDiskCapacity', 'invalid capacity 0 on image filesystem',
                        {'kind': 'Node', 'name': 'owned-0', 'uid': 'owned-0'},
                        '2026-10-21T19:00:00Z', 'kubelet',
                        {'component': 'kubelet', 'host': 'owned-0'}, legacy=True))
    events.append(event('ip-warning', 'IPAddressWrongReference',
                        'IPAddress: 172.21.0.8 for Service rook-qualification/rook-ceph-mgr '
                        'has a wrong reference; cleaning up',
                        {'kind': 'IPAddress', 'name': '172.21.0.8', 'uid': 'old-ip-uid'},
                        '2026-10-21T19:01:00Z', 'ipallocator-repair-controller'))
    events.append(event('mon-warning', 'ReconcileFailed',
                        'triggering a new reconcile to restart the mon daemons after mon cephx key rotation',
                        {'kind': 'CephCluster', 'namespace': 'rook-qualification',
                         'name': 'rook-qualification', 'uid': 'ceph-uid'},
                        '2026-10-21T19:09:00Z', 'rook-ceph-cluster-controller'))
    uids = {'owned-' + str(n): 'node-uid-' + str(n) for n in range(3)}
    evidence = {'cluster_uid': 'cluster-uid', 'node_uids': uids, 'stages': stages,
                'core_key_changes': subject.core_key_changes(
                    {key: 'before' for key in ('client.admin', 'mon.', 'mgr.a', 'mgr.b',
                                               'osd.0', 'osd.1', 'osd.2')},
                    {key: 'after' for key in ('client.admin', 'mon.', 'mgr.a', 'mgr.b',
                                              'osd.0', 'osd.1', 'osd.2')}),
                'warning_observations': [{'stage': stage['name'], 'events': events[:2] if n < 2 else events}
                                         for n, stage in enumerate(stages)]}
    witness = {'cluster_uid': 'cluster-uid', 'events': events, 'nodes': {
        name: {'uid': uid, 'created': '2026-10-21T19:00:00Z',
               'conditions': [{'type': key, 'status': value} for key, value in (
                   ('Ready', 'True'), ('DiskPressure', 'False'),
                   ('MemoryPressure', 'False'), ('PIDPressure', 'False'))],
               'gc': {'initial_failures': ['2026-10-21T19:00:00.1Z'],
                      'repeated_failures': [], 'successes': ['2026-10-21T19:05:00Z']},
               'image_fs': {'time': '2026-10-21T19:12:10Z', 'capacityBytes': 100,
                            'availableBytes': 50, 'usedBytes': 50, 'inodes': 100, 'inodesFree': 50}}
        for name, uid in uids.items()},
        'services': [{'name': 'rook-ceph-mgr', 'namespace': 'rook-qualification',
                      'uid': 'service-uid', 'ips': ['172.21.0.9']}],
        'addresses': [{'name': '172.21.0.9', 'uid': 'current-ip-uid',
                       'parent': {'resource': 'services', 'namespace': 'rook-qualification',
                                  'name': 'rook-ceph-mgr'}}],
        'observed_at': '2026-10-21T19:12:20Z'}
    return evidence, witness


class RuntimeGuardTests(unittest.TestCase):
    def test_warning_resolution_requires_native_recovery_for_every_exact_event(self):
        evidence, witness = warning_case()
        result = subject.require_warning_resolutions(evidence, witness)
        self.assertEqual({row['warning_uid'] for row in result}, {'gc-warning', 'ip-warning', 'mon-warning'})
        self.assertEqual(len(result), 3)
        self.assertEqual(len(witness['events']), 3)
        for kind in ('unknown', 'wrong-source', 'wrong-count', 'wrong-object', 'series',
                     'no-gc', 'repeated-gc', 'zero-capacity', 'stale-fs', 'node-uid',
                     'node-pressure', 'old-ip', 'orphan-ip', 'duplicate-ip', 'bad-parent',
                     'foreign-service', 'unrotated-key', 'wrong-key-entity', 'old-mon-event',
                     'wrong-cluster', 'missing-object-check', 'missing-stage', 'missing-event'):
            evidence, witness = warning_case()
            gc, ip, mon = witness['events']
            node = witness['nodes']['owned-0']
            if kind == 'unknown':gc['reason'] = 'FailedMount'
            elif kind == 'wrong-source':gc['source']['host'] = 'foreign'
            elif kind == 'wrong-count':gc['count'] = 2
            elif kind == 'wrong-object':mon['object']['uid'] = 'foreign'
            elif kind == 'series':ip['series'] = {'count': 2}
            elif kind == 'no-gc':node['gc']['successes'] = []
            elif kind == 'repeated-gc':node['gc']['repeated_failures'] = ['2026-10-21T19:06:00Z']
            elif kind == 'zero-capacity':node['image_fs']['capacityBytes'] = 0
            elif kind == 'stale-fs':node['image_fs']['time'] = '2026-10-21T19:00:00Z'
            elif kind == 'node-uid':node['uid'] = 'foreign'
            elif kind == 'node-pressure':node['conditions'][1]['status'] = 'True'
            elif kind == 'old-ip':witness['addresses'][0]['uid'] = 'old-ip-uid'
            elif kind == 'orphan-ip':witness['addresses'].append(witness['addresses'][0] | {'name': '172.21.0.7'})
            elif kind == 'duplicate-ip':witness['services'].append(witness['services'][0])
            elif kind == 'bad-parent':witness['addresses'][0]['parent']['resource'] = 'foreign'
            elif kind == 'foreign-service':ip['allocation'][1] = 'foreign'
            elif kind == 'unrotated-key':evidence['core_key_changes'][0]['changed'] = False
            elif kind == 'wrong-key-entity':evidence['core_key_changes'][0]['entity'] = 'foreign'
            elif kind == 'old-mon-event':mon['event_time'] = '2026-10-21T19:01:00Z'
            elif kind == 'wrong-cluster':witness['cluster_uid'] = 'foreign'
            elif kind == 'missing-object-check':evidence['stages'][3]['objects_verified'] = 0
            elif kind == 'missing-stage':evidence['stages'].pop()
            elif kind == 'missing-event':witness['events'] = witness['events'][:-1]
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                subject.require_warning_resolutions(evidence, witness)

    def test_warning_record_and_gc_parser_do_not_retain_private_log_output(self):
        record = subject.warning_record({'metadata': {'uid': 'owned'}, 'message': 'private-output'})
        self.assertNotIn('private-output', json.dumps(record))
        raw = (b'2026-10-21T19:00:00Z private-output\n'
               b'2026-10-21T19:00:01Z Image garbage collection failed once. Stats initialization may not have completed yet\n'
               b'2026-10-21T19:05:01Z Image garbage collection succeeded\n')
        result = subject.image_gc_observation(raw)
        self.assertNotIn('private-output', json.dumps(result))
        self.assertEqual(result['successes'], ['2026-10-21T19:05:01Z'])
        with self.assertRaises(RuntimeError):
            subject.image_gc_observation(b'bad-time Image garbage collection succeeded')
        with self.assertRaises(RuntimeError):
            subject.timestamp('2026-10-21T19:00:00')

    def test_changed_or_vanished_warning_evidence_cannot_be_reinterpreted(self):
        evidence, witness = warning_case()
        witness = copy.deepcopy(witness)
        witness['events'][0]['message_sha256'] = 'changed'
        with self.assertRaises(RuntimeError):
            subject.require_warning_resolutions(evidence, witness)
        witness['events'] = []
        with self.assertRaises(RuntimeError):
            subject.require_warning_resolutions(evidence, witness)

    def test_witness_reads_exact_native_nodes_logs_stats_and_allocations(self):
        evidence, witness = warning_case()
        runner = object.__new__(subject.Qualification)
        runner.identity = Mock()
        runner.cluster_uid, runner.node_uids = evidence['cluster_uid'], evidence['node_uids']
        runner.resource_uids = ('ceph-uid', 'pool-uid')
        runner.evidence = {}
        runner.workloads_ready = Mock()
        runner.storage_ready = Mock(return_value=(
            {'quorum_names': ['a', 'b', 'c']}, [{'size': 3, 'min_size': 2}]))
        cluster = {'metadata': {'uid': 'ceph-uid'}, 'status': {
            'phase': 'Ready', 'ceph': {'health': 'HEALTH_OK'},
            'cephx': {key: {'keyGeneration': 2, 'keyCephVersion': '20.2.4-0'}
                      for key in subject.CORE_KEYS}}}
        nodes = [{'metadata': {'name': name, 'uid': row['uid'], 'creationTimestamp': row['created']},
                  'status': {'conditions': row['conditions']}} for name, row in witness['nodes'].items()]
        stats = {'node': {'runtime': {'imageFs': witness['nodes']['owned-0']['image_fs']}}}
        runner.kubectl = Mock(side_effect=[cluster, {'items': nodes},
                                            json.dumps(stats), json.dumps(stats), json.dumps(stats),
                                            cluster, {'items': []}, {'items': []}, {'items': []}])
        runner.command = Mock(return_value=b'2026-10-21T19:05:00Z Image garbage collection succeeded\n')
        result = runner.warning_witness()
        self.assertEqual(set(result['nodes']), set(evidence['node_uids']))
        self.assertEqual(result['events'], [])
        runner.workloads_ready.assert_called_once_with()
        runner.storage_ready.assert_called_once_with()
        self.assertEqual(runner.command.call_count, 3)
        for call in runner.command.call_args_list:
            self.assertTrue(call.kwargs['combined'])
            self.assertEqual(call.args[0][:3], ['docker', 'logs', '--timestamps'])
        for call in runner.kubectl.call_args_list[2:5]:
            self.assertFalse(call.kwargs['json_output'])
            self.assertIn('/proxy/stats/summary', call.args[1])
        runner.kubectl = Mock(return_value=cluster | {'metadata': {'uid': 'foreign'}})
        runner.command.reset_mock()
        with self.assertRaises(RuntimeError):
            runner.warning_witness()
        runner.command.assert_not_called()

    def test_final_cluster_waits_only_for_healthy_owned_generation_two_progress(self):
        runner = object.__new__(subject.Qualification)
        runner.resource_uids = ('ceph-uid', 'pool-uid')
        cluster = {'metadata': {'uid': 'ceph-uid'}, 'status': {
            'phase': 'Ready', 'ceph': {'health': 'HEALTH_OK'},
            'cephx': {key: {'keyGeneration': 2, 'keyCephVersion': '20.2.4-0'}
                      for key in subject.CORE_KEYS}}}
        progressing = copy.deepcopy(cluster)
        progressing['status']['phase'] = 'Progressing'
        runner.evidence = {}
        runner.kubectl = Mock(side_effect=[progressing, progressing, cluster])
        with patch.object(subject.time, 'sleep') as sleep:
            runner.final_cluster_ready()
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([row['phase'] for row in runner.evidence['final_cluster_observations']],
                         ['Progressing', 'Ready'])
        for field in ('uid', 'phase', 'health', 'generation'):
            invalid = copy.deepcopy(cluster)
            if field == 'uid':invalid['metadata']['uid'] = 'private-output'
            elif field == 'phase':invalid['status']['phase'] = 'private-output'
            elif field == 'health':invalid['status']['ceph']['health'] = 'private-output'
            else:invalid['status']['cephx']['mon']['keyGeneration'] = 1
            runner.evidence = {}
            runner.kubectl = Mock(return_value=invalid)
            with self.subTest(field=field), patch.object(subject.time, 'sleep') as sleep:
                with self.assertRaises(RuntimeError):
                    runner.final_cluster_ready()
                sleep.assert_not_called()
                self.assertEqual(runner.kubectl.call_count, 1)
                self.assertNotIn('private-output', json.dumps(runner.evidence))
        runner.evidence = {}
        runner.kubectl = Mock(return_value=progressing)
        with patch.object(subject.time, 'monotonic', side_effect=[0, 1200]), \
                patch.object(subject.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'did not converge'):
                runner.final_cluster_ready()
            sleep.assert_not_called()

    def test_monitor_key_requires_exact_native_entity_and_modern_key(self):
        key = base64.b64encode(struct.pack('<HIIH', 2, 1, 0, 32) + bytes(32)).decode()
        self.assertEqual(subject.native_monitor_key([{'entity': 'mon.', 'key': key}]), key)
        invalid = [None, {}, [], [{'entity': 'mon.', 'key': key}] * 2,
                   [{'entity': 'client.admin', 'key': key}], [{'entity': 'mon.'}],
                   [{'entity': 'mon.', 'key': b'private-output'}],
                   [{'entity': 'mon.', 'key': 'private-output'}]]
        for rows in invalid:
            with self.subTest(shape=type(rows).__name__), self.assertRaises(RuntimeError) as error:
                subject.native_monitor_key(rows)
            self.assertNotIn('private-output', str(error.exception))
        previous = {name: key for name in ('client.admin', 'mgr.a', 'mgr.b', 'osd.0', 'osd.1', 'osd.2')}
        self.assertFalse(all(row['changed'] for row in subject.core_key_changes(previous, previous)))
        previous['mon.'] = key
        changed = base64.b64encode(struct.pack('<HIIH', 2, 2, 0, 32) + bytes(32)).decode()
        self.assertTrue(all(row['changed'] for row in subject.core_key_changes(
            previous, {name: changed for name in previous})))

    def test_key_change_diagnostic_never_retains_keys_or_foreign_names(self):
        previous = {'client.admin': 'secret-before', 'mon.': 'same-secret',
                    'mgr.a': 'removed-secret', 'foreign-secret-name': 'foreign-secret-value'}
        current = {'client.admin': 'secret-after', 'mon.': 'same-secret', 'osd.0': 'new-secret'}
        rows = subject.core_key_changes(previous, current)
        self.assertEqual(len(rows), 7)
        self.assertTrue(rows[0]['changed'])
        self.assertFalse(rows[1]['changed'])
        self.assertFalse(rows[2]['present_after'])
        self.assertFalse(rows[4]['present_before'])
        self.assertNotIn('secret', json.dumps(rows))
        self.assertTrue(all(type(row['changed']) is bool for row in rows))

    def test_osd_refusal_retains_only_typed_native_fields(self):
        value = {'ok_to_stop': False, 'osds': [0], 'num_ok_pgs': 0, 'num_not_ok_pgs': 1,
                 'bad_become_inactive': ['2.a'], 'foreign': 'private-output-never-retain'}
        result = subject.osd_stop_diagnostic(value, 0)
        self.assertNotIn('foreign', result)
        self.assertNotIn('private-output', str(result))
        for fields in ({'osds': [1]}, {'osds': [False]}, {'ok_to_stop': 0},
                       {'num_not_ok_pgs': True}, {'num_ok_pgs': -1},
                       {'bad_become_inactive': ['private-output']}, {'unknown': '2.a'}):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                subject.osd_stop_diagnostic(value | fields, 0)

    def test_only_exact_native_ebusy_can_supply_pending_safety_evidence(self):
        value = {'ok_to_stop': False, 'osds': [0], 'num_ok_pgs': 0, 'num_not_ok_pgs': 1,
                 'bad_become_inactive': ['2.a'], 'foreign': 'private-output-never-retain'}
        arguments = ['kubectl', 'exec', '--', 'ceph', 'osd', 'ok-to-stop', '0', '-f', 'json']
        runner = object.__new__(subject.Qualification)
        runner.count, runner.env = 0, {}
        child = Mock(returncode=16)
        child.communicate.return_value = (json.dumps(value).encode(), b'unsafe to stop')
        with patch.object(subject.subprocess, 'Popen', return_value=child), \
                self.assertRaises(RuntimeError) as context:
            runner.command(arguments)
        self.assertEqual(context.exception.osd_stop['bad_become_inactive'], ['2.a'])
        self.assertNotIn('private-output', str(context.exception.osd_stop))
        for code, changed in ((13, arguments), (16, arguments[:-3] + ['1', '-f', 'json']),
                              (16, arguments[:-6] + ['ceph', 'auth', 'get', '0', '-f', 'json'])):
            child.returncode = code
            with patch.object(subject.subprocess, 'Popen', return_value=child), \
                    self.assertRaises(RuntimeError) as context:
                runner.command(changed)
            self.assertFalse(hasattr(context.exception, 'osd_stop'))

    def test_osd_convergence_needs_all_three_native_successes_and_preserves_refusal(self):
        runner = object.__new__(subject.Qualification)
        runner.stage, runner.evidence = 'initial', {}
        refusal = RuntimeError('native safety refusal')
        refusal.osd_stop = {'ok_to_stop': False, 'osds': [0], 'num_ok_pgs': 0,
                            'num_not_ok_pgs': 1, 'bad_become_inactive': ['2.a']}
        def safe(osd):
            return {'ok_to_stop': True, 'osds': [osd], 'num_not_ok_pgs': 0}
        runner.ceph = Mock(side_effect=[refusal, safe(1), safe(2), safe(0), safe(1), safe(2)])
        with patch.object(subject.time, 'sleep') as sleep:
            runner.osds_safe()
        self.assertEqual(runner.ceph.call_count, 6)
        sleep.assert_called_once_with(2)
        self.assertEqual(runner.evidence['osd_stop_refusals'][0]['bad_become_inactive'], ['2.a'])
        runner.ceph = Mock(side_effect=RuntimeError('permission refused'))
        with patch.object(subject.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
            runner.osds_safe()
        sleep.assert_not_called()
        runner.ceph = Mock(side_effect=[refusal, safe(1), safe(2)])
        with patch.object(subject.time, 'monotonic', side_effect=[0, 1200]), \
                patch.object(subject.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
            runner.osds_safe()
        sleep.assert_not_called()

    def test_three_copy_profile_preserves_two_copy_quorum_and_original_candidate(self):
        arguments = ('qualification-12345678', 'rook-12345678', inventory())
        original = subject.candidate.resources(*arguments)
        rows = subject.resources(*arguments)
        self.assertEqual(original[3]['spec']['replicated']['size'], 2)
        self.assertEqual(rows[3]['spec']['replicated'], {'size': 3, 'requireSafeReplicaSize': True})
        self.assertEqual(rows[3]['spec']['parameters']['min_size'], '2')
        config = rows[2]['spec']['cephConfig']['global']
        self.assertEqual(config['osd_pool_default_size'], '3')
        self.assertEqual(config['osd_pool_default_min_size'], '2')
        for key, value in config.items():
            self.assertIn(key + ' = ' + value + '\n', rows[1]['data']['config'])
        for key in ('skipUpgradeChecks', 'continueUpgradeAfterChecksEvenIfNotHealthy',
                    'removeOSDsIfOutAndSafeToRemove'):
            self.assertFalse(rows[2]['spec'][key])

    def test_three_copy_objects_require_every_exact_osd_and_matching_up_set(self):
        value = {'pool': 'qualification', 'objname': 'owned', 'acting': [2, 0, 1], 'up': [2, 0, 1]}
        subject.require_three_copy_placement(value, 'owned')
        for fields in ({'pool': 'foreign'}, {'objname': 'foreign'}, {'acting': [0, 1]},
                       {'acting': [0, 1, 1]}, {'acting': [0, 1, 3]},
                       {'acting': [0, True, 2]}, {'up': [0, 1, 2]}, {'acting': None}):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                subject.require_three_copy_placement(value | fields, 'owned')

    def test_rolling_restart_requires_native_osd_safety_acceptance(self):
        value = {'ok_to_stop': True, 'osds': [0], 'num_not_ok_pgs': 0}
        subject.require_osd_stop_safety(value, 0)
        for fields in ({'ok_to_stop': False}, {'ok_to_stop': 1}, {'osds': [1]},
                       {'osds': [0, 1]}, {'osds': [False]}, {'num_not_ok_pgs': 1},
                       {'num_not_ok_pgs': False}):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                subject.require_osd_stop_safety(value | fields, 0)

    def test_final_warning_gate_preserves_findings_from_every_prior_stage(self):
        subject.require_no_warnings([{'stage': name, 'events': []} for name in ('initial', 'final')])
        for rows in ([], [{'stage': 'initial', 'events': [{'reason': 'Failed'}]},
                         {'stage': 'final', 'events': []}]):
            with self.assertRaises(RuntimeError):
                subject.require_no_warnings(rows)

    def test_separate_profile_preserves_upstream_orchestrator_safety_without_changing_original_candidate(self):
        arguments = ('qualification-12345678', 'rook-12345678', inventory())
        original = subject.candidate.resources(*arguments)
        rows = subject.resources(*arguments)
        self.assertEqual(original[2]['spec']['mgr']['modules'], [{'name': 'rook', 'enabled': True}])
        self.assertEqual(rows[2]['spec']['mgr']['modules'], [{'name': 'rook', 'enabled': False}])
        modules = {'enabled_modules': [], 'always_on_modules': ['orchestrator', 'crash'],
                   'force_disabled_modules': []}
        subject.require_disabled_orchestrator(modules, [])
        subject.require_disabled_orchestrator(modules, [{'name': 'mgr/orchestrator/orchestrator', 'value': ''}])
        for changed, configuration in ((modules | {'enabled_modules': ['rook']}, []),
                                        (modules | {'always_on_modules': ['orchestrator', 'rook']}, []),
                                        (modules | {'always_on_modules': []}, []),
                                        (modules | {'force_disabled_modules': ['rook']}, []),
                                        ({}, []),
                                        (modules, [{'name': 'mgr/orchestrator/orchestrator', 'value': 'rook'}]),
                                        (modules, [{'name': 'mgr/orchestrator/orchestrator', 'value': 'cephadm'}]),
                                        (modules, [{'name': 'mgr/orchestrator/a/orchestrator', 'value': 'rook'}])):
            with self.assertRaises(RuntimeError):
                subject.require_disabled_orchestrator(changed, configuration)

    def test_messenger_inspection_requires_every_running_daemon_and_valid_exact_names(self):
        mons = {'mons': [{'name': name} for name in ('a', 'b', 'c')]}
        manager = {'active_name': 'a', 'standbys': [{'name': 'b'}]}
        self.assertEqual(subject.messenger_entities(mons, manager),
                         ['mon.a', 'mon.b', 'mon.c', 'mgr.a', 'mgr.b', 'osd.0', 'osd.1', 'osd.2'])
        for changed_mons, changed_manager in (({'mons': mons['mons'][:2]}, manager),
                                              ({'mons': [{'name': 'a'}] * 3}, manager),
                                              (mons, {'active_name': 'a', 'standbys': []}),
                                              (mons, manager | {'active_name': 'b'}),
                                              (mons, manager | {'active_name': '--foreign'})):
            with self.assertRaises(RuntimeError):
                subject.messenger_entities(changed_mons, changed_manager)

    def test_storage_waits_for_native_convergence_without_weakening_identity_or_health(self):
        healthy = {'fsid': 'owned', 'health': {'status': 'HEALTH_OK', 'checks': {}},
                   'mgrmap': {'available': True},
                   'pgmap': {'pgs_by_state': [{'state_name': 'active+clean'}]}}
        pending = healthy | {'pgmap': {'pgs_by_state': [{'state_name': 'peering'}]}}
        osds = [{'osd': number, 'up': 1, 'in': 1} for number in range(3)]
        pools = [{'pool_name': 'qualification', 'pool_id': 1, 'size': 2, 'min_size': 2}]
        runner = object.__new__(subject.Qualification)
        runner.fsid = None
        runner.evidence = {}
        runner.ceph = Mock(side_effect=[pending, {'osds': osds}, pools,
                                        healthy, {'osds': osds}, pools])
        with patch.object(subject.time, 'sleep') as sleep:
            self.assertEqual(runner.storage_ready(), (healthy, pools))
            sleep.assert_called_once_with(2)
        self.assertEqual(runner.evidence['storage_readiness_polls'], 2)
        for changed in (healthy | {'fsid': 'foreign'},
                        healthy | {'health': {'status': 'HEALTH_WARN', 'checks': {'OSD_DOWN': {}}}}):
            runner.ceph = Mock(side_effect=[changed, {'osds': osds}, pools])
            with self.assertRaises(RuntimeError):
                runner.storage_ready()
        runner.ceph = Mock(side_effect=[pending, {'osds': osds}, pools])
        with patch.object(subject.time, 'monotonic', side_effect=[0, 1200]), self.assertRaises(RuntimeError):
            runner.storage_ready()
        self.assertEqual(runner.evidence['last_storage_observation']['pg_states'], ['peering'])

    def test_native_storage_diagnostic_records_missing_manager_and_pending_pgs_without_raw_output(self):
        status = {'health': {'status': 'HEALTH_OK', 'checks': {}},
                  'pgmap': {'pgs_by_state': [{'state_name': 'peering'}]}}
        osds = [{'osd': number, 'up': 1, 'in': 1} for number in range(3)]
        pools = [{'pool_name': 'qualification', 'pool_id': 1, 'size': 2, 'min_size': 2}]
        result = subject.storage_observation(status, osds, pools)
        self.assertEqual(result['pg_states'], ['peering'])
        self.assertIsNone(result['manager_available'])
        self.assertEqual(result['osds'], osds)
        for changed in (osds[:2], [osds[0] | {'up': 'unknown'}, *osds[1:]]):
            with self.assertRaises(RuntimeError):
                subject.storage_observation(status, changed, pools)
        with self.assertRaises(RuntimeError):
            subject.storage_observation(status | {'pgmap': {'pgs_by_state': [{'state_name': 'unsafe\nraw'}]}},
                                        osds, pools)

    def test_node_visibility_assigns_one_exact_device_and_masks_only_other_owned_raw_paths(self):
        names = ['rook-12345678-' + str(n) for n in range(3)]
        rows = subject.node_layout(inventory(), names)
        self.assertEqual([row['filter'] for row in rows], ['server:0', 'agent:0', 'agent:1'])
        self.assertEqual([row['device']['path'] for row in rows], ['/dev/vdc', '/dev/vdd', '/dev/vde'])
        for row in rows:
            self.assertEqual(set(row['masked']), {'/dev/vdc', '/dev/vdd', '/dev/vde'} - {row['device']['path']})
        changed = inventory()
        changed['blockdevices'][0]['path'] = '/dev/sda'
        with self.assertRaises(RuntimeError):
            subject.node_layout(changed, names)

    def test_apply_handles_consecutive_native_objects_and_refuses_response_identity_drift(self):
        runner = object.__new__(subject.Qualification)
        runner.identity = Mock()
        rows = subject.resources('qualification-12345678', 'rook-12345678', inventory())[:2]
        for raw in (b'\n'.join(json.dumps(row).encode() for row in rows),
                    json.dumps({'kind': 'List', 'items': rows}).encode()):
            runner.kubectl = Mock(return_value=raw)
            self.assertEqual(runner.apply(rows), rows)
            self.assertFalse(runner.kubectl.call_args.kwargs['json_output'])
        for value in (rows[:1], [rows[0], rows[1] | {'metadata': {'name': 'foreign'}}]):
            runner.kubectl = Mock(return_value=json.dumps({'kind': 'List', 'items': value}).encode())
            with self.assertRaises(RuntimeError):
                runner.apply(rows)

    def test_node_device_fields_need_exact_framing_and_all_four_identities(self):
        device = inventory()['blockdevices'][0]
        raw = b'lima-rook-12345678-0\n254:32\n16777216\nfe:20\n'
        self.assertEqual(subject.require_node_device(raw, device)['major_minor'], '254:32')
        for changed in (raw.replace(b'-0\n', b'-0254:32\n', 1), raw.replace(b'fe:20', b'fe:21'),
                        raw.replace(b'16777216', b'4096'), raw + b'extra\n', b'\xff\n'):
            with self.subTest(raw=changed), self.assertRaises(RuntimeError) as context:
                subject.require_node_device(changed, device)
            self.assertIn('actual', context.exception.observation)

    def test_failure_evidence_retains_only_fixed_markers_and_no_output_or_key_hash(self):
        secret = b'synthetic-private-output-never-retain'
        value = subject.command_failure(['/owned/kubectl', 'exec'], 9,
                                        b'Permission denied: ' + secret)
        self.assertEqual(value['markers'], ['permission denied', 'denied'])
        self.assertEqual(set(value), {'executable', 'exit', 'markers', 'raw_output_retained'})
        self.assertNotIn(secret.decode(), str(value))
        self.assertFalse(value['raw_output_retained'])
        self.assertEqual(subject.command_failure(['ceph'], 22, b"Error EINVAL: unrecognized entity 'global'")
                         ['markers'], ['einval', 'unrecognized entity'])

    def test_runtime_requires_every_secure_mode_in_both_configuration_paths(self):
        rows = subject.resources('qualification-12345678', 'rook-12345678', inventory())
        for key in subject.MODES:
            self.assertEqual(rows[2]['spec']['cephConfig']['global'][key], 'secure')
            self.assertIn(key + ' = secure\n', rows[1]['data']['config'])
        self.assertNotIn('keyType', rows[2]['spec']['security']['cephx']['daemon'])
        self.assertTrue(rows[2]['spec']['csi']['skipUserCreation'])

    def test_toolbox_rejects_privilege_host_access_and_secret_mount_mutation(self):
        value = subject.toolbox()
        subject.require_toolbox(value)
        for key, data in [('hostNetwork', True), ('hostPID', True), ('hostIPC', True),
                          ('automountServiceAccountToken', True), ('volumes', [{'hostPath': '/'}]),
                          ('initContainers', [{'name': 'foreign'}])]:
            changed = copy.deepcopy(value)
            changed['spec'][key] = data
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_toolbox(changed)
        for key, data in [('privileged', True), ('readOnlyRootFilesystem', False),
                          ('allowPrivilegeEscalation', True),
                          ('capabilities', {'drop': ['ALL'], 'add': ['SYS_ADMIN']})]:
            changed = copy.deepcopy(value)
            changed['spec']['containers'][0]['securityContext'][key] = data
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_toolbox(changed)

    def test_toolbox_accepts_only_api_false_mount_default_and_reports_field_without_values(self):
        value = subject.toolbox()
        for mount in value['spec']['containers'][0]['volumeMounts']:
            if not mount['readOnly']:
                del mount['readOnly']
        before = copy.deepcopy(value)
        subject.require_toolbox(value)
        self.assertEqual(value, before)
        for number, mount in enumerate(subject.toolbox()['spec']['containers'][0]['volumeMounts']):
            changed = copy.deepcopy(value)
            changed['spec']['containers'][0]['volumeMounts'][number]['readOnly'] = not mount['readOnly']
            with self.subTest(mount=number), self.assertRaises(RuntimeError) as context:
                subject.require_toolbox(changed)
            self.assertEqual(context.exception.observation,
                             {'required_field_mismatch': f'spec.containers.0.volumeMounts.{number}.readOnly'})
        changed = copy.deepcopy(value)
        changed['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']['name'] = 'private-value'
        with self.assertRaises(RuntimeError) as context:
            subject.require_toolbox(changed)
        self.assertNotIn('private-value', str(context.exception.observation))

    def test_all_six_daemon_statuses_must_prove_generation_and_modern_version(self):
        value = {'status': {'cephx': {name: {'keyGeneration': 2, 'keyCephVersion': '20.2.4-0'}
                                     for name in subject.CORE_KEYS}}}
        subject.require_generation(value, 2)
        for name in subject.CORE_KEYS:
            for key, data in [('keyGeneration', 1), ('keyCephVersion', '20.2.3-0'),
                              ('keyType', 'aes')]:
                changed = copy.deepcopy(value)
                changed['status']['cephx'][name][key] = data
                with self.subTest(name=name, key=key), self.assertRaises(RuntimeError):
                    subject.require_generation(changed, 2)
        with self.assertRaises(RuntimeError):
            subject.require_generation({}, 2)

    def test_monitor_cipher_policy_and_every_address_must_be_modern(self):
        cipher = {'name': 'aes256k', 'value': 2}
        value = {'auth_allowed_ciphers': [cipher], 'auth_service_cipher': cipher,
                 'auth_preferred_cipher': cipher,
                 'mons': [{'public_addrs': {'addrvec': [{'type': 'v2'}]}} for _ in range(3)]}
        subject.require_mon_security(value)
        for key, data in [('auth_allowed_ciphers', [cipher, {'name': 'aes', 'value': 1}]),
                          ('auth_service_cipher', {'name': 'aes', 'value': 1}),
                          ('auth_preferred_cipher', {'name': 'aes256k', 'value': 1}),
                          ('mons', value['mons'][:2])]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_mon_security(value | {key: data})
        for addresses in ([], [{'type': 'v1'}], [{'type': 'v2'}, {'type': 'v1'}]):
            changed = copy.deepcopy(value)
            changed['mons'][0]['public_addrs']['addrvec'] = addresses
            with self.assertRaises(RuntimeError):
                subject.require_mon_security(changed)

    def test_osd_evidence_requires_exact_device_fsid_id_and_uuid(self):
        uuid = '12345678-1234-1234-1234-123456789abc'
        row = {'osd_id': 0, 'device': '/dev/vdc', 'ceph_fsid': 'owned', 'osd_uuid': uuid}
        self.assertEqual(subject.require_osd_device({'a': row}, 0, 'owned', '/dev/vdc'), uuid)
        for key, data in [('osd_id', 1), ('device', '/dev/sda'), ('ceph_fsid', 'foreign'),
                          ('osd_uuid', '')]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_osd_device({'a': row | {key: data}}, 0, 'owned', '/dev/vdc')
        with self.assertRaises(RuntimeError):
            subject.require_osd_device({'a': row, 'b': row}, 0, 'owned', '/dev/vdc')
        with self.assertRaises(RuntimeError):
            subject.require_osd_device({'a': row, 'b': row | {'osd_id': 1}}, 0, 'owned', '/dev/vdc')

    def test_completed_pod_needs_exact_successful_job_and_all_container_evidence(self):
        value = {'metadata': {'ownerReferences': [{'kind': 'Job', 'uid': 'owned'}]},
                 'spec': {'restartPolicy': 'OnFailure', 'containers': [{'name': 'main'}],
                          'initContainers': [{'name': 'init'}]},
                 'status': {'phase': 'Succeeded',
                            'containerStatuses': [{'name': 'main', 'state': {'terminated': {'exitCode': 0}}}],
                            'initContainerStatuses': [{'name': 'init', 'state': {'terminated': {'exitCode': 0}}}]}}
        subject.require_pod_completion(value, {'owned'})
        for mutate in (lambda x: x['metadata'].update(ownerReferences=[{'kind': 'Job', 'uid': ''}]),
                       lambda x: x['metadata'].update(deletionTimestamp='now'),
                       lambda x: x['spec'].update(restartPolicy='Always'),
                       lambda x: x['status'].update(containerStatuses=[]),
                       lambda x: x['status'].update(initContainerStatuses=[]),
                       lambda x: x['status']['initContainerStatuses'][0]['state']['terminated'].update(exitCode=1)):
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.assertRaises(RuntimeError):
                subject.require_pod_completion(changed, {'owned'})
        with self.assertRaises(RuntimeError):
            subject.require_pod_completion(value, {'foreign'})

    def test_running_phase_and_ready_condition_are_insufficient_without_running_containers(self):
        value = {'metadata': {}, 'spec': {'containers': [{'name': 'main'}]},
                 'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                            'containerStatuses': [{'name': 'main', 'ready': True,
                                                   'state': {'running': {'startedAt': 'now'}}}]}}
        subject.require_pod_completion(value, set())
        for status in ({'name': 'main', 'ready': False, 'state': {'running': {}}},
                       {'name': 'main', 'ready': True, 'state': {'waiting': {}}},
                       {'name': 'foreign', 'ready': True, 'state': {'running': {'startedAt': 'now'}}}):
            changed = copy.deepcopy(value)
            changed['status']['containerStatuses'] = [status]
            with self.assertRaises(RuntimeError):
                subject.require_pod_completion(changed, set())


if __name__ == '__main__':
    unittest.main()
