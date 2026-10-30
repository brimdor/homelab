"""Composition failures must recover SOURCE without replaying a service intent."""

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import maintenance_etcd_production as production
import maintenance_k3s_contract as contract
import maintenance_production_node as shared


class CompositionTests(unittest.TestCase):
    def test_real_bundle_is_small_and_imports_without_repository_fallback(self):
        import subprocess
        names = (*shared.MODULES, 'maintenance_k3s_contract', 'maintenance_k3s_binary',
                 'maintenance_k3s_production', *production.MODULES)
        bundle = {name: Path(shared.__file__).with_name(name + '.py').read_text() for name in names}
        owner = {'node': 'charmander', 'owner': 'maintenance-owner'}
        source = production.program(bundle, owner, {}, {}, '', 'send', {}, 'a' * 64)
        self.assertNotIn('maintenance_host_security', production.native_bundle(bundle))
        self.assertLess(len(production.command(source)), 90000)
        self.assertLess(len(production.command(production.receiver_program(production.native_bundle(bundle),
            '/protected/point', {'owner': owner}, 'a' * 64, True))), 90000)
        load = ('import sys,types\n' + 'BUNDLE=' + repr(production.native_bundle(bundle)) + '\n' +
                'for name,source in BUNDLE.items():\n module=types.ModuleType(name);sys.modules[name]=module;'
                'exec(compile(source,name+".py","exec"),module.__dict__)\n')
        subprocess.run([production.sys.executable, '-I', '-B', '-'], input=load.encode(),
                       check=True, capture_output=True)

    def test_payload_preflight_failure_never_dispatches_a_stop(self):
        with patch.object(shared, 'remote', return_value={'header.json': {}}) as remote, \
                patch.object(production, 'command', side_effect=RuntimeError('oversized')):
            with self.assertRaisesRegex(RuntimeError, 'oversized'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertEqual(remote.call_count, 2)  # Initial read and finally's original-intent observation.

    def test_payload_preflight_failure_still_recovers_an_already_stopped_source(self):
        operations = []
        def remote(_args, source):
            operation = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'OPERATION')
            operations.append(operation)
            return ({'header.json': {}, 'stop-intent.json': {}, 'stopped.json': {}}
                    if operation == 'resume' else {'accepted': True})
        with patch.object(shared, 'remote', side_effect=remote), \
                patch.object(production, 'command', side_effect=RuntimeError('oversized')):
            with self.assertRaisesRegex(RuntimeError, 'oversized'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertEqual(operations, ['resume', 'resume', 'observe-stopped', 'start'])

    def test_large_sender_stderr_cannot_block_receiver_eof_or_source_recovery(self):
        sender = "import sys;sys.stderr.write('x'*200000+'\\nRuntimeError: synthetic failure\\n');sys.stderr.flush();sys.stdout.write('payload');sys.stdout.flush();sys.exit(1)"
        receiver = "import sys,json;sys.stdin.buffer.read();print(json.dumps({'accepted':True,'source_manifest_sha256':'" + 'a' * 64 + "'}))"
        operations = [];reads = []
        def remote(_args, source):
            operation = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'OPERATION')
            operations.append(operation)
            if operation == 'resume':
                reads.append(True)
                return {'header.json': {}} if len(reads) == 1 else {'stop-intent.json': {}, 'stopped.json': {}}
            if operation == 'manifest':return {'binding': {}, 'point': '/synthetic', 'sha256': 'a' * 64}
            return {'accepted': True}
        def ssh(_args, address=None):
            return [production.sys.executable, '-B', '-c', receiver if address else sender]
        with patch.object(shared, 'remote', side_effect=remote), patch.object(shared, 'ssh', side_effect=ssh):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertEqual(operations.count('start'), 1)
        self.assertEqual(operations[-2:], ['observe-stopped', 'start'])

    def test_completed_native_acceptance_is_returned_without_any_new_command(self):
        receipt = {'original_before': {'pid': 1}, 'accepted': True}
        with patch.object(shared, 'remote', return_value={'legacy_already_accepted': receipt}) as remote:
            self.assertEqual(production.run(None, {'node': 'charmander'}, {}, {}), receipt)
        self.assertEqual(remote.call_count, 1)

    def test_surviving_voter_proof_does_not_reenter_the_cycle_lock(self):
        from types import SimpleNamespace
        context = production.Context.__new__(production.Context)
        context.owner = {'node': 'charmander'};context.native = object()
        context.api = SimpleNamespace(snapshot=lambda: (None, None, [
            {'metadata': {'name': n}, 'status': {'nodeInfo': {'kubeletVersion': production.SOURCE}}}
            for n in production.ENDPOINTS]))
        context.cycle = SimpleNamespace(before={}, header={'owners': {'host': {'identity': {}}}}, guard=lambda: True)
        def quorum(_host, _versions, confirm_stopped):
            self.assertTrue(confirm_stopped());self.assertTrue(confirm_stopped())
        with patch.object(production.quorum, 'native_observe', side_effect=quorum), \
                patch.object(production.cycles.stopped, 'observe', return_value={'accepted': True}) as stopped:
            self.assertTrue(context.voters(stopped=True))
        self.assertEqual(stopped.call_count, 2)

    def test_manifest_failure_still_starts_the_proven_stopped_source_once(self):
        operations = []
        state = {'header.json': {}, 'stop-intent.json': {}, 'stopped.json': {}}
        def remote(_args, source):
            operation = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'OPERATION')
            operations.append(operation)
            if operation == 'resume': return state
            if operation == 'observe-stopped': return {'accepted': True}
            if operation == 'manifest': raise RuntimeError('copy manifest failed')
            if operation == 'start': return {'dispatched_once': True}
            raise AssertionError(operation)
        with patch.object(shared, 'remote', side_effect=remote):
            with self.assertRaisesRegex(RuntimeError, 'copy manifest failed'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertEqual(operations.count('start'), 1)
        self.assertNotIn('stop', operations)

    def test_uncertain_start_is_never_dispatched_again(self):
        operations = []
        state = {'header.json': {}, 'stop-intent.json': {}, 'stopped.json': {}, 'start-intent.json': {}}
        def remote(_args, source):
            operation = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'OPERATION')
            operations.append(operation)
            if operation == 'resume': return state
            if operation == 'plan': raise RuntimeError('inspect original copy')
            raise AssertionError(operation)
        with patch.object(shared, 'remote', side_effect=remote):
            with self.assertRaisesRegex(RuntimeError, 'inspect original copy'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertNotIn('start', operations)
        self.assertNotIn('stop', operations)

    def test_unproven_stop_never_starts_or_copies(self):
        operations = []
        def remote(_args, source):
            operation = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'OPERATION')
            operations.append(operation)
            if operation == 'resume': return {'header.json': {}}
            if operation == 'stop': raise RuntimeError('pre-stop guard refused')
            raise AssertionError(operation)
        with patch.object(shared, 'remote', side_effect=remote):
            with self.assertRaisesRegex(RuntimeError, 'pre-stop guard refused'):
                production.run(None, {'node': 'charmander'}, {}, {})
        self.assertNotIn('start', operations)
        self.assertNotIn('manifest', operations)

    def test_remote_programs_compile_after_decoding(self):
        tree = ast.parse(Path(production.__file__).read_text())
        found = 0
        for n in ast.walk(tree):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                    and any(isinstance(t, ast.Name) and t.id in ('source', 'receive', 'check') for t in n.targets)):
                compile(n.value.value, 'decoded-native-etcd-program', 'exec');found += 1
        self.assertEqual(found, 3)

    def test_returned_pid_cannot_be_used_without_matching_native_cycle_and_hop(self):
        from maintenance_hop_journal import canonical, digest
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); owner = {'owner': 'original'};before = {'version': 'source', 'pid': 10, 'boot': 'same'}
            path = root / 'etcd-cycles/original';path.mkdir(parents=True, mode=0o700)
            returned = {'runtime': dict(before, pid=11)}
            p = path / 'source-returned.json';p.write_bytes(canonical(returned));p.chmod(0o600)
            receipt = {'owner': owner, 'original_before': before, 'accepted': True, 'SOURCE_returned': returned,
                       'cycle_files': {p.name: digest(p.read_bytes())}}
            p = root / 'legacy-accepted-original.json';p.write_bytes(canonical(receipt));p.chmod(0o600)
            hop = root / 'transactions/original';hop.mkdir(parents=True)
            p = hop / '00000006.json';p.write_bytes(canonical({'kind': 'accepted', 'step': 'check_legacy_etcd',
                'receipt_sha256': digest(canonical(receipt))}));p.chmod(0o600)
            hold = SimpleNamespace(state=root)
            self.assertEqual(production.source_baseline(hold, owner, before), returned['runtime'])
            (path / 'source-returned.json').write_bytes(canonical({'runtime': dict(before, pid=12)}))
            with self.assertRaisesRegex(RuntimeError, 'native cycle changed'):
                production.source_baseline(hold, owner, before)


