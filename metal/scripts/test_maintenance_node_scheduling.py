"""Real durable journal/crash boundaries; Kubernetes and systemd are synthetic."""

import copy
import json
import os
import unittest
from unittest.mock import patch

import maintenance_hop_journal as hops
import maintenance_node_scheduling as scheduling
from maintenance_node_drain import hashed
import test_maintenance_hop_journal as journal_tests


class NodeAPI:
    def __init__(self, ownership):
        self.ownership, self.patches = ownership, []
        self.before_patch = None
        self.reject, self.lose_response = False, False

    @property
    def node(self):
        return self.ownership.nodes[0]

    def call(self, *args):
        if args[0] == 'get':
            assert args == ('get', 'node', 'fixture-a', '-o', 'json')
            return copy.deepcopy(self.node)
        assert args[:4] == ('patch', 'node', 'fixture-a', '--type=json')
        assert args[4] == '--patch' and args[6:] == ('-o', 'json')
        operations = json.loads(args[5])
        self.patches.append(operations)
        if self.before_patch:self.before_patch()
        if self.reject:raise RuntimeError('synthetic API access refused')
        candidate = copy.deepcopy(self.node)
        for operation in operations:
            section, field = operation['path'].strip('/').split('/')
            if operation['op'] == 'test':
                if candidate[section][field] != operation['value']:
                    raise RuntimeError('synthetic API precondition conflict')
            else:
                assert operation['op'] == 'add' and operation['path'] == '/spec/unschedulable'
                candidate[section][field] = operation['value']
        candidate['metadata']['resourceVersion'] = str(int(candidate['metadata']['resourceVersion']) + 1)
        # Kubernetes omits a false zero-value spec.unschedulable when serializing a Node.
        if candidate['spec'].get('unschedulable') is False:candidate['spec'].pop('unschedulable')
        self.ownership.nodes[0] = candidate
        if self.lose_response:raise RuntimeError('lost scheduling response after committed patch')
        return copy.deepcopy(candidate)


