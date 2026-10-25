"""Refuse ambiguous native unit outcomes and compile actual guest programs."""

import ast
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fedora_package_dispatch_qualification as qualification


SUCCESS = {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'exited',
           'Result': 'success', 'ExecMainCode': '1', 'ExecMainStatus': '0',
           'InvocationID': 'a' * 32, 'NRestarts': '0'}


class PackageQualificationTests(unittest.TestCase):
    def fixture(self):
        fixture = object.__new__(qualification.Qualification)
        fixture.args = SimpleNamespace(revision='a' * 40)
        fixture.ssh = ['ssh', 'synthetic-only']
        fixture.persist = Mock()
        return fixture

    def test_native_unit_requires_exact_completion_without_restart(self):
        self.assertTrue(qualification.service_complete(SUCCESS))
        running = {**SUCCESS, 'SubState': 'running', 'ExecMainCode': '0'}
        self.assertFalse(qualification.service_complete(running))
        for key, value in (('ExecMainStatus', '1'), ('Result', 'exit-code'), ('ExecMainCode', '2')):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'unit failed'):
                qualification.service_complete({**SUCCESS, key: value})
        for key, value in (('LoadState', 'not-found'), ('InvocationID', ''),
                           ('InvocationID', '0' * 32), ('ActiveState', 'unknown'),
                           ('NRestarts', '1'), ('ActiveState', 'failed'), ('ActiveState', 'inactive')):
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                qualification.service_complete({**SUCCESS, key: value})
        for key in SUCCESS:
            fields = dict(SUCCESS);fields.pop(key)
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                qualification.service_complete(fields)

    def test_read_only_observation_refuses_changed_invocation(self):
        fixture = self.fixture()
        fixture.package_guest = Mock(side_effect=[
            {'unit': {**SUCCESS, 'SubState': 'running', 'ExecMainCode': '0'}, 'failure_journal': None},
            {'unit': {**SUCCESS, 'InvocationID': 'b' * 32}, 'failure_journal': None}])
        with patch.object(qualification.time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'invocation changed'):
            fixture.wait_unit('prepare_source')
        self.assertEqual(fixture.package_guest.call_count, 2)

    def test_failed_unit_retains_native_failure_before_refusal(self):
        fixture = self.fixture()
        evidence = {'unit': {**SUCCESS, 'ActiveState': 'failed', 'Result': 'exit-code',
                             'ExecMainStatus': '1'}, 'failure_journal': 'synthetic native error'}
        fixture.package_guest = Mock(return_value=evidence)
        with self.assertRaisesRegex(RuntimeError, 'unit failed'):
            fixture.wait_unit('download_release')
        fixture.persist.assert_called_once_with('native-package-unit-failure',
                                                phase='download_release', observation=evidence)

    def test_plugin_no_op_verifies_provider_without_inventing_downloads(self):
        fixture = self.fixture()
        history = {'id': 1, 'native_history_sha256': 'a' * 64}
        fixture.history = Mock(side_effect=[history, history])
        fixture.command = Mock()
        fixture.guest = Mock(return_value={'installed_provider': 'synthetic-provider',
                                           'native_rpm_verification_clean': True})
        fixture.signatures = Mock(side_effect=AssertionError('no packages downloaded'))
        fixture.prepare_plugin()
        fixture.signatures.assert_not_called()
        receipt = fixture.persist.call_args.kwargs
        self.assertFalse(receipt['new_transaction'])
        self.assertIsNone(receipt['signatures'])
        self.assertEqual(receipt['no_op_provenance'], 'verified pinned cloud image')
        fixture.command.assert_called_once_with(
            fixture.ssh + ['sudo /usr/bin/dnf -y install dnf-plugin-system-upgrade'])
        self.assertIn("native('rpm','-V',provider)", fixture.guest.call_args.args[0])

    def test_plugin_new_transaction_requires_cache_signatures(self):
        fixture = self.fixture()
        fixture.history = Mock(side_effect=[{'id': 1}, {'id': 2}])
        fixture.command = Mock();fixture.guest = Mock(return_value={'provider': 'synthetic'})
        fixture.signatures = Mock(return_value={'native_signature_verified': True})
        fixture.prepare_plugin()
        fixture.signatures.assert_called_once_with()
        self.assertTrue(fixture.persist.call_args.kwargs['new_transaction'])
        self.assertEqual(fixture.persist.call_args.kwargs['signatures'],
                         {'native_signature_verified': True})
        fixture.signatures = Mock(side_effect=RuntimeError('bad signature'))
        fixture.history = Mock(side_effect=[{'id': 2}, {'id': 3}]);fixture.persist.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'bad signature'):
            fixture.prepare_plugin()
        fixture.persist.assert_not_called()

    def test_plugin_ambiguous_history_or_provider_refuses(self):
        for after in (0, 3):
            fixture = self.fixture()
            fixture.history = Mock(side_effect=[{'id': 1}, {'id': after}])
            fixture.command = Mock();fixture.guest = Mock();fixture.signatures = Mock()
            with self.subTest(after=after), self.assertRaisesRegex(RuntimeError, 'history ambiguously'):
                fixture.prepare_plugin()
            fixture.guest.assert_not_called();fixture.signatures.assert_not_called()
            fixture.persist.assert_not_called()
        fixture = self.fixture()
        fixture.history = Mock(side_effect=[{'id': 1}, {'id': 1}])
        fixture.command = Mock();fixture.guest = Mock(side_effect=RuntimeError('provider verification failed'))
        fixture.signatures = Mock()
        with self.assertRaisesRegex(RuntimeError, 'provider verification failed'):
            fixture.prepare_plugin()
        fixture.signatures.assert_not_called();fixture.persist.assert_not_called()

    def test_actual_complete_guest_programs_compile(self):
        fixture = self.fixture()
        programs = []
        def command(_argv, **kwargs):
            program = kwargs['data'].decode()
            compile(program, '<actual-package-guest>', 'exec')
            programs.append(program)
            if kwargs.get('expected', 0) == 73:
                return b''
            if 'failure_journal' in program:
                return json.dumps({'unit': SUCCESS, 'failure_journal': None}).encode()
            return b'{}'
        fixture.command = command
        fixture.initialize()
        fixture.dispatch('prepare_source', lose_response=True)
        fixture.dispatch('download_release')
        fixture.dispatch('offline_transaction')
        fixture.refuse_replay('prepare_source')
        fixture.wait_unit('prepare_source')
        fixture.history()
        fixture.accept('prepare_source', {'synthetic': True}, 39, copy.deepcopy(SUCCESS))
        fixture.accept('offline_transaction', {'synthetic': True}, 41)
        self.assertEqual(len(programs), 9)
        self.assertIn('os._exit(73)', programs[1])
        self.assertIn("root/'state'", programs[0])
        source = qualification.Path(qualification.__file__).read_text()
        tree = ast.parse(source)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == 'guest' and call.args:
                if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                    compile(qualification.upgrade.GUEST + call.args[0].value, '<actual-direct-guest>', 'exec')


if __name__ == '__main__':
    unittest.main()