class RecoveryRetryTests(unittest.TestCase):
    def setUp(self):
        from test_maintenance_etcd_cycle import SourceCycleTests
        self.fixture = SourceCycleTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f = self.fixture;f.stop();f.start()
        self.returned = f.worker().observe_returned(lambda: dict(f.before, pid=456), lambda: True)
        self.original = production.files(f.worker().path)
        self.plan_path = f.hold.state / ('legacy-copy-' + f.owner['owner'] + '.json')
        plan = {'point': '/protected/original-point', 'binding': {'owner': f.owner,
                'hop_sha256': f.header['pending']['sha256']}}
        production.actors.exclusive_file(self.plan_path, production.hops.canonical(plan), 0o600)
        self.context = SimpleNamespace(hold=f.hold, owner=f.owner, cycle=f.worker(), retry=None,
            plan_path=self.plan_path, runtime=lambda: self.returned['runtime'], voters=lambda: True, close=lambda: None)

    def prepare(self, expected=None):
        from contextlib import redirect_stdout
        import io
        if expected is None:expected = {'point': '/protected/original-point', 'absent': True}
        with patch.object(production, 'Context', return_value=self.context), redirect_stdout(io.StringIO()):
            production.native_operation(self.fixture.owner, {}, None, None, 'prepare-retry', expected=expected)

    def test_new_cycle_keeps_original_records_and_uses_distinct_intents(self):
        self.prepare();f = self.fixture
        retry = production.recovery_retry(f.hold, f.owner, f.worker(), self.plan_path)
        self.assertEqual(retry['original_cycle_files'], self.original)
        from maintenance_etcd_cycle import Cycle
        worker = Cycle(f.hold, f.owner, f.header, retry['returned_source']['runtime'], f.native, f.owned)
        worker.path = worker.parent / (f.owner['owner'] + production.RETRY_SUFFIX)
        worker.initialize()
        worker.dispatch_stop(lambda: True, lambda: self.returned['runtime'])
        with self.assertRaisesRegex(RuntimeError, 'observe only'):
            worker.dispatch_stop(lambda: True, lambda: self.returned['runtime'])
        self.assertEqual(production.files(f.worker().path), self.original)
        self.assertEqual(f.native.call_count, 3)  # Original stop/start plus one distinct stop.
        with self.assertRaises(RuntimeError):self.prepare()

    def test_committed_partial_foreign_or_unreturned_source_never_creates_retry(self):
        for expected in ({'point': '/protected/original-point', 'absent': False},
                         {'point': '/foreign', 'absent': True}):
            with self.subTest(expected=expected), self.assertRaises(RuntimeError):self.prepare(expected)
        self.context.runtime = lambda: dict(self.returned['runtime'], boot='changed')
        with self.assertRaises(RuntimeError):self.prepare()
        self.assertFalse((self.fixture.hold.state / ('legacy-copy-retry-' + self.fixture.owner['owner'] + '.json')).exists())

    def test_changed_original_cycle_refuses_before_another_service_action(self):
        self.prepare();f = self.fixture
        path = f.worker().path / 'source-returned.json'
        changed = copy.deepcopy(self.returned);changed['runtime']['pid'] = 789
        path.write_bytes(production.hops.canonical(changed))
        with self.assertRaisesRegex(RuntimeError, 'retry binding changed'):
            production.recovery_retry(f.hold, f.owner, f.worker(), self.plan_path)
        self.assertEqual(f.native.call_count, 2)

    def test_final_source_pid_requires_both_unchanged_cycles_and_original_runtime(self):
        self.prepare();f = self.fixture
        retry = production.recovery_retry(f.hold, f.owner, f.worker(), self.plan_path)
        from maintenance_etcd_cycle import Cycle
        worker = Cycle(f.hold, f.owner, f.header, self.returned['runtime'], f.native, f.owned)
        worker.path = worker.parent / (f.owner['owner'] + production.RETRY_SUFFIX)
        worker.initialize();worker.dispatch_stop(lambda: True, lambda: self.returned['runtime'])
        with patch.object(production.cycles.stopped, 'observe', return_value=f.proof):
            worker.observe_stopped();worker.dispatch_start(lambda: True)
        returned = worker.observe_returned(lambda: dict(f.before, pid=789), lambda: True)
        receipt = {'owner': f.owner, 'original_before': f.before, 'accepted': True,
                   'SOURCE_returned': returned, 'cycle_files': production.files(worker.path),
                   'retry_sha256': production.hops.digest(production.hops.canonical(retry))}
        production.actors.exclusive_file(f.hold.state / ('legacy-accepted-' + f.owner['owner'] + '.json'),
                                        production.hops.canonical(receipt), 0o600)
        production.actors.exclusive_file(f.hop / '00000006.json', production.hops.canonical({
            'kind': 'accepted', 'step': 'check_legacy_etcd',
            'receipt_sha256': production.hops.digest(production.hops.canonical(receipt))}), 0o600)
        self.assertEqual(production.source_baseline(f.hold, f.owner, f.before), returned['runtime'])
        for name, value in (('legacy-ownership-', {}), ('legacy-hop-', f.header), ('k3s-before-', f.before)):
            production.actors.exclusive_file(f.hold.state / (name + f.owner['owner'] + '.json'),
                                            production.hops.canonical(value), 0o600)
        with patch.object(production, 'Reader', return_value=SimpleNamespace(close=lambda: None)), \
                patch('maintenance_coordination.Ownership', return_value=SimpleNamespace()), \
                patch.object(production.actors, 'Hold', return_value=f.hold):
            context = production.Context(f.owner, {}, lambda: {}, f.native)
            self.assertEqual(context.cycle.path, worker.path)
            self.assertEqual(context.original_before, f.before)
            context.close()
        path = f.worker().path / 'source-returned.json'
        path.write_bytes(production.hops.canonical({'runtime': dict(f.before, pid=999)}))
        with self.assertRaisesRegex(RuntimeError, 'original failed cycle changed'):
            production.source_baseline(f.hold, f.owner, f.before)


