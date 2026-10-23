#!/usr/bin/env python3
"""Reject unsafe monitor targets and loss of the original surviving quorum."""

import copy
import unittest

import rook_monitor_qualification as subject


class MonitorQualificationTests(unittest.TestCase):
    def deployment(self):
        return {'metadata': {'name': 'rook-ceph-mon-a', 'namespace': 'rook-qualification',
                             'uid': 'owned-deployment', 'resourceVersion': '123', 'labels': {'mon': 'a'},
                             'ownerReferences': [{'apiVersion': 'ceph.rook.io/v1', 'kind': 'CephCluster',
                                                  'name': 'rook-qualification', 'uid': 'owned-cluster'}]},
                'spec': {'replicas': 1}, 'status': {'readyReplicas': 1}}

    def test_patch_requires_exact_ownership_and_tests_identity_before_scaling(self):
        original = self.deployment()
        patch = subject.scale_patch(original, 'a', 'owned-cluster')
        self.assertEqual(patch, [
            {'op': 'test', 'path': '/metadata/uid', 'value': 'owned-deployment'},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '123'},
            {'op': 'test', 'path': '/spec/replicas', 'value': 1},
            {'op': 'replace', 'path': '/spec/replicas', 'value': 0}])
        changes = [('metadata', 'name', 'foreign'), ('metadata', 'namespace', 'rook-ceph'),
                   ('metadata', 'uid', ''), ('metadata', 'resourceVersion', ''),
                   ('metadata', 'labels', {'mon': 'b'}), ('metadata', 'ownerReferences', []),
                   ('spec', 'replicas', 2), ('status', 'readyReplicas', 0)]
        for parent, key, value in changes:
            changed = copy.deepcopy(original)
            changed[parent][key] = value
            with self.subTest(field=key), self.assertRaises(RuntimeError):
                subject.scale_patch(changed, 'a', 'owned-cluster')
        for key, value in (('apiVersion', 'foreign/v1'), ('kind', 'Namespace'),
                           ('name', 'production'), ('uid', 'foreign-cluster')):
            changed = copy.deepcopy(original)
            changed['metadata']['ownerReferences'][0][key] = value
            with self.subTest(owner=key), self.assertRaises(RuntimeError):
                subject.scale_patch(changed, 'a', 'owned-cluster')

    def values(self, names=('a', 'b', 'c'), quorum=('b', 'c'), checks=('MON_DOWN',)):
        return ({'fsid': 'owned-fsid', 'quorum_names': list(quorum),
                 'health': {'status': 'HEALTH_WARN' if checks else 'HEALTH_OK',
                            'checks': {key: {} for key in checks}}},
                {'fsid': 'owned-fsid', 'mons': [{'name': name} for name in names]})

    def test_only_actual_new_identity_with_both_survivors_completes(self):
        for names, quorum, checks, expected in (
                (('a', 'b', 'c'), ('b', 'c'), ('MON_DOWN',), False),
                (('a', 'b', 'c', 'd'), ('b', 'c', 'd'), ('MON_DOWN',), False),
                (('b', 'c', 'd'), ('b', 'c', 'd'), (), True),
                (('a', 'b', 'c'), ('a', 'b', 'c'), (), False)):
            status, monmap = self.values(names, quorum, checks)
            self.assertEqual(subject.monitor_view(status, monmap, ['a', 'b', 'c'], 'a',
                                                  'owned-fsid')['complete'], expected)

    def test_foreign_state_quorum_loss_duplicate_members_and_other_health_faults_refuse(self):
        cases = [self.values(quorum=('b',)), self.values(quorum=('b', 'd')),
                 self.values(quorum=('b', 'c', 'c')), self.values(names=('a', 'b', 'b')),
                 self.values(names=('b', 'c', 'd', 'e')), self.values(checks=('OSD_DOWN',))]
        status, monmap = self.values()
        cases.extend([(dict(status, fsid='foreign'), monmap), (status, dict(monmap, fsid='foreign')),
                      (dict(status, health={'status': 'HEALTH_OK', 'checks': {'MON_DOWN': {}}}), monmap)])
        for status, monmap in cases:
            with self.subTest(status=status, monmap=monmap), self.assertRaises(RuntimeError):
                subject.monitor_view(status, monmap, ['a', 'b', 'c'], 'a', 'owned-fsid')


if __name__ == '__main__':
    unittest.main()
