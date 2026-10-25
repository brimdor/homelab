"""Check native cluster isolation and actual generated guest programs."""

import ast
from pathlib import Path
import shlex
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fedora_release_upgrade_qualification as upgrade
import maintenance_native_cluster as cluster
from maintenance_fedora_endpoint import endpoint


class NativeCluster(unittest.TestCase):
    def test_fixed_roles_and_private_network_with_no_inline_token(self):
        for index in range(3):
            value=cluster.configuration(index)
            self.assertEqual(value['node-name'],'qualification-native-'+str(index))
            self.assertEqual(value['node-ip'],'192.0.2.'+str(11+index))
            self.assertIs(value['selinux'],True)
            self.assertNotIn('token',value)
            self.assertEqual(value['flannel-iface'],'cluster0')
            if index==1:self.assertEqual(value['tls-san'],['192.0.2.12'])
            else:
                self.assertEqual(value['server'],'https://192.0.2.12:6443')
                self.assertEqual(value['token-file'],'/etc/rancher/k3s/qualification-token')
        for index in (-1,3,True,'0',None):
            with self.subTest(index=index),self.assertRaises(RuntimeError):cluster.configuration(index)

    def test_foreign_fleet_or_asset_directory_refused_before_media_or_process(self):
        with patch.object(cluster,'require_media')as media,patch.object(cluster.subprocess,'Popen')as process:
            args=SimpleNamespace(assets_dir=Path('/foreign'),work_dir=Path('/owned'))
            for nodes in ([],[SimpleNamespace(endpoint=endpoint(i,23000+i))for i in (2,1,0)]):
                with self.assertRaises(RuntimeError):cluster.Cluster(nodes,args)
            nodes=[SimpleNamespace(endpoint=endpoint(i,23000+i))for i in range(3)]
            with self.assertRaises(RuntimeError):cluster.Cluster(nodes,args)
            media.assert_not_called();process.assert_not_called()

    def test_prepare_and_start_refuse_redispatch_after_uncertain_effect(self):
        fixture=object.__new__(cluster.Cluster);fixture.prepared=set();fixture.started=set()
        def stopped(*_args):raise RuntimeError('observed owned preparation failure')
        fixture.nodes=[SimpleNamespace(repositories=stopped)for _ in range(3)]
        with self.assertRaisesRegex(RuntimeError,'observed owned'):fixture.prepare(0)
        with self.assertRaisesRegex(RuntimeError,'never replay'):fixture.prepare(0)
        fixture.nodes[0].guest=stopped
        with self.assertRaisesRegex(RuntimeError,'observed owned'):fixture.start(0)
        with self.assertRaisesRegex(RuntimeError,'never replay'):fixture.start(0)
        with self.assertRaisesRegex(RuntimeError,'not prepared'):fixture.start(1)

    def test_actual_import_and_wrapper_programs_compile_and_refuse_foreign_endpoints(self):
        fixture=object.__new__(cluster.Cluster);fixture.started={0,1,2};programs=[]
        def guest(body):
            compile(upgrade.guest_source('qualification-native-0')+body,'<native-runtime>','exec')
            programs.append(body)
        fixture.nodes=[SimpleNamespace(guest=guest)for _ in range(3)]
        for index in range(3):fixture.import_images(index)
        for index in(0,1):fixture.wrapper(index)
        self.assertEqual(len(programs),5)
        with self.assertRaises(RuntimeError):fixture.wrapper(2)
        fixture.started=set()
        with self.assertRaises(RuntimeError):fixture.import_images(0)

    def test_actual_native_programs_and_secure_transfer_shell_compile(self):
        with tempfile.TemporaryDirectory()as temporary:
            fixture=object.__new__(cluster.Cluster);fixture.prepared=set();fixture.started=set()
            fixture.args=SimpleNamespace(assets_dir=Path(temporary));fixture.assets={'k3s':'a'*64}
            programs=[]
            def guest(body):
                compile(upgrade.guest_source('qualification-native-0')+body,'<actual-cluster-program>','exec')
                programs.append(body);return {'compiled':True}
            node=SimpleNamespace(repositories=lambda *_:None,configure=lambda:{'configured':True},guest=guest)
            fixture.nodes=[node,node,node]
            with patch.object(cluster.Combined,'upload')as upload:
                fixture.prepare(0);upload.assert_called_once()
            fixture.start(0)
            self.assertEqual(len(programs),3)
            self.assertIn("=='1.6-1.el8.noarch'",programs[1])
            self.assertNotIn('1.6-1.el9.noarch',programs[1])
            tree=ast.parse(programs[-1]);self.assertEqual(ast.literal_eval(tree.body[0].value),cluster.configuration(0))
            calls=[]
            class Child:
                pid=19001
                def __init__(self,argv,**_kw):
                    import io
                    calls.append(argv);self.stdout=io.BytesIO();self.returncode=None
                def wait(self,**_kw):self.returncode=0;return 0
                def poll(self):return self.returncode
            source=SimpleNamespace(endpoint=endpoint(1,23001),ssh=['owned-source'])
            target=SimpleNamespace(endpoint=endpoint(0,23000),ssh=['owned-target'])
            with patch.object(cluster.subprocess,'Popen',Child):
                for kind in ('join-token','admin-config'):cluster.transfer_private(source,target,kind)
            for argv in calls[1::2]:
                words=shlex.split(argv[-1]);self.assertEqual(words[:3],['sudo','python3','-c'])
                compile(words[3],'<actual-private-writer>','exec')
                self.assertIn('os.O_EXCL|os.O_NOFOLLOW',words[3])
            with patch.object(cluster.subprocess,'Popen')as process:
                for kind in ('foreign',None,True):
                    with self.assertRaises(RuntimeError):cluster.transfer_private(source,target,kind)
                with self.assertRaises(RuntimeError):cluster.transfer_private(target,source,'join-token')
                process.assert_not_called()


if __name__=='__main__':unittest.main()
