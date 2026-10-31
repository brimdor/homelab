"""Real immutable files/flock/process death; host and Kubernetes APIs synthetic."""

import copy
import os
import unittest
from unittest.mock import patch

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_safe_release as release
import test_maintenance_hop_journal as journal_tests


class Systemd:
    """Synthetic idle query permits an absent marker, as the native query does."""
    def __init__(self):
        self.active = False

    def idle(self, _marker):
        if self.active:
            raise RuntimeError('package actor active')


class ReleaseTests(unittest.TestCase):
    fresh_hold = journal_tests.HopJournalTests.fresh_hold
    fresh_journal = journal_tests.HopJournalTests.fresh_journal
    wait_child = journal_tests.HopJournalTests.wait_child

    def setUp(self):
        journal_tests.HopJournalTests.setUp(self)
        self.native = Systemd()
        self.journal = self.fresh_journal()
        self.hold = self.journal.hold
        self.worker = release.Release(self.journal)

    def complete(self, steps=hops.STEPS):
        for step in steps:
            intent = self.journal.begin(step, 'b' * 64, 'c' * 64, lambda *_: True)
            self.journal.accept(intent['pending']['sha256'], 'd' * 64, lambda *_: True)

    def prepare(self):
        self.complete()
        return self.worker.prepare('e' * 64, lambda *_: True)

    def fresh(self):
        return release.Release(self.fresh_journal())

    def host(self, verify=lambda *_: True):
        return self.worker.release_host('f' * 64, verify)

    def global_release(self, verify=lambda *_: True):
        return self.worker.release_global('a' * 64, verify)

    def observe(self, verify=lambda *_: True):
        return self.fresh().observe('b' * 64, verify)

    def test_explicit_complete_release_preserves_journal_guards_and_annotations(self):
        self.prepare()
        journal = {p:p.read_bytes()for p in self.journal.path.iterdir()}
        guards = {p:p.read_bytes()for p in self.units.rglob('*.conf')}
        self.assertFalse(self.host()['complete'])
        self.assertFalse(self.hold.marker.exists())
        self.assertEqual(self.api.controller().resume(self.token), self.owner)
        final = self.global_release()
        self.assertTrue(final['complete']);self.assertFalse(final['mutation_replayed'])
        self.assertEqual(final['state']['kinds'], list(release.KINDS))
        self.assertEqual(self.api.writes, 2)
        self.assertEqual(self.api.ds['metadata']['annotations'], {'unrelated': 'preserve'})
        self.assertEqual({p:p.read_bytes()for p in journal}, journal)
        self.assertEqual({p:p.read_bytes()for p in guards}, guards)
        self.assertTrue(self.observe()['complete'])
        self.assertEqual(self.api.writes, 2)

    def test_every_incomplete_prefix_and_pending_final_step_refuse_preparation(self):
        for count in range(len(hops.STEPS)):
            with self.subTest(count=count):
                if count:self.setUp()
                self.complete(hops.STEPS[:count])
                with self.assertRaisesRegex(RuntimeError, 'every accepted hop'):self.worker.prepare('e'*64, lambda *_: True)
                self.assertFalse(self.worker.path.exists())
        self.journal.begin(hops.STEPS[-1], 'b'*64, 'c'*64, lambda *_: True)
        with self.assertRaisesRegex(RuntimeError, 'every accepted hop'):self.worker.prepare('e'*64, lambda *_: True)
        self.assertTrue(self.hold.marker.exists());self.assertEqual(self.api.writes, 1)

    def test_prepare_refusal_or_bad_digest_never_creates_release_state(self):
        self.complete()
        for digest,verify in [('bad', lambda *_: True), ('e'*64, lambda *_: False)]:
            with self.subTest(digest=digest), self.assertRaises(RuntimeError):self.worker.prepare(digest, verify)
            self.assertFalse(self.worker.path.exists())
        self.assertTrue(self.hold.marker.exists())

    def test_host_then_global_order_and_repeated_dispatch_refuse(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'accepted host release'):self.global_release()
        self.host()
        with self.assertRaisesRegex(RuntimeError, 'observe only'):self.host()
        self.global_release()
        with self.assertRaisesRegex(RuntimeError, 'observe only'):self.global_release()
        self.assertEqual(self.api.writes, 2)

    def test_lost_host_response_observes_absence_without_second_release(self):
        self.prepare();original = self.hold.release
        def lost(*args):original(*args);raise RuntimeError('lost committed host release response')
        with patch.object(self.hold, 'release', side_effect=lost) as dispatch:
            with self.assertRaisesRegex(RuntimeError, 'lost committed'):self.host()
            self.assertEqual(dispatch.call_count, 1)
        self.assertFalse(self.hold.marker.exists())
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:2]))
        self.assertFalse(self.observe()['complete'])
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:3]))
        self.assertEqual(self.api.writes, 1)
        self.assertTrue(self.global_release()['complete'])

    def test_lost_global_response_observes_absence_without_second_patch(self):
        self.prepare();self.host();self.api.uncertain = True
        with self.assertRaisesRegex(RuntimeError, 'transport lost'):self.global_release()
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:4]))
        self.assertTrue(self.observe()['complete'])
        self.assertEqual(self.api.writes, 2)

    def test_native_child_death_after_host_intent_retains_holds_and_never_replays(self):
        self.prepare();pid = os.fork()
        if pid == 0:
            try:
                with patch.object(self.hold, 'release', side_effect=lambda *_: os._exit(73)):self.host()
            except BaseException:os._exit(91)
            os._exit(92)
        self.assertEqual(self.wait_child(pid), 73)
        before = self.worker.read()
        self.assertEqual(before['kinds'], list(release.KINDS[:2]))
        for _ in range(2):self.assertFalse(self.observe()['complete'])
        self.assertEqual(self.worker.read(), before)
        with self.assertRaisesRegex(RuntimeError, 'observe only'):self.host()
        self.assertTrue(self.hold.marker.exists());self.assertEqual(self.api.writes, 1)

    def test_rejected_global_patch_stays_pending_without_replay(self):
        self.prepare();self.host()
        with patch.object(self.api, 'patch', side_effect=RuntimeError('API access refused')) as dispatch:
            with self.assertRaisesRegex(RuntimeError, 'access refused'):self.global_release()
            for _ in range(2):self.assertFalse(self.observe()['complete'])
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:4]))
        self.assertEqual(self.api.writes, 1)

    def test_final_safety_refusal_does_not_create_dispatch_intent(self):
        self.prepare();self.host()
        observations = iter([True, False])
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):
            self.global_release(lambda *_: next(observations))
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:3]))
        self.assertEqual(self.api.writes, 1)
        self.assertTrue(self.global_release()['complete'])
        self.assertEqual(self.api.writes, 2)

    def test_refused_fresh_safety_never_releases_owners_or_accepts_observation(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):self.host(lambda *_: False)
        self.assertEqual(self.worker.read()['kinds'], ['header'])
        self.host()
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):self.global_release(lambda *_: False)
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:3]))
        self.api.uncertain = True
        with self.assertRaisesRegex(RuntimeError, 'transport lost'):self.global_release()
        with self.assertRaisesRegex(RuntimeError, 'safe release evidence'):self.observe(lambda *_: False)
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:4]))

    def test_active_actor_after_host_release_retains_global_owner(self):
        self.prepare();self.host();self.native.active = True
        with self.assertRaisesRegex(RuntimeError, 'actor active'):self.global_release()
        self.assertEqual(self.worker.read()['kinds'], list(release.KINDS[:3]))
        self.assertEqual(self.api.writes, 1)

    def test_host_identity_or_original_hop_hash_change_refuses_after_host_release(self):
        self.prepare();self.host()
        with patch.object(self.hold, 'identity', return_value={'machine': 'foreign', 'root_uuid': 'foreign'}):
            with self.assertRaisesRegex(RuntimeError, 'host identity differs'):self.worker.read()
        path = self.journal.path/'00000018.json'
        raw = path.read_bytes();path.write_bytes(raw.replace(b'dddddddd', b'eeeeeeee', 1))
        with self.assertRaisesRegex(RuntimeError, 'hop record changed'):self.global_release()
        self.assertEqual(self.api.writes, 1)

    def test_guard_foreign_record_or_bad_permissions_refuse(self):
        self.prepare();guard = next(self.units.rglob('*.conf'));original = guard.read_bytes()
        guard.write_bytes(b'foreign')
        with self.assertRaisesRegex(RuntimeError, 'changed maintenance guard'):self.host()
        guard.write_bytes(original)
        path = self.worker.path/'00000000.json';path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'unsafe drain record'):self.worker.read()
        path.chmod(0o600)
        actors.exclusive_file(self.worker.path/'foreign.json', b'{}', 0o600)
        with self.assertRaisesRegex(RuntimeError, 'foreign release records'):self.worker.read()
        self.assertTrue(self.hold.marker.exists())

    def test_returned_host_marker_and_partial_or_foreign_global_owner_refuse(self):
        self.prepare();marker = self.hold.marker.read_bytes();self.host()
        actors.exclusive_file(self.hold.marker, marker, 0o600)
        with self.assertRaisesRegex(RuntimeError, 'released host marker returned'):self.observe()
        self.hold.marker.unlink()
        annotations = copy.deepcopy(self.api.ds['metadata']['annotations'])
        for changed in ({coordination.LOCK: annotations[coordination.LOCK]},
                        dict(annotations, **{coordination.LOCK: '{}'})):
            self.api.ds['metadata']['annotations'] = changed
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):self.observe()
        self.assertEqual(self.api.writes, 1)


if __name__ == '__main__':
    unittest.main()
