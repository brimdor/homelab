#!/usr/bin/env python3
"""Refuse stale identities; passive tracing must not expand recovery authority."""

import copy
import unittest

import builder_current_readiness_trace as subject


class CurrentIdentity(unittest.TestCase):
    def runtime(self):
        p = subject.CURRENT['builder-canary']
        return {'status': {'id': p['container_id'], 'state': 'CONTAINER_RUNNING',
                           'imageRef': 'sha256:' + p['digest'], 'labels': {
                               'io.kubernetes.pod.uid': p['pod_uid'],
                               'io.kubernetes.pod.namespace': 'builder-canary',
                               'io.kubernetes.container.name': 'main'}},
                'info': {'pid': p['pid'], 'runtimeSpec': {'process': {
                    'user': {'uid': 1000, 'gid': 1000, 'additionalGids': [1000]}}}}}

    def test_current_runtime_and_every_foreign_identity_refused(self):
        p = subject.CURRENT['builder-canary']
        runtime = self.runtime()
        self.assertEqual(subject.validate_runtime(runtime, 'builder-canary', p), runtime['info']['runtimeSpec'])
        for path, wrong in ((('status', 'id'), 'foreign'), (('status', 'state'), 'CONTAINER_EXITED'),
                            (('status', 'imageRef'), 'sha256:' + '0' * 64),
                            (('status', 'labels', 'io.kubernetes.pod.uid'), subject.original.SOURCES['builder-canary']['pod_uid']),
                            (('status', 'labels', 'io.kubernetes.pod.namespace'), 'builder'),
                            (('status', 'labels', 'io.kubernetes.container.name'), 'sidecar'),
                            (('info', 'pid'), 7894),
                            (('info', 'runtimeSpec', 'process', 'user'), {'uid': 0, 'gid': 0})):
            with self.subTest(path=path):
                changed = copy.deepcopy(runtime)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = wrong
                with self.assertRaises(RuntimeError):
                    subject.validate_runtime(changed, 'builder-canary', p)

    def test_clean_exact_release_required_and_recovery_profiles_unchanged(self):
        p = subject.CURRENT['builder-canary']
        release = {'sourceRevision': p['source_revision'], 'gitTree': p['git_tree'], 'sourceClean': True}
        subject.validate_release(release, p['bundle_sha256'], p)
        for key, wrong in (('sourceRevision', '0' * 40), ('gitTree', '0' * 40), ('sourceClean', False)):
            with self.assertRaises(RuntimeError):
                subject.validate_release({**release, key: wrong}, p['bundle_sha256'], p)
        with self.assertRaises(RuntimeError):
            subject.validate_release(release, '0' * 64, p)
        self.assertEqual(subject.original.SOURCES['builder-canary']['pid'], 7894)
        self.assertEqual(subject.original.SOURCES['builder']['pid'], 4754)
        self.assertIsNot(subject.CURRENT['builder']['stores'], subject.original.SOURCES['builder']['stores'])

    def test_only_slow_intervals_retained_with_exact_monotonic_pairs(self):
        samples = subject.trace.Samples({9407}, {11: {'store': 'recovery'}})
        for timestamp, payload in (('100.000000', '(fd: b)'), ('100.500000', ' -> 0x0'),
                                   ('101.000000', '(fd: b)'), ('101.000001', ' -> 0x0')):
            samples.add(f' node-9407 [002] .... {timestamp}: sys_fsync{payload}')
        slow = samples.result(include_intervals=True)['slow_intervals']
        self.assertEqual(len(slow), 1)
        self.assertEqual((slow[0]['started_ns'], slow[0]['finished_ns']), (100000000000, 100500000000))
        self.assertNotIn('slow_intervals', samples.result())


if __name__ == '__main__':
    unittest.main()
