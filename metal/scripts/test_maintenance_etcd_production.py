"""Composition failures must recover SOURCE without replaying a service intent."""

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_etcd_production as production
import maintenance_k3s_contract as contract
import maintenance_production_node as shared


class CompositionTests(unittest.TestCase):
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