class CephPolicyTests(unittest.TestCase):
    def test_later_stage_requires_exact_zero_prior_and_cipher_policy(self):
        cluster = {'status': {'phase': 'Ready', 'cephx': {'csi': {
            'keyGeneration': 1, 'keyType': 'aes256k', 'keyCephVersion': '20.2.4-0'}}},
            'spec': {'security': {'cephx': {'allowedCiphers': ['aes256k'], 'csi': {
                'keyRotationPolicy': 'KeyGeneration', 'keyGeneration': 1,
                'keepPriorKeyCountMax': 0, 'keyType': 'aes256k'}}}}}
        self.assertTrue(contract.ceph_policy(cluster, contract.VERSIONS[1:3]))
        for key, value in (('allowedCiphers', ['aes', 'aes256k']), ('csi', {'keepPriorKeyCountMax': 1})):
            altered = copy.deepcopy(cluster);altered['spec']['security']['cephx'][key] = value
            self.assertFalse(contract.ceph_policy(altered, contract.VERSIONS[1:3]))
        cluster['status']['cephx']['csi']['priorKeyCount'] = 1
        self.assertFalse(contract.ceph_policy(cluster, contract.VERSIONS[1:3]))
        self.assertTrue(contract.ceph_policy(cluster, contract.VERSIONS[:2]))


if __name__ == '__main__':
    unittest.main()
