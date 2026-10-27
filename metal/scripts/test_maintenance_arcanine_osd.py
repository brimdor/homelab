"""Arcanine's two OSDs form one failure domain, never two independent stops."""

import ast
import copy
import datetime
import json
import unittest
from unittest.mock import patch

import maintenance_osd_host as osd
from maintenance_coordination import JOURNAL
from test_maintenance_osd_host import fixture, NOW
from test_maintenance_osd_protection_wait import API as ProtectionAPI


def arcanine(owned=False, down=()):
    value = fixture(owned)
    profile = osd.profile_for('arcanine')
    value['node']['metadata'].update(name='arcanine', uid=profile['node_uid'])
    template = value.pop('deployment')
    value['deployments'] = {}
    for target, uid in profile['osds'].items():
        deployment = copy.deepcopy(template)
        deployment['metadata']['uid'] = uid
        deployment['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname'] = 'arcanine'
        if target in down:
            deployment['status']['readyReplicas'] = 0
        value['deployments'][target] = deployment
    value['ok_to_stop']['osds'] = [2, 8]
    if owned:
        owner = json.loads(value['kured']['metadata']['annotations'][JOURNAL])
        owner.update(node='arcanine', node_uid=profile['node_uid'])
        value['kured']['metadata']['annotations'][JOURNAL] = json.dumps(owner)
    if down:
        value['restored_mapping'] = {p['pgid']: p['up'][:] for p in value['pgs']}
        for item in value['map']['osds']:
            if item['osd'] in down:
                item['up'] = 0
        value['map']['crush_node_flags'] = {'arcanine': ['noout']}
        value['pdb_state']['data'] = {'draining-failure-domain': 'arcanine', 'set-no-out': 'true',
            'arcanine-noout-last-set-at': (NOW - datetime.timedelta(minutes=5)).isoformat()}
        value['health'] = {'status': 'HEALTH_WARN', 'checks': {
            name: {'severity': 'HEALTH_WARN'} for name in ('OSD_DOWN', 'OSD_FLAGS', 'PG_DEGRADED')}, 'mutes': []}
        for pg in value['pgs']:
            if set(down) & set(pg['up']):
                pg.update(state='active+undersized+degraded',
                          up=[i for i in pg['up'] if i not in down],
                          acting=[i for i in pg['acting'] if i not in down])
    return value


