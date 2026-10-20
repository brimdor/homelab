"""Refusal regressions for the zero-Pod Argo fixture adapter."""

import copy
import hashlib
import unittest

import maintenance_argo_qualification as q


TOKEN = 'fixture-owner-103-11111111-1111-4111-8111-111111111111'
LOCK = q.encoded({'nodeID': TOKEN, 'metadata': {'unschedulable': True}, 'TTL': 0, 'created': 'fixture'})
JOURNAL = q.encoded({'owner': TOKEN, 'fixture': True, 'created': 'fixture'})


class API:
    def __init__(self):
        self.value = {'namespace': {'metadata': {'name': q.NAMESPACE, 'uid': 'namespace-uid',
                      'labels': {q.LABEL: 'maintenance-103'}}},
            'daemonset': {'metadata': {'name': q.NAME, 'namespace': q.NAMESPACE, 'uid': 'ds-uid',
                'generation': 1, 'resourceVersion': '1', 'labels': {q.LABEL: 'maintenance-103'},
                'annotations': {q.REVISION: 'first'}}, 'spec': {'synthetic': True},
                'status': {'observedGeneration': 1, 'desiredNumberScheduled': 0}},
            'quota': {'metadata': {'namespace': q.NAMESPACE, 'name': 'no-pods'},
                      'spec': {'hard': {'pods': '0'}}}, 'nodes': [], 'pods': [], 'pvcs': []}
        self.calls = []

    def snapshot(self):
        return copy.deepcopy(self.value)

    def patch(self, operations):
        candidate = copy.deepcopy(self.value['daemonset'])
        for operation in operations:
            parts = [p.replace('~1', '/').replace('~0', '~') for p in operation['path'].split('/')[1:]]
            parent = candidate
            for part in parts[:-1]:
                parent = parent[part]
            key = parts[-1]
            if operation['op'] == 'test':
                if parent.get(key) != operation['value']:
                    raise RuntimeError('resourceVersion or UID conflict')
            elif operation['op'] == 'add':
                parent[key] = operation['value']
            elif operation['op'] == 'remove':
                del parent[key]
        candidate['metadata']['resourceVersion'] = str(int(candidate['metadata']['resourceVersion']) + 1)
        self.value['daemonset'] = candidate
        self.calls.append(copy.deepcopy(operations))


class ArgoOwnership(unittest.TestCase):
    def fixture(self):
        api = API()
        digest = hashlib.sha256(q.encoded(api.value['daemonset']['spec']).encode()).hexdigest()
        return api, q.Fixture(api, 'namespace-uid', 'ds-uid', digest)

    def test_persistent_owner_exact_bytes_and_explicit_release(self):
        api, fixture = self.fixture()
        fixture.claim(LOCK, JOURNAL)
        api.value['daemonset']['metadata']['annotations'][q.REVISION] = 'second'
        fresh = q.Fixture(api, fixture.namespace_uid, fixture.uid, fixture.spec_sha256)
        fresh.resume(LOCK, JOURNAL, 'second')
        with self.assertRaises(RuntimeError):
            fresh.release(LOCK, JOURNAL.replace('fixture', 'foreign'))
        self.assertEqual(len(api.calls), 1)
        fresh.release(LOCK, JOURNAL)
        self.assertEqual(api.value['daemonset']['metadata']['annotations'], {q.REVISION: 'second'})

    def test_foreign_owner_is_not_overwritten(self):
        api, fixture = self.fixture()
        api.value['daemonset']['metadata']['annotations'][q.LOCK] = 'foreign'
        with self.assertRaises(RuntimeError):
            fixture.claim(LOCK, JOURNAL)
        self.assertFalse(api.calls)

    def test_identity_spec_and_zero_pod_gates(self):
        for key in ('namespace', 'daemonset', 'spec', 'pods', 'pvcs', 'nodes', 'quota'):
            api, fixture = self.fixture()
            if key in ('namespace', 'daemonset'):
                api.value[key]['metadata']['uid'] = 'foreign'
            elif key == 'spec':
                api.value['daemonset']['spec']['synthetic'] = False
            elif key in ('pods', 'pvcs'):
                api.value[key] = [{'metadata': {'name': 'unexpected'}}]
            elif key == 'nodes':
                api.value[key] = [{'metadata': {'labels': {'homelab.eaglepass.io/qualification-103': 'never'}}}]
            else:
                api.value[key]['spec']['hard']['pods'] = '1'
            with self.assertRaises(RuntimeError):
                fixture.claim(LOCK, JOURNAL)
            self.assertFalse(api.calls)

    def test_stale_patch_refuses_without_partial_annotation_write(self):
        api, fixture = self.fixture()
        before = fixture.observed('first')
        operations = fixture.preconditions(before) + [{'op': 'add', 'path': fixture.pointer(q.LOCK), 'value': LOCK}]
        api.value['daemonset']['metadata']['resourceVersion'] = '2'
        with self.assertRaises(RuntimeError):
            api.patch(operations)
        self.assertNotIn(q.LOCK, api.value['daemonset']['metadata']['annotations'])


if __name__ == '__main__':
    unittest.main()
