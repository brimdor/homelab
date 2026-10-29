
"""Worker bridge recovery and dispatch boundaries; no live operations."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import maintenance_k3s_production as bridge
import maintenance_k3s_contract as contract
import maintenance_production_node as shared

class WorkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.nodes=[{'metadata':{'name':n,'uid':'uid-'+n},
                     'status':{'nodeInfo':{'kubeletVersion':bridge.TARGET if i<contract.ORDER.index('pikachu') else bridge.SOURCE}}}
                    for i,n in enumerate(contract.ORDER)]
        self.copy={'accepted':True,'phase':'protected-copy','manifest_sha256':'a'*64,'point':'/protected/etcd',
                   'metadata':{'version':bridge.TARGET,'source_host':'bulbasaur',
                               'nodes':{n['metadata']['name']:n['metadata']['uid']for n in self.nodes}}}
        self.restore={'accepted':True,'phase':'full-restore','manifest_sha256':'a'*64,
                      'version':bridge.TARGET,'protected_point_unchanged':True,
                      'protected_point_labels_unchanged':True,'protected_secret_readback_matches':True,
                      'cleanup':{k:True for k in('container_absent','scratch_absent','staged_copy_absent')}}
        self.identity={'machine':'fixture-machine','root_uuid':'fixture-root'}
        self.config={'accepted':True,'header':{'node':'pikachu','node_uid':'uid-pikachu',
                     'identity':self.identity,'version':bridge.SOURCE},'receiver':'totodile',
                     'files':{'/usr/local/bin/k3s':{'sha256':contract.SHA256[bridge.SOURCE]}},
                     'point':'/protected/config','archive_sha256':'b'*64}
        self.args=types.SimpleNamespace(node='pikachu',recovery_copy=str(self.root/'copy'),
                    recovery_receipt=str(self.root/'restore'),node_recovery=str(self.root/'config'))
        self.remote=self.enterContext(patch.object(shared,'remote',return_value={}))
        self.enterContext(patch.object(shared,'UID','uid-pikachu'))
        self.enterContext(patch.object(shared,'IDENTITY',self.identity))
    def verify(self):
        for name,value in(('copy',self.copy),('restore',self.restore),('config',self.config)):
            (self.root/name).write_text(json.dumps(value))
        return bridge.verify_recovery(self.args,self.nodes,fresh=True)
    def test_worker_keeps_source_binary_backup_and_matching_target_control_plane_restore(self):
        result=self.verify();self.assertEqual(result['configuration'],self.config)
        self.assertEqual([c.args[2]for c in self.remote.call_args_list],['10.0.20.14','10.0.20.17'])
        snapshot,config=[c.args[1]for c in self.remote.call_args_list]
        for program in(snapshot,config):compile(program,'remote-fixture','exec')
        self.assertIn("'source_version': '"+bridge.TARGET+"'",snapshot)
        self.assertIn("'receiver_version': '"+bridge.SOURCE+"'",snapshot)
        self.assertIn("require_host('pikachu', RECEIVER_VERSION)",snapshot)
        self.assertIn("socket.gethostname()==RECEIVER['name']",config)
        next(n for n in self.nodes if n['metadata']['name']=='pikachu')['status']['nodeInfo']['kubeletVersion']=bridge.TARGET
        self.remote.reset_mock();self.verify()
        self.assertIn("'receiver_version': '"+bridge.TARGET+"'",self.remote.call_args_list[0].args[1])
    def test_recovery_rejects_empty_cleanup_mixed_versions_wrong_binding_or_local_backup(self):
        for change in(
            lambda:self.restore.update(cleanup={}),
            lambda:self.restore['cleanup'].update(container_absent=False),
            lambda:self.restore.update(version=bridge.SOURCE),
            lambda:self.copy['metadata'].update(version=bridge.SOURCE),
            lambda:self.copy['metadata'].update(source_host='pikachu'),
            lambda:self.copy['metadata']['nodes'].update(pikachu='foreign'),
            lambda:self.config.update(receiver='pikachu'),
            lambda:self.config['header'].update(version=bridge.TARGET),
            lambda:self.config['files']['/usr/local/bin/k3s'].update(sha256='foreign')):
            original=copy.deepcopy((self.copy,self.restore,self.config));change()
            with self.assertRaises(RuntimeError):self.verify()
            self.remote.assert_not_called()
            self.copy,self.restore,self.config=original
    def test_worker_cannot_start_before_all_servers_finish(self):
        for node in self.nodes[2:]:node['status']['nodeInfo']['kubeletVersion']=bridge.SOURCE
        with self.assertRaisesRegex(RuntimeError,'finish all servers'):self.verify()
        self.remote.assert_not_called()
    def test_server_recovery_remains_valid_after_its_activation(self):
        self.args.node='bulbasaur'
        self.config['header'].update(node='bulbasaur');self.config['receiver']='pikachu'
        self.copy['metadata']['version']=self.restore['version']=bridge.SOURCE
        self.verify()
        self.assertEqual([c.args[2]for c in self.remote.call_args_list],['10.0.20.14','10.0.20.14'])
    def test_configuration_receiver_is_off_node_and_exact(self):
        for node in contract.ORDER:
            r=bridge.configuration_receiver(node)
            self.assertNotEqual(r['name'],node)
            self.assertEqual(r['name'],'totodile' if node=='pikachu' else 'pikachu')
            self.assertEqual(set(r),{'name','address','machine','root_uuid'})
        with self.assertRaises(RuntimeError):bridge.configuration_receiver('foreign')

class WorkerDispatchTests(unittest.TestCase):
    def test_all_inventory_nodes_pass_native_bridge_inspect_but_no_new_versions(self):
        journal=MagicMock();journal.inspect.return_value={'pending':None}
        with patch('maintenance_hop_journal.Journal',return_value=journal):
            for node in contract.ORDER:
                context=dict.fromkeys(('api','controller','native','identity','rpc'))
                context.update(operation='inspect',hold=types.SimpleNamespace(state=Path('/fixture')),
                    owner={'component':'k3s','node':node,'owner':'fixture',
                           'source':bridge.SOURCE,'target':bridge.TARGET})
                with redirect_stdout(io.StringIO()):bridge.native_operation(context)
        self.assertEqual(journal.inspect.call_count,len(contract.ORDER))
    def test_one_queued_osd_eviction_precedes_read_only_rook_protection_wait(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);worker=MagicMock();worker.path=root/'drain-state';worker.path.write_text('{}')
            worker.inventory.return_value={}
            journal=MagicMock();journal.inspect.return_value={'pending':True}
            events=[];ref={'namespace':'rook-ceph','controller':{'kind':'ReplicaSet','name':'rook-ceph-osd-1-abc'}}
            def advance(*args,**kwargs):events.append('advance');return {'complete':False,'queued':ref}
            def rpc(kind,**kwargs):
                if kind=='await_osd_protection':events.append('wait');self.assertEqual(kwargs,{'ref':ref})
                return {'accepted':True}
            worker.advance.side_effect=advance
            context=dict(api=None,controller=None,native=None,identity=None,rpc=rpc,
                operation='drain',hold=types.SimpleNamespace(state=root),
                owner={'component':'k3s','node':'cyndaquil','owner':'fixture',
                       'source':bridge.SOURCE,'target':bridge.TARGET})
            with patch('maintenance_hop_journal.Journal',return_value=journal), \
                    patch('maintenance_node_drain.Drain',return_value=worker):
                with redirect_stdout(io.StringIO()):bridge.native_operation(context)
                self.assertEqual(events,['advance','wait']);self.assertEqual(worker.advance.call_count,1)
                events.clear();ref['namespace']='other'
                with redirect_stdout(io.StringIO()):bridge.native_operation(context)
                self.assertEqual(events,['advance'])
            journal.accept.assert_not_called()


class OSDCollectionTests(unittest.TestCase):
    def test_second_collection_cannot_hide_new_osd_or_pg_state(self):
        from test_maintenance_k3s_osd_bridge import bridge_fixture
        import maintenance_osd_host as osd
        from test_maintenance_osd_host import NOW
        v=bridge_fixture(True,True)
        proof=osd.validate(v,NOW,k3s_bridge=True)
        nodes=[{'metadata':{'name':n,'uid':'uid-'+n},'spec':{},
                'status':{'nodeInfo':{'kubeletVersion':bridge.TARGET if i<4 else bridge.SOURCE},
                          'conditions':[{'type':k,'status':'True' if k=='Ready' else 'False'}
                                        for k in('Ready','MemoryPressure','DiskPressure','PIDPressure')]}}
               for i,n in enumerate(contract.ORDER)]
        target=next(n for n in nodes if n['metadata']['name']=='cyndaquil')
        target['metadata']['uid']=v['node']['metadata']['uid'];target['spec']['unschedulable']=True
        v['cluster']['status']['cephx']['csi'].update(keyCephVersion='20.2.4-0')
        class API:
            def call(self,*args):
                if args[:2]==('get','nodes'):return {'items':nodes}
                if args[:2]==('get','cephcluster'):return v['cluster']
                if args[:2]==('get','deployments,statefulsets'):return {'items':[]}
                if 'health' in args:return v['health']
                if 'stat' in args:return {'pg_summary':{'num_pgs':177,
                    'num_pg_by_state':[{'name':n,'num':c}for n,c in proof['pg_states'].items()]}}
                if 'dump' in args:return v['map']
                raise AssertionError(args)
        # The bounded PG fixture has two PGs; scale only its summary for this observer integration.
        proof['checked_pgs']=177;proof['pg_states']={k:(176 if 'clean' in k else 1)
                                                  for k in proof['pg_states']}
        original=copy.deepcopy(v['map'])
        with patch.object(shared,'NODE','cyndaquil'),patch.object(shared,'UID',target['metadata']['uid']), \
                patch('maintenance_control_plane.observe',return_value={'members':{'members':[{'ID':1},{'ID':2},{'ID':3}]}}), \
                patch.object(osd,'native_identity'),patch.object(osd,'observe',return_value=proof), \
                patch.object(bridge,'registry'):
            result=bridge.observe(None,API(),{'node':'cyndaquil'},'prerequisites')
            self.assertEqual(result['owned_osd_findings'],sorted(set(v['health']['checks'])-bridge.AUTH_WARNINGS))
            self.assertEqual(result['clean_pgs'],proof['clean_pgs'])
            for field,value in(('up',0),('in',0),('uuid','foreign'),('weight',0)):
                # Select a surviving foreign OSD, not the already-down maintained target.
                v['map']=copy.deepcopy(original);v['map']['osds'][1][field]=value
                with self.subTest(field=field),self.assertRaises(RuntimeError):
                    bridge.observe(None,API(),{'node':'cyndaquil'},'prerequisites')

if __name__=='__main__':unittest.main()
