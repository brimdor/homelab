#!/usr/bin/env python3
"""Reject unsafe runtime evidence without running a daemon or using a credential."""

import copy
import unittest

import rook_runtime_qualification as subject
from test_rook_native_candidate import inventory


class RuntimeGuardTests(unittest.TestCase):
    def test_node_device_fields_need_exact_framing_and_all_four_identities(self):
        device = inventory()['blockdevices'][0]
        raw = b'lima-rook-12345678-0\n254:32\n16777216\nfe:20\n'
        self.assertEqual(subject.require_node_device(raw, device)['major_minor'], '254:32')
        for changed in (raw.replace(b'-0\n', b'-0254:32\n', 1), raw.replace(b'fe:20', b'fe:21'),
                        raw.replace(b'16777216', b'4096'), raw + b'extra\n', b'\xff\n'):
            with self.subTest(raw=changed), self.assertRaises(RuntimeError) as context:
                subject.require_node_device(changed, device)
            self.assertIn('actual', context.exception.observation)

    def test_failure_evidence_retains_only_fixed_markers_and_no_output_or_key_hash(self):
        secret = b'synthetic-private-output-never-retain'
        value = subject.command_failure(['/owned/kubectl', 'exec'], 9,
                                        b'Permission denied: ' + secret)
        self.assertEqual(value['markers'], ['permission denied', 'denied'])
        self.assertEqual(set(value), {'executable', 'exit', 'markers', 'raw_output_retained'})
        self.assertNotIn(secret.decode(), str(value))
        self.assertFalse(value['raw_output_retained'])

    def test_runtime_requires_every_secure_mode_in_both_configuration_paths(self):
        rows = subject.resources('qualification-12345678', 'rook-12345678', inventory())
        for key in subject.MODES:
            self.assertEqual(rows[2]['spec']['cephConfig']['global'][key], 'secure')
            self.assertIn(key + ' = secure\n', rows[1]['data']['config'])
        self.assertNotIn('keyType', rows[2]['spec']['security']['cephx']['daemon'])
        self.assertTrue(rows[2]['spec']['csi']['skipUserCreation'])

    def test_toolbox_rejects_privilege_host_access_and_secret_mount_mutation(self):
        value = subject.toolbox()
        subject.require_toolbox(value)
        for key, data in [('hostNetwork', True), ('hostPID', True), ('hostIPC', True),
                          ('automountServiceAccountToken', True), ('volumes', [{'hostPath': '/'}]),
                          ('initContainers', [{'name': 'foreign'}])]:
            changed = copy.deepcopy(value)
            changed['spec'][key] = data
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_toolbox(changed)
        for key, data in [('privileged', True), ('readOnlyRootFilesystem', False),
                          ('allowPrivilegeEscalation', True),
                          ('capabilities', {'drop': ['ALL'], 'add': ['SYS_ADMIN']})]:
            changed = copy.deepcopy(value)
            changed['spec']['containers'][0]['securityContext'][key] = data
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_toolbox(changed)

    def test_all_six_daemon_statuses_must_prove_generation_and_modern_version(self):
        value = {'status': {'cephx': {name: {'keyGeneration': 2, 'keyCephVersion': '20.2.4-0'}
                                     for name in subject.CORE_KEYS}}}
        subject.require_generation(value, 2)
        for name in subject.CORE_KEYS:
            for key, data in [('keyGeneration', 1), ('keyCephVersion', '20.2.3-0'),
                              ('keyType', 'aes')]:
                changed = copy.deepcopy(value)
                changed['status']['cephx'][name][key] = data
                with self.subTest(name=name, key=key), self.assertRaises(RuntimeError):
                    subject.require_generation(changed, 2)
        with self.assertRaises(RuntimeError):
            subject.require_generation({}, 2)

    def test_monitor_cipher_policy_and_every_address_must_be_modern(self):
        cipher = {'name': 'aes256k', 'value': 2}
        value = {'auth_allowed_ciphers': [cipher], 'auth_service_cipher': cipher,
                 'auth_preferred_cipher': cipher,
                 'mons': [{'public_addrs': {'addrvec': [{'type': 'v2'}]}} for _ in range(3)]}
        subject.require_mon_security(value)
        for key, data in [('auth_allowed_ciphers', [cipher, {'name': 'aes', 'value': 1}]),
                          ('auth_service_cipher', {'name': 'aes', 'value': 1}),
                          ('auth_preferred_cipher', {'name': 'aes256k', 'value': 1}),
                          ('mons', value['mons'][:2])]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_mon_security(value | {key: data})
        for addresses in ([], [{'type': 'v1'}], [{'type': 'v2'}, {'type': 'v1'}]):
            changed = copy.deepcopy(value)
            changed['mons'][0]['public_addrs']['addrvec'] = addresses
            with self.assertRaises(RuntimeError):
                subject.require_mon_security(changed)

    def test_osd_evidence_requires_exact_device_fsid_id_and_uuid(self):
        uuid = '12345678-1234-1234-1234-123456789abc'
        row = {'osd_id': 0, 'device': '/dev/vdc', 'ceph_fsid': 'owned', 'osd_uuid': uuid}
        self.assertEqual(subject.require_osd_device({'a': row}, 0, 'owned', '/dev/vdc'), uuid)
        for key, data in [('osd_id', 1), ('device', '/dev/sda'), ('ceph_fsid', 'foreign'),
                          ('osd_uuid', '')]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.require_osd_device({'a': row | {key: data}}, 0, 'owned', '/dev/vdc')
        with self.assertRaises(RuntimeError):
            subject.require_osd_device({'a': row, 'b': row}, 0, 'owned', '/dev/vdc')

    def test_completed_pod_needs_exact_successful_job_and_all_container_evidence(self):
        value = {'metadata': {'ownerReferences': [{'kind': 'Job', 'uid': 'owned'}]},
                 'spec': {'restartPolicy': 'OnFailure', 'containers': [{'name': 'main'}],
                          'initContainers': [{'name': 'init'}]},
                 'status': {'phase': 'Succeeded',
                            'containerStatuses': [{'name': 'main', 'state': {'terminated': {'exitCode': 0}}}],
                            'initContainerStatuses': [{'name': 'init', 'state': {'terminated': {'exitCode': 0}}}]}}
        subject.require_pod_completion(value, {'owned'})
        for mutate in (lambda x: x['metadata'].update(ownerReferences=[{'kind': 'Job', 'uid': ''}]),
                       lambda x: x['metadata'].update(deletionTimestamp='now'),
                       lambda x: x['spec'].update(restartPolicy='Always'),
                       lambda x: x['status'].update(containerStatuses=[]),
                       lambda x: x['status'].update(initContainerStatuses=[]),
                       lambda x: x['status']['initContainerStatuses'][0]['state']['terminated'].update(exitCode=1)):
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.assertRaises(RuntimeError):
                subject.require_pod_completion(changed, {'owned'})
        with self.assertRaises(RuntimeError):
            subject.require_pod_completion(value, {'foreign'})

    def test_running_phase_and_ready_condition_are_insufficient_without_running_containers(self):
        value = {'metadata': {}, 'spec': {'containers': [{'name': 'main'}]},
                 'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                            'containerStatuses': [{'name': 'main', 'ready': True,
                                                   'state': {'running': {'startedAt': 'now'}}}]}}
        subject.require_pod_completion(value, set())
        for status in ({'name': 'main', 'ready': False, 'state': {'running': {}}},
                       {'name': 'main', 'ready': True, 'state': {'waiting': {}}},
                       {'name': 'foreign', 'ready': True, 'state': {'running': {'startedAt': 'now'}}}):
            changed = copy.deepcopy(value)
            changed['status']['containerStatuses'] = [status]
            with self.assertRaises(RuntimeError):
                subject.require_pod_completion(changed, set())


if __name__ == '__main__':
    unittest.main()
