"""Synthetic persistence and uncertain-return checks; never run native services."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import maintenance_actor_hold as actors
import maintenance_etcd_cycle as cycle
from test_maintenance_actor_hold import IDENTITY, TOKEN, Systemd


class SourceCycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name);units = self.root / 'units';units.mkdir()
        self.hold = actors.Hold(Systemd(), lambda: dict(IDENTITY), lambda token: token == TOKEN,
                                self.root / 'state', units)
        host = self.hold.acquire(TOKEN, IDENTITY, 'a' * 40)
        self.owner = {'owner': TOKEN, 'component': 'k3s', 'node': 'charmander',
                      'source': 'v1.33.10+k3s1', 'target': 'v1.33.13+k3s2', 'revision': 'a' * 40}
        self.header = {'owners': {'host': host, 'global': self.owner}, 'completed': ['cordon', 'drain'],
                       'pending': {'step': 'check_legacy_etcd', 'sha256': 'b' * 64}}
        self.transactions = self.hold.state / 'transactions';self.transactions.mkdir(mode=0o700)
        self.hop = self.transactions / TOKEN;self.hop.mkdir(mode=0o700)
        previous = None
        for index, (kind, step) in enumerate((('header', None), ('intent', 'cordon'),
                ('accepted', 'cordon'), ('intent', 'drain'), ('accepted', 'drain'),
                ('intent', 'check_legacy_etcd'))):
            value = {'version': 1, 'sequence': index, 'previous': previous, 'kind': kind}
            if index == 0:
                value['owners'] = self.header['owners']
            else:
                value['step'] = step
                value.update({'inputs_sha256': 'd' * 64, 'prerequisites_sha256': 'e' * 64}
                             if kind == 'intent' else
                             {'intent_sha256': previous, 'receipt_sha256': 'f' * 64})
            raw = cycle.hops.canonical(value)
            actors.exclusive_file(self.hop / (str(index).zfill(8) + '.json'), raw, 0o600)
            previous = cycle.hops.digest(raw)
        self.header.update(records=6, head_sha256=previous)
        self.header['pending'].update(sequence=5, sha256=previous)
        self.before = {'version': 'v1.33.10+k3s1', 'boot': 'original-boot', 'pid': 123,
                       'configs': {'original': 'unchanged'}, 'runtime_sha256': 'c' * 64}
        self.native = Mock(return_value='');self.owned = Mock(return_value=True)
        self.proof = {'accepted': True, 'source': self.before['version'],
                      'original_identity': dict(IDENTITY), 'original_boot': self.before['boot']}
        self.worker().initialize()

    def worker(self):
        return cycle.Cycle(self.hold, self.owner, self.header, self.before, self.native, self.owned)

    def stop(self):
        self.worker().dispatch_stop(lambda: True, lambda: self.before)
        with patch.object(cycle.stopped, 'observe', return_value=self.proof):self.worker().observe_stopped()

    def start(self):
        with patch.object(cycle.stopped, 'observe', return_value=self.proof):
            return self.worker().dispatch_start(lambda: True)

    def test_copy_failure_still_allows_one_source_start_and_verified_return(self):
        marker = self.hold.marker.read_bytes();original = copy.deepcopy(self.before)
        self.stop()
        # No copy receipt exists: restoration must remain possible after failed transfer.
        self.start()
        runtime = dict(self.before, pid=456)
        accepted = self.worker().observe_returned(lambda: runtime, lambda: True)
        self.assertEqual(accepted['runtime'], runtime)
        self.assertEqual(self.worker().observe_returned(lambda: runtime, lambda: True), accepted)
        self.assertEqual(self.before, original);self.assertEqual(self.hold.marker.read_bytes(), marker)
        self.assertEqual([call.args for call in self.native.call_args_list],
                         [('systemctl', 'stop', 'k3s'), ('systemctl', 'start', 'k3s')])

    def test_uncertain_stop_and_start_are_observed_without_command_replay(self):
        self.native.side_effect = RuntimeError('lost native response')
        with self.assertRaisesRegex(RuntimeError, 'lost native response'):
            self.worker().dispatch_stop(lambda: True, lambda: self.before)
        self.assertIn('stop-intent.json', self.worker().read())
        with self.assertRaisesRegex(RuntimeError, 'observe only'):
            self.worker().dispatch_stop(lambda: True, lambda: self.before)
        with patch.object(cycle.stopped, 'observe', return_value=self.proof):self.worker().observe_stopped()
        with self.assertRaisesRegex(RuntimeError, 'lost native response'):self.start()
        self.assertIn('start-intent.json', self.worker().read())
        with self.assertRaisesRegex(RuntimeError, 'observe only'):self.start()
        self.worker().observe_returned(lambda: dict(self.before, pid=456), lambda: True)
        self.assertEqual(self.native.call_count, 2)

    def test_failed_quorum_runtime_and_ownership_do_not_dispatch(self):
        for voters, runtime in ((False, self.before), (1, self.before), (True, dict(self.before, pid=456))):
            with self.subTest(voters=voters, runtime=runtime), self.assertRaises(RuntimeError):
                self.worker().dispatch_stop(lambda: voters, lambda: runtime)
        self.native.assert_not_called()
        self.owned.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):self.worker().read()
        self.native.assert_not_called()

    def test_start_requires_observed_stop_and_exact_two_voter_proof(self):
        with self.assertRaises(RuntimeError):self.start()
        self.stop()
        with patch.object(cycle.stopped, 'observe', return_value=self.proof), self.assertRaises(RuntimeError):
            self.worker().dispatch_start(lambda: False)
        self.assertEqual(self.native.call_count, 1)
        with patch.object(cycle.stopped, 'observe', return_value=dict(self.proof, accepted=False)), self.assertRaises(RuntimeError):
            self.worker().dispatch_start(lambda: True)
        self.assertEqual(self.native.call_count, 1)

    def test_return_requires_all_three_voters_and_only_a_new_source_pid(self):
        self.stop();self.start()
        for runtime in (self.before, dict(self.before, pid=0), dict(self.before, pid=456, boot='changed'),
                        dict(self.before, pid=456, version='v1.33.13+k3s2'),
                        dict(self.before, pid=456, runtime_sha256='changed')):
            with self.subTest(runtime=runtime), self.assertRaises(RuntimeError):
                self.worker().observe_returned(lambda: runtime, lambda: True)
        with self.assertRaises(RuntimeError):
            self.worker().observe_returned(lambda: dict(self.before, pid=456), lambda: False)
        self.assertNotIn('source-returned.json', self.worker().read())

    def test_foreign_or_changed_records_preserve_owner_and_refuse(self):
        path = self.worker().path / 'foreign.json';path.write_text('{}');path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'foreign'):self.worker().read()
        path.unlink()
        self.hold.marker.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):self.worker().read()
        self.native.assert_not_called()

    def test_changed_original_hop_refuses_before_service_action(self):
        original = (self.hop / '00000005.json').read_bytes()
        value = cycle.private_json(self.hop / '00000005.json')
        value['inputs_sha256'] = '0' * 64
        (self.hop / '00000005.json').write_bytes(cycle.hops.canonical(value))
        with self.assertRaisesRegex(RuntimeError, 'original pending hop changed'):
            self.worker().dispatch_stop(lambda: True, lambda: self.before)
        self.native.assert_not_called()
        (self.hop / '00000005.json').write_bytes(original)
        actors.exclusive_file(self.hop / '00000006.json', b'{}', 0o600)
        with self.assertRaisesRegex(RuntimeError, 'original hop records changed'):
            self.worker().dispatch_stop(lambda: True, lambda: self.before)
        self.native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
