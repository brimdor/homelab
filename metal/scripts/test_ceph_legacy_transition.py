#!/usr/bin/env python3
"""Protect legacy-transition isolation, metadata and original data identities."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

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

    def test_native_types_require_complete_unambiguous_metadata_and_drop_values(self):
        value = self.metadata()
        parsed = subject.key_types(value)
        self.assertEqual(parsed['rotating'], {'osd.*': ['aes', 'aes256k']})
        self.assertEqual(parsed['entities']['client.ordinary'], 'aes')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(parsed))
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


if __name__ == '__main__':
    unittest.main()
