"""Exact bridge authentication exceptions retain OSD safety gates."""
import copy
import json
import unittest
import maintenance_osd_host as osd
from test_maintenance_osd_host import fixture, NOW, OWNER
from maintenance_coordination import JOURNAL

def bridge_fixture(owned=False, down=False):
    value=fixture(owned,down)
    value['cluster']['status']={'phase':'Ready','cephx':{'csi':{
        'keyGeneration':1,'keyType':'aes256k','priorKeyCount':1,'keyCephVersion':'20.2.4-0'}}}
    if owned:
        owner=dict(OWNER,component='k3s',source='v1.33.6+k3s1',target='v1.33.10+k3s1')
        value['kured']['metadata']['annotations'][JOURNAL]=json.dumps(owner)
    value['health']['status']='HEALTH_WARN'
    value['health']['checks'].update({name:{'severity':'HEALTH_WARN'}for name in osd.K3S_AUTH_WARNINGS})
    return value

class BridgeOSDTests(unittest.TestCase):
    def test_unowned_auth_migration_is_visible_and_requires_recovered_data_plane(self):
        value=bridge_fixture()
        result=osd.validate(value,NOW,k3s_bridge=True)
        self.assertEqual(result['scope'],'K3S_AUTH_MIGRATION')
        self.assertEqual(result['health'],'HEALTH_WARN')
        self.assertEqual(set(result['auth_migration_findings']),osd.K3S_AUTH_WARNINGS)
        value['map']['osds'][0]['up']=0
        with self.assertRaises(RuntimeError):osd.validate(value,NOW,k3s_bridge=True)

    def test_owned_auth_and_exact_target_degradation_union(self):
        result=osd.validate(bridge_fixture(True,True),NOW,k3s_bridge=True)
        self.assertEqual(result['scope'],'OWNED_OSD_HOST_INTERVAL')
        self.assertEqual(set(result['auth_migration_findings']),osd.K3S_AUTH_WARNINGS)

    def test_default_fedora_gate_never_accepts_bridge_or_auth(self):
        for value in(bridge_fixture(),bridge_fixture(True),bridge_fixture(True,True)):
            with self.assertRaises(RuntimeError):osd.validate(value,NOW)

    def test_owner_is_exact_and_no_component_or_version_substitution(self):
        for field,new in(('node_uid','foreign'),('owner','invalid'),('node','growlithe'),
                          ('component','fedora'),('source','v1.33.10+k3s1'),('target','v1.33.13+k3s2')):
            value=bridge_fixture(True,True)
            owner=json.loads(value['kured']['metadata']['annotations'][JOURNAL]);owner[field]=new
            value['kured']['metadata']['annotations'][JOURNAL]=json.dumps(owner)
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                osd.validate(value,NOW,k3s_bridge=True)

    def test_csi_migration_identity_and_generation_required(self):
        for field,new in(('keyCephVersion','foreign'),('keyGeneration',0),('keyGeneration',2),('keyType','aes128'),('priorKeyCount',0),('priorKeyCount',2)):
            value=bridge_fixture(True,True)
            value['cluster']['status']['cephx']['csi'][field]=new
            with self.subTest(field=field,new=new),self.assertRaises(RuntimeError):
                osd.validate(value,NOW,k3s_bridge=True)
        value=bridge_fixture();value['cluster']['status']['phase']='Progressing'
        with self.assertRaises(RuntimeError):osd.validate(value,NOW,k3s_bridge=True)

    def test_auth_migration_does_not_mask_health_or_pg_regressions(self):
        for label,change in(
                ('foreign warning',lambda v:v['health']['checks'].update({'PG_DAMAGED':{'severity':'HEALTH_WARN'}})),
                ('wrong severity',lambda v:v['health']['checks']['AUTH_INSECURE_KEYS_ALLOWED'].update(severity='HEALTH_ERR')),
                ('false healthy',lambda v:v['health'].update(status='HEALTH_OK')),
                ('muted',lambda v:v['health']['mutes'].append({'code':'PG_DAMAGED'})),
                ('unrelated OSD down',lambda v:v['map']['osds'][1].update(up=0)),
                ('missing noout',lambda v:v['map'].update(crush_node_flags={})),
                ('unrelated degraded PG',lambda v:v['pgs'][1].update(state='active+undersized+degraded')),
                ('no replica',lambda v:v['pgs'][0].update(acting=[1])),
                ('bad mapping',lambda v:v['restored_mapping'].update({'1.1':[6,2]})),
                ('quorum lost',lambda v:v['quorum'].update(quorum_names=['l','n'])),
                ('unknown backend',lambda v:v['map']['osds'][0].update(uuid='foreign'))):
            value=bridge_fixture(True,True);change(value)
            with self.subTest(label=label),self.assertRaises(RuntimeError):
                osd.validate(value,NOW,k3s_bridge=True)

    def test_uncordoned_recovery_requires_all_osds_and_flags_restored(self):
        value=bridge_fixture(True);value['node']['spec']['unschedulable']=False
        self.assertEqual(osd.validate(value,NOW,k3s_bridge=True)['health'],'HEALTH_WARN')
        for change in(lambda v:v['map'].update(crush_node_flags={osd.NODE:['noout']}),
                      lambda v:v['map']['osds'][0].update(up=0),
                      lambda v:v['deployment']['status'].update(readyReplicas=0)):
            changed=copy.deepcopy(value);change(changed)
            with self.assertRaises(RuntimeError):osd.validate(changed,NOW,k3s_bridge=True)

if __name__=='__main__':unittest.main()
