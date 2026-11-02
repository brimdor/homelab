"""Fence the first serial-pull mitigation and its single-file activation boundary."""

import copy
import hashlib
import json
from pathlib import Path
import unittest

import maintenance_coordination as coordination
import maintenance_hop_journal as hops
import maintenance_kubelet_image_pulls as subject


class SerialImagePullTests(unittest.TestCase):
    def test_registry_observation_preserves_identity_and_excludes_target(self):
        status = dict(containerID='original-container', imageID='original-image', restartCount=0, ready=True)
        pod = {'metadata': {'uid': 'original-pod', 'name': 'zot-0'},
               'spec': {'nodeName': 'growlithe'}, 'status': {'containerStatuses': [status]}}
        original = dict(uid='original-pod', name='zot-0', node='growlithe',
                        container={k: status[k] for k in ('containerID', 'imageID', 'restartCount')})
        subject.preserve_registry_observation(pod, original)
        for key, value in (('containerID', 'new'), ('imageID', 'new'), ('restartCount', 1), ('ready', False)):
            changed = copy.deepcopy(pod); changed['status']['containerStatuses'][0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.preserve_registry_observation(changed, original)
        for key, value in (('uid', 'new'), ('node', 'squirtle')):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.preserve_registry_observation(pod, dict(original, **{key: value}))

    def test_first_target_cannot_gain_a_nas_or_application_volume(self):
        pod = {'metadata': {'namespace': 'kube-system'}, 'spec': {'volumes': [{'hostPath': {}}]}}
        subject.storage_boundary([pod])
        for volume in ({'nfs': {}}, {'persistentVolumeClaim': {}}, {'csi': {}}):
            with self.subTest(volume=volume), self.assertRaises(RuntimeError):
                subject.storage_boundary([dict(pod, spec={'volumes': [volume]})])
        with self.assertRaises(RuntimeError):
            subject.storage_boundary([dict(pod, metadata={'namespace': 'zot'})])
        subject.storage_boundary([dict(pod, metadata={'namespace': 'tsurreal-canary'},
                                       spec={'volumes': [{'persistentVolumeClaim': {}}]})])
        with self.assertRaises(RuntimeError):
            subject.storage_boundary([dict(pod, metadata={'namespace': 'tsurreal-other'},
                                           spec={'volumes': [{'persistentVolumeClaim': {}}]})])

    def test_only_the_first_reviewed_master_has_execution_authority(self):
        self.assertTrue(coordination.reviewed_hop('squirtle', 'parallel', 'serial', 'kubelet-image-pulls'))
        for node in ('bulbasaur', 'charmander', 'cyndaquil', 'chikorita'):
            self.assertFalse(coordination.reviewed_hop(node, 'parallel', 'serial', 'kubelet-image-pulls'))
        owner = {'component': 'kubelet-image-pulls', 'node': 'squirtle', 'source': 'parallel', 'target': 'serial'}
        self.assertEqual(hops.steps(owner),
                         ('cordon', 'drain', 'apply_policy', 'restore_scheduling', 'accept_applications'))
        for key, value in (('node', 'bulbasaur'), ('source', 'serial'), ('target', 'parallel')):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                hops.steps(dict(owner, **{key: value}))

    def test_repository_policy_contains_no_other_kubelet_change(self):
        path = Path(__file__).resolve().parents[1] / 'roles/k3s/files/kubelet-serial-image-pulls.conf'
        self.assertEqual(subject.policy_bytes(path.read_text()), path.read_bytes())
        for value in (dict(subject.REQUIRED, serializeImagePulls=False),
                      dict(subject.REQUIRED, serializeImagePulls=1),
                      dict(subject.REQUIRED, seccompDefault=False), {}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                subject.policy_bytes(json.dumps(value))

    def test_activation_requires_new_process_and_only_the_owned_file(self):
        content = json.dumps(subject.REQUIRED).encode()
        before = {'version': subject.VERSION, 'binary_sha256': 'binary', 'runtime_sha256': 'runtime',
                  'pid': 101, 'boot': 'boot', 'configs': {'main': 'unchanged'},
                  'unit_sha256': 'unit', 'selinux': 'Enforcing', 'stargz': True,
                  'kubelet_configs': {'defaults': 'default'}}
        after = copy.deepcopy(before); after['pid'] = 202
        after['kubelet_configs'][str(subject.POLICY)] = hashlib.sha256(content).hexdigest()
        subject.installed(before, after, content)
        for key, value in (('pid', 101), ('boot', 'rebooted'), ('configs', {}),
                           ('runtime_sha256', 'other'), ('selinux', 'Permissive'),
                           ('kubelet_configs', {'foreign': 'file'})):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                subject.installed(before, dict(after, **{key: value}), content)
        existing = copy.deepcopy(before)
        existing['kubelet_configs'][str(subject.POLICY)] = hashlib.sha256(content).hexdigest()
        with self.assertRaises(RuntimeError):
            subject.installed(existing, after, content)


if __name__ == '__main__':
    unittest.main()
