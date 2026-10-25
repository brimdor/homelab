"""Exercise native availability refusals and compile actual controller programs."""

import ast
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import maintenance_native_controller_qualification as native


class NativeController(unittest.TestCase):
    def test_API_reads_request_JSON_and_plain_commands_keep_exact_arguments(self):
        fixture=object.__new__(native.Qualification);calls=[]
        def command(argv,**kwargs):
            calls.append((argv,kwargs));return b'{"items":[]}' if '-o json' in argv[-1] else b'plain\n'
        fixture.endpoints=[None,SimpleNamespace(ssh=['owned-pinned-SSH'],command=command)]
        self.assertEqual(fixture.kubectl('get','nodes'),{'items':[]})
        self.assertTrue(calls[-1][0][-1].endswith('get nodes -o json'))
        self.assertEqual(fixture.kubectl('get','--raw=/owned',json_output=False),b'plain\n')
        self.assertTrue(calls[-1][0][-1].endswith('get --raw=/owned'))

    def test_actual_availability_requires_ready_generation_exact_endpoints_and_http(self):
        body=next(v for v in ast.parse(native.NATIVE).body if isinstance(v,ast.FunctionDef)and v.name=='available')
        deployment={'metadata':{'generation':1,'uid':'owned-deployment'},'status':{
            'observedGeneration':1,'replicas':3,'readyReplicas':3,'availableReplicas':3,'updatedReplicas':3}}
        pods=[{'metadata':{'uid':str(i)},'spec':{'nodeName':'native-'+str(i)},
               'status':{'containerStatuses':[{'ready':True}]}}for i in range(3)]
        slices=[{'endpoints':[{'targetRef':{'uid':str(i)},'conditions':{'ready':True}}for i in range(3)]}]
        values={'deployment':deployment,'pods':{'items':pods},'endpointslice':{'items':slices}}
        scope={'api':SimpleNamespace(call=lambda *args:copy.deepcopy(values[args[1]])),
               'native':lambda *_:native.PAYLOAD.decode(),'hashlib':native.hashlib}
        exec(compile(ast.Module(body=[body],type_ignores=[]),'<actual-native-availability>','exec'),scope)
        expected=scope['available']()
        self.assertEqual(expected['endpoint_uids'],['0','1','2'])
        self.assertEqual(expected['http_sha256'],native.hashlib.sha256(native.PAYLOAD).hexdigest())
        for key in('observedGeneration','readyReplicas','availableReplicas','updatedReplicas'):
            old=deployment['status'][key];deployment['status'][key]=0
            with self.subTest(key=key),self.assertRaises(AssertionError):scope['available']()
            deployment['status'][key]=old
        pods[0]['status']['containerStatuses'][0]['ready']=False
        with self.assertRaises(AssertionError):scope['available']()
        pods[0]['status']['containerStatuses'][0]['ready']=True
        slices[0]['endpoints'][0]['targetRef']['uid']='foreign'
        with self.assertRaises(AssertionError):scope['available']()
        slices[0]['endpoints'][0]['targetRef']['uid']='0'
        scope['native']=lambda *_:'wrong body\n'
        with self.assertRaises(AssertionError):scope['available']()

    def test_exact_guest_programs_compile_with_real_native_API_and_actor_modules(self):
        self.assertTrue(issubclass(native.Target,native.Endpoint))
        self.assertTrue(issubclass(native.Target,native.package.Qualification))
        self.assertTrue(all(not name.startswith('test_')for name in native.MODULES))
        fixture=object.__new__(native.Qualification);programs=[];calls=[]
        target=object.__new__(native.Target);target.hostname='qualification-native-0'
        target.args=SimpleNamespace(revision='a'*40);fixture.endpoints=[target]
        def control(body):
            compile(native.program(body,target.hostname,target.args.revision),'<actual-native-control>','exec')
            programs.append(body)
            if 'selected[0]'in body:return {'selected':{'name':'owned-pod'}}
            return {'compiled':True}
        fixture.control=control
        fixture.kubectl=lambda *args,**kw:calls.append((args,kw))
        fixture.persist=lambda *args,**kw:None
        fixture.initialize();fixture.drain();fixture.restore_and_release()
        self.assertEqual(len(programs),5)
        self.assertTrue(any('release.Release' in body for body in programs))
        payload=next(kw['data']for args,kw in calls if args[:2]==('apply','-f'))
        canary=json.loads(payload);pod=canary['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'],{'kubernetes.io/hostname':'qualification-native-0'})
        self.assertEqual(pod['containers'][0]['imagePullPolicy'],'Never')
        self.assertTrue(pod['containers'][0]['image'].endswith(native.WORKLOAD['digest']))
        self.assertIn('actors.Systemd()',native.NATIVE)
        self.assertIn("class API(coordination.Kubectl)",native.NATIVE)

    def test_actual_package_program_uses_exact_endpoint_hostname_and_exit_status(self):
        target=object.__new__(native.Target);target.hostname='qualification-native-0'
        target.args=SimpleNamespace(revision='b'*40);target.ssh=['owned-pinned-SSH'];seen=[]
        def command(argv,**kwargs):
            compile(kwargs['data'],'<native-package-context>','exec');seen.append((argv,kwargs))
            return b'{"owned":true}'if kwargs['expected']==0 else b''
        target.command=command
        self.assertEqual(target.package_guest("print(json.dumps({'owned':True}))"),{'owned':True})
        self.assertEqual(target.package_guest('os._exit(73)',expected=73),b'')
        self.assertEqual(seen[-1][1]['expected'],73)
        self.assertTrue(seen[0][1]['data'].startswith(b"fixture_hostname='qualification-native-0'\n"))
        with self.assertRaises(RuntimeError):native.program('', 'foreign-host','b'*40)

    def test_recovery_uses_distinct_named_snapshot_and_actual_program(self):
        fixture=object.__new__(native.Qualification);calls=[];programs=[]
        state={'identity':{'machine':'owned','root_uuid':'root','architecture':'x86_64','kernel':'fc39'},
               'native':{'release':39},'corpus':{'owned':'bytes'}}
        target=SimpleNamespace(corpus=lambda **_kw:state['corpus'],state=lambda *_:copy.deepcopy(state),
                               stop=lambda:calls.append('stop'),boot=lambda:calls.append('boot'),
                               wait_ready=lambda:calls.append('ready'),disk=native.Path('/owned/disk.qcow2'))
        target.command=lambda argv:calls.append(argv)
        def guest(body):
            compile(native.program(body,'qualification-native-0','a'*40),'<actual-native-restore>','exec')
            programs.append(body);return {'owned_mutation_observed':True}
        target.guest=guest;fixture.endpoints=[target]
        fixture.args=SimpleNamespace(qemu_img='/owned/qemu-img')
        fixture.ready=lambda:[{'metadata':{'name':'owned-node','uid':'owned-uid'}}]
        fixture.persist=lambda *args,**kw:None
        self.assertEqual(fixture.recovery(),state['corpus'])
        commands=[v for v in calls if isinstance(v,list)]
        self.assertEqual([v[2]for v in commands],['-c','-a'])
        self.assertTrue(all(v[3]=='native-protected39'for v in commands))
        self.assertEqual(len(programs),1)

    def test_infrastructure_requires_unchanged_survivors_and_public_keys(self):
        fixture=object.__new__(native.Qualification)
        before=[{'stable':{'boot':'boot-'+str(i)},'private_endpoint':{'owned':i}}for i in range(3)]
        keys=[{'host':str(i)+'a'*63,'login':str(i)+'b'*63}for i in range(3)]
        fixture.endpoints=[SimpleNamespace(private_identity=lambda i=i:copy.deepcopy(before[i]),
                              prepared_keys=lambda i=i:copy.deepcopy(keys[i]),child=SimpleNamespace(pid=20+i))
                           for i in range(3)]
        fixture.endpoints[0].corpus=lambda:{'owned':'data'}
        fixture.hub=SimpleNamespace(running=lambda:11);programs=[]
        def control(body):
            compile(native.program(body,'qualification-native-0','a'*40),'<actual-native-infrastructure>','exec')
            programs.append(body);return {'compiled':True}
        fixture.control=control;fixture.persist=lambda *args,**kw:None
        fixture.accept_infrastructure({'owned':'data'},{'identity':{'owned':True}},before,11,[21,22],keys)
        self.assertEqual(len(programs),1)
        fixture.endpoints[2].child.pid=99
        with self.assertRaisesRegex(RuntimeError,'process/key'):
            fixture.accept_infrastructure({'owned':'data'},{'identity':{}},before,11,[21,22],keys)

    def test_target_reconnect_requires_actual_fresh_boot_program(self):
        target=object.__new__(native.Target);target.cluster_started=True;programs=[]
        target.guest=lambda body:programs.append(native.program(body,'qualification-native-0','a'*40))
        with patch.object(native.Endpoint,'wait_ready')as parent:target.wait_ready();parent.assert_called_once()
        self.assertEqual(len(programs),1)
        compile(programs[0],'<actual-native-reconnect>','exec')
        self.assertIn("get('bootID')",programs[0])
        target.cluster_started=False
        with patch.object(native.Endpoint,'wait_ready'):target.wait_ready()
        self.assertEqual(len(programs),1)


if __name__=='__main__':unittest.main()
