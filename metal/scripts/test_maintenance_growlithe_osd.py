"""Second serial OSD profile must never authorize a foreign failure domain."""
import ast
import datetime
import json
import unittest
import maintenance_osd_host as osd
from test_maintenance_osd_host import fixture, NOW
from maintenance_coordination import JOURNAL


def growlithe(owned=False, down=False):
    value=fixture(owned)
    value['node']['metadata'].update(name='growlithe',uid=osd.PROFILES['growlithe']['node_uid'])
    value['deployment']['metadata']['uid']=osd.PROFILES['growlithe']['deployment_uid']
    value['deployment']['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname']='growlithe'
    value['ok_to_stop']['osds']=[6]
    if owned:
        owner=json.loads(value['kured']['metadata']['annotations'][JOURNAL])
        owner.update(node='growlithe',node_uid=osd.PROFILES['growlithe']['node_uid'])
        value['kured']['metadata']['annotations'][JOURNAL]=json.dumps(owner)
    if down:
        value['restored_mapping']={p['pgid']:p['up'][:]for p in value['pgs']}
        next(o for o in value['map']['osds']if o['osd']==6)['up']=0
        value['map']['crush_node_flags']={'growlithe':['noout']}
        value['pdb_state']['data']={'draining-failure-domain':'growlithe','set-no-out':'true',
            'growlithe-noout-last-set-at':(NOW-datetime.timedelta(minutes=5)).isoformat()}
        value['health']={'status':'HEALTH_WARN','checks':{n:{'severity':'HEALTH_WARN'}for n in ('OSD_DOWN','OSD_FLAGS','PG_DEGRADED')},'mutes':[]}
        value['deployment']['status']['readyReplicas']=0
        value['pgs'][1].update(state='active+undersized+degraded',up=[7],acting=[7])
        value['pgs'][2].update(state='active+undersized+degraded',up=[1,8],acting=[1,8])
    return value


class GrowlitheOSDTests(unittest.TestCase):
    def test_clean_and_exact_owned_osd_six(self):
        self.assertEqual(osd.validate(growlithe(),NOW,node='growlithe')['osd'],6)
        self.assertEqual(osd.validate(growlithe(True,True),NOW,node='growlithe')['scope'],'OWNED_OSD_HOST_INTERVAL')

    def test_foreign_down_osd_or_cyndaquil_identity_is_rejected(self):
        value=growlithe(True)
        next(o for o in value['map']['osds']if o['osd']==1)['up']=0
        with self.assertRaisesRegex(RuntimeError,'unowned or unrelated'):osd.validate(value,NOW,node='growlithe')
        with self.assertRaisesRegex(RuntimeError,'identity differs'):osd.validate(fixture(),NOW,node='growlithe')

    def test_owned_lease_expiry_and_survivor_loss_are_rejected(self):
        value=growlithe(True,True)
        value['pdb_state']['data']['growlithe-noout-last-set-at']=(NOW-datetime.timedelta(minutes=90)).isoformat()
        with self.assertRaisesRegex(RuntimeError,'expired'):osd.validate(value,NOW,node='growlithe')
        value=growlithe(True,True);value['pgs'][2]['acting']=[1]
        with self.assertRaisesRegex(RuntimeError,'surviving replica'):osd.validate(value,NOW,node='growlithe')

    def test_unknown_profile_is_refused_before_api_read(self):
        with self.assertRaisesRegex(RuntimeError,'unreviewed'):osd.observe(None,node='unreviewed-host')

    def test_native_program_guards_both_disks_and_real_nvme_osd(self):
        ast.parse(osd.NATIVE_IDENTITY);ast.parse(osd.GROWLITHE_NATIVE_IDENTITY)
        for value in ('3C320074050513551212','S58SNM0R508184P','7f1094b0-d185-448d-9a09-6a35e46309e5','af9a1561-010c-4a61-b73b-e54c75f5c44b','e7ccd0a2-4d7a-41bb-aac9-5464abe2ba85'):
            self.assertIn(value,osd.GROWLITHE_NATIVE_IDENTITY)
        self.assertIn("os.readlink(root/'block')=='/dev/nvme0n1p1'",osd.GROWLITHE_NATIVE_IDENTITY)
        self.assertIn("('whoami','6')",osd.GROWLITHE_NATIVE_IDENTITY)
        self.assertNotIn('10.0.40.3',osd.GROWLITHE_NATIVE_IDENTITY)


if __name__=='__main__':unittest.main()
