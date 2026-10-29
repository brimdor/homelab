import copy
import unittest

import maintenance_sprigatito_evacuation as evacuation


def baseline():
    pools = [{'pool': i, 'pool_name': p[0], 'size': p[1], 'min_size': p[2], 'crush_rule': p[3],
              'type': 1, 'pg_num': 1} for i, p in evacuation.POOLS.items()]
    return {
        'kured': {'metadata': {'uid': evacuation.DS_UID}},
        'pdb_state': {'metadata': {'uid': evacuation.STATE_UID}, 'data': {}},
        'node': {'metadata': {'uid': evacuation.recovery.UID}, 'spec': {},
                 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}},
        'cluster': {'metadata': {'uid': evacuation.CLUSTER_UID}, 'spec': {
            'removeOSDsIfOutAndSafeToRemove': False,
            'disruptionManagement': {'managePodBudgets': True, 'osdMaintenanceTimeout': 90}}},
        'deployment': {'metadata': {'uid': evacuation.DEPLOYMENT_UID}, 'spec': {
            'replicas': 1, 'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': 'sprigatito'}}}}},
        'metadata': {'id': 7, 'hostname': 'sprigatito', 'device_ids': 'sda=KingFast_DI0403Y002080',
                     'bluestore_bdev_partition_path': '/dev/sda3'},
        'map': {'epoch': 5, 'fsid': evacuation.FSID, 'osds': [
            {'osd': i, 'uuid': uid, 'up': 1, 'in': 1, 'weight': 1} for i, uid in evacuation.OSDS.items()],
            'pools': pools, 'flags_set': sorted(evacuation.BASE_FLAGS), 'crush_node_flags': {},
            'device_class_flags': {}, 'nearfull_ratio': 0.85},
        'quorum': {'quorum_names': ['p', 'q', 'r'], 'monmap': {
            'fsid': evacuation.FSID, 'mons': [{'name': n} for n in ['p', 'q', 'r']]}},
        'pgs': {'pg_ready': True, 'pg_stats': [
            {'pgid': str(i) + '.0', 'state': 'active+clean', 'up': [7, 2] if i != 4 else [1, 2, 6],
             'acting': [7, 2] if i != 4 else [1, 2, 6],
             'stat_sum': {'num_objects_unfound': 0, 'num_scrub_errors': 0, 'num_bytes': 1024}}
            for i in range(1, 5)]},
        'health': {'status': 'HEALTH_OK', 'checks': {}, 'mutes': []},
        'df': {'nodes': [{'id': i, 'utilization': 50, 'kb_used': 500000, 'kb': 1000000}
                        for i in evacuation.OSDS]},
    }


class EvacuationTests(unittest.TestCase):
    def test_shutdown_accepts_only_evacuated_target_and_owned_protection(self):
        value = baseline()
        value['node']['spec']['unschedulable'] = True
        next(o for o in value['map']['osds'] if o['osd'] == 7).update({'in': 0, 'weight': 0, 'up': 0})
        for pg in value['pgs']['pg_stats']:
            if pg['pgid'] != '4.0':
                pg['up'] = pg['acting'] = [1, 2]
        self.assertTrue(evacuation.validate(value, stopped=True)['complete'])
        value['map']['crush_node_flags'] = {'sprigatito': ['noout']}
        value['pdb_state']['data'] = {'draining-failure-domain': 'sprigatito', 'set-no-out': 'true'}
        value['health'] = {'status': 'HEALTH_WARN', 'checks': {'OSD_FLAGS': {'severity': 'HEALTH_WARN'}}}
        self.assertTrue(evacuation.validate(value, stopped=True)['clean'])
        for change in ('foreign-down', 'foreign-flags', 'missing-replica'):
            bad = copy.deepcopy(value)
            if change == 'foreign-down':
                bad['map']['osds'][0]['up'] = 0
            elif change == 'foreign-flags':
                bad['map']['crush_node_flags'] = {'arcanine': ['noout']}
            else:
                bad['pgs']['pg_stats'][0]['acting'] = [1]
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                evacuation.validate(bad, stopped=True)

    def test_completion_needs_full_clean_replicas_elsewhere(self):
        value = baseline()
        self.assertTrue(evacuation.validate(value, baseline=True)['clean'])
        value['node']['spec']['unschedulable'] = True
        next(o for o in value['map']['osds'] if o['osd'] == 7).update({'in': 0, 'weight': 0})
        self.assertFalse(evacuation.validate(value)['complete'])
        for pg in value['pgs']['pg_stats']:
            if pg['pgid'] != '4.0':
                pg['up'] = pg['acting'] = [1, 2]
        self.assertTrue(evacuation.validate(value)['complete'])
        bad = copy.deepcopy(value)
        bad['pgs']['pg_stats'][0]['up'] = bad['pgs']['pg_stats'][0]['acting'] = [2, 8]
        with self.assertRaisesRegex(RuntimeError, 'failure domains'):
            evacuation.validate(bad)
        bad = copy.deepcopy(value)
        bad['map']['osds'][0]['uuid'] = 'another-device'
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            evacuation.validate(bad)

    def test_offline_model_checks_each_pg_and_peak_capacity(self):
        value = baseline()
        result = {'map': {'epoch': 5, 'fsid': evacuation.FSID}, 'cleanup': '', 'mapping': '\n'.join(
            str(i) + '.0 raw ([1,2], p1) up ([' + ('1,2,6' if i == 4 else '1,2') +
            '], p1) acting ([1,2], p1)' for i in range(1, 5))}
        class API:
            def call(self, *args):
                return result
        self.assertEqual(evacuation.model(API(), value)['pg_count'], 4)
        result['mapping'] = result['mapping'].replace('up ([1,2], p1)', 'up ([2,8], p2)', 1)
        with self.assertRaisesRegex(RuntimeError, 'independent replicas'):
            evacuation.model(API(), value)

    def test_rejoin_reports_full_replica_remap_without_accepting_completion(self):
        value = baseline()
        pg = value['pgs']['pg_stats'][0]
        pg.update(state='active+remapped+backfill_wait', up=[2, 1], acting=[2, 6])
        pg['stat_sum'].update(num_objects_missing=0, num_objects_missing_on_primary=0,
                              num_objects_degraded=0)
        result = evacuation.rejoin_state(value)
        self.assertFalse(result['complete'])
        self.assertFalse(result['clean'])
        self.assertEqual(result['unrelated_fully_replicated_remaps'], [
            {'pgid': pg['pgid'], 'state': pg['state'], 'up': [2, 1], 'acting': [2, 6]}])
        for field in ('num_objects_missing', 'num_objects_missing_on_primary', 'num_objects_degraded'):
            bad = copy.deepcopy(value); bad['pgs']['pg_stats'][0]['stat_sum'][field] = 1
            with self.subTest(field=field), self.assertRaises(RuntimeError): evacuation.rejoin_state(bad)
            del bad['pgs']['pg_stats'][0]['stat_sum'][field]
            with self.subTest(missing=field), self.assertRaises(RuntimeError): evacuation.rejoin_state(bad)
        for state, acting in [('active+undersized', [2]), ('active+degraded+remapped', [2, 6]),
                              ('active+remapped+backfill_wait', [2, 8]),
                              ('active+remapped+backfill_wait', [2, 2])]:
            bad = copy.deepcopy(value); bad['pgs']['pg_stats'][0].update(state=state, acting=acting)
            with self.subTest(state=state, acting=acting), self.assertRaises(RuntimeError):
                evacuation.rejoin_state(bad)
        pg.update(state='active+clean', acting=[2, 1])
        self.assertTrue(evacuation.rejoin_state(value)['complete'])
