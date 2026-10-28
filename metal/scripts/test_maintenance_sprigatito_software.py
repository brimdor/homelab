"""Evacuated software maintenance must retain complete independent replicas."""

import copy
import json
import unittest
from unittest.mock import patch

import maintenance_osd_host as osd
import maintenance_production_node as production
import maintenance_sprigatito_evacuation as evacuation
from maintenance_coordination import JOURNAL
from test_maintenance_sprigatito_evacuation import baseline


def evacuated():
    value = baseline()
    next(o for o in value['map']['osds'] if o['osd'] == 7).update({'in': 0, 'weight': 0})
    for pg in value['pgs']['pg_stats']:
        if pg['pgid'] != '4.0':
            pg['up'] = pg['acting'] = [1, 2]
    return value


class SoftwareTests(unittest.TestCase):
    def test_out_osd_requires_full_replicas_and_exact_owned_downtime(self):
        value = evacuated()
        with patch.object(evacuation, 'collect', return_value=value):
            self.assertEqual(osd.observe(None, 'sprigatito')['scope'], 'EVACUATED_OSD7_FULL_REPLICAS')
            for fault in ('unowned-down', 'foreign-down', 'dependent', 'same-host', 'foreign-owner', 'foreign-flag'):
                bad = copy.deepcopy(value)
                if fault == 'unowned-down':next(o for o in bad['map']['osds'] if o['osd'] == 7)['up'] = 0
                if fault == 'foreign-down':bad['map']['osds'][0]['up'] = 0
                if fault == 'dependent':bad['pgs']['pg_stats'][0]['acting'] = [7, 2]
                if fault == 'same-host':bad['pgs']['pg_stats'][0]['up'] = bad['pgs']['pg_stats'][0]['acting'] = [2, 8]
                if fault == 'foreign-owner':bad['kured']['metadata']['annotations'] = {JOURNAL: json.dumps({'node': 'arcanine'})}
                if fault == 'foreign-flag':bad['map']['crush_node_flags'] = {'arcanine': ['noout']}
                with self.subTest(fault=fault), patch.object(evacuation, 'collect', return_value=bad), self.assertRaises(RuntimeError):
                    osd.observe(None, 'sprigatito')
        value['kured']['metadata']['annotations'] = {JOURNAL: json.dumps({
            'node': 'sprigatito', 'node_uid': evacuation.recovery.UID, 'source': 39, 'target': 41, 'owner': 'synthetic'})}
        value['node']['spec']['unschedulable'] = True
        next(o for o in value['map']['osds'] if o['osd'] == 7)['up'] = 0
        with patch.object(evacuation, 'collect', return_value=value):
            self.assertEqual(osd.observe(None, 'sprigatito')['owner'], 'synthetic')

    def test_exact_profile_and_native_programs_compile(self):
        names = ('NODE', 'ADDRESS', 'UID', 'MAC', 'IDENTITY', 'BACKUPS', 'RECEIVER', 'RECEIVER_ADDRESS', 'RECEIVER_IDENTITY')
        original = {name: getattr(production, name) for name in names}
        try:
            production.select_node('sprigatito')
            self.assertEqual(production.UID, evacuation.recovery.UID)
            self.assertEqual(production.BACKUPS[39], evacuation.recovery.POINT)
            self.assertEqual(osd.targets_for('sprigatito'), {7: evacuation.DEPLOYMENT_UID})
            compile(production.NATIVE, 'native-controller', 'exec')
            compile(osd.SPRIGATITO_NATIVE_IDENTITY, 'native-identities', 'exec')
            self.assertIn("'/sys/class/net/eno1/address'", osd.SPRIGATITO_NATIVE_IDENTITY)
        finally:
            for name, value in original.items():setattr(production, name, value)


if __name__ == '__main__':
    unittest.main()
