"""Refuse ambiguous native unit outcomes and compile actual guest programs."""

import ast
import copy
import json
from pathlib import Path
import tempfile
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

    def test_history_success_binds_complete_original_output(self):
        output = 'Transaction ID : 12\nEnd time : native-time\nReturn-Code    : Success\nPackages Altered:\n'
        self.assertEqual(qualification.dnf4_history(output),
                         {'id': 12, 'return_code': 'Success',
                          'native_history_sha256': qualification.hashlib.sha256(output.encode()).hexdigest()})

    def test_history_refuses_missing_ambiguous_failed_or_aborted_evidence(self):
        success = 'Transaction ID : 12\nReturn-Code    : Success\n'
        cases = [None, {}, '', 'Transaction ID : 12\n', 'Return-Code : Success\n',
                 success + 'Transaction ID : 13\n', success + 'Return-Code : Success\n',
                 success + 'Return-Code : Failure: 1\n']
        for value in ('Failure: 1', 'Failures: 1, 2', '** Aborted **', 'Unknown', ''):
            cases.append(success.replace('Success', value))
        for value in ('0', '-1', '01', '1..12', '12 extra', ''):
            cases.append(success.replace('ID : 12', 'ID : ' + value))
        for value in cases:
            with self.subTest(output=value), self.assertRaises(RuntimeError):
                qualification.dnf4_history(value)

    def test_actual_history_method_requires_native_success_and_fixed_locale(self):
        fixture = self.fixture()
        fixture.guest = Mock(return_value={'native_history_output': 'Transaction ID : 2\nReturn-Code : Success\n'})
        self.assertEqual(fixture.history()['return_code'], 'Success')
        self.assertIn("os.environ['LC_ALL']='C.UTF-8'", fixture.guest.call_args.args[0])
        fixture.guest.return_value = {'native_history_output': 'Transaction ID : 2\nReturn-Code : Failure: 1\n'}
        with self.assertRaisesRegex(RuntimeError, 'outcome refused'):
            fixture.history()

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
        self.assertEqual(receipt['no_op_provenance'], 'verified installed provider; no new transaction')
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

    def test_actual_run_prepares_plugin_after_source_reboot_and_rebinds_history(self):
        fixture = self.fixture()
        events = []
        backend = {'id': 1, 'boot': 'initial', 'release': 39}
        stable = {'machine': 'synthetic-machine', 'root_uuid': 'synthetic-root',
                  'architecture': 'x86_64'}
        fixture.persist.side_effect = lambda stage, **_values: events.append(stage)
        fixture.prepare = Mock();fixture.wait_ready = Mock();fixture.configure = Mock(return_value={})
        fixture.corpus = Mock(return_value={'synthetic': True})
        fixture.state = lambda *_args: {'identity': {**stable, 'boot': backend['boot']}}
        fixture.repositories = Mock();fixture.initialize = Mock(return_value={})
        fixture.history = lambda: {'id': backend['id']}
        def command(argv):
            self.assertIn('native-updated-source-reboot', events)
            self.assertEqual(argv, fixture.ssh + ['sudo /usr/bin/dnf -y install dnf-plugin-system-upgrade'])
            self.assertEqual(backend['id'], 2)
            backend['id'] = 3
        fixture.command = command
        def guest(program):
            if 'installed_provider' in program:
                return {'installed_provider': 'synthetic-plugin', 'native_rpm_verification_clean': True}
            return {'release': backend['release'], 'boot': backend['boot'], 'offline_pending': False}
        fixture.guest = guest
        def dispatch(step, **_kwargs):
            if step == 'offline_transaction':
                backend.update(id=4, release=41, boot='offline-reboot')
        fixture.dispatch = dispatch
        fixture.refuse_replay = Mock(return_value={})
        def wait_unit(step):
            if step == 'prepare_source':backend['id'] = 2
            return copy.deepcopy(SUCCESS)
        fixture.wait_unit = wait_unit
        fixture.signatures = Mock(return_value={'native_signature_verified': True})
        fixture.accept = Mock(return_value={})
        fixture.checkpoint = lambda _name: backend.update(boot='updated-source-reboot')
        fixture.identity = lambda: {**stable, 'boot': backend['boot']}
        fixture.server = SimpleNamespace(errors=[])
        fixture.result = {}
        with tempfile.TemporaryDirectory(prefix='package-run-') as directory:
            fixture.root = Path(directory)
            result = fixture.run()
            self.assertTrue(result['accepted'])
            self.assertTrue((fixture.root / 'upgrade-result.json').is_file())
        self.assertEqual(backend['id'], 4)
        self.assertEqual([call.args[0] for call in fixture.accept.call_args_list],
                         ['prepare_source', 'download_release', 'offline_transaction'])
        self.assertEqual(fixture.signatures.call_count, 4)
        backend.update(id=1, boot='initial', release=39)
        events.clear();fixture.accept.reset_mock();fixture.persist.reset_mock()
        fixture.server.errors = [{'error': 'synthetic recorded transport failure'}]
        fixture.result = {}
        with tempfile.TemporaryDirectory(prefix='package-refusal-') as directory:
            fixture.root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'repository transport reported a failure'):
                fixture.run()
            self.assertFalse((fixture.root / 'upgrade-result.json').exists())
        self.assertIn('native-offline-transaction-observed', events)
        self.assertNotIn('native-offline-transaction-accepted', events)
        self.assertEqual([call.args[0] for call in fixture.accept.call_args_list],
                         ['prepare_source', 'download_release'])
        self.assertNotIn('accepted', fixture.result)

    def test_actual_prerequisite_resolves_capability_and_refuses_missing_provider(self):
        node = next(node for node in ast.parse(qualification.CONTEXT).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'prerequisites')
        available = True
        calls = []
        def native(*argv):
            calls.append(argv)
            if argv == ('rpm', '-E', '%fedora'):return '39'
            if argv == ('rpm', '-q', '--whatprovides', 'dnf-plugin-system-upgrade') and available:
                return 'synthetic-provider'
            raise RuntimeError('installed capability unavailable')
        def path(name):
            if name == '/etc/dnf/dnf.conf':
                return SimpleNamespace(read_bytes=lambda: b'gpgcheck=True\nlocalpkg_gpgcheck=True\n')
            return SimpleNamespace(read_text=lambda: '1' if name.endswith('/enforce') else 'synthetic-boot')
        scope = {'pathlib': SimpleNamespace(Path=path), 'native': native,
                 'identity': lambda: {'synthetic': True}, 'hashlib': qualification.hashlib,
                 'subprocess': SimpleNamespace(run=lambda *_args, **_kwargs:
                                               SimpleNamespace(returncode=1, stdout=b'masked'))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-prerequisites>', 'exec'), scope)
        for phase in ('download_release', 'offline_transaction'):
            self.assertTrue(scope['prerequisites']({'owner': 'synthetic'}, phase)['enforcing'])
        self.assertEqual(calls.count(('rpm', '-q', '--whatprovides', 'dnf-plugin-system-upgrade')), 2)
        available = False
        with self.assertRaisesRegex(RuntimeError, 'capability unavailable'):
            scope['prerequisites']({'owner': 'synthetic'}, 'download_release')

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
            if 'native_history_output' in program:
                return json.dumps({'native_history_output': 'Transaction ID : 1\nReturn-Code : Success\n'}).encode()
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
