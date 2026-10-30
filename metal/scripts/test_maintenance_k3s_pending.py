"""Pending drain replacements stay unstarted, owned and separate from app acceptance."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import maintenance_k3s_pending as pending
import maintenance_k3s_production as production
from maintenance_node_drain import Drain, hashed


class RookSurgeTests(unittest.TestCase):
    def fixture(self):
        item = {'kind': 'Deployment', 'metadata': {'namespace': 'rook-ceph',
                'name': 'rook-ceph-crashcollector-cyndaquil', 'uid': 'deployment',
                'ownerReferences': [{'controller': True, 'kind': 'CephCluster',
                    'uid': '901ad331-70b6-40cf-8654-2c6ed97a06b2'}]},
                'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'collector'}},
                    'strategy': {'type': 'RollingUpdate', 'rollingUpdate': {
                        'maxSurge': '25%', 'maxUnavailable': '25%'}},
                    'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': 'cyndaquil'}}}}}
        pods = [{'metadata': {'uid': 'pod-' + str(i), 'labels': {'app': 'collector'},
                 'ownerReferences': [{'controller': True, 'kind': 'ReplicaSet',
                                      'name': 'replica-' + str(i), 'uid': 'rs-' + str(i)}]},
                 'spec': copy.deepcopy(item['spec']['template']['spec']),
                 'status': {'phase': 'Pending', 'conditions': [{'type': 'PodScheduled',
                    'status': 'False', 'reason': 'Unschedulable'}]}} for i in range(2)]
        replicas = {'replica-' + str(i): {'metadata': {'uid': 'rs-' + str(i),
            'ownerReferences': [{'controller': True, 'kind': 'Deployment',
                'name': item['metadata']['name'], 'uid': 'deployment'}]}} for i in range(2)}
        facts = {'item': item, 'pods': pods, 'replicas': replicas,
                 'owner': {'component': 'k3s', 'node': 'cyndaquil', 'phase': 'OWNED_KURED_ONLY'}}

        class API:
            def call(self, *args):
                assert args[0] == 'get'
                return {'items': facts['pods']} if args[1] == 'pods' else facts['replicas'][args[2]]

        return facts, API()

    def test_only_two_owned_unstarted_pinned_rollout_pods(self):
        facts, api = self.fixture()
        self.assertTrue(pending.pending_rook_rollout(api, facts['item'], facts['owner']))
        mutations = [
            lambda f: f['pods'][1]['status'].update(phase='Running'),
            lambda f: f['pods'][1]['status'].update(containerStatuses=[{'ready': False}]),
            lambda f: f['pods'][1]['status'].update(initContainerStatuses=[{'ready': False}]),
            lambda f: f['pods'][1]['spec'].update(nodeName='cyndaquil'),
            lambda f: f['pods'][1]['spec']['nodeSelector'].update({'kubernetes.io/hostname': 'other'}),
            lambda f: f['pods'][1]['metadata'].update(deletionTimestamp='now'),
            lambda f: f['replicas']['replica-1']['metadata']['ownerReferences'][0].update(uid='foreign'),
            lambda f: f['item']['metadata']['ownerReferences'][0].update(uid='foreign'),
            lambda f: f['item']['spec'].update(strategy={'type': 'Recreate'}),
            lambda f: f['pods'].append(copy.deepcopy(f['pods'][0])),
            lambda f: f['pods'][1]['metadata'].update(ownerReferences=copy.deepcopy(f['pods'][0]['metadata']['ownerReferences'])),
            lambda f: f['item']['spec'].update(replicas=2),
            lambda f: f['item']['metadata'].update(name='unrelated'),
            lambda f: f['owner'].update(component='fedora'),
            lambda f: f['pods'][1]['status'].update(conditions=[]),
        ]
        for i, mutate in enumerate(mutations):
            facts, api = self.fixture(); mutate(facts)
            with self.subTest(case=i):
                self.assertFalse(pending.pending_rook_rollout(api, facts['item'], facts['owner']))


class VersaReplacementTests(unittest.TestCase):
    def fixture(self):
        profile = json.loads(Path('metal/maintenance/k3s-cyndaquil-pending-versa.json').read_text())
        profile['bindings'] = [{'claim': 'data', 'claim_uid': 'claim', 'volume': 'pv', 'volume_uid': 'volume'}]
        template = {'spec': {'nodeSelector': {'kubernetes.io/hostname': 'cyndaquil'},
                    'containers': [{'name': k, 'image': v} for k, v in profile['images'].items()],
                    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}}]}}
        profile['template_sha256'] = hashed(template)
        pod = {'metadata': {'uid': profile['replacement_uid'],
                'creationTimestamp': profile['replacement_created'], 'labels': {'app': 'versa'},
                'ownerReferences': [copy.deepcopy(profile['ref']['controller'])]},
                'spec': copy.deepcopy(template['spec']), 'status': {'phase': 'Pending'}}
        deployment = {'kind': 'Deployment', 'metadata': {'namespace': 'versa', 'name': 'versa',
                'uid': profile['deployment_uid'], 'generation': profile['generation']},
                'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'versa'}}, 'template': template},
                'status': {'observedGeneration': profile['generation']}}
        replica = {'metadata': {'uid': profile['ref']['controller']['uid'],
                    'ownerReferences': [{'controller': True, 'kind': 'Deployment', 'name': 'versa',
                                          'uid': profile['deployment_uid']}]}}
        facts = {'profile': profile, 'pod': pod, 'deployment': deployment, 'replica': replica,
            'node': {'metadata': {'uid': profile['owner']['node_uid']}, 'spec': {'unschedulable': True}},
            'claim': {'metadata': {'uid': 'claim'}, 'status': {'phase': 'Bound'}, 'spec': {'volumeName': 'pv'}},
            'volume': {'metadata': {'uid': 'volume'}, 'spec': {'claimRef': {'uid': 'claim'}}},
            'app': {'metadata': {'uid': profile['application_uid']}, 'status': {'sync': {'status': 'Synced'}}}}

        class API:
            def call(self, *args):
                assert args[0] == 'get'
                if args[1] == 'pods':
                    return {'items': [facts['pod']]}
                return facts[{'node': 'node', 'deployment': 'deployment', 'replicaset': 'replica',
                              'application': 'app', 'pvc': 'claim', 'pv': 'volume'}[args[1]]]

        return facts, API()

    def invoke(self, facts, api, published=True, dirty=False):
        raw = json.dumps(facts['profile']).encode()
        def git(args):
            return (raw if published else b'different') if args[1] == 'show' else (b'changed' if dirty else b'')
        with patch.object(pending.Path, 'read_bytes', return_value=raw), \
                patch.object(pending.subprocess, 'check_output', side_effect=git):
            return pending.pending_versa_replacement(api, facts['profile']['owner'], facts['profile']['ref'])

    def test_exact_pending_replacement_is_only_drain_acceptance(self):
        facts, api = self.fixture()
        proof = self.invoke(facts, api)
        Drain.removal_proof(facts['profile']['ref'], proof)
        self.assertEqual(proof['replacement_uid'], facts['pod']['metadata']['uid'])
        self.assertNotIn('healthy', proof)
        for published, dirty in [(False, False), (True, True)]:
            with self.subTest(published=published, dirty=dirty), self.assertRaises(RuntimeError):
                self.invoke(facts, api, published, dirty)

    def test_changed_process_candidate_owner_and_storage_stop_acceptance(self):
        mutations = [
            lambda f: f['node']['spec'].update(unschedulable=False),
            lambda f: f['node']['metadata'].update(uid='foreign'),
            lambda f: f['pod']['metadata'].update(uid='foreign'),
            lambda f: f['pod']['metadata'].update(creationTimestamp='earlier'),
            lambda f: f['pod']['status'].update(phase='Running'),
            lambda f: f['pod']['status'].update(containerStatuses=[{'ready': False}]),
            lambda f: f['pod']['status'].update(initContainerStatuses=[{'ready': False}]),
            lambda f: f['pod']['spec']['containers'][0].update(image='foreign'),
            lambda f: f['pod']['spec'].update(volumes=[]),
            lambda f: f['deployment']['metadata'].update(generation=999),
            lambda f: f['deployment']['spec'].update(replicas=2),
            lambda f: f['deployment']['spec']['template']['spec'].update(hostNetwork=True),
            lambda f: f['replica']['metadata']['ownerReferences'][0].update(uid='foreign'),
            lambda f: f['claim']['metadata'].update(uid='foreign'),
            lambda f: f['volume']['spec']['claimRef'].update(uid='foreign'),
            lambda f: f['app']['status']['sync'].update(status='OutOfSync'),
        ]
        for i, mutate in enumerate(mutations):
            facts, api = self.fixture(); mutate(facts)
            with self.subTest(case=i), self.assertRaises(RuntimeError):
                self.invoke(facts, api)
        facts, api = self.fixture()
        raw = json.dumps(facts['profile']).encode()
        with patch.object(pending.Path, 'read_bytes', return_value=raw), \
                patch.object(pending.subprocess, 'check_output', return_value=raw), self.assertRaises(RuntimeError):
            pending.pending_versa_replacement(api, dict(facts['profile']['owner'], owner='foreign'), facts['profile']['ref'])


class CoherentReadTests(unittest.TestCase):
    def test_recollects_only_typed_snapshot_races(self):
        cases = [([production.SnapshotChanged('race'), {'valid': True}], 2, None),
                 (production.SnapshotChanged('race'), 3, production.SnapshotChanged),
                 (RuntimeError('unrelated failure'), 1, RuntimeError)]
        for effect, count, error in cases:
            observed = Mock(side_effect=effect)
            with self.subTest(effect=effect), patch.object(production, '_observe_once', observed):
                if error:
                    with self.assertRaises(error): production.observe(None, None, None, None)
                else:
                    self.assertEqual(production.observe(None, None, None, None), {'valid': True})
                self.assertEqual(observed.call_count, count)


if __name__ == '__main__':
    unittest.main()
