#!/usr/bin/env python3
"""Protect legacy-transition isolation, metadata and original data identities."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ceph_legacy_transition as subject
import test_ceph_runtime_qualification as runtime_tests


class LegacyTransitionTests(unittest.TestCase):
    def metadata(self):
        return {'data': {
            'secrets': [{'entity': {'type_str': name.split('.')[0], 'id': name.split('.')[1]},
                         'auth': {'key': {'type_str': 'aes', 'key': 'PRIVATE_SENTINEL'}}}
                        for name in sorted(subject.CORE | {'client.ordinary'})],
            'rotating_secrets': [{'entity': {'type_str': 'osd', 'id': '*'}, 'secrets': {'keys': [
                {'id': 1, 'expiring_key': {'key': {'type_str': 'aes', 'key': 'PRIVATE_SENTINEL'}}},
                {'id': 2, 'expiring_key': {'key': {'type_str': 'aes256k'}}}]}}]}}

    def test_selected_host_identity_precedes_all_fixture_operations(self):
        sources = {name: 'source' for name in ('ceph_legacy_transition.py',
                   'ceph_runtime_qualification.py', 'etcd_recovery.py')}
        for host in ('totodile', 'cyndaquil'):
            with patch.object(subject.common, 'require_host') as identity, \
                    patch.object(subject.common, 'private_root', side_effect=RuntimeError('end-of-host-check')):
                with self.assertRaisesRegex(RuntimeError, 'end-of-host-check'):
                    subject.qualify('legacy103-owned', sources, host=host)
                identity.assert_called_once_with(host)
        with patch.object(subject.common, 'require_host') as identity:
            with self.assertRaisesRegex(RuntimeError, 'unsupported synthetic transition host'):
                subject.qualify('legacy103-owned', sources, host='production-or-unknown')
            identity.assert_not_called()

    def test_native_types_require_complete_unambiguous_metadata_and_drop_values(self):
        value = self.metadata()
        parsed = subject.key_types(value)
        self.assertEqual(parsed['rotating'], {'osd.*': ['aes', 'aes256k']})
        self.assertEqual(parsed['entities']['client.ordinary'], 'aes')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(parsed))
        without_monitor = copy.deepcopy(value)
        without_monitor['data']['secrets'] = [row for row in without_monitor['data']['secrets']
                                              if row['entity']['type_str'] != 'mon']
        self.assertNotIn('mon.', subject.key_types(without_monitor)['entities'])
        incomplete = copy.deepcopy(value)
        incomplete['data']['rotating_secrets'] = []
        with self.assertRaises(RuntimeError) as error:
            subject.key_types(incomplete)
        self.assertIn('"rotating": {}', str(error.exception))
        self.assertNotIn('PRIVATE_SENTINEL', str(error.exception))
        changes = []
        changed = copy.deepcopy(value)
        changed['data']['secrets'].append(changed['data']['secrets'][0])
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['secrets'].pop()
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['secrets'][0]['auth']['key']['type_str'] = 'unknown'
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['rotating_secrets'] = []
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['rotating_secrets'][0]['secrets']['keys'] = []
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['rotating_secrets'][0]['secrets']['keys'][1]['id'] = 1
        changes.append(changed)
        changed = copy.deepcopy(value)
        changed['data']['rotating_secrets'][0]['secrets']['keys'][0]['expiring_key']['key']['type_str'] = 'none'
        changes.append(changed)
        for changed in changes:
            with self.subTest(changed=changes.index(changed)), self.assertRaises(RuntimeError):
                subject.key_types(changed)

    def test_both_exact_artifacts_preserve_all_existing_isolation_guards(self):
        for image in (subject.BASELINE, subject.modern.IMAGE):
            value = runtime_tests.RuntimeGuardTests().container()
            value['Config']['Image'] = image
            before = copy.deepcopy(value)
            subject.require_container(value, image, Path('/owned'), 'fixture-103', [])
            self.assertEqual(value, before)
            for field in ({'NetworkMode': 'host'}, {'Privileged': True}, {'CapAdd': ['SYS_ADMIN']}):
                changed = copy.deepcopy(value)
                changed['HostConfig'].update(field)
                with self.assertRaises(RuntimeError):
                    subject.require_container(changed, image, Path('/owned'), 'fixture-103', [])
            with self.assertRaises(RuntimeError):
                subject.require_container(value, 'quay.io/ceph/ceph:latest', Path('/owned'), 'fixture-103', [])
            value['Config']['Image'] = subject.BASELINE if image == subject.modern.IMAGE else subject.modern.IMAGE
            with self.assertRaises(RuntimeError):
                subject.require_container(value, image, Path('/owned'), 'fixture-103', [])

    def test_verification_refuses_changed_identity_and_complete_data(self):
        runtime = object.__new__(subject.Runtime)
        original = {'block': {'inode': 12}, 'osd_uuid': 'owned', 'fsid': 'owned', 'client_sha256': 'original'}
        payload = b'complete synthetic object'
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            (runtime.root / 'baseline.json').write_text(json.dumps({
                'identity': original, 'payload_bytes': len(payload), 'payload_sha256': hashlib.sha256(payload).hexdigest()}))
            (runtime.root / 'readback').write_bytes(payload)
            runtime.identity = Mock(return_value=original)
            runtime.client = Mock()
            runtime.verify()
            for field in original:
                runtime.identity.return_value = original | {field: 'foreign'}
                with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                    runtime.verify()
            runtime.identity.return_value = original
            (runtime.root / 'readback').write_bytes(payload[:-1])
            with self.assertRaisesRegex(RuntimeError, 'complete transition object differs'):
                runtime.verify()

    def test_expected_auth_findings_are_retained_other_faults_refused(self):
        runtime = object.__new__(subject.Runtime)
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            value = {'mgrmap': {'available': True}, 'osdmap': {'num_up_osds': 1, 'num_in_osds': 1},
                     'pgmap': {'pgs_by_state': [{'state_name': 'active+clean'}]},
                     'health': {'status': 'HEALTH_ERR', 'checks': {'AUTH_INSECURE_SERVICE_KEY_TYPE': {}}}}
            runtime.status = Mock(return_value=value)
            self.assertEqual(runtime.steady(), {'status': 'HEALTH_ERR', 'checks': ['AUTH_INSECURE_SERVICE_KEY_TYPE']})
            value['health']['checks']['OSD_DOWN'] = {}
            with self.assertRaisesRegex(RuntimeError, 'unexpected transition health findings'):
                runtime.steady()

    def test_monitor_rotation_updates_actual_restart_keyring_and_refuses_path_changes(self):
        runtime = object.__new__(subject.Runtime)
        runtime.root = Path('/work')
        with patch.object(subject.modern.Runtime, 'rotate_keyring') as rotate:
            runtime.rotate_keyring('mon.', Path('/work/mon.keyring'), Path('/work/rotated-mon.keyring'))
            rotate.assert_called_once_with('mon.', Path('/work/mon.keyring'), Path('/work/mon.keyring'))
            with self.assertRaises(RuntimeError):
                runtime.rotate_keyring('mon.', Path('/foreign'), Path('/work/rotated-mon.keyring'))
        runtime.command = Mock(return_value=Mock(stdout=b'synthetic-mon-key\n'))
        runtime.ceph = Mock(return_value=b'synthetic-mon-key\n')
        self.assertEqual(runtime.monitor_key_hash(), hashlib.sha256(b'synthetic-mon-key').hexdigest())
        runtime.ceph.return_value = b'foreign\n'
        with self.assertRaisesRegex(RuntimeError, 'authentication differ'):
            runtime.monitor_key_hash()

    def test_transition_retains_type_only_snapshot_before_native_health_refusal(self):
        runtime = object.__new__(subject.Runtime)
        before = self.metadata()
        after = copy.deepcopy(before)
        for row in after['data']['secrets']:
            if row['entity']['type_str'] + '.' + row['entity']['id'] in subject.CORE:
                row['auth']['key']['type_str'] = 'aes256k'
        runtime.command = Mock(return_value=Mock(stdout=b'ceph version 20.2.4 native'))
        runtime.start = runtime.verify = runtime.rotate_core = Mock()
        runtime.monitor_key_hash = Mock(side_effect=['old-hash', 'new-hash'])
        runtime.steady = Mock(side_effect=[{'status': 'HEALTH_ERR', 'checks': []},
                                          {'status': 'HEALTH_ERR', 'checks': ['AUTH_INSECURE_SERVICE_TICKETS']}])
        runtime.ceph = Mock(side_effect=[json.dumps(before).encode(), b'',
                                        b'{"auth_service_cipher":{"name":"aes256k"}}', json.dumps(after).encode()])
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            (runtime.root / 'baseline.json').write_text('{"monitor_key_sha256":"old-hash"}')
            with self.assertRaisesRegex(RuntimeError, 'core migration incomplete'):
                runtime.transition()
            saved = json.loads((runtime.root / 'transition-progress.json').read_text())
        self.assertEqual(saved, runtime.transition_progress)
        self.assertEqual(saved['observations'][0]['health']['checks'], ['AUTH_INSECURE_SERVICE_TICKETS'])
        self.assertEqual(saved['observations'][0]['key_types']['entities']['mon.'], 'aes256k')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(saved))


if __name__ == '__main__':
    unittest.main()
