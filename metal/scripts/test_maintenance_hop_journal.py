"""Synthetic native persistence/process tests; no package, Node or release operation."""

import copy
import json
import os
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import patch

import maintenance_actor_hold as actors
import maintenance_hop_journal as hops
from test_maintenance_actor_hold import IDENTITY, Systemd
from test_maintenance_coordination import API


class HopJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = API()
        self.owner = self.api.controller().acquire('fixture-a', 39, 41, 'a' * 40)
        self.token = self.owner['owner']
        self.native = Systemd()
        self.units = self.root / 'units'
        self.units.mkdir()
        self.hold = self.fresh_hold()
        self.hold.acquire(self.token, IDENTITY, 'a' * 40)
        self.journal = self.fresh_journal()
        self.journal.initialize()

    def fresh_hold(self):
        def verify(token):
            return self.api.controller().resume(token) == self.owner
        return actors.Hold(self.native, lambda: dict(IDENTITY), verify, self.root / 'state', self.units)

    def fresh_journal(self):
        return hops.Journal(self.api.controller(), self.fresh_hold(), self.token)

    def begin(self, step='cordon'):
        return self.journal.begin(step, 'b' * 64, 'c' * 64, lambda _step, _hash: True)

    def wait_child(self, pid):
        reaped = False
        try:
            end = time.monotonic() + 10
            while time.monotonic() < end:
                found, status = os.waitpid(pid, os.WNOHANG)
                if found:
                    reaped = True
                    return os.waitstatus_to_exitcode(status)
                time.sleep(.01)
            self.fail('owned synthetic child did not finish')
        finally:
            if not reaped:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(pid, 0)

    def test_complete_order_fresh_resume_preserves_global_host_and_guards(self):
        before = copy.deepcopy(self.api.ds)
        marker = self.hold.marker.read_bytes()
        guards = {p: p.read_bytes() for p in self.units.rglob('*.conf')}
        for step in hops.STEPS:
            state = self.begin(step)
            self.assertEqual(self.fresh_journal().inspect(), state)
            state = self.fresh_journal().accept(state['pending']['sha256'], 'd' * 64,
                                              lambda observed, receipt: observed == step and receipt == 'd' * 64)
            self.assertIsNone(state['pending'])
        self.assertEqual(state['completed'], list(hops.STEPS))
        with self.assertRaisesRegex(RuntimeError, 'pending or out-of-order'):
            self.begin()
        self.assertEqual(self.api.ds, before)
        self.assertEqual(self.hold.marker.read_bytes(), marker)
        self.assertEqual({p: p.read_bytes() for p in guards}, guards)
        self.assertEqual(self.api.writes, 1)

    def test_pending_and_out_of_order_never_replay(self):
        with self.assertRaisesRegex(RuntimeError, 'out-of-order'):
            self.begin('offline_transaction')
        state = self.begin()
        for step in ('cordon', 'drain'):
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                self.begin(step)
        self.assertEqual(self.fresh_journal().inspect(), state)
        with self.assertRaisesRegex(RuntimeError, 'exact pending'):
            self.journal.accept('e' * 64, 'd' * 64, lambda *_: True)
        self.assertEqual(self.journal.inspect(), state)

    def test_rejected_prerequisite_or_observation_leaves_exact_evidence(self):
        state = self.journal.inspect()
        with self.assertRaisesRegex(RuntimeError, 'prerequisite'):
            self.journal.begin('cordon', 'b' * 64, 'c' * 64, lambda *_: False)
        self.assertEqual(self.journal.inspect(), state)
        state = self.begin()
        with self.assertRaisesRegex(RuntimeError, 'observed hop'):
            self.journal.accept(state['pending']['sha256'], 'd' * 64, lambda *_: False)
        self.assertEqual(self.fresh_journal().inspect(), state)

    def test_lost_response_after_native_commit_is_observed_without_replay(self):
        append = self.journal.append
        def uncertain(record):
            append(record)
            raise RuntimeError('lost response after native durable commit')
        with patch.object(self.journal, 'append', side_effect=uncertain), self.assertRaisesRegex(RuntimeError, 'lost response'):
            self.begin()
        fresh = self.fresh_journal()
        state = fresh.inspect()
        self.assertEqual(state['records'], 2)
        self.assertEqual(state['pending']['step'], 'cordon')
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            fresh.begin('cordon', 'b' * 64, 'c' * 64, lambda *_: True)
        def uncertain_acceptance(record):
            append(record)
            raise RuntimeError('lost acceptance response')
        with patch.object(fresh, 'append', side_effect=uncertain_acceptance):
            with self.assertRaisesRegex(RuntimeError, 'lost acceptance'):
                fresh.accept(state['pending']['sha256'], 'd' * 64, lambda *_: True)
        state = self.fresh_journal().inspect()
        self.assertEqual(state['completed'], ['cordon'])
        self.assertIsNone(state['pending'])
        with self.assertRaisesRegex(RuntimeError, 'exact pending'):
            self.fresh_journal().accept('e' * 64, 'd' * 64, lambda *_: True)

    def test_native_child_death_keeps_intent_and_releases_flock_only(self):
        pid = os.fork()
        if pid == 0:
            try:
                self.begin()
            except BaseException:
                os._exit(91)
            os._exit(73)
        self.assertEqual(self.wait_child(pid), 73)
        fresh = self.fresh_journal()
        state = fresh.inspect()
        self.assertEqual(state['pending']['step'], 'cordon')
        self.assertTrue(self.hold.marker.exists())
        self.assertEqual(self.api.controller().resume(self.token), self.owner)
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            self.begin()

    def test_native_cross_process_lock_excludes_second_controller(self):
        with self.hold.serialized():
            pid = os.fork()
            if pid == 0:
                try:
                    self.fresh_journal().inspect()
                except BlockingIOError:
                    os._exit(42)
                except BaseException:
                    os._exit(91)
                os._exit(92)
            self.assertEqual(self.wait_child(pid), 42)
        self.assertEqual(self.fresh_journal().inspect()['records'], 1)

    def test_changed_host_owner_revision_guard_and_active_actor_refuse(self):
        state = self.journal.inspect()
        with patch.object(self.journal.hold, 'identity', return_value={**IDENTITY, 'machine': 'replacement'}):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.begin()
        self.native.active = True
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.begin()
        self.native.active = False
        path = self.journal.path / '00000000.json'
        original = path.read_bytes()
        self.hold.marker.write_text(json.dumps({**json.loads(self.hold.marker.read_bytes()), 'revision': 'b' * 40}))
        with self.assertRaisesRegex(RuntimeError, 'revisions differ'):
            self.begin()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(state['records'], 1)

    def test_corruption_permissions_link_sequence_and_foreign_files_refused(self):
        path = self.journal.path / '00000000.json'
        original = path.read_bytes()
        for data in [b'{', b'null', original + b'\n', original.replace(b'"sequence":0', b'"sequence":1')]:
            path.write_bytes(data)
            with self.assertRaises((RuntimeError, ValueError)):
                self.journal.inspect()
        path.write_bytes(original)
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'unsafe hop record'):
            self.journal.inspect()
        path.chmod(0o600)
        link = self.journal.path / 'extra'
        os.link(path, link)
        with self.assertRaises(RuntimeError):
            self.journal.inspect()
        link.unlink()
        path.unlink()
        target = self.root / 'external'
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaises(OSError):
            self.journal.inspect()
        self.assertEqual(target.read_bytes(), original)

    def test_owner_change_during_callback_refuses_and_never_appends(self):
        before = list(self.journal.path.iterdir())
        def changed(*_):
            self.api.nodes[0]['metadata']['uid'] = 'replacement'
            return True
        with self.assertRaisesRegex(RuntimeError, 'identities changed'):
            self.journal.begin('cordon', 'b' * 64, 'c' * 64, changed)
        self.assertEqual(list(self.journal.path.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
