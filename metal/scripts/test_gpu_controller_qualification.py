#!/usr/bin/env python3
"""Protect controller-only identity, no-device isolation and honest readiness."""

import copy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import gpu_controller_qualification as subject


class ControllerQualificationTests(unittest.TestCase):
    def fixture(self):
        stage = {'version': '24.9.2', 'operator': {'args': ['--leader-elect']}}
        host = {'NetworkMode': 'container:' + 'a' * 64, 'ReadonlyRootfs': True,
                'Privileged': False, 'CapDrop': ['ALL'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 256, 'NanoCpus': 500000000,
                'Memory': 350 * 1024 * 1024, 'Tmpfs': {'/tmp': 'rw,nosuid,nodev'},
                'SecurityOpt': ['no-new-privileges:true'], 'LogConfig': {'Type': 'none'}}
        return stage, {'HostConfig': host, 'Config': {
            'Labels': {'io.eaglepass.maintenance': '103', 'io.eaglepass.recovery-run': 'gpu103-owned',
                       'io.eaglepass.gpu-version': '24.9.2'},
            'Image': 'nvcr.io/nvidia/gpu-operator@sha256:' + subject.IMAGES['24.9.2'],
            'User': '0', 'Entrypoint': ['gpu-operator'], 'Cmd': ['--leader-elect']},
            'Mounts': [{'Type': 'bind', 'Source': '/owned/' + source, 'Destination': destination, 'RW': False}
                       for source, destination in (('kubeconfig', '/qualification/kubeconfig'),
                                                   ('gpu-os-release', '/host-etc/os-release'))]}

    def test_only_exact_owned_loopback_peer_readonly_inputs_and_process_are_allowed(self):
        stage, value = self.fixture()
        subject.require_operator(value, 'a' * 64, Path('/owned'), 'gpu103-owned', stage)
        for field, invalid in (('NetworkMode', 'host'), ('NetworkMode', 'container:' + 'b' * 64),
                               ('Privileged', True), ('CapAdd', ['SYS_ADMIN']), ('Devices', ['gpu']),
                               ('DeviceRequests', ['all']), ('PortBindings', {'8080': []}),
                               ('ReadonlyRootfs', False), ('Memory', 0), ('NanoCpus', 0),
                               ('LogConfig', {'Type': 'json-file'})):
            changed = copy.deepcopy(value)
            changed['HostConfig'][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(RuntimeError):
                subject.require_operator(changed, 'a' * 64, Path('/owned'), 'gpu103-owned', stage)
        for mutate in (lambda v: v['Mounts'][0].update(Source='/production/kubeconfig'),
                       lambda v: v['Mounts'][0].update(RW=True),
                       lambda v: v['Config'].update(Image='nvcr.io/nvidia/gpu-operator:latest'),
                       lambda v: v['Config'].update(Cmd=['--foreign']),
                       lambda v: v['Config']['Labels'].update({'io.eaglepass.recovery-run': 'other'})):
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.assertRaises(RuntimeError):
                subject.require_operator(changed, 'a' * 64, Path('/owned'), 'gpu103-owned', stage)

    def test_unreviewed_bundle_refused_before_any_native_resource_operation(self):
        with patch.object(subject.common, 'qualify') as native:
            with self.assertRaisesRegex(RuntimeError, 'bundle changed'):
                subject.qualify({'stages': []}, 'gpu103-owned')
            native.assert_not_called()

    def test_workload_inventory_requires_complete_uid_scoped_owner_chain(self):
        deployment = {'kind': 'Deployment', 'metadata': {'name': 'owned', 'uid': 'deployment',
            'ownerReferences': [{'kind': 'ClusterPolicy', 'uid': 'policy', 'controller': True}]},
            'spec': {'template': {'spec': {'containers': [{'image': 'public:pin'}]}}}}
        replica = {'kind': 'ReplicaSet', 'metadata': {'name': 'owned-rs', 'uid': 'replica',
            'ownerReferences': [{'kind': 'Deployment', 'uid': 'deployment', 'controller': True}]}}
        pod = {'kind': 'Pod', 'metadata': {'name': 'owned-pod', 'uid': 'pod',
            'ownerReferences': [{'kind': 'ReplicaSet', 'uid': 'replica', 'controller': True}]}}
        values = [pod, replica, deployment]
        self.assertEqual(subject.workload_inventory(values, 'policy')[-1]['images'], ['public:pin'])
        for invalid in ([pod, deployment], [pod, replica, deployment, pod]):
            with self.assertRaises(RuntimeError):
                subject.workload_inventory(invalid, 'policy')
        for owner in ({'kind': 'ClusterPolicy', 'uid': 'foreign', 'controller': True},
                      {'kind': 'Deployment', 'uid': 'deployment', 'controller': True},
                      {'kind': 'ClusterPolicy', 'uid': 'policy', 'controller': False}):
            changed = copy.deepcopy(values)
            changed[-1]['metadata']['ownerReferences'] = [owner]
            with self.assertRaises(RuntimeError):
                subject.workload_inventory(changed, 'policy')

    def test_ready_is_explicit_no_nfd_condition_and_never_device_acceptance(self):
        value = {'metadata': {'uid': 'owned'}, 'status': {'state': 'ready', 'conditions': [
            {'type': 'Ready', 'status': 'True', 'reason': 'NFDLabelsMissing'}]}}
        self.assertTrue(subject.ready_policy(value, 'owned'))
        for status in ({}, {'state': 'notReady'}, {'state': 'ready', 'conditions': []},
                       {'state': 'ready', 'conditions': [{'type': 'Ready', 'status': 'True', 'reason': 'NoGPUNodes'}]},
                       {'state': 'ready', 'conditions': [{'type': 'Ready', 'status': 'False', 'reason': 'NFDLabelsMissing'}]}):
            self.assertFalse(subject.ready_policy({'metadata': {'uid': 'owned'}, 'status': status}, 'owned'))
        for metadata in ({'uid': 'foreign'}, {'uid': 'owned', 'deletionTimestamp': 'now'}):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                subject.ready_policy({'metadata': metadata}, 'owned')

    def test_ready_endpoint_reads_only_owned_namespace_and_requires_successful_ok(self):
        with patch.object(subject.common, 'inspect', return_value={'State': {'Pid': 42}}), \
                patch.object(subject.common, 'command') as command:
            command.return_value = Mock(returncode=0, stdout=b'ok\n')
            self.assertTrue(subject.ready_endpoint('a' * 64))
            argv = command.call_args.args[0]
            self.assertEqual(argv[:-1], ['nsenter', '-t', '42', '-n', 'python3', '-c'])
            self.assertIn('http://127.0.0.1:8081/readyz', argv[-1])
            command.return_value = Mock(returncode=1, stdout=b'ok\n')
            self.assertFalse(subject.ready_endpoint('a' * 64))
            command.return_value = Mock(returncode=0, stdout=b'unready')
            self.assertFalse(subject.ready_endpoint('a' * 64))

    def test_startup_diagnostic_keeps_errors_without_opaque_or_credential_material(self):
        raw = (b'ordinary unselected output\nunknown flag: --example\n'
               b'{"msg":"startup failed","error":"token=PRIVATE_SENTINEL password=PRIVATE_PASSWORD"}\n'
               b'{"msg":"PRIVATE KEY must not be retained"}\n'
               b'Error: opaque AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n')
        value = subject.startup_diagnostic(raw)
        self.assertIn('unknown flag: --example', value)
        self.assertIn('[opaque]', value[-1])
        self.assertNotIn('PRIVATE', str(value))
        self.assertNotIn('unselected', str(value))


if __name__ == '__main__':
    unittest.main()
