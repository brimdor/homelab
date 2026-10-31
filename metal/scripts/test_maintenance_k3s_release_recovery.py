"""Exact queued-request recovery; synthetic API, real immutable native journals."""

import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import maintenance_coordination as coordination
import maintenance_k3s_release_recovery as recovery
from maintenance_node_drain import hashed
from maintenance_safe_release import KINDS
import test_maintenance_safe_release as release_tests


class RecoveryTests(unittest.TestCase):
    setUp = release_tests.ReleaseTests.setUp
    fresh_hold = release_tests.ReleaseTests.fresh_hold
    fresh_journal = release_tests.ReleaseTests.fresh_journal
    complete = release_tests.ReleaseTests.complete
    prepare = release_tests.ReleaseTests.prepare
    host = release_tests.ReleaseTests.host

    def fixture(self):
        self.prepare();self.host()
        state = self.worker.read()
        self.worker.append(state, 'global-intent', 'a' * 64)
        for key in (coordination.JOURNAL, coordination.LOCK):
            del self.api.ds['metadata']['annotations'][key]
        self.api.writes += 1
        requested = datetime.now(timezone.utc).isoformat()
        for node in self.api.nodes:
            node['metadata'].update(resourceVersion='1', annotations={recovery.REQUEST: requested, 'keep': 'original'})
            node['status']['nodeInfo'] = {'bootID': node['metadata']['name'] + '-boot'}
        return {'owner': self.owner, 'identity': self.hold.identity(),
                'audit_time': datetime.now(timezone.utc).isoformat(),
                'release_records': {p.name: hashed(recovery.json.loads(p.read_bytes())) for p in self.worker.path.iterdir()},
                'nodes': {n['metadata']['name']: {'uid': n['metadata']['uid'],
                    'boot': n['status']['nodeInfo']['bootID'], 'queued_reboot': requested} for n in self.api.nodes}}

    def recover(self, profile, verify=lambda *_: True, runtime=lambda: True):
        # Fixed closed-window instant; native execution uses the actual clock.
        with patch.object(coordination, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 15, tzinfo=timezone.utc)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            return recovery.recover(self.worker, profile, verify, runtime)

    def test_committed_global_release_is_observed_without_second_global_patch(self):
        profile = self.fixture();spec = copy.deepcopy(self.api.ds['spec'])
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(self.worker.read()['kinds'], list(KINDS))
        self.assertEqual(self.api.writes, 2);self.assertEqual(len(self.api.node_writes), 2)
        self.assertEqual(self.api.ds['spec'], spec)
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(len(self.api.node_writes), 2);self.assertEqual(self.api.writes, 2)

    def test_partial_request_cleanup_resumes_without_repeating_first_patch(self):
        profile = self.fixture();original = self.api.call
        def interrupted(*argv):
            if argv[0] == 'patch' and argv[2] == 'fixture-b':
                raise RuntimeError('connection lost before second node write')
            return original(*argv)
        with patch.object(self.api, 'call', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'connection lost'):
                self.recover(profile)
        self.assertEqual(len(self.api.node_writes), 1)
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(len(self.api.node_writes), 2);self.assertEqual(self.api.writes, 2)

    def test_changed_request_boot_journal_or_returned_owner_refuses(self):
        for change in ('request', 'boot', 'journal', 'owner'):
            self.setUp();profile = self.fixture()
            if change == 'request':self.api.nodes[0]['metadata']['annotations'][recovery.REQUEST] = '2000-01-01T00:00:00Z'
            if change == 'boot':self.api.nodes[0]['status']['nodeInfo']['bootID'] = 'replacement'
            if change == 'journal':profile['release_records']['00000003.json'] = 'b' * 64
            if change == 'owner':self.api.ds['metadata']['annotations'][coordination.LOCK] = '{}'
            with self.subTest(change=change), self.assertRaises(RuntimeError):self.recover(profile)
            self.assertFalse(self.api.node_writes);self.assertEqual(self.api.writes, 2)

    def test_open_window_or_failed_application_safety_refuses_before_cleanup(self):
        profile = self.fixture()
        with patch.object(coordination, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
            with self.assertRaisesRegex(RuntimeError, 'closed reboot window'):
                recovery.recover(self.worker, profile, lambda *_: True, lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'safety refused'):self.recover(profile, lambda *_: False)
        self.assertFalse(self.api.node_writes);self.assertEqual(self.api.writes, 2)

    def test_runtime_change_before_next_patch_stops_and_preserves_pending_receipt(self):
        profile = self.fixture()
        observations = iter([True, True, False])
        with self.assertRaisesRegex(RuntimeError, 'runtime changed'):
            self.recover(profile, runtime=lambda: next(observations))
        self.assertEqual(len(self.api.node_writes), 1)
        self.assertEqual(self.worker.read()['kinds'], list(KINDS[:4]))
        self.assertEqual(self.api.writes, 2)


class FirstPatchTests(unittest.TestCase):
    setUp = RecoveryTests.setUp
    fresh_hold = RecoveryTests.fresh_hold
    fresh_journal = RecoveryTests.fresh_journal
    complete = RecoveryTests.complete
    prepare = RecoveryTests.prepare
    host = RecoveryTests.host

    def fixture(self):
        self.prepare();self.host()
        self.worker.append(self.worker.read(), 'global-intent', 'a' * 64)
        return {'kind': 'unsubmitted-global', 'owner': self.owner, 'identity': self.hold.identity(),
                'release_records': {p.name: hashed(recovery.json.loads(p.read_bytes()))
                                    for p in self.worker.path.iterdir()},
                'nodes': {n['metadata']['name']: {'uid': n['metadata']['uid']} for n in self.api.nodes}}

    def recover(self, profile, verify=lambda *_: True, runtime=lambda: True):
        return recovery.recover_unsubmitted(self.worker, profile, verify, runtime)

    def test_fresh_refusal_then_success_preserves_original_records(self):
        profile = self.fixture()
        original = {p: p.read_bytes() for p in self.worker.path.iterdir()}
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):
            self.recover(profile, verify=lambda *_: False)
        self.assertFalse(list(self.hold.state.glob('release-first-patch-*')))
        self.assertEqual(self.api.writes, 1)
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(self.api.writes, 2)
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(self.api.writes, 2)

    def test_rejected_patch_marker_prevents_another_dispatch(self):
        profile = self.fixture()
        with patch.object(self.api, 'patch', side_effect=RuntimeError('API refused')) as dispatch:
            with self.assertRaisesRegex(RuntimeError, 'API refused'):self.recover(profile)
            with self.assertRaisesRegex(RuntimeError, 'uncertain; observe only'):self.recover(profile)
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.api.writes, 1)
        self.assertEqual(self.worker.read()['kinds'], list(KINDS[:4]))

    def test_lost_committed_response_only_observes_original_intent(self):
        profile = self.fixture();self.api.uncertain = True
        with self.assertRaisesRegex(RuntimeError, 'transport lost'):self.recover(profile)
        self.api.uncertain = False
        self.assertTrue(self.recover(profile)['complete'])
        self.assertEqual(self.api.writes, 2)

    def test_final_safety_refusal_leaves_no_marker(self):
        profile = self.fixture();checks = iter([True, False])
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):
            self.recover(profile, verify=lambda *_: next(checks))
        self.assertFalse(list(self.hold.state.glob('release-first-patch-*')))
        self.assertEqual(self.api.writes, 1)

    def test_changed_runtime_record_identity_or_actor_refuses(self):
        for change in ('runtime', 'record', 'identity', 'actor'):
            self.setUp();profile = self.fixture()
            if change == 'record':profile['release_records']['00000003.json'] = 'b' * 64
            if change == 'identity':profile['identity'] = {'machine': 'foreign', 'root_uuid': 'foreign'}
            if change == 'actor':self.native.active = True
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.recover(profile, runtime=lambda: change != 'runtime')
            self.assertEqual(self.api.writes, 1)

    def test_rpc_only_removes_exact_original_owner(self):
        profile = self.fixture();before = copy.deepcopy(self.api.ds)
        annotations = dict(before['metadata']['annotations'])
        del annotations[coordination.LOCK];del annotations[coordination.JOURNAL]
        operations = [
            {'op': 'test', 'path': '/metadata/uid', 'value': before['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': before['metadata']['resourceVersion']},
            {'op': 'add', 'path': '/metadata/annotations', 'value': annotations}]
        for change in ('uid', 'version', 'unrelated', 'spec'):
            wrong = copy.deepcopy(operations)
            if change == 'uid':wrong[0]['value'] = 'foreign'
            if change == 'version':wrong[1]['value'] = 'stale'
            if change == 'unrelated':wrong[2]['value'] = {}
            if change == 'spec':wrong.append({'op': 'remove', 'path': '/spec'})
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                recovery.global_patch(self.api, profile, before['metadata']['uid'], wrong)
        with patch.object(self.api, 'call') as call:
            recovery.global_patch(self.api, profile, before['metadata']['uid'], operations)
            self.assertEqual(call.call_args.args[:5], ('patch', 'daemonset', 'kured', '-n', 'kured'))
        self.assertEqual(self.api.ds, before)


if __name__ == '__main__':
    unittest.main()
