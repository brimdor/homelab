"""Focused safety regressions for the exact Issue 103 OSD host interval."""

import copy
import datetime
import json
import unittest

import maintenance_osd_host as osd
from maintenance_coordination import JOURNAL


NOW = datetime.datetime(2026, 10, 27, 1, tzinfo=datetime.timezone.utc)
OWNER = {'owner': 'homelab-maintenance-103-00000000-0000-4000-8000-000000000000',
         'node': osd.NODE, 'node_uid': osd.NODE_UID, 'source': 39, 'target': 41}


def fixture(owned=False, down=False):
    value = {
        'node': {'metadata': {'name': osd.NODE, 'uid': osd.NODE_UID},
                 'spec': {'unschedulable': owned}},
        'cluster': {'metadata': {'uid': osd.CLUSTER_UID}, 'spec': {
            'removeOSDsIfOutAndSafeToRemove': False,
            'disruptionManagement': {'managePodBudgets': True, 'osdMaintenanceTimeout': 90}}},
        'deployment': {'metadata': {'uid': osd.DEPLOYMENT_UID, 'generation': 1},
                       'spec': {'replicas': 1, 'template': {'spec': {'nodeSelector': {
                           'kubernetes.io/hostname': osd.NODE}}}},
                       'status': {'observedGeneration': 1, 'readyReplicas': 1, 'updatedReplicas': 1}},
        'kured': {'metadata': {'uid': '4abc4fee-c3be-440e-8945-34bb3fb15ce1',
                               'annotations': {JOURNAL: json.dumps(OWNER)} if owned else {}}},
        'pdb_state': {'metadata': {'uid': osd.STATE_UID},
                      'data': {'draining-failure-domain': '', 'set-no-out': ''}},
        'map': {'fsid': osd.FSID, 'flags_set': sorted(osd.BASE_FLAGS),
                'device_class_flags': {}, 'crush_node_flags': {},
                'osds': [{'osd': i, 'uuid': uid, 'in': 1, 'up': 1, 'weight': 1,
                         'state': ['exists', 'up']} for i, uid in osd.OSDS.items()],
                'pools': [{'pool': i, 'pool_name': p[0], 'type': 1, 'size': p[1],
                           'min_size': p[2], 'crush_rule': p[3]} for i, p in osd.POOLS.items()]},
        'quorum': {'monmap': {'fsid': osd.FSID, 'mons': [{'name': n} for n in 'lno']},
                   'quorum_names': list('lno')},
        'health': {'status': 'HEALTH_OK', 'checks': {}, 'mutes': []},
        'pgs': [{'pgid': '1.1', 'state': 'active+clean', 'up': [1, 2], 'acting': [1, 2]},
                {'pgid': '1.2', 'state': 'active+clean', 'up': [6, 7], 'acting': [6, 7]},
                {'pgid': '4.1', 'state': 'active+clean', 'up': [1, 6, 8], 'acting': [1, 6, 8]}],
        'num_pgs': 3, 'ok_to_stop': {'ok_to_stop': True, 'osds': [1], 'num_not_ok_pgs': 0}}
    if down:
        value['map']['osds'][0]['up'] = 0
        value['map']['crush_node_flags'] = {osd.NODE: ['noout']}
        value['pdb_state']['data'] = {'draining-failure-domain': osd.NODE, 'set-no-out': 'true',
                                     osd.NODE + '-noout-last-set-at': (NOW - datetime.timedelta(minutes=5)).isoformat()}
        value['health'] = {'status': 'HEALTH_WARN', 'checks': {
            n: {'severity': 'HEALTH_WARN'} for n in ['OSD_DOWN', 'OSD_FLAGS', 'PG_DEGRADED']}, 'mutes': []}
        value['deployment']['status']['readyReplicas'] = 0
        value['pgs'][0].update(state='active+undersized+degraded', acting=[2])
        value['pgs'][2].update(state='active+undersized+degraded', acting=[6, 8])
    return value


