#!/usr/bin/env python3
"""Race, crash/resume and refusal coverage for persistent maintenance ownership."""

import copy
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import maintenance_coordination as owner


class API:
    def __init__(self):
        self.mutex = threading.Lock()
        self.uncertain = False
        self.before_patch = None
        self.ds = {'metadata': {'name': 'kured', 'namespace': 'kured', 'uid': 'ds-uid',
                               'generation': 1, 'resourceVersion': '1',
                               'annotations': {'unrelated': 'preserve'}},
                   'spec': {'template': {'spec': {'containers': [{
                       'name': 'kured', 'image': owner.IMAGE, 'command': ['/usr/bin/kured'],
                       'args': list(owner.ARGS), 'env': copy.deepcopy(owner.ENV)}]}}},
                   'status': {'observedGeneration': 1, 'desiredNumberScheduled': 2,
                              'currentNumberScheduled': 2, 'updatedNumberScheduled': 2,
                              'numberReady': 2, 'numberAvailable': 2}}
        self.nodes = [{'metadata': {'name': name, 'uid': name + '-uid'}, 'status': {
            'conditions': [{'type': 'Ready', 'status': 'True'}] + [
                {'type': t, 'status': 'False'} for t in ('MemoryPressure', 'DiskPressure', 'PIDPressure')]}}
                      for name in ['fixture-a', 'fixture-b']]
        self.pods = [{'metadata': {'name': name, 'ownerReferences': [
            {'uid': 'ds-uid', 'controller': True}]},
            'spec': dict(copy.deepcopy(self.ds['spec']['template']['spec']), nodeName=name),
            'status': {'phase': 'Running', 'containerStatuses': [{
                'name': 'kured', 'ready': True, 'imageID': owner.IMAGE.replace(':1.21.0', '')}]}}
                     for name in ['fixture-a', 'fixture-b']]
        self.writes = 0
        self.node_writes = []

    def call(self, *argv):
        if argv[:2] == ('get', 'nodes'):
            return {'items': copy.deepcopy(self.nodes)}
        node = next(n for n in self.nodes if n['metadata']['name'] == argv[2])
        if argv[0] == 'get':
            return copy.deepcopy(node)
        operations = json.loads(argv[5])
        pointer = '/metadata/annotations/weave.works~1kured-reboot-in-progress'
        self.assert_node_patch(node, operations, pointer)
        del node['metadata']['annotations']['weave.works/kured-reboot-in-progress']
        node['metadata']['resourceVersion'] = str(int(node['metadata']['resourceVersion']) + 1)
        self.node_writes.append(operations)
        return copy.deepcopy(node)

    @staticmethod
    def assert_node_patch(node, operations, pointer):
        assert operations == [
            {'op': 'test', 'path': '/metadata/uid', 'value': node['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
            {'op': 'test', 'path': pointer, 'value': node['metadata']['annotations']['weave.works/kured-reboot-in-progress']},
            {'op': 'remove', 'path': pointer},
        ]

    def snapshot(self):
        with self.mutex:
            return copy.deepcopy((self.ds, self.pods, self.nodes))

    def patch(self, operations):
        if self.before_patch:
            self.before_patch()
        with self.mutex:
            candidate = copy.deepcopy(self.ds)
            for operation in operations:
                keys = operation['path'].lstrip('/').split('/')
                parent = candidate
                for key in keys[:-1]:
                    parent = parent[key]
                key = keys[-1]
                if operation['op'] == 'test':
                    if parent[key] != operation['value']:
                        raise RuntimeError('API precondition conflict')
                elif operation['op'] == 'add':
                    parent[key] = operation['value']
                else:
                    raise AssertionError('unsupported fixture operation')
            candidate['metadata']['resourceVersion'] = str(int(candidate['metadata']['resourceVersion']) + 1)
            self.ds = candidate
            self.writes += 1
            if self.uncertain:
                raise RuntimeError('transport lost after committed write')
            return copy.deepcopy(self.ds)

    def controller(self):
        return owner.Ownership(self, 'ds-uid', {n['metadata']['name']: n['metadata']['uid'] for n in self.nodes})


class CoordinationTests(unittest.TestCase):
    def test_every_rollout_field_is_required_before_ownership_transition(self):
        for field in ('observedGeneration', 'desiredNumberScheduled', 'currentNumberScheduled',
                      'updatedNumberScheduled', 'numberReady', 'numberAvailable', 'numberMisscheduled'):
            for value in (None, -1, 3):
                with self.subTest(field=field, value=value):
                    api = API()
                    api.ds['status'][field] = value
                    self.assertFalse(owner.rollout_ready(api.ds['metadata'], api.ds['status'], 2))
                    with self.assertRaisesRegex(RuntimeError, 'Kured rollout is incomplete'):
                        self.acquire(api)
                    self.assertEqual(api.writes, 0)

    def acquire(self, api):
        return api.controller().acquire('fixture-a', 39, 41, 'a' * 40)

    def test_persistent_resume_and_explicit_release_preserve_everything_else(self):
        api = API()
        original = copy.deepcopy(api.ds)
        journal = self.acquire(api)
        self.assertEqual(api.controller().resume(journal['owner']), journal)
        self.assertEqual(json.loads(api.ds['metadata']['annotations'][owner.LOCK])['TTL'], 0)
        self.assertEqual(api.controller().release(journal['owner'], lambda _: True), journal)
        self.assertEqual(api.ds['spec'], original['spec'])
        self.assertEqual(api.ds['metadata']['annotations'], original['metadata']['annotations'])
        self.assertEqual(api.writes, 2)

    def test_normal_owner_clears_only_queued_requests_before_global_removal(self):
        api = API();journal = self.acquire(api)
        key = 'weave.works/kured-reboot-in-progress'
        for node in api.nodes:
            node['metadata'].update(resourceVersion='1', annotations={key: datetime.now(timezone.utc).isoformat(), 'keep': 'original'})
        original = copy.deepcopy(api.ds['spec'])
        original_patch = api.patch
        def checked_patch(operations):
            self.assertTrue(all(key not in n['metadata']['annotations'] for n in api.nodes))
            return original_patch(operations)
        with patch.object(api, 'patch', side_effect=checked_patch):
            api.controller().release(journal['owner'], lambda _: True)
        self.assertEqual(len(api.node_writes), 2)
        self.assertEqual(api.writes, 2)
        self.assertEqual(api.ds['spec'], original)
        self.assertTrue(all(n['metadata']['annotations'] == {'keep': 'original'} for n in api.nodes))

    def test_release_refuses_request_older_than_owner_without_mutation(self):
        api = API();journal = self.acquire(api)
        requested = datetime.fromisoformat(journal['created'].replace('Z', '+00:00')) - timedelta(seconds=1)
        api.nodes[0]['metadata'].update(resourceVersion='1', annotations={
            'weave.works/kured-reboot-in-progress': requested.isoformat()})
        with self.assertRaisesRegex(RuntimeError, 'predates verified'):
            api.controller().release(journal['owner'], lambda _: True)
        self.assertEqual(api.writes, 1);self.assertFalse(api.node_writes)

    def test_simultaneous_controllers_only_one_can_claim(self):
        api = API()
        barrier = threading.Barrier(2)
        api.before_patch = barrier.wait
        results = []

        def claim():
            try:
                results.append(('acquired', self.acquire(api)))
            except RuntimeError as error:
                results.append(('refused', str(error)))

        children = [threading.Thread(target=claim) for _ in range(2)]
        for child in children:
            child.start()
        for child in children:
            child.join(timeout=10)
            self.assertFalse(child.is_alive())
        self.assertEqual(sorted(x[0] for x in results), ['acquired', 'refused'])
        self.assertEqual(api.writes, 1)

    def test_uncertain_write_remains_owned_without_blind_replay(self):
        api = API()
        api.uncertain = True
        with self.assertRaisesRegex(RuntimeError, 'transport lost'):
            self.acquire(api)
        journal = json.loads(api.ds['metadata']['annotations'][owner.JOURNAL])
        self.assertEqual(api.controller().resume(journal['owner']), journal)
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.acquire(api)
        self.assertEqual(api.writes, 1)

    def test_existing_foreign_expired_or_malformed_lock_never_stolen(self):
        for value in ['not-json', '{}', json.dumps({'nodeID': 'fixture-b', 'TTL': 1,
                                                   'created': '2000-01-01T00:00:00Z'})]:
            with self.subTest(value=value):
                api = API()
                api.ds['metadata']['annotations'][owner.LOCK] = value
                before = copy.deepcopy(api.ds)
                with self.assertRaisesRegex(RuntimeError, 'already exists|foreign reboot lock|malformed maintenance ownership state'):
                    self.acquire(api)
                self.assertEqual(api.ds, before)
                self.assertEqual(api.writes, 0)

    def test_journal_without_lock_is_not_overwritten(self):
        api = API()
        api.ds['metadata']['annotations'][owner.JOURNAL] = '{}'
        with self.assertRaises(RuntimeError):
            self.acquire(api)
        self.assertEqual(api.writes, 0)

    def test_unsafe_runtime_or_identity_refuses_before_write(self):
        def extra_flag(api):
            api.pods[0]['spec']['containers'][0]['args'].append('--force-reboot=true')

        def env_override(api):
            api.ds['spec']['template']['spec']['containers'][0]['env'].append(
                {'name': 'KURED_CONCURRENCY', 'value': '2'})

        def unready(api):
            api.pods[0]['status']['containerStatuses'][0]['ready'] = False

        def node_reboot(api):
            api.nodes[0]['metadata']['annotations'] = {'weave.works/kured-reboot-in-progress': 'true'}

        def wrong_image(api):
            api.pods[0]['status']['containerStatuses'][0]['imageID'] = 'foreign'

        def deleting(api):
            api.pods[0]['metadata']['deletionTimestamp'] = '2026-10-20T00:00:00Z'

        def incomplete(api):
            api.ds['status']['updatedNumberScheduled'] = 1

        def foreign_pod(api):
            pod = copy.deepcopy(api.pods[0])
            pod['metadata']['ownerReferences'][0]['uid'] = 'old-controller'
            api.pods.append(pod)

        def changed_uid(api):
            api.ds['metadata']['uid'] = 'foreign'

        for mutate in [extra_flag, env_override, unready, node_reboot, wrong_image,
                       deleting, incomplete, foreign_pod, changed_uid]:
            with self.subTest(mutate=mutate.__name__):
                api = API()
                mutate(api)
                with self.assertRaises(RuntimeError):
                    self.acquire(api)
                self.assertEqual(api.writes, 0)

    def test_bad_hop_revision_or_node_refuses(self):
        for node, source, target, revision in [('fixture-a', 39, 44, 'a' * 40),
                                              ('foreign', 39, 41, 'a' * 40),
                                              ('fixture-a', 39, 41, 'master')]:
            api = API()
            with self.assertRaises(RuntimeError):
                api.controller().acquire(node, source, target, revision)
            self.assertEqual(api.writes, 0)

    def test_release_refusal_retains_lock_and_journal(self):
        api = API()
        journal = self.acquire(api)
        before = copy.deepcopy(api.ds)
        with self.assertRaisesRegex(RuntimeError, 'gates did not pass'):
            api.controller().release(journal['owner'], lambda _: False)
        self.assertEqual(api.ds, before)

    def test_changed_node_uid_cannot_resume(self):
        api = API()
        journal = self.acquire(api)
        controller = api.controller()
        api.nodes[0]['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'identities changed'):
            controller.resume(journal['owner'])
        self.assertEqual(api.writes, 1)

    def test_changed_owner_during_release_callback_cannot_release(self):
        api = API()
        journal = self.acquire(api)

        def changed(_):
            lock = json.loads(api.ds['metadata']['annotations'][owner.LOCK])
            lock['nodeID'] = 'fixture-b'
            api.ds['metadata']['annotations'][owner.LOCK] = json.dumps(lock)
            return True

        with self.assertRaisesRegex(RuntimeError, 'ownership changed|ownership contract differs'):
            api.controller().release(journal['owner'], changed)
        self.assertEqual(api.writes, 1)

    def test_resource_change_between_observation_and_write_refuses(self):
        api = API()

        def concurrent():
            api.ds['metadata']['annotations']['operator-note'] = 'new'
            api.ds['metadata']['resourceVersion'] = '2'

        api.before_patch = concurrent
        with self.assertRaisesRegex(RuntimeError, 'conflict'):
            self.acquire(api)
        self.assertEqual(api.writes, 0)
        self.assertEqual(api.ds['metadata']['annotations']['operator-note'], 'new')

    def test_malformed_resumed_state_never_releases(self):
        for value in ['null', '[]', '{}', 'not-json']:
            api = API()
            journal = self.acquire(api)
            api.ds['metadata']['annotations'][owner.JOURNAL] = value
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                api.controller().resume(journal['owner'])
            self.assertEqual(api.writes, 1)


if __name__ == '__main__':
    unittest.main()