class ArcanineOSDTests(unittest.TestCase):
    def test_stable_owner_interval_with_either_or_both_exact_osds_down(self):
        clean = osd.validate(arcanine(), NOW, node='arcanine')
        self.assertEqual(clean['scope'], 'HEALTH_OK')
        self.assertEqual(clean['osds'], {str(i): osd.OSDS[i] for i in (2, 8)})
        expected = osd.validate(arcanine(True), NOW, node='arcanine')
        self.assertEqual(expected['managed_deployment_uids'], sorted(osd.targets_for('arcanine').values()))
        for down in ((2,), (8,), (2, 8)):
            with self.subTest(down=down):
                self.assertEqual(osd.validate(arcanine(True, down), NOW, node='arcanine'), expected)

    def test_combined_stop_and_all_controller_identities_are_required(self):
        cases = [
            lambda v: v['ok_to_stop'].update(osds=[2]),
            lambda v: v['ok_to_stop'].update(ok_to_stop=False),
            lambda v: v['deployments'].pop(8),
            lambda v: v['deployments'].update({7: copy.deepcopy(v['deployments'][8])}),
            lambda v: v['deployments'][8]['metadata'].update(uid='replacement'),
            lambda v: v['deployments'][2]['status'].update(readyReplicas=0),
            lambda v: v['pgs'][0].update(up=[2, 8], acting=[2, 8]),
        ]
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                value = arcanine(); change(value)
                with self.assertRaises(RuntimeError):
                    osd.validate(value, NOW, node='arcanine')

    def test_foreign_failures_missing_survivors_and_expired_protection_are_rejected(self):
        cases = [
            lambda v: v['map']['osds'][0].update(up=0),
            lambda v: v['kured']['metadata'].update(annotations={}),
            lambda v: v['node']['spec'].update(unschedulable=False),
            lambda v: v['deployments'][8]['metadata'].update(uid='replacement'),
            lambda v: v['pgs'][2].update(acting=[1]),
            lambda v: v.pop('restored_mapping'),
            lambda v: v['pdb_state']['data'].update({'arcanine-noout-last-set-at':
                (NOW - datetime.timedelta(minutes=90)).isoformat()}),
            lambda v: v['health']['checks'].update({'MON_DOWN': {'severity': 'HEALTH_WARN'}}),
        ]
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                value = arcanine(True, (2, 8)); change(value)
                with self.assertRaises((RuntimeError, KeyError)):
                    osd.validate(value, NOW, node='arcanine')

    def test_both_exact_evictions_wait_for_the_same_rook_host_protection(self):
        for target in (2, 8):
            api = ProtectionAPI('cyndaquil')
            profile = osd.profile_for('arcanine')
            api.owner.update(node='arcanine', node_uid=profile['node_uid'])
            api.ds['metadata']['annotations'][JOURNAL] = json.dumps(api.owner)
            api.node['metadata']['uid'] = profile['node_uid']
            api.ref['controller']['name'] = 'rook-ceph-osd-' + str(target) + '-abc123'
            api.replica['metadata']['ownerReferences'][0]['uid'] = profile['osds'][target]
            api.after['data']['draining-failure-domain'] = 'arcanine'
            api.map['crush_node_flags'] = {'arcanine': ['noout']}
            with patch.object(osd, 'observe', return_value={'owner': api.owner['owner']}):
                result = osd.wait_for_protection(api, 'arcanine', api.owner, api.ref)
            self.assertEqual(result['osd'], target)
            self.assertFalse(result['mutation_performed'])

    def test_observer_requests_combined_stop_and_readonly_map_restoration(self):
        value = arcanine(True, (2, 8))
        calls = []

        class API:
            def call(self, *args):
                calls.append(args)
                if args[0] == 'get':
                    if args[1] == 'deployment':
                        return value['deployments'][int(args[2].rsplit('-', 1)[1])]
                    return value[{'node': 'node', 'cephcluster': 'cluster', 'daemonset': 'kured',
                                  'configmap': 'pdb_state'}[args[1]]]
                command = args[args.index('--') + 1:]
                if command[0] == 'python3':
                    return {'map': value['map'], 'temporary_removed': True, 'mapping': '\n'.join(
                        p + ' raw ([' + ','.join(map(str, ids)) + '], p1) up ([' +
                        ','.join(map(str, ids)) + '], p1) acting ([], p-1)'
                        for p, ids in value['restored_mapping'].items())}
                if command[1] == 'status':return {'pgmap': {'num_pgs': value['num_pgs']}}
                if command[1] == 'osd':
                    return value['map'] if command[2] == 'dump' else value['ok_to_stop']
                if command[1] == 'quorum_status':return value['quorum']
                if command[1] == 'health':return value['health']
                if command[1] == 'pg':return {'pg_stats': value['pgs']}
                raise AssertionError(command)

        with patch.object(osd.datetime, 'datetime', wraps=datetime.datetime) as clock:
            clock.now.return_value = NOW
            osd.observe(API(), node='arcanine')
        mapping = next(c for c in calls if 'python3' in c)
        self.assertEqual(mapping[-2:], ('2', '8'))
        calls.clear(); value = arcanine()
        osd.observe(API(), node='arcanine')
        self.assertTrue(any(c[-5:] == ('ok-to-stop', '2', '8', '--format', 'json') for c in calls))
        ast.parse(osd.OFFLINE_MAPPING)
        self.assertNotIn("'--save'", osd.OFFLINE_MAPPING)
        self.assertIn("['--mark-up-in']", osd.OFFLINE_MAPPING)


if __name__ == '__main__':
    unittest.main()