class SchedulingTests(unittest.TestCase):
    fresh_hold = journal_tests.HopJournalTests.fresh_hold
    fresh_journal = journal_tests.HopJournalTests.fresh_journal
    wait_child = journal_tests.HopJournalTests.wait_child

    def setUp(self):
        journal_tests.HopJournalTests.setUp(self)
        self.api.nodes[0].update(apiVersion='v1', kind='Node', spec={
            'taints': [{'key': 'unrelated', 'value': 'preserve', 'effect': 'PreferNoSchedule'}]})
        self.api.nodes[0]['metadata'].update(resourceVersion='10', annotations={'unrelated': 'preserve'})
        self.nodes = NodeAPI(self.api)
        self.worker = self.fresh()

    def fresh(self):
        return scheduling.Scheduling(self.fresh_journal(), self.nodes)

    def dispatch(self, plan, verify=lambda *_: True):
        return self.worker.dispatch(plan, hashed(plan), 'c' * 64, verify)

    def observe(self, plan, verify=lambda *_: True):
        return self.fresh().observe(plan, 'd' * 64, verify)

    def cordon(self):
        plan = self.worker.plan('cordon')
        self.dispatch(plan)
        self.assertTrue(self.observe(plan)['accepted'])
        return plan

    def restore_ready(self):
        original = self.cordon()
        for step in hops.STEPS[1:hops.STEPS.index('restore_scheduling')]:
            pending = self.journal.begin(step, 'e' * 64, 'f' * 64, lambda *_: True)
            self.journal.accept(pending['pending']['sha256'], 'b' * 64, lambda *_: True)
        return original, self.worker.plan('restore_scheduling', original)

    def test_cordon_then_restore_exact_patches_preserve_holds_and_other_fields(self):
        original_node = copy.deepcopy(self.nodes.node)
        marker = self.hold.marker.read_bytes()
        original, plan = self.restore_ready()
        self.assertEqual(plan['original_cordon'], original)
        self.dispatch(plan)
        result = self.observe(plan)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['journal']['completed'], list(hops.STEPS[:-1]))
        self.assertEqual(len(self.nodes.patches), 2)
        for operations, value, version in zip(self.nodes.patches, [True, False], ['10', '11']):
            self.assertEqual(operations, [
                {'op': 'test', 'path': '/metadata/uid', 'value': 'fixture-a-uid'},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': version},
                {'op': 'add', 'path': '/spec/unschedulable', 'value': value}])
        self.assertEqual(self.nodes.node['spec']['taints'], original_node['spec']['taints'])
        self.assertEqual(self.nodes.node['metadata']['annotations'], original_node['metadata']['annotations'])
        self.assertNotIn('unschedulable', self.nodes.node['spec'])
        self.assertEqual(self.hold.marker.read_bytes(), marker)
        self.assertEqual(self.api.controller().resume(self.token), self.owner)
        self.assertEqual(self.api.writes, 1)

    def test_lost_response_observes_once_without_second_patch_for_each_transition(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                if restore:
                    self.setUp()
                    _, plan = self.restore_ready()
                else:plan = self.worker.plan('cordon')
                count = len(self.nodes.patches)
                self.nodes.lose_response = True
                with self.assertRaisesRegex(RuntimeError, 'lost scheduling response'):
                    self.dispatch(plan)
                self.assertTrue(self.observe(plan)['accepted'])
                self.assertEqual(len(self.nodes.patches), count + 1)
                with self.assertRaisesRegex(RuntimeError, 'pending or out-of-order'):
                    self.dispatch(plan)

    def test_api_rejection_retains_pending_and_observers_never_patch(self):
        plan = self.worker.plan('cordon');self.nodes.reject = True
        with self.assertRaisesRegex(RuntimeError, 'access refused'):self.dispatch(plan)
        state = self.journal.inspect()
        for _ in range(2):self.assertFalse(self.observe(plan)['accepted'])
        self.assertEqual(self.journal.inspect(), state)
        self.assertEqual(len(self.nodes.patches), 1)

    def test_native_child_death_after_intent_before_patch_is_never_replayed(self):
        plan = self.worker.plan('cordon');begin = self.worker.journal.begin
        pid = os.fork()
        if pid == 0:
            def die(*args):begin(*args);os._exit(73)
            try:
                with patch.object(self.worker.journal, 'begin', side_effect=die):self.dispatch(plan)
            except BaseException:os._exit(91)
            os._exit(92)
        self.assertEqual(self.wait_child(pid), 73)
        self.assertFalse(self.observe(plan)['accepted'])
        with self.assertRaisesRegex(RuntimeError, 'pending or out-of-order'):self.dispatch(plan)
        self.assertEqual(self.nodes.patches, [])
        self.assertTrue(self.hold.marker.exists())

    def test_version_race_is_rejected_by_actual_patch_preconditions(self):
        plan = self.worker.plan('cordon')
        self.nodes.before_patch = lambda: self.nodes.node['metadata'].update(resourceVersion='99')
        with self.assertRaisesRegex(RuntimeError, 'precondition conflict'):self.dispatch(plan)
        self.assertFalse(self.observe(plan)['accepted'])
        self.assertEqual(len(self.nodes.patches), 1)

    def test_unrelated_updates_before_dispatch_use_fresh_version_for_each_transition(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                if restore:
                    self.setUp()
                    _, plan = self.restore_ready()
                else:plan = self.worker.plan('cordon')
                reviewed = copy.deepcopy(plan)
                self.nodes.node['metadata'].update(resourceVersion='99', annotations={'other': 'new'})
                self.nodes.node['status']['conditions'][0]['lastHeartbeatTime'] = '2026-10-25T10:00:00Z'
                dispatched = self.dispatch(plan)
                self.assertEqual(dispatched['before']['resource_version'], '99')
                self.assertEqual(self.nodes.patches[-1][1], {
                    'op': 'test', 'path': '/metadata/resourceVersion', 'value': '99'})
                self.assertEqual(plan, reviewed)
                self.assertTrue(self.observe(plan)['accepted'])
                self.assertEqual(self.nodes.node['metadata']['annotations'], {'other': 'new'})
                self.assertEqual(self.nodes.node['status']['conditions'][0]['lastHeartbeatTime'],
                                 '2026-10-25T10:00:00Z')

    def test_changed_identity_deletion_or_scheduling_before_dispatch_never_patches(self):
        for section, field, value in [('metadata', 'uid', 'foreign'),
                                      ('metadata', 'deletionTimestamp', 'now'),
                                      ('spec', 'unschedulable', True)]:
            with self.subTest(field=field):
                self.setUp();plan = self.worker.plan('cordon');original = copy.deepcopy(self.nodes.node)
                self.nodes.node[section][field] = value
                with self.assertRaises(RuntimeError):self.dispatch(plan)
                self.assertEqual(self.nodes.patches, [])
                self.api.nodes[0] = original
                # Ownership can reject a foreign/deleting Node before intent is created.
                if field == 'unschedulable':self.assertIsNotNone(self.journal.read()['pending'])

    def test_initially_cordoned_node_is_not_adopted(self):
        self.nodes.node['spec']['unschedulable'] = True
        with self.assertRaisesRegex(RuntimeError, 'unreviewed scheduling transition'):self.worker.plan('cordon')
        self.assertIsNone(self.journal.inspect()['pending'])

    def test_restore_requires_exact_original_durable_cordon_plan(self):
        original, plan = self.restore_ready()
        for value in (None, dict(original, resource_version='foreign'), dict(original, from_unschedulable=True)):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.worker.plan('restore_scheduling', value)
        forged = copy.deepcopy(plan);forged['original_cordon']['resource_version'] = 'foreign'
        with self.assertRaisesRegex(RuntimeError, 'original cordon differs'):self.dispatch(forged)
        self.assertEqual(len(self.nodes.patches), 1)

    def test_restore_before_infrastructure_acceptance_refuses(self):
        original = self.cordon()
        plan = self.worker.plan('restore_scheduling', original)
        with self.assertRaisesRegex(RuntimeError, 'pending or out-of-order'):self.dispatch(plan)
        self.assertEqual(len(self.nodes.patches), 1)

    def test_prerequisites_fail_before_intent_or_before_patch_without_mutation(self):
        plan = self.worker.plan('cordon')
        with self.assertRaisesRegex(RuntimeError, 'prerequisite'):self.dispatch(plan, lambda *_: False)
        self.assertIsNone(self.journal.inspect()['pending'])
        calls = []
        def changed(*_):calls.append(True);return len(calls) == 1
        with self.assertRaisesRegex(RuntimeError, 'current scheduling prerequisites'):self.dispatch(plan, changed)
        self.assertIsNotNone(self.journal.inspect()['pending'])
        self.assertEqual(self.nodes.patches, [])

    def test_pending_plan_and_reviewed_digest_mismatch_refuse(self):
        plan = self.worker.plan('cordon')
        with self.assertRaisesRegex(RuntimeError, 'reviewed digest'):
            self.worker.dispatch(plan, 'b' * 64, 'c' * 64, lambda *_: True)
        self.dispatch(plan)
        changed = dict(plan, resource_version='99')
        with self.assertRaisesRegex(RuntimeError, 'pending scheduling plan differs'):self.observe(changed)

    def refused_restore(self):
        _, plan = self.restore_ready();calls = []
        def changed(*_):calls.append(True);return len(calls) == 1
        with self.assertRaisesRegex(RuntimeError, 'current scheduling prerequisites'):
            self.dispatch(plan, changed)
        state = self.journal.inspect()
        proof = {'owner': self.token, 'intent_sha256': state['pending']['sha256'],
                 'failure_sha256': 'f' * 64}
        return plan, proof

    def first_restore(self, plan, proof, verify=lambda *_: True):
        return self.worker.dispatch(plan, hashed(plan), 'c' * 64, verify, precheck_proof=proof)

    def test_proven_first_dispatch_uses_fresh_version_and_preserves_journal(self):
        plan, proof = self.refused_restore();pending = self.journal.inspect()
        self.nodes.node['metadata']['resourceVersion'] = '99'
        self.first_restore(plan, proof)
        self.assertEqual(self.journal.inspect(), pending)
        self.assertEqual(self.nodes.patches[-1][1]['value'], '99')
        self.assertEqual(len(self.nodes.patches), 2)
        marker = self.hold.state / ('scheduling-first-dispatch-' + self.token + '.json')
        self.assertEqual(json.loads(marker.read_bytes())['proof'], proof)
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.observe(plan)['accepted'])

    def test_first_dispatch_rejects_foreign_owner_intent_and_bad_failure(self):
        plan, proof = self.refused_restore()
        for key, value in [('owner', 'foreign'), ('intent_sha256', 'a' * 64),
                           ('failure_sha256', 'invalid')]:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'proof differs'):
                self.first_restore(plan, dict(proof, **{key: value}))
        self.assertEqual(len(self.nodes.patches), 1)

    def test_first_dispatch_rechecks_prerequisites_before_arming(self):
        plan, proof = self.refused_restore()
        with self.assertRaisesRegex(RuntimeError, 'current scheduling prerequisites'):
            self.first_restore(plan, proof, lambda *_: False)
        marker = self.hold.state / ('scheduling-first-dispatch-' + self.token + '.json')
        self.assertFalse(marker.exists());self.assertEqual(len(self.nodes.patches), 1)
        self.first_restore(plan, proof)
        self.assertTrue(self.observe(plan)['accepted'])

    def test_first_dispatch_api_failure_never_permits_second_request(self):
        plan, proof = self.refused_restore();self.nodes.reject = True
        with self.assertRaisesRegex(RuntimeError, 'access refused'):self.first_restore(plan, proof)
        self.assertFalse(self.observe(plan)['accepted'])
        with self.assertRaisesRegex(RuntimeError, 'already armed'):self.first_restore(plan, proof)
        self.assertEqual(len(self.nodes.patches), 2)

    def test_first_dispatch_lost_response_observes_without_replay(self):
        plan, proof = self.refused_restore();self.nodes.lose_response = True
        with self.assertRaisesRegex(RuntimeError, 'lost scheduling response'):self.first_restore(plan, proof)
        self.assertTrue(self.observe(plan)['accepted'])
        with self.assertRaisesRegex(RuntimeError, 'proof differs'):self.first_restore(plan, proof)
        self.assertEqual(len(self.nodes.patches), 2)

    def test_actor_becomes_busy_during_verification_refuses_before_patch(self):
        plan = self.worker.plan('cordon');calls = []
        original = self.native.idle
        def busy(marker):
            if len(calls) == 2:raise RuntimeError('synthetic package actor became active')
            return original(marker)
        def verified(*_):calls.append(True);return True
        with patch.object(self.native, 'idle', side_effect=busy):
            with self.assertRaisesRegex(RuntimeError, 'actor became active'):self.dispatch(plan, verified)
        self.assertEqual(self.nodes.patches, [])
        self.assertIsNotNone(self.journal.inspect()['pending'])

    def test_changed_snapshot_or_refused_observation_retains_intent(self):
        plan = self.worker.plan('cordon');self.dispatch(plan);pending = self.journal.inspect()
        with self.assertRaisesRegex(RuntimeError, 'observed hop result'):self.observe(plan, lambda *_: False)
        def changed(*_):self.nodes.node['spec']['unschedulable'] = False;return True
        with self.assertRaisesRegex(RuntimeError, 'observed hop result'):self.observe(plan, changed)
        self.assertEqual(self.journal.inspect(), pending)
        self.assertEqual(len(self.nodes.patches), 1)

    def test_observer_accepts_unrelated_version_updates_without_a_second_patch(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                if restore:
                    self.setUp()
                    _, plan = self.restore_ready()
                else:plan = self.worker.plan('cordon')
                self.dispatch(plan);count = len(self.nodes.patches)
                def changed(*_):
                    self.nodes.node['metadata']['resourceVersion'] = '99'
                    return True
                accepted = self.observe(plan, changed)
                self.assertTrue(accepted['accepted'])
                self.assertEqual(len(self.nodes.patches), count)

    def test_foreign_deleting_or_malformed_node_refuses(self):
        node = copy.deepcopy(self.nodes.node)
        for section, key, value in [('metadata', 'uid', 'foreign'), ('metadata', 'deletionTimestamp', 'now'),
                                    ('metadata', 'resourceVersion', 0), ('spec', 'unschedulable', None),
                                    ('spec', 'unschedulable', 0)]:
            self.api.nodes[0] = copy.deepcopy(node);self.nodes.node[section][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):self.worker.plan('cordon')
        self.assertEqual(self.nodes.patches, [])

    def test_observer_rejects_invalid_digest_and_does_not_dispatch(self):
        plan = self.worker.plan('cordon');self.dispatch(plan)
        with self.assertRaisesRegex(RuntimeError, 'prerequisite digest'):
            self.fresh().observe(plan, 'invalid', lambda *_: True)
        self.assertEqual(len(self.nodes.patches), 1)


if __name__ == '__main__':
    unittest.main()
