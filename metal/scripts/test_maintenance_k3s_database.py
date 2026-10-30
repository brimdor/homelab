"""Totodile's database outage allowance rejects changes outside its published identities."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import maintenance_production_node as shared
import maintenance_k3s_production as current

observe_dependency = current.pending_postgres_bridge

def fixture():
 owner={'component':'k3s','node':'totodile','node_uid':'node-uid','source':current.SOURCE,'target':current.TARGET,'phase':'OWNED_KURED_ONLY','owner':'homelab-maintenance-103-00000000-0000-4000-8000-000000000001','created':'2026-10-30T00:00:00Z'}
 dep={'kind':'Deployment','metadata':{'namespace':'versa','name':'versa','uid':'deployment','generation':40},'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'web','image':'immutable'}]}}}}
 database={'kind':'Deployment','metadata':{'namespace':'postgres','name':'postgres','uid':'database','generation':15},'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'postgres','image':'pg-immutable'}],'volumes':[{'name':'db','persistentVolumeClaim':{'claimName':'postgres'}}]}}}}
 def deployment_ref(v):
  meta=v['metadata'];return {**{k:meta[k]for k in('namespace','name','uid','generation')},'template_sha256':hashlib.sha256(shared.encoded(v['spec']['template']).encode()).hexdigest()}
 states=[{'name':name,'containerID':name+'-container','imageID':name+'-digest','restartCount':0,'started':True,'ready':name=='worker','state':{'running':{'startedAt':'2026-10-29T20:00:00Z'}}}for name in('web','worker')]
 init=[{'name':'migrate','containerID':'migration-container','imageID':'migration-digest','restartCount':0,'state':{'terminated':{'finishedAt':'2026-10-29T19:59:59Z','exitCode':0}}}]
 pod={'metadata':{'name':'versa-pod','uid':'dependent-pod','ownerReferences':[{'kind':'ReplicaSet','controller':True,'name':'replica','uid':'replica-uid'}]},'spec':{'nodeName':'cyndaquil'},'status':{'phase':'Running','containerStatuses':states,'initContainerStatuses':init}}
 replica={'metadata':{'uid':'replica-uid','ownerReferences':[{'kind':'Deployment','controller':True,'uid':'deployment'}]}}
 dbpod={'metadata':{'uid':'new-db-pod','creationTimestamp':'2026-10-30T00:01:00Z'},'spec':{'containers':copy.deepcopy(database['spec']['template']['spec']['containers']),'volumes':copy.deepcopy(database['spec']['template']['spec']['volumes'])},'status':{'phase':'Pending'}}
 claim={'metadata':{'uid':'claim-uid'},'status':{'phase':'Bound'},'spec':{'volumeName':'pv'}}
 volume={'metadata':{'uid':'pv-uid'},'spec':{'claimRef':{'uid':'claim-uid'}}}
 expected=deployment_ref(dep);expected.update(pod_uid='dependent-pod',node='cyndaquil',replica_uid='replica-uid',replica_name='replica',containers={c['name']:{k:c[k]for k in('containerID','imageID','restartCount')}|{'time':c['state']['running']['startedAt']if c in states else c['state']['terminated']['finishedAt']}for c in states+init})
 dbref=deployment_ref(database);dbref.update(original_pod_uid='original-db-pod',bindings=[{'claim':'postgres','claim_uid':'claim-uid','volume':'pv','volume_uid':'pv-uid'}])
 profile={'node_uid':'node-uid','database':dbref,'dependents':{'versa':expected}}
 facts={'owner':owner,'dep':dep,'profile':profile,'database':database,'pod':pod,'replica':replica,'dbpod':dbpod,'claim':claim,'volume':volume,'node':{'metadata':{'uid':'node-uid'},'spec':{'unschedulable':True}},'proof':{'host':'postgres.postgres.svc.cluster.local','health':200,'ok':True,'readiness':503,'ready':False}}
 class API:
  def call(self,*args):
   if args[0]=='exec':return facts['proof']
   kind=args[1]
   if kind=='pods':return {'items':[facts['dbpod']if args[3]=='postgres'else facts['pod']]}
   return facts[{'node':'node','deployment':'database','pvc':'claim','pv':'volume','replicaset':'replica'}[kind]]
 return facts,API()
def invoke(facts,api,pending=True):
 with patch.object(shared,'pending_on_maintained_node',return_value=pending):
  return observe_dependency(api,facts['dep'],facts['owner'],facts['profile'])

mutations=[
 ('malformed owner',lambda f:f['owner'].update(owner='homelab-maintenance-103-untrusted'),'reject'),
 ('foreign target',lambda f:f['owner'].update(node='cyndaquil'),'none'),
 ('uncordoned database node',lambda f:f['node']['spec'].update(unschedulable=False),'reject'),
 ('changed application candidate',lambda f:f['dep']['spec']['template']['spec']['containers'][0].update(image='other'),'reject'),
 ('reused database Pod UID',lambda f:f['dbpod']['metadata'].update(uid='original-db-pod'),'reject'),
 ('preexisting replacement',lambda f:f['dbpod']['metadata'].update(creationTimestamp='2026-10-29T23:00:00Z'),'reject'),
 ('changed database claim UID',lambda f:f['claim']['metadata'].update(uid='foreign'),'reject'),
 ('changed PV claim ownership',lambda f:f['volume']['spec']['claimRef'].update(uid='foreign'),'reject'),
 ('missing persistent claim',lambda f:f['dbpod']['spec'].update(volumes=[]),'reject'),
 ('changed database image',lambda f:f['dbpod']['spec']['containers'][0].update(image='other'),'reject'),
 ('dependent process restarted',lambda f:f['pod']['status']['containerStatuses'][1].update(restartCount=1),'reject'),
 ('dependent Pod replacement',lambda f:f['pod']['metadata'].update(uid='replacement'),'reject'),
 ('failed migration',lambda f:f['pod']['status']['initContainerStatuses'][0]['state']['terminated'].update(exitCode=1),'reject'),
 ('unrelated HTTP failure',lambda f:f['proof'].update(health=500),'reject'),
 ('foreign database host',lambda f:f['proof'].update(host='other'),'reject'),
 ('worker unready',lambda f:f['pod']['status']['containerStatuses'][1].update(ready=False),'reject'),
]


class DatabaseOutageTests(unittest.TestCase):
    def test_exact_expected_outage(self):
        facts, api = fixture()
        self.assertEqual(invoke(facts, api)['database_pending_uid'], 'new-db-pod')

    def test_foreign_runtime_candidates_storage_and_failures_are_rejected(self):
        for name, mutate, expected in mutations:
            facts, api = fixture()
            mutate(facts)
            with self.subTest(case=name):
                if expected == 'none':
                    self.assertIsNone(invoke(facts, api))
                else:
                    with self.assertRaises(RuntimeError):
                        invoke(facts, api)

    def test_database_must_be_exact_pinned_pending_replacement(self):
        facts, api = fixture()
        with self.assertRaises(RuntimeError):
            invoke(facts, api, pending=False)


def healthy_fixture():
    facts, _ = fixture()
    for d in (facts['dep'], facts['database']):
        d['status'] = {'observedGeneration': d['metadata']['generation'], 'readyReplicas': 1, 'updatedReplicas': 1}
    facts['dep']['spec']['template']['spec']['containers'] = [
        {'name': 'web', 'image': 'immutable'}, {'name': 'worker', 'image': 'immutable'}]
    facts['pod']['spec']['containers'] = copy.deepcopy(facts['dep']['spec']['template']['spec']['containers'])
    facts['pod']['status']['containerStatuses'][0]['ready'] = True
    facts['dbpod']['metadata'].update(uid='original-db-pod', ownerReferences=[
        {'controller': True, 'kind': 'ReplicaSet', 'name': 'db-replica', 'uid': 'db-replica-uid'}])
    facts['dbpod']['spec']['nodeName'] = 'totodile'
    facts['dbpod']['status'] = {'phase': 'Running', 'containerStatuses': [
        {'name': 'postgres', 'containerID': 'db-container', 'imageID': 'db-image', 'restartCount': 0,
         'ready': True, 'state': {'running': {'startedAt': '2026-10-29T19:00:00Z'}}}]}
    facts['dbreplica'] = {'metadata': {'uid': 'db-replica-uid', 'ownerReferences': [
        {'controller': True, 'kind': 'Deployment', 'uid': facts['database']['metadata']['uid']}]}}
    expected = facts['profile']['database']
    expected.update(replica_uid='db-replica-uid', replica_name='db-replica', containers={})
    for c in facts['dbpod']['status']['containerStatuses']:
        expected['containers'][c['name']] = {k: c[k] for k in ('containerID', 'imageID', 'restartCount')}
        expected['containers'][c['name']]['time'] = c['state']['running']['startedAt']
    facts['profile']['dependents']['versa']['template_sha256'] = hashlib.sha256(
        shared.encoded(facts['dep']['spec']['template']).encode()).hexdigest()
    facts['proof'].update(readiness=200, ready=True)
    class API:
        def call(self, *args):
            if args[0] == 'exec':
                return facts['proof']
            kind = args[1]
            if kind == 'deployment':
                return facts['database'] if args[2] == 'postgres' else facts['dep']
            if kind == 'pods':
                return {'items': [facts['dbpod'] if args[3] == 'postgres' else facts['pod']]}
            if kind == 'replicaset':
                return facts['dbreplica'] if args[4] == 'postgres' else facts['replica']
            return facts[{'node': 'node', 'pvc': 'claim', 'pv': 'volume'}[kind]]
    return facts, API()


class HealthyBeforeEvictionTests(unittest.TestCase):
    def test_exact_published_healthy_source_and_dependents(self):
        facts, api = healthy_fixture()
        observed = current.healthy_database_dependencies(api, facts['owner'], facts['profile'])
        self.assertEqual({p['pod_uid'] for p in observed}, {'original-db-pod', 'dependent-pod'})

    def test_changed_runtimes_storage_candidates_and_readiness_stop_before_eviction(self):
        cases = [
            ('database restart', lambda f: f['dbpod']['status']['containerStatuses'][0].update(containerID='replacement')),
            ('database moved', lambda f: f['dbpod']['spec'].update(nodeName='other')),
            ('database deletion', lambda f: f['dbpod']['metadata'].update(deletionTimestamp='now')),
            ('database parent', lambda f: f['dbreplica']['metadata']['ownerReferences'][0].update(uid='other')),
            ('database generation', lambda f: f['database']['metadata'].update(generation=999)),
            ('database volume', lambda f: f['volume']['metadata'].update(uid='other')),
            ('database unready', lambda f: f['dbpod']['status']['containerStatuses'][0].update(ready=False)),
            ('dependent unready', lambda f: f['pod']['status']['containerStatuses'][0].update(ready=False)),
            ('dependent restarted', lambda f: f['pod']['status']['containerStatuses'][1].update(restartCount=1)),
            ('dependent replacement', lambda f: f['pod']['metadata'].update(uid='other')),
            ('dependent moved', lambda f: f['pod']['spec'].update(nodeName='other')),
            ('HTTP readiness', lambda f: f['proof'].update(readiness=503, ready=False)),
            ('foreign owner', lambda f: f['owner'].update(node='cyndaquil')),
            ('uncordoned', lambda f: f['node']['spec'].update(unschedulable=False)),
        ]
        for name, mutate in cases:
            with self.subTest(case=name):
                facts, api = healthy_fixture()
                mutate(facts)
                with self.assertRaises(RuntimeError):
                    current.healthy_database_dependencies(api, facts['owner'], facts['profile'])


if __name__ == '__main__':
    unittest.main()
