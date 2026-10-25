"""Package dispatch boundaries; native packages and service manager stay synthetic."""

import copy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_hop_journal as hops
import maintenance_package_dispatch as package
import test_maintenance_hop_journal as journal_tests


class PackageDispatchTests(journal_tests.HopJournalTests):
    def prepare(self, step='prepare_source'):
        for previous in hops.STEPS[:hops.STEPS.index(step)]:
            state = self.begin(previous)
            self.journal.accept(state['pending']['sha256'], 'd' * 64, lambda *_: True)
        return hops.digest(hops.canonical(package.command(self.owner, step)))

    def dispatch(self, step='prepare_source', reviewed=None, verify=lambda *_: True):
        return package.dispatch(self.journal, step, reviewed or self.reviewed, 'c' * 64, verify)

    def test_exact_command_for_every_phase_and_supported_hop(self):
        for source, target in ((39, 41), (41, 43), (43, 44)):
            owner = {**self.owner, 'source': source, 'target': target}
            dnf = '/usr/bin/dnf' if source == 39 else '/usr/bin/dnf5'
            expected = {
                'prepare_source': [dnf, '-y', '--refresh', 'upgrade'],
                'download_release': [dnf, '-y', 'system-upgrade', 'download', '--releasever=' + str(target)],
                'offline_transaction': [dnf, '-y', 'system-upgrade' if source == 39 else 'offline', 'reboot'],
            }
            for step, native in expected.items():
                argv = package.command(owner, step)
                self.assertEqual(argv[argv.index('--') + 1:], native)
                self.assertIn('--service-type=exec', argv)
                self.assertIn('--property=Restart=no', argv)
                self.assertIn('--remain-after-exit', argv)
                self.assertNotIn('--wait', argv)
        for owner, step in (({**self.owner, 'source': 40}, 'prepare_source'),
                            ({**self.owner, 'source': 39.0}, 'prepare_source'),
                            (self.owner, 'drain'), ({**self.owner, 'owner': 'foreign; command'}, 'prepare_source')):
            with self.assertRaises(RuntimeError):
                package.command(owner, step)

    def test_native_source_identity_refuses_before_any_intent(self):
        with patch.object(package.Path, 'read_text', return_value='ID=fedora\nVERSION_ID=39\n'), \
                patch.object(package.socket, 'gethostname', return_value=self.owner['node']), \
                patch.object(package.os, 'geteuid', return_value=0):
            package.require_native(self.owner)
            for owner in ({**self.owner, 'source': 41}, {**self.owner, 'node': 'foreign'}):
                with self.assertRaisesRegex(RuntimeError, 'source host'):
                    package.require_native(owner)
            with patch.object(package.os, 'geteuid', return_value=1000):
                with self.assertRaisesRegex(RuntimeError, 'source host'):
                    package.require_native(self.owner)

    def test_durable_intent_before_one_launch_and_no_automatic_acceptance(self):
        self.reviewed = self.prepare()
        original = copy.deepcopy(self.owner)
        def launch(argv, **kwargs):
            state = self.fresh_journal().read()
            self.assertEqual(state['pending']['step'], 'prepare_source')
            self.assertEqual(argv, package.command(original, 'prepare_source'))
            self.assertFalse(kwargs['check'])
            self.assertEqual(kwargs['cwd'], '/')
            self.assertNotIn('shell', kwargs)
            return SimpleNamespace(returncode=0)
        with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run', side_effect=launch) as run:
            result = self.dispatch()
            self.assertTrue(result['queued'])
            self.assertFalse(result['accepted'])
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                self.dispatch()
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.fresh_journal().inspect()['pending'], result['intent'])
        self.assertEqual(self.api.controller().resume(self.token), original)
        self.assertTrue(self.hold.marker.exists())

    def test_refused_inputs_prerequisites_and_identity_do_not_launch(self):
        self.reviewed = self.prepare()
        before = self.journal.inspect()
        with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'reviewed inputs'):
                self.dispatch(reviewed='e' * 64)
            with self.assertRaisesRegex(RuntimeError, 'prerequisite'):
                self.dispatch(verify=lambda *_: False)
            run.assert_not_called()
        self.assertEqual(self.journal.inspect(), before)
        with patch.object(package, 'require_native', side_effect=RuntimeError('foreign native identity')), \
                patch.object(package.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'native identity'):
                self.dispatch()
            run.assert_not_called()
        self.assertEqual(self.journal.inspect(), before)

    def test_nonzero_launch_keeps_pending_and_cannot_retry(self):
        self.reviewed = self.prepare('download_release')
        with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run',
                                                                 return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                self.dispatch('download_release')
            pending = self.journal.inspect()
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                self.dispatch('download_release')
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.fresh_journal().inspect(), pending)

    def test_native_controller_death_after_dispatch_never_repeats_mutation(self):
        self.reviewed = self.prepare()
        marker = self.root / 'dispatched'
        pid = os.fork()
        if pid == 0:
            def lost_response(*_args, **_kwargs):
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(descriptor, b'one synthetic mutation\n')
                os.fsync(descriptor)
                os.close(descriptor)
                os._exit(73)
            with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run', side_effect=lost_response):
                self.dispatch()
            os._exit(91)
        self.assertEqual(self.wait_child(pid), 73)
        self.assertEqual(marker.read_bytes(), b'one synthetic mutation\n')
        with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                self.dispatch()
            run.assert_not_called()
        fresh = self.fresh_journal()
        pending = fresh.inspect()['pending']
        state = fresh.accept(pending['sha256'], 'd' * 64, lambda *_: marker.read_bytes() == b'one synthetic mutation\n')
        self.assertIn('prepare_source', state['completed'])

    def test_changed_ownership_after_intent_refuses_dispatch(self):
        self.reviewed = self.prepare()
        original = self.journal.begin
        def changed(*args):
            state = original(*args)
            self.api.nodes[0]['metadata']['uid'] = 'replacement'
            return state
        with patch.object(package, 'require_native'), patch.object(self.journal, 'begin', side_effect=changed), \
                patch.object(package.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'identities changed'):
                self.dispatch()
            run.assert_not_called()

    def test_second_native_identity_check_keeps_intent_without_launch(self):
        self.reviewed = self.prepare()
        with patch.object(package, 'require_native', side_effect=[None, RuntimeError('changed native identity')]), \
                patch.object(package.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'changed native'):
                self.dispatch()
            run.assert_not_called()
        self.assertEqual(self.fresh_journal().inspect()['pending']['step'], 'prepare_source')

    def test_launch_holds_native_flock_against_other_controller(self):
        self.reviewed = self.prepare()
        def launch(*_args, **_kwargs):
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
            return SimpleNamespace(returncode=0)
        with patch.object(package, 'require_native'), patch.object(package.subprocess, 'run', side_effect=launch):
            self.dispatch()


if __name__ == '__main__':
    unittest.main()