class OSDHostTests(unittest.TestCase):
    def test_clean_and_exact_owned_down_state(self):
        self.assertEqual(osd.validate(fixture(), NOW)['scope'], 'HEALTH_OK')
        self.assertEqual(osd.validate(fixture(True, True), NOW)['scope'], 'OWNED_OSD_HOST_INTERVAL')

    def test_owner_interval_stable_across_cordon(self):
        before = fixture(True);before['node']['spec']['unschedulable'] = False
        self.assertEqual(osd.validate(before, NOW), osd.validate(fixture(True), NOW))
        self.assertEqual(osd.validate(before, NOW), osd.validate(fixture(True, True), NOW))

    def test_rejection_boundaries(self):
        cases = [
            ('unowned', lambda v: v['kured']['metadata'].update(annotations={})),
            ('uncordoned', lambda v: v['node']['spec'].update(unschedulable=False)),
            ('node identity', lambda v: v['node']['metadata'].update(uid='foreign')),
            ('owner identity', lambda v: v['kured']['metadata']['annotations'].update({JOURNAL: json.dumps(dict(OWNER, node_uid='foreign'))})),
            ('second down', lambda v: v['map']['osds'][1].update(up=0)),
            ('out target', lambda v: v['map']['osds'][0].update({'in': 0})),
            ('OSD replacement', lambda v: v['map']['osds'][0].update(uuid='replacement')),
            ('global flag', lambda v: v['map']['flags_set'].append('noout')),
            ('foreign noout', lambda v: v['map'].update(crush_node_flags={'growlithe': ['noout']})),
            ('missing noout', lambda v: v['map'].update(crush_node_flags={})),
            ('other domain', lambda v: v['pdb_state']['data'].update({'draining-failure-domain': 'growlithe'})),
            ('expired', lambda v: v['pdb_state']['data'].update({osd.NODE + '-noout-last-set-at': (NOW - datetime.timedelta(minutes=90)).isoformat()})),
            ('future', lambda v: v['pdb_state']['data'].update({osd.NODE + '-noout-last-set-at': (NOW + datetime.timedelta(seconds=1)).isoformat()})),
            ('inactive PG', lambda v: v['pgs'][0].update(state='peering+undersized')),
            ('missing PG', lambda v: v.update(num_pgs=4)),
            ('no live replica', lambda v: v['pgs'][0].update(acting=[1])),
            ('mgr quorum lost', lambda v: v['pgs'][2].update(acting=[6])),
            ('unrelated degraded PG', lambda v: v['pgs'][1].update(state='active+undersized+degraded')),
            ('replication change', lambda v: v['map']['pools'][0].update(min_size=2)),
            ('unrelated warning', lambda v: v['health']['checks'].update({'PG_DAMAGED': {'severity': 'HEALTH_WARN'}})),
            ('muted finding', lambda v: v['health']['mutes'].append({'code': 'PG_DAMAGED'})),
            ('quorum lost', lambda v: v['quorum'].update(quorum_names=['l', 'n'])),
            ('protection removed', lambda v: v['cluster']['spec'].update(removeOSDsIfOutAndSafeToRemove=True)),
            ('deployment replaced', lambda v: v['deployment']['metadata'].update(uid='replacement'))]
        for label, change in cases:
            with self.subTest(label=label):
                value = copy.deepcopy(fixture(True, True));change(value)
                with self.assertRaises((RuntimeError, KeyError, ValueError)):
                    osd.validate(value, NOW)

    def test_healthy_still_requires_stop_safety_and_clean_pgs(self):
        value = fixture();value['ok_to_stop']['ok_to_stop'] = False
        with self.assertRaisesRegex(RuntimeError, 'not safe to stop'):osd.validate(value, NOW)
        value = fixture();value['pgs'][0]['state'] = 'active+undersized+degraded'
        with self.assertRaisesRegex(RuntimeError, 'unhealthy PG'):osd.validate(value, NOW)


    def test_controller_exception_is_exact_and_other_hosts_stay_strict(self):
        from unittest import mock
        import maintenance_production_node as production
        nodes = [{'metadata': {'name': osd.NODE if i == 0 else 'peer-' + str(i),
                               'uid': osd.NODE_UID if i == 0 else 'peer-' + str(i)},
                  'status': {'conditions': [{'type': 'Ready', 'status': 'True'},
                      *[{'type': name, 'status': 'False'} for name in
                        ('DiskPressure', 'MemoryPressure', 'PIDPressure')]]}} for i in range(9)]
        target = fixture(True, True)['deployment']
        target['metadata'].update(namespace='rook-ceph', name='rook-ceph-osd-1')

        class API:
            deployments = [target]

            def call(self, *args):
                if args[:2] == ('get', 'nodes'):return {'items': nodes}
                if args[:2] == ('get', 'deployments'):return {'items': self.deployments}
                if args[:2] == ('get', 'statefulsets'):return {'items': []}
                if args[0] == 'exec':return {'status': 'HEALTH_WARN'}
                raise AssertionError(args)

        api = API()
        gate = osd.validate(fixture(True, True), NOW)
        with mock.patch.object(production, 'NODE', osd.NODE), mock.patch.object(
                production, 'UID', osd.NODE_UID), mock.patch.object(osd, 'observe', return_value=gate) as observe:
            self.assertEqual(production.prerequisites(api)['osd_host'], gate)
            observe.assert_called_once_with(api)
            foreign = copy.deepcopy(target);foreign['metadata'].update(uid='unreviewed', name='rook-ceph-osd-2')
            api.deployments = [target, foreign]
            with self.assertRaisesRegex(RuntimeError, 'controller unready'):
                production.prerequisites(api)
        nodes[1]['metadata']['name'] = 'totodile'
        with mock.patch.object(production, 'NODE', 'totodile'), mock.patch.object(production, 'UID', 'peer-1'):
            with self.assertRaisesRegex(RuntimeError, 'not HEALTH_OK'):
                production.prerequisites(api)


    def test_uncordon_acceptance_waits_for_osd_recovery_without_replaying_patch(self):
        import types
        import maintenance_production_node as production
        start = production.NATIVE.index("elif operation in('cordon','restore-scheduling'):")
        end = production.NATIVE.index("elif operation in('trusted-reconnect'", start)
        block = production.NATIVE[start:end].replace('elif operation', 'if operation', 1)

        class StoredPlan:
            def __truediv__(self, name):return self
            def exists(self):return True
            def read_bytes(self):return b'{}'

        class Worker:
            dispatches = 0
            observations = 0

            def dispatch(self, *args):self.dispatches += 1
            def observe(self, *args):
                self.observations += 1
                return {'accepted': True}

        worker = Worker()
        pending = {'step': 'restore_scheduling'}
        scope = {'operation': 'restore-scheduling', 'expected_node': 'cyndaquil',
                 'owner': {'owner': 'test'}, 'root': StoredPlan(),
                 'state': {'pending': None, 'completed': []},
                 'journal': types.SimpleNamespace(inspect=lambda: {'pending': pending}),
                 'api': None, 'scheduling': types.SimpleNamespace(Scheduling=lambda *args: worker),
                 'evidence': lambda: {}, 'prerequisites': lambda value: lambda *args: True,
                 'drain': types.SimpleNamespace(hashed=lambda value: 'digest'),
                 'hops': types.SimpleNamespace(STEPS=['restore_scheduling']), 'json': json}
        exec(block, scope)
        self.assertFalse(scope['result']['accepted'])
        self.assertEqual((worker.dispatches, worker.observations), (1, 0))
        scope['state']['pending'] = pending
        exec(block, scope)
        self.assertTrue(scope['result']['accepted'])
        self.assertEqual((worker.dispatches, worker.observations), (1, 1))
        scope['state']['pending'] = None;scope['expected_node'] = 'totodile'
        exec(block, scope)
        self.assertTrue(scope['result']['accepted'])
        self.assertEqual((worker.dispatches, worker.observations), (2, 2))


if __name__ == '__main__':
    unittest.main()
