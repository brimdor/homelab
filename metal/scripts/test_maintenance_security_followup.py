"""Real immutable journal files; synthetic ownership, scheduling and native APIs."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_host_security as security
import maintenance_node_drain as drain
import maintenance_production_node as production
import maintenance_safe_release as release
from test_maintenance_actor_hold import IDENTITY, Systemd as ActorSystemd
from test_maintenance_coordination import API
from test_maintenance_safe_release import Systemd


class SecurityFollowupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.api = API()
        self.api.nodes[0]['metadata']['name'] = 'totodile'
        self.api.pods[0]['spec']['nodeName'] = 'totodile'
        self.owner = self.api.controller().acquire('totodile', 44, 44, 'a' * 40)
        self.units = self.root / 'units'
        self.units.mkdir()
        self.hold = actors.Hold(ActorSystemd(), lambda: dict(IDENTITY),
            lambda token: self.api.controller().resume(token) == self.owner,
            self.root / 'state', self.units)
        self.hold.acquire(self.owner['owner'], IDENTITY, 'a' * 40)
        self.hold.systemd = Systemd()
        self.journal = hops.Journal(self.api.controller(), self.hold, self.owner['owner'])
        self.journal.initialize()

    def test_security_receipt_spacing_never_weakens_drain_record_format(self):
        path = self.root / 'security.json'
        value = {'owner': self.owner['owner'], 'identity': IDENTITY}
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        checksum = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(RuntimeError, 'noncanonical drain record'):
            drain.private_json(path)
        self.assertEqual(drain.private_json(path, security_receipt=True), value)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), checksum)
        for damaged in (raw + b'\n', json.dumps(value, indent=2).encode(), hops.canonical(value)):
            path.write_bytes(damaged)
            with self.assertRaisesRegex(RuntimeError, 'noncanonical drain record'):
                drain.private_json(path, security_receipt=True)
        path.write_bytes(raw)
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'unsafe drain record'):
            drain.private_json(path, security_receipt=True)

    def test_distinct_security_sequence_never_accepts_fake_upgrade_or_early_release(self):
        worker = release.Release(self.journal)
        with self.assertRaises(RuntimeError):
            self.journal.begin('prepare_source', 'b' * 64, 'c' * 64, lambda *_: True)
        with self.assertRaises(RuntimeError):
            worker.prepare('b' * 64, lambda *_: True)
        for step in hops.SECURITY_STEPS:
            pending = self.journal.begin(step, 'b' * 64, 'c' * 64, lambda *_: True)
            self.journal.accept(pending['pending']['sha256'], 'd' * 64, lambda *_: True)
        self.assertEqual(self.journal.inspect()['completed'], list(hops.SECURITY_STEPS))
        worker.prepare('e' * 64, lambda *_: True)
        worker.release_host('f' * 64, lambda *_: True)
        result = worker.release_global('a' * 64, lambda *_: True)
        self.assertTrue(result['complete'])
        self.assertFalse(result['mutation_replayed'])
        self.assertEqual(self.api.ds['metadata']['annotations'], {'unrelated': 'preserve'})
        self.assertEqual(len(result['state']['header']['hop_records']), 15)

    def test_only_reviewed_node_and_exact_integer_hops(self):
        for node, source, target in [('growlithe', 44, 44), ('bulbasaur', 44, 44),
                                     ('totodile', 44, 45), ('totodile', True, 44)]:
            self.assertFalse(coordination.reviewed_hop(node, source, target))
        self.assertTrue(coordination.reviewed_hop('totodile', 44, 44))
        self.assertTrue(coordination.reviewed_hop('pikachu', 44, 44))
        self.assertTrue(coordination.reviewed_hop('squirtle', 44, 44))
        self.assertEqual(hops.steps({'node': 'squirtle', 'source': 44, 'target': 44}), hops.SECURITY_STEPS)
        self.assertEqual(hops.steps({'node': 'pikachu', 'source': 44, 'target': 44}), hops.SECURITY_STEPS)
        self.assertEqual(hops.steps({'node': 'fixture-a', 'source': 43, 'target': 44}), hops.STEPS)

    def test_pikachu_prior_receipts_and_historical_repair_are_exact(self):
        self.assertNotEqual(security.default_profile('pikachu')['owner'], security.default_profile('totodile')['owner'])
        with self.assertRaises(AssertionError): security.default_profile('bulbasaur')
        record = {'type': 'AVC', 'comm': 'sporecast-backe', 'denied': ['lock'], 'permissive': '0',
                  'scontext': 'system_u:system_r:container_t:s0:c599,c776', 'tclass': 'file',
                  'tcontext': 'system_u:object_r:container_file_t:s0:c317,c677', 'timestamp': 1793131965.0}
        self.assertTrue(security.default_audit_resolved(record, 'pikachu'))
        self.assertFalse(security.default_audit_resolved(record, 'totodile'))
        for key, value in [('timestamp', 1793132061.1), ('timestamp', float('inf')), ('comm', 'different'),
                           ('scontext', 'system_u:system_r:container_t:s0:c317,c677'), ('denied', ['write']),
                           ('tcontext', 'system_u:object_r:container_file_t:s0:c1,c2'), ('permissive', '1')]:
            changed = dict(record); changed[key] = value
            with self.subTest(key=key): self.assertFalse(security.default_audit_resolved(changed, 'pikachu'))
        del record['timestamp']; self.assertFalse(security.default_audit_resolved(record, 'pikachu'))

    def test_configuration_preserves_original_and_refuses_existing_arguments(self):
        before = 'selinux: true\nsnapshotter: stargz\n'
        with patch.object(security, 'DEFAULT_CONFIG_SHA256', hashlib.sha256(before.encode()).hexdigest()):
            self.assertEqual(security.default_config(before), before + 'kubelet-arg:\n  - seccomp-default=true\n')
            with self.assertRaises(AssertionError):
                security.default_config(before + 'debug: true\n')
        before += 'kubelet-arg:\n  - existing=true\n'
        with patch.object(security, 'DEFAULT_CONFIG_SHA256', hashlib.sha256(before.encode()).hexdigest()):
            with self.assertRaises(AssertionError):
                security.default_config(before)

    def test_squirtle_config_cannot_use_a_worker_configuration_or_foreign_prior_receipts(self):
        profile = security.default_profile('squirtle')
        self.assertEqual(profile['owner'], 'homelab-maintenance-103-929029ce-3dc6-4f06-89cd-578a342f678e')
        self.assertEqual(profile['proofs']['host-enforce-'], '863eb6fbd29b690d4d9f8b1b6c31187c0eefefd2f3275d6a4c753546f3d09bb0')
        self.assertEqual(profile['release'], 'ffda155e4a4c8acc91ce6cc20c48a61bd3c4189ad1bb52c68e86376eda39c312')
        worker = 'selinux: true\nsnapshotter: stargz\n'
        with patch.object(security, 'DEFAULT_CONFIG_SHA256', hashlib.sha256(worker.encode()).hexdigest()):
            self.assertIn('seccomp-default=true', security.default_config(worker, 'pikachu'))
            with self.assertRaisesRegex(AssertionError, 'review changed'):
                security.default_config(worker, 'squirtle')
        with self.assertRaisesRegex(AssertionError, 'unreviewed'):
            security.default_config(worker, 'unknown')

    def test_pending_allowance_requires_exact_owner_unscheduled_and_never_a_failed_runtime(self):
        item = {'kind': 'Deployment', 'metadata': {'namespace': 'test', 'name': 'main', 'uid': 'deployment'},
                'spec': {'selector': {'matchLabels': {'app': 'main'}},
                         'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': 'totodile'}}}}}
        pod = {'metadata': {'labels': {'app': 'main'}, 'ownerReferences': [
            {'controller': True, 'kind': 'ReplicaSet', 'name': 'main-rs', 'uid': 'replica'}]},
            'spec': copy.deepcopy(item['spec']['template']['spec']), 'status': {'phase': 'Pending'}}
        replica = {'metadata': {'uid': 'replica', 'ownerReferences': [
            {'controller': True, 'kind': 'Deployment', 'name': 'main', 'uid': 'deployment'}]}}
        class PendingAPI:
            def call(self, *argv):
                return {'items': [pod]} if argv[1] == 'pods' else replica
        api = PendingAPI()
        self.assertTrue(production.pending_on_maintained_node(api, item, 'totodile'))
        for mutation in (
            lambda: pod['spec'].update(nodeName='totodile'),
            lambda: pod['status'].update(phase='Failed'),
            lambda: pod['status'].update(containerStatuses=[{'ready': False}]),
            lambda: pod['metadata'].update(deletionTimestamp='now'),
            lambda: replica['metadata']['ownerReferences'][0].update(uid='foreign'),
        ):
            original = copy.deepcopy((pod, replica))
            mutation()
            self.assertFalse(production.pending_on_maintained_node(api, item, 'totodile'))
            pod.clear(); pod.update(original[0]); replica.clear(); replica.update(original[1])


if __name__ == '__main__':
    unittest.main()
