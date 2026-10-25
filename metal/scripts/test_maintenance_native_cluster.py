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
    def test_policy_ghost_disposition_refuses_every_unclassified_verification_failure(self):
        import hashlib,json
        namespace={'json':json,'hashlib':hashlib}
        exec(compile(cluster.POLICY_VERIFICATION,'<actual-policy-validator>','exec'),namespace)
        verify=namespace['verify_policy_packages']
        with patch.dict(namespace,native=unittest.mock.Mock(return_value='')),self.assertRaises(AssertionError):
            verify(None)
        exact='.M.......  g /var/lib/selinux/targeted/active/modules/200/container\n'
        failure={'command':['rpm','-V','container-selinux','k3s-selinux'],'exit':1,'stderr':'',
                 'verification_stdout':exact,'verification_stdout_bytes':len(exact.encode()),
                 'verification_stdout_sha256':hashlib.sha256(exact.encode()).hexdigest()}
        for change in ({'verification_stdout':exact.replace('.M.......','SM5......')},
                       {'verification_stdout':exact+exact},{'verification_stdout':exact.replace('container\n','foreign\n')},
                       {'exit':2},{'stderr':'failure'},{'verification_stdout_bytes':1},
                       {'verification_stdout_sha256':'0'*64}):
            native=unittest.mock.Mock(side_effect=RuntimeError(json.dumps({**failure,**change})))
            with self.subTest(change=change),patch.dict(namespace,native=native),self.assertRaises(AssertionError):
                verify(None)
            self.assertEqual(native.call_count,1)

    def test_actual_policy_ghost_validator_checks_payloads_directory_and_cleans_exports(self):
        import bz2,hashlib,json,subprocess
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);assets=root/'assets';assets.mkdir()
            store=root/'store';store.mkdir(mode=0o700)
            cache=root/'cache';cache.mkdir();rpm=cache/'container-selinux-2.233.0-1.fc39.noarch.rpm'
            vendor=root/'vendor';vendor.mkdir()
            (vendor/'container.pp.bz2').write_bytes(bz2.compress(b'vendor container policy'))
            (vendor/'k3s.pp').write_bytes(b'vendor k3s policy')
            enforcement=root/'enforce';enforcement.write_text('1\n')
            selected={'case':'valid'}
            class OwnedPath(type(Path())):
                def is_symlink(self):
                    return (selected['case']=='symlink'and self==store)or super().is_symlink()
                def lstat(self):
                    value=super().lstat()
                    return SimpleNamespace(**{key:getattr(value,key)for key in(
                        'st_dev','st_ino','st_mode','st_nlink','st_mtime_ns')},
                        st_uid=1 if selected['case']=='owner' else 0,st_gid=0)
            def path(value):
                mapped={'/var/cache/dnf':cache,'/usr/share/selinux/packages':vendor,
                        '/var/lib/selinux/targeted/active/modules/200/container':store,
                        '/sys/fs/selinux/enforce':enforcement}
                return OwnedPath(mapped.get(str(value),value))
            exact='.M.......  g /var/lib/selinux/targeted/active/modules/200/container\n'
            failure={'command':['rpm','-V','container-selinux','k3s-selinux'],'exit':1,'stderr':'',
                     'verification_stdout':exact,'verification_stdout_bytes':len(exact.encode()),
                     'verification_stdout_sha256':hashlib.sha256(exact.encode()).hexdigest()}
            def native(*args):
                case=selected['case']
                if args==tuple(failure['command']):
                    if case=='clean RPM':return ''
                    raise RuntimeError(json.dumps(failure))
                if args[:3]==('rpm','-q','--qf'):
                    if args[3].startswith('%{EPOCHNUM}'):
                        return 'foreign'if case=='NEVRA'else'2:2.233.0-1.fc39.noarch'
                    row=str(store)+'\t64\t32768\t4294967256\n'
                    return row+row if case=='ghost inventory'else row
                if args==('rpm','-V','--noghost','container-selinux','k3s-selinux'):
                    if case=='payload verification':raise RuntimeError('payload verification failed')
                    return ''
                if args[:2]==('matchpathcon','-V'):
                    if case=='context':raise RuntimeError('context verification failed')
                    return 'verified'
                raise AssertionError(args)
            def extract(args,**kwargs):
                self.assertEqual(args,['semodule','-X','200','--hll','-E','container','k3s'])
                output=Path(kwargs['cwd']);case=selected['case']
                for name in('container','k3s'):
                    raw=('vendor '+name+' policy').encode()
                    (output/(name+'.pp')).write_bytes(b'changed'if case=='module content'else raw)
                if case=='foreign export':(output/'foreign').touch()
                if case=='changed directory':store.chmod(0o755)
                return subprocess.CompletedProcess(args,1 if case=='extraction'else 0,b'',b'')
            def digest(raw):
                if raw==b'exact cached public RPM':return SimpleNamespace(hexdigest=lambda:'45012036a3c4f011d98509e310f640c448c43d500b80762204434b825cb5feeb')
                return hashlib.sha256(raw)
            def attributes(_path):
                selected['attributes']+=1
                return ['user.changed']if selected['case']=='changed xattr'and selected['attributes']>1 else []
            namespace={'json':json,'hashlib':SimpleNamespace(sha256=digest),'pathlib':SimpleNamespace(Path=path),
                       'os':SimpleNamespace(listxattr=attributes,getxattr=lambda *_:b'changed'),
                       'subprocess':subprocess,'native':native}
            exec(compile(cluster.POLICY_VERIFICATION,'<actual-policy-validator>','exec'),namespace)
            for case in('valid','clean RPM','NEVRA','cached RPM','ghost inventory','symlink','mode','owner','context',
                        'payload verification','extraction','module content','foreign export',
                        'changed directory','changed xattr','enforcement'):
                selected.update(case=case,attributes=0);store.chmod(0o755 if case=='mode'else 0o700)
                rpm.write_bytes(b'changed'if case=='cached RPM'else b'exact cached public RPM')
                enforcement.write_text('0\n'if case=='enforcement'else'1\n')
                with self.subTest(case=case),patch.object(subprocess,'run',side_effect=extract):
                    if case in('valid','clean RPM'):
                        result=namespace['verify_policy_packages'](assets)
                        self.assertEqual(result['original_rpm_finding'],None if case=='clean RPM'else failure)
                        self.assertIs(result['policy_or_permissions_modified'],False)
                        self.assertIs(result['owned_extraction_removed'],True)
                        self.assertEqual(result['vendor_modules_byte_equal']['container']['bytes'],len(b'vendor container policy'))
                    else:
                        with self.assertRaises((AssertionError,RuntimeError)):
                            namespace['verify_policy_packages'](assets)
                self.assertEqual(list(assets.iterdir()),[])

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
