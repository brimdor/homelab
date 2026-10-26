#!/usr/bin/env python3
"""Issue 103 production controller: exact Totodile identity, existing secure access.

The workstation retains Kubernetes credentials. The root SSH child calls back over
its existing protected stdio channel for fresh API observations and mutations.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

from fedora_public_key import armor_public_key
from maintenance_coordination import JOURNAL, Ownership, encoded, require
from maintenance_api_reader import Reader


NODE = 'totodile'
ADDRESS = '10.0.20.17'
UID = '83e0e536-e94a-45a1-8dfb-1cedac1e9bd7'
DS_UID = '4abc4fee-c3be-440e-8945-34bb3fb15ce1'
IDENTITY = {'machine': '0f1915a59a124d999d8d68b53f406af1',
            'root_uuid': '489f1af8-5d55-4356-8d48-418fcb2069a2'}
BACKUPS = {39: '/var/lib/homelab-recovery/maintenance-103/totodile-config-20261026-a',
           41: '/var/lib/homelab-recovery/maintenance-103/totodile-fedora41-config-20261026-a',
           43: '/var/lib/homelab-recovery/maintenance-103/totodile-fedora43-config-20261026-a'}
MODULES = ('maintenance_coordination', 'maintenance_actor_hold', 'maintenance_hop_journal',
           'maintenance_package_dispatch', 'maintenance_node_drain',
           'maintenance_node_scheduling', 'maintenance_kured_20261026', 'maintenance_safe_release')
ACTIVE_READER = None


def ssh(args, address=ADDRESS):
    return ['ssh', '-i', args.identity, '-o', 'IdentitiesOnly=yes',
            '-o', 'UserKnownHostsFile=' + args.known_hosts, '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UpdateHostKeys=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            'root@' + address]


def remote(args, program, address=ADDRESS):
    result = subprocess.run(ssh(args, address) + ['python3 -B -'], input=program.encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode == 0, 'protected remote operation failed: ' + result.stderr.decode()[-1500:])
    return json.loads(result.stdout)


def recovery(args, source, capture=False):
    require(source in BACKUPS, 'unreviewed recovery source release')
    backup = BACKUPS[source]
    readback = """
import hashlib,json,os,pathlib,socket,stat
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
root=pathlib.Path(%r)
assert not any(p.is_symlink()for p in(root,*root.parents))
manifest=root/'verified.json'
if not manifest.exists():print(json.dumps(None))
else:
 value=json.loads(manifest.read_bytes());archive=root/'node-config.tar'
 assert stat.S_IMODE(root.stat().st_mode)==0o700 and stat.S_IMODE(archive.stat().st_mode)==0o600
 digest=hashlib.sha256()
 with archive.open('rb')as source:
  for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
 assert archive.stat().st_size==value['bytes']and digest.hexdigest()==value['sha256']
 print(json.dumps(value))
""" % backup
    existing = remote(args, readback, '10.0.20.14')
    if existing is not None:
        require(existing['identity'] == IDENTITY and existing['node_uid'] == UID and
                existing.get('source_release', 39) == source, 'recovery identity or source changed')
        return existing
    require(capture, 'capture protected Totodile configuration before production ownership')
    source_program = """
import os,pathlib,socket,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
assert int(subprocess.check_output(['rpm','-E','%%fedora']))==%r
assert '6c:4b:90:5b:a3:56'in{p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
pid=subprocess.check_output(['systemctl','show','k3s','-p','MainPID','--value'],text=True).strip()
argv=(pathlib.Path('/proc')/pid/'cmdline').read_bytes().split(bytes([0]))
assert argv[0]in(b'k3s agent',b'k3s-agent',b'/usr/local/bin/k3s agent') or len(argv)>1 and argv[1]==b'agent'
etcd=pathlib.Path('/var/lib/rancher/k3s/server/db/etcd')
assert not etcd.exists() or {p.name for p in etcd.iterdir()}<={'name'}
listeners=subprocess.check_output(['ss','-H','-lnt'],text=True)
assert not any(':2379'in line or ':2380'in line for line in listeners.splitlines())
command=['tar','--numeric-owner','--acls','--xattrs','--selinux','--one-file-system',
 '--exclude=var/lib/rancher/k3s/agent/containerd','--exclude=var/lib/rancher/k3s/agent/images',
 '-C','/','-cf','-','etc','boot','boot/efi','usr/local/bin/k3s','var/lib/rancher/k3s/agent','var/lib/rancher/k3s/server']
sys.exit(subprocess.run(command).returncode)
""" % (IDENTITY['machine'], IDENTITY['root_uuid'], source)
    receiver = """
import hashlib,json,os,pathlib,socket,stat,sys
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
root=pathlib.Path(%r)
assert not any(p.is_symlink()for p in(root,*root.parents))
assert root.parent.is_dir()
if root.exists():
 partial=root/'node-config.partial';info=partial.stat()
 assert {p.name for p in root.iterdir()}=={'node-config.partial'}and info.st_size==0 and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600
 partial.unlink()
else:root.mkdir(mode=0o700)
assert stat.S_IMODE(root.stat().st_mode)==0o700
path=root/'node-config.partial';digest=hashlib.sha256();size=0
with path.open('xb')as target:
 os.fchmod(target.fileno(),0o600)
 while True:
  chunk=sys.stdin.buffer.read(1024*1024)
  if not chunk:break
  space=os.statvfs(root);assert space.f_bavail>space.f_blocks//5,'receiver capacity guard'
  target.write(chunk);digest.update(chunk);size+=len(chunk)
 target.flush();os.fsync(target.fileno())
print(json.dumps({'sha256':digest.hexdigest(),'bytes':size}))
""" % backup
    producer = subprocess.Popen(ssh(args) + ['python3 -B -c ' + shlex.quote(source_program)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = subprocess.Popen(ssh(args, '10.0.20.14') + ['python3 -B -c ' + shlex.quote(receiver)],
                                stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    producer.stdout.close()
    try:
        output, receiver_error = consumer.communicate()
        producer.wait()
        require(producer.returncode == 0 and consumer.returncode == 0,
                'configuration stream failed; protected partial retained: ' +
                producer.stderr.read().decode()[-700:] + receiver_error.decode()[-700:])
        manifest = json.loads(output)
        manifest.update(identity=IDENTITY, node_uid=UID, node=NODE, source_release=source, recovery_scope='configuration-boot-worker-identity')
        finalize = """
import hashlib,json,os,pathlib
root=pathlib.Path(%r);value=%r;partial=root/'node-config.partial';digest=hashlib.sha256()
with partial.open('rb')as source:
 for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
assert partial.stat().st_size==value['bytes']and digest.hexdigest()==value['sha256']
os.link(partial,root/'node-config.tar');partial.unlink()
with(root/'verified.json').open('x')as output:
 os.fchmod(output.fileno(),0o600);json.dump(value,output);output.flush();os.fsync(output.fileno())
descriptor=os.open(root,os.O_DIRECTORY);os.fsync(descriptor);os.close(descriptor)
print(json.dumps(value))
""" % (backup, manifest)
        remote(args, finalize, '10.0.20.14')
        return remote(args, readback, '10.0.20.14')
    finally:
        for child in (producer, consumer):
            if child.poll() is None:
                child.terminate();child.wait()


NATIVE = r'''
import base64,fcntl,hashlib,json,os,pathlib,socket,subprocess,sys,types
for module_name,source in bundle.items():
 module=types.ModuleType(module_name);sys.modules[module_name]=module
 exec(compile(source,module_name+'.py','exec'),module.__dict__)
coord=sys.modules['maintenance_coordination'];actors=sys.modules['maintenance_actor_hold']
hops=sys.modules['maintenance_hop_journal'];packages=sys.modules['maintenance_package_dispatch']
drain=sys.modules['maintenance_node_drain'];scheduling=sys.modules['maintenance_node_scheduling']
def native(*argv):
 return actors.Systemd.call(*argv).decode().strip()
def identity():
 result={'machine':pathlib.Path('/etc/machine-id').read_text().strip(),
         'root_uuid':native('findmnt','-n','-o','UUID','/')}
 assert os.geteuid()==0 and socket.gethostname()=='totodile' and result==expected_identity
 assert '6c:4b:90:5b:a3:56' in {p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
 return result
identity()
def rpc(kind,**payload):
 print(json.dumps({'rpc':kind,**payload}),flush=True)
 reply=json.loads(sys.stdin.readline());assert reply.get('ok'),reply.get('error','controller refused')
 return reply['result']
class API:
 def call(self,*argv,data=None):return rpc('api',argv=list(argv),data=data.decode()if data else None)
 def snapshot(self):
  return(self.call('get','daemonset','kured','-n','kured','-o','json'),
   self.call('get','pods','-n','kured','-o','json')['items'],self.call('get','nodes','-o','json')['items'])
 def patch(self,operations):return self.call('patch','daemonset','kured','-n','kured','--type=json','--patch',coord.encoded(operations),'-o','json')
 def drain_controllers(self):
  return{(v['kind'],v['metadata']['namespace'],v['metadata']['name']):v for v in rpc('drain_controllers')}
api=API();controller=coord.Ownership(api,expected_ds_uid,node_uids)
assert controller.resume(owner['owner'])==owner
hold=actors.Hold(actors.Systemd(),identity,lambda token:controller.resume(token)==owner)
root=hold.state
def evidence():return rpc('prerequisites')
def prerequisites(value):
 return lambda step,digest:evidence()==value and digest==drain.hashed(value)
def offline_repository_override():
 assert owner['source']==39 and owner['target']==41
 directory=root/('fedora-repositories-41-'+owner['owner'])
 assert(directory/'maintenance.repo').is_file()
 parent=pathlib.Path('/etc/systemd/system/dnf-system-upgrade.service.d');actors.safe(parent)
 parent.mkdir(mode=0o755,exist_ok=True)
 path=parent/('90-'+owner['owner']+'.conf')
 arguments='/usr/bin/dnf-3 --setopt=reposdir='+str(directory)+' --setopt=gpgcheck=True --setopt=localpkg_gpgcheck=True system-upgrade upgrade'
 content=('[Service]\nExecStart=\nExecStart='+arguments+'\n').encode()
 if not path.exists():
  assert 'argv[]=/usr/bin/dnf-3 system-upgrade upgrade ;'in native('systemctl','show','dnf-system-upgrade.service','-p','ExecStart','--value')
  actors.exclusive_file(path,content,0o600)
 assert path.read_bytes()==content
 native('systemctl','daemon-reload')
 assert 'argv[]='+arguments+' ;'in native('systemctl','show','dnf-system-upgrade.service','-p','ExecStart','--value')
 return {'path':str(path),'sha256':hashlib.sha256(content).hexdigest()}
def remove_offline_repository_override():
 path=pathlib.Path('/etc/systemd/system/dnf-system-upgrade.service.d')/('90-'+owner['owner']+'.conf')
 actors.safe(path)
 if path.exists():
  directory=root/('fedora-repositories-41-'+owner['owner'])
  content=('[Service]\nExecStart=\nExecStart=/usr/bin/dnf-3 --setopt=reposdir='+str(directory)+' --setopt=gpgcheck=True --setopt=localpkg_gpgcheck=True system-upgrade upgrade\n').encode()
  assert owner['source']==39 and path.read_bytes()==content
  path.unlink();actors.fsync_directory(path.parent)
 native('systemctl','daemon-reload')
if operation=='release':
 release=sys.modules['maintenance_safe_release'].Release(hops.Journal(controller,hold,owner['owner']))
 value=rpc('applications');digest=drain.hashed(value)
 def safe_release(header,observed_digest):
  return observed_digest==digest and rpc('applications')==value and identity()==header['owners']['host']['identity']
 if not release.path.exists():release.prepare(digest,safe_release)
 status=release.observe(digest,safe_release)
 if status['state']['kinds']==['header']:status=release.release_host(digest,safe_release)
 if status['state']['kinds']==list(sys.modules['maintenance_safe_release'].KINDS[:3]):
  status=release.release_global(digest,safe_release)
 print(json.dumps({'result':status}),flush=True)
elif operation=='initialize':
 if hold.marker.exists():hold.resume(owner['owner'])
 else:hold.acquire(owner['owner'],expected_identity,owner['revision'])
 recovery_path=root/('production-recovery.json'if owner['source']==39 else 'production-recovery-'+owner['owner']+'.json')
 if not recovery_path.exists():actors.exclusive_file(recovery_path,hops.canonical(recovery_manifest),0o600)
 assert json.loads(recovery_path.read_bytes())==recovery_manifest
 journal=hops.Journal(controller,hold,owner['owner'])
 if not journal.path.exists():journal.initialize()
 print(json.dumps({'result':{'owner':owner,'journal':journal.inspect(),'identity':identity()}}),flush=True)
else:
 journal=hops.Journal(controller,hold,owner['owner']);state=journal.inspect()
 if operation=='inspect':
  result={'owner':owner,'journal':state,'identity':identity(),'release':native('rpm','-E','%fedora'),
   'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
   'kernel':native('uname','-r')}
 elif operation in('cordon','restore-scheduling'):
  step=operation.replace('-','_')
  path=root/(step+'-'+owner['owner']+'.json');worker=scheduling.Scheduling(journal,api)
  value=evidence();verify=prerequisites(value);digest=drain.hashed(value)
  original=json.loads((root/('cordon-'+owner['owner']+'.json')).read_bytes())if step=='restore_scheduling'else None
  if not path.exists():actors.exclusive_file(path,hops.canonical(worker.plan(step,original)),0o600)
  plan=json.loads(path.read_bytes())
  if not state['pending']:
   assert step==hops.STEPS[len(state['completed'])];worker.dispatch(plan,drain.hashed(plan),digest,verify)
  result=worker.observe(plan,digest,verify)
 elif operation in('trusted-reconnect','verify-infrastructure','accept-applications'):
  step=operation.replace('-','_')
  before=json.loads((root/('before-offline-'+owner['owner']+'.json')).read_bytes())
  boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
  kernel=native('uname','-r')
  assert identity()==before['identity'] and boot!=before['boot']
  assert native('rpm','-E','%fedora')==str(owner['target'])and '.fc'+str(owner['target'])+'.'in kernel
  value={'identity':identity(),'boot':boot,'kernel':kernel,'release':owner['target']}
  if step!='trusted_reconnect':
   assert not native('systemctl','--failed','--no-legend','--plain'),'failed native units remain'
   value['runtime']=rpc('applications'if step=='accept_applications'else'infrastructure')
  else:value['prerequisites']=evidence()
  digest=drain.hashed(value)
  def verified_observation(step_name,observed_digest):
   if step_name!=step or observed_digest!=digest or identity()!=value['identity']:return False
   if step=='trusted_reconnect':return evidence()==value['prerequisites']
   return rpc('applications'if step=='accept_applications'else'infrastructure')==value['runtime']
  if state['pending'] is None:state=journal.begin(step,digest,digest,verified_observation)
  assert state['pending']['step']==step
  result={'receipt':value,'journal':journal.accept(state['pending']['sha256'],digest,verified_observation)}
 elif operation=='drain':
  worker=drain.Drain(journal,api);path=root/('drain-'+owner['owner']+'.json')
  value=evidence();verify=prerequisites(value);digest=drain.hashed(value)
  if not path.exists():actors.exclusive_file(path,hops.canonical(worker.inventory()),0o600)
  plan=json.loads(path.read_bytes())
  if not state['pending']:worker.start(plan,drain.hashed(plan),digest,verify)
  elif not worker.path.exists():worker.attach(plan)
  result=worker.advance(digest,verify)
  if result.get('complete'):
   accepted=dict(result)
   def verify_drain(step,digest):
    return step=='drain' and digest==drain.hashed(accepted) and evidence()==value and not worker.read()['pending'] and len(worker.read()['completed'])==len(worker.read()['targets'])
   journal.accept(result['parent_intent']['sha256'],drain.hashed(accepted),verify_drain)
 elif operation=='resolve-drain-precheck':
  assert precheck_proof and owner['owner']==precheck_proof['owner'] and state['pending']['step']=='drain'
  worker=drain.Drain(journal,api);value=evidence()
  def certain(pending,failure_digest):
   return pending['intent_sha256']==precheck_proof['intent_sha256'] and pending['pod']['uid']==precheck_proof['pod_uid'] and failure_digest==precheck_proof['failure_sha256']
  result=worker.first_dispatch(precheck_proof['intent_sha256'],precheck_proof['failure_sha256'],
   drain.hashed(value),certain,prerequisites(value))
 elif operation in('source-repositories','target-repositories'):
  expected=['cordon','drain']+(['prepare_source']if operation=='target-repositories'else[])
  assert state['completed']==expected and not state['pending']
  hold.systemd.idle(hold.marker);assert native('rpm','-E','%fedora')==str(owner['source'])
  release=str(owner['source']if operation=='source-repositories'else owner['target'])
  directory=root/('fedora-repositories-'+release+'-'+owner['owner']);directory.mkdir(mode=0o700,exist_ok=True)
  for key_release,raw in public_keys.items():
   key=base64.b64decode(raw);path=directory/('fedora'+key_release+'.asc')
   if not path.exists():actors.exclusive_file(path,key,0o600)
   assert path.read_bytes()==key;native('rpmkeys','--import',str(path))
  base='https://ftp-stud.hs-esslingen.de/pub/Mirrors/archive.fedoraproject.org/fedora/linux/'if int(release)<43 else 'https://dl.fedoraproject.org/pub/fedora/linux/'
  keys=' '.join('file://'+str(directory/('fedora'+r+'.asc'))for r in public_keys)
  content=''
  for name,url in [('fedora','releases/'+release+'/Everything/x86_64/os/'),('updates','updates/'+release+'/Everything/x86_64/')]:
   content+='[maintenance-'+name+']\nname=Issue 103 signed Fedora '+release+' '+name+'\nbaseurl='+base+url+'\nenabled=1\ngpgcheck=1\ngpgkey='+keys+'\n'
  path=directory/'maintenance.repo'
  if not path.exists():actors.exclusive_file(path,content.encode(),0o600)
  assert path.read_text()==content
  result={'repos_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'release':release,'gpgcheck':True}
 elif operation=='repair-offline-repositories':
  assert owner['owner']=='homelab-maintenance-103-c8345d91-1dfe-4e58-8c13-b7c7b7519d54'
  assert owner['source']==39 and owner['target']==41 and native('rpm','-E','%fedora')=='39'
  assert state['pending']['step']=='offline_transaction'and state['pending']['sha256']=='b868cc31fc75e88cd7ae1dab713d1b9cba05da91e9fcef70a4fbefb7aff03f46'
  assert pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='b76b2d31-b03f-4a5c-896a-5e070d0f4171'
  assert not pathlib.Path('/system-update').exists()and not pathlib.Path('/system-update').is_symlink()
  cache=pathlib.Path('/var/lib/dnf/system-upgrade')
  saved=json.loads((cache/'system-upgrade-state.json').read_bytes())
  assert saved['system_releasever']=='39'and saved['target_releasever']=='41'and saved['download_status']=='complete'and saved['upgrade_status']=='ready'
  assert saved['gpgcheck']is True and set(saved['gpgcheck_repos'])=={'maintenance-fedora','maintenance-updates'}
  failure=native('journalctl','--no-pager','-b','3db3caf7534445ab96b0aaa0fa5432a3','-u','dnf-system-upgrade.service','-o','cat')
  assert "Error: Cache-only enabled but no cache for 'fedora'"in failure and 'status=1/FAILURE'in failure
  assert 'Starting system upgrade. This will take a while.'not in failure
  files=sorted(cache.rglob('*.rpm'));assert len(files)==663
  signatures=[]
  for path in files:
   assert path.is_file()and not path.is_symlink()
   output=native('rpmkeys','--checksig','--verbose',str(path))
   assert all(v not in output for v in('NOKEY','NOT OK','BAD'))and 'signature'in output.lower()and 'OK'in output
   signatures.append([path.name,hashlib.sha256(path.read_bytes()).hexdigest()])
  directory=root/('fedora-repositories-41-'+owner['owner'])
  command=packages.command(owner,'offline_transaction');command[1]='--unit='+owner['owner']+'-offline-repository-recovery'
  position=command.index('/usr/bin/dnf');command[position+1:position+1]=['--setopt=reposdir='+str(directory),'--setopt=gpgcheck=True','--setopt=localpkg_gpgcheck=True']
  value=evidence()
  with hold.serialized():
   journal.owners(idle=True);assert journal.read()==state
   override=offline_repository_override()
   record={'version':1,'pending':state['pending'],'failed_boot':'3db3caf7534445ab96b0aaa0fa5432a3','boot':'b76b2d31-b03f-4a5c-896a-5e070d0f4171',
    'failure_sha256':hashlib.sha256(failure.encode()).hexdigest(),'saved_state_sha256':drain.hashed(saved),
    'transaction_sha256':hashlib.sha256((cache/'system-upgrade-transaction.json').read_bytes()).hexdigest(),
    'signed_rpms_sha256':drain.hashed(signatures),'override':override,'command':command,'prerequisites':value}
   actors.exclusive_file(root/('offline-repository-recovery-'+owner['owner']+'.json'),hops.canonical(record),0o600)
   native(*command)
  result={'dispatched_recovery':True,'original_pending_preserved':True,'record_sha256':drain.hashed(record)}
 elif operation=='observe-offline':
  assert state['pending'] and state['pending']['step']=='offline_transaction'
  before=json.loads((root/('before-offline-'+owner['owner']+'.json')).read_bytes())
  assert before['identity']==identity() and before['source']==owner['source']and before['target']==owner['target']
  boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
  assert boot!=before['boot'] and native('rpm','-E','%fedora')==str(owner['target'])
  assert not pathlib.Path('/system-update').exists()and not pathlib.Path('/system-update').is_symlink()
  kernel=native('uname','-r');assert '.fc'+str(owner['target'])+'.'in kernel
  assert native('rpm','-q','--qf','%{VERSION}-%{RELEASE}.%{ARCH}','kernel-core-'+kernel)==kernel
  native('/usr/bin/dnf5','--setopt=reposdir='+str(root/('fedora-repositories-'+str(owner['target'])+'-'+owner['owner'])),'check')
  native('rpm','-V','fedora-release-common')
  if owner['source']==39:remove_offline_repository_override()
  value=evidence();receipt={'before':before,'boot':boot,'kernel':kernel,'release':owner['target'],'identity':identity(),'prerequisites':value}
  def verified(step,digest):return step=='offline_transaction' and digest==drain.hashed(receipt) and evidence()==value and identity()==before['identity']
  result={'receipt':receipt,'journal':journal.accept(state['pending']['sha256'],drain.hashed(receipt),verified)}
 elif operation=='observe-package':
  assert state['pending'] and state['pending']['step']in('prepare_source','download_release')
  step=state['pending']['step'];unit=owner['owner']+'-'+step.replace('_','-')+'.service'
  raw=native('systemctl','show',unit,'-p','LoadState','-p','ActiveState','-p','Result','-p','ExecMainStatus','-p','MainPID','-p','ControlPID')
  fields=dict(line.split('=',1)for line in raw.splitlines())
  assert fields['LoadState']=='loaded','unit absent; retain uncertain intent'
  result={'unit':unit,'status':fields,'accepted':False}
  if fields['MainPID']=='0' and fields['ControlPID']=='0':
   if fields['Result']=='success' and fields['ExecMainStatus']=='0' and fields['ActiveState']=='active':
    value=evidence();receipt={'unit':unit,'status':fields,'release':native('rpm','-E','%fedora'),'prerequisites':value}
    assert receipt['release']==str(owner['source'])
    if step=='prepare_source' and owner['source']==39:
     receipt['upgrade_plugin_provider']=native('rpm','-q','--whatprovides','dnf-plugin-system-upgrade')
     assert 'System-upgrade command-specific options:'in native('/usr/bin/dnf','system-upgrade','--help')
    if step=='download_release':
     cache=pathlib.Path('/var/lib/dnf/system-upgrade')if owner['source']==39 else pathlib.Path('/usr/lib/sysimage/libdnf5/offline')
     files=sorted(cache.rglob('*.rpm'));assert files,'offline target RPMs absent'
     signed=[];target_release=False;target_kernel=False
     for path in files:
      assert path.is_file()and not path.is_symlink()
      output=native('rpmkeys','--checksig','--verbose',str(path))
      assert all(v not in output for v in('NOKEY','NOT OK','BAD'))and 'signature'in output.lower()and 'OK'in output
      metadata=native('rpm','-qp','--qf','%{NAME} %{VERSION} %{RELEASE}',str(path)).split()
      target_release=target_release or metadata[0]=='fedora-release-common'and metadata[1]==str(owner['target'])
      target_kernel=target_kernel or metadata[0]=='kernel-core'and '.fc'+str(owner['target'])in metadata[2]
      digest=hashlib.sha256()
      with path.open('rb')as source:
       for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
      signed.append([path.name,digest.hexdigest()])
     assert target_release and target_kernel
     receipt['signed_rpms']={'count':len(signed),'sha256':drain.hashed(signed),'target_release_and_kernel':True}
    def verified(step_name,digest):return step_name==step and digest==drain.hashed(receipt) and evidence()==value
    result['journal']=journal.accept(state['pending']['sha256'],drain.hashed(receipt),verified);result['accepted']=True
   elif fields['ActiveState']=='failed':
    result['failure_log']=native('journalctl','--no-pager','-u',unit,'-n','30','-o','cat')
 elif operation in('prepare-source','download-release','offline-transaction'):
  assert native('rpm','-E','%fedora')==str(owner['source'])
  step=operation.replace('-','_')
  expected=['cordon','drain']+(['prepare_source']if step!='prepare_source'else[])+(['download_release']if step=='offline_transaction'else[])
  assert state['completed']==expected and not state['pending']
  release=owner['source']if step=='prepare_source'else owner['target']
  directory=root/('fedora-repositories-'+str(release)+'-'+owner['owner']);assert(directory/'maintenance.repo').is_file()
  command=packages.command(owner,step);position=command.index('/usr/bin/dnf'if owner['source']==39 else '/usr/bin/dnf5')
  command[position+1:position+1]=['--setopt=reposdir='+str(directory),'--setopt=gpgcheck=True','--setopt=localpkg_gpgcheck=True']
  if owner['source']==39 and step=='prepare_source':
   upgrade_command=command[position:]
   plugin_command=upgrade_command[:5]+['install','dnf-plugin-system-upgrade']
   payload='import subprocess;subprocess.run('+repr(upgrade_command)+',check=True);subprocess.run('+repr(plugin_command)+',check=True)'
   command[position:]=['/usr/bin/python3','-c',payload]
  if step=='offline_transaction':
   if owner['source']==39:offline_repository_override()
   before={'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'identity':identity(),'source':owner['source'],'target':owner['target']}
   actors.exclusive_file(root/('before-offline-'+owner['owner']+'.json'),hops.canonical(before),0o600)
  value=evidence();pending=journal.begin(step,drain.hashed(command),drain.hashed(value),prerequisites(value))
  with hold.serialized():
   assert journal.read()==pending;journal.owners(idle=True)
   native(*command)
  result={'dispatched':True,'command':command,'pending':pending['pending']}
 else:raise RuntimeError('unreviewed operation')
 print(json.dumps({'result':result}),flush=True)
'''


def prerequisites(api):
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    require(len(nodes) == 9 and any(n['metadata']['uid'] == UID and n['metadata']['name'] == NODE for n in nodes),
            'production node membership differs')
    for node in nodes:
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        require(conditions.get('Ready') == 'True' and all(conditions.get(k) == 'False'
                for k in ('DiskPressure', 'MemoryPressure', 'PIDPressure')), 'node health is not green')
    health = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                      'ceph', 'health', '-f', 'json')
    require(health['status'] == 'HEALTH_OK', 'Ceph is not HEALTH_OK')
    exceptions = []
    for kind in ('deployments', 'statefulsets'):
        for item in api.call('get', kind, '-A', '-o', 'json')['items']:
            desired = item['spec'].get('replicas', 1)
            status = item.get('status', {})
            if (status.get('observedGeneration') == item['metadata']['generation'] and
                    status.get('readyReplicas', 0) == desired and
                    status.get('updatedReplicas', 0) == desired):
                continue
            meta = item['metadata']
            pinned = item['spec']['template']['spec'].get('nodeSelector', {})
            # These node-local Rook observers return only after the node is uncordoned.
            if (meta['namespace'] == 'rook-ceph' and pinned.get('kubernetes.io/hostname') == NODE and
                    (meta['name'].startswith('rook-ceph-crashcollector-') or
                     meta['name'].startswith('rook-ceph-exporter-'))):
                exceptions.append(meta['uid'])
                continue
            raise RuntimeError('controller unready: ' + meta['namespace'] + '/' + meta['name'])
    return {'node_uids': {n['metadata']['name']: n['metadata']['uid'] for n in nodes},
            'ceph': health['status'], 'controllers_ready_except_target_observers': True}


def infrastructure(api, applications=False):
    result = prerequisites(api)
    pods = api.call('get', 'pods', '-A', '--field-selector', 'spec.nodeName=' + NODE, '-o', 'json')['items']
    cilium = []
    expected_csi = {'rook-ceph.rbd.csi.ceph.com-nodeplugin',
                    'rook-ceph.cephfs.csi.ceph.com-nodeplugin'}
    daemonsets = api.call('get', 'daemonsets', '-n', 'rook-ceph', '-o', 'json')['items']
    csi_owners = {d['metadata']['uid']: d['metadata']['name'] for d in daemonsets
                  if d['metadata']['name'] in expected_csi and not d['metadata'].get('deletionTimestamp')}
    require(set(csi_owners.values()) == expected_csi, 'expected Rook CSI controllers absent')
    csi = {}
    for pod in pods:
        meta, status = pod['metadata'], pod.get('status', {})
        require(not meta.get('deletionTimestamp') and status.get('phase') == 'Running' and
                any(c['type'] == 'Ready' and c['status'] == 'True' for c in status.get('conditions', [])) and
                all(c.get('ready') for c in status.get('containerStatuses', [])) and
                len(status.get('containerStatuses', [])) == len(pod['spec']['containers']),
                'target node Pod is not ready: ' + meta['namespace'] + '/' + meta['name'])
        if meta['namespace'] == 'kube-system' and meta.get('labels', {}).get('k8s-app') == 'cilium':
            cilium.append(pod)
        for reference in meta.get('ownerReferences', []):
            if (meta['namespace'] == 'rook-ceph' and reference.get('kind') == 'DaemonSet' and
                    reference.get('controller') is True and reference.get('uid') in csi_owners):
                name = csi_owners[reference['uid']]
                require(name not in csi and meta.get('labels', {}).get('app') == name,
                        'duplicate or mismatched target CSI Pod')
                csi[name] = meta['uid']
    require(len(cilium) == 1 and set(csi) == expected_csi, 'target Cilium or both CSI node plugins absent')
    registration = api.call('get', 'csinode', NODE, '-o', 'json')
    require(not registration['metadata'].get('deletionTimestamp') and
            any(o.get('kind') == 'Node' and o.get('uid') == UID
                for o in registration['metadata'].get('ownerReferences', [])) and
            {d['name'] for d in registration['spec']['drivers'] if d['nodeID'] == NODE} ==
            {name.removesuffix('-nodeplugin') for name in expected_csi},
            'both CSI drivers are not registered to the exact target Node')
    status = api.call('exec', '-n', 'kube-system', cilium[0]['metadata']['name'], '-c', 'cilium-agent',
                      '--', 'cilium-dbg', 'status', '--output', 'json')
    require(status['cilium']['state'] == 'Ok' and status['kubernetes']['state'] == 'Ok',
            'target Cilium runtime or Kubernetes connectivity is not healthy')
    result.update(cilium_uid=cilium[0]['metadata']['uid'], csi_uids=sorted(csi.values()), target_pods_ready=True)
    if applications:
        node = api.call('get', 'node', NODE, '-o', 'json')
        require(not node['spec'].get('unschedulable', False), 'target node remains cordoned')
        for kind in ('deployments', 'statefulsets'):
            for item in api.call('get', kind, '-A', '-o', 'json')['items']:
                desired = item['spec'].get('replicas', 1)
                observed = item.get('status', {})
                require(observed.get('observedGeneration') == item['metadata']['generation'] and
                        observed.get('readyReplicas', 0) == desired and
                        observed.get('updatedReplicas', 0) == desired,
                        'controller recovery incomplete: ' + item['metadata']['namespace'] + '/' + item['metadata']['name'])
        apps = api.call('get', 'applications', '-n', 'argocd', '-o', 'json')['items']
        require(apps and all(a.get('status', {}).get('sync', {}).get('status') == 'Synced' and
                            a['status'].get('health', {}).get('status') == 'Healthy' for a in apps),
                'Argo application recovery incomplete')
        result['applications_synced_healthy'] = sorted(a['metadata']['name'] for a in apps)
    return result


def run_worker(args, api, owner, public_keys, recovery_manifest, bundle, precheck_proof=None):
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    program = ('bundle=' + repr(bundle) + '\nexpected_identity=' + repr(IDENTITY) +
               '\nexpected_ds_uid=' + repr(DS_UID) + '\nowner=' + repr(owner) +
               '\nnode_uids=' + repr({n['metadata']['name']: n['metadata']['uid'] for n in nodes}) +
               '\noperation=' + repr(args.operation) + '\npublic_keys=' + repr(public_keys) +
               '\nprecheck_proof=' + repr(precheck_proof) +
               '\nrecovery_manifest=' + repr(recovery_manifest) + '\n' + NATIVE)
    bootstrap = 'import json,sys;exec(compile(json.loads(sys.stdin.readline())["program"],"production-controller","exec"))'
    child = subprocess.Popen(ssh(args) + ['python3 -u -c ' + shlex.quote(bootstrap)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        child.stdin.write(json.dumps({'program': program}) + '\n');child.stdin.flush()
        result = None
        for line in child.stdout:
            request = json.loads(line)
            if 'result' in request:
                result = request['result'];continue
            try:
                if request['rpc'] == 'prerequisites':
                    value = prerequisites(api)
                elif request['rpc'] in ('infrastructure', 'applications'):
                    value = infrastructure(api, applications=request['rpc'] == 'applications')
                elif request['rpc'] == 'drain_controllers':
                    items = api.call('get', 'daemonsets,replicasets,statefulsets,jobs,replicationcontrollers',
                                     '-A', '-o', 'json')['items']
                    value = [{'apiVersion': item['apiVersion'], 'kind': item['kind'],
                              'metadata': {k: item['metadata'].get(k) for k in
                                           ('namespace', 'name', 'uid', 'deletionTimestamp')}} for item in items]
                else:
                    argv = request['argv']
                    require(argv[0] in ('get', 'patch', 'create'), 'unreviewed RPC operation')
                    if argv[0] == 'patch':
                        require(argv[1:3] in (['daemonset', 'kured'], ['node', NODE]), 'unreviewed patch target')
                    if argv[0] == 'create':
                        body = json.loads(request['data'])
                        require(body['kind'] == 'Eviction' and body['apiVersion'] == 'policy/v1' and
                                body['deleteOptions']['preconditions']['uid'], 'unreviewed creation')
                    value = api.call(*argv, data=request.get('data').encode() if request.get('data') else None)
                reply = {'ok': True, 'result': value}
            except Exception as error:
                reply = {'ok': False, 'error': str(error)}
            child.stdin.write(json.dumps(reply) + '\n');child.stdin.flush()
        child.wait()
        require(child.returncode == 0 and result is not None,
                'remote operation failed; keep ownership; inspect native journal: ' + child.stderr.read()[-2000:])
        return result
    finally:
        if child.poll() is None:
            child.terminate();child.wait()


def main():
    global ACTIVE_READER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'initialize', 'inspect', 'cordon', 'drain', 'observe-package',
                                             'source-repositories', 'target-repositories', 'prepare-source',
                                             'download-release', 'offline-transaction', 'observe-offline',
                                             'trusted-reconnect', 'verify-infrastructure', 'restore-scheduling',
                                             'accept-applications', 'release', 'resolve-drain-precheck',
                                             'repair-offline-repositories'])
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--failure-receipt')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    remote = subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0]
    require(remote == revision, 'publish reviewed source before production use')
    bundle = {}
    for name in (*MODULES, 'maintenance_production_node', 'maintenance_api_reader', 'fedora_public_key'):
        relative = 'metal/scripts/' + name + '.py'
        published = subprocess.check_output(['git', 'show', revision + ':' + relative])
        require(Path(relative).read_bytes() == published, 'unpublished controller source: ' + relative)
        if name in MODULES:
            bundle[name] = published.decode()
    precheck_proof = None
    if args.operation == 'resolve-drain-precheck':
        require(args.failure_receipt, 'exact captured pre-dispatch failure is required')
        raw = Path(args.failure_receipt).read_bytes()
        expected_failure = '1553dfc2b049c0bb7cd6e8a379e691e72555c711581878a2016ece428393c44e'
        require(hashlib.sha256(raw).hexdigest() == expected_failure, 'pre-dispatch failure receipt differs')
        failure = json.loads(raw)
        require(failure['exit'] == 1 and failure['output'] == '' and
                'maintenance_node_drain.py", line 229, in advance' in failure['error'] and
                failure['error'].endswith('RuntimeError: native package actor active; never terminate it\n\n'),
                'failure did not prove the reviewed pre-dispatch exit')
        original = subprocess.check_output(['git', 'show',
            '70db7b9e06e699f375cf5fac39e75507c7d0eeee:metal/scripts/maintenance_node_drain.py'], text=True)
        require(original.splitlines()[228].strip() == 'self.journal.owners(idle=True)' and
                original.index("result = self.api.call('create'") > original.index('self.journal.owners(idle=True)'),
                'original failure path does not precede the first eviction request')
        precheck_proof = {'owner': 'homelab-maintenance-103-c8345d91-1dfe-4e58-8c13-b7c7b7519d54',
            'pod_uid': 'a9c87317-b6df-414b-8357-454bd5361e49',
            'intent_sha256': 'c6e261fbd338d54ea9314cf2cabeb650f76af3e1a2be6182127326498768a03b',
            'failure_sha256': expected_failure}
    api = ACTIVE_READER = Reader(args.kubectl)
    ds, _, nodes = api.snapshot()
    controller = Ownership(api, DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes})
    annotations = ds['metadata'].get('annotations', {})
    if JOURNAL in annotations:
        owner = json.loads(annotations[JOURNAL]);owner = controller.resume(owner['owner'])
        require(owner['node'] == NODE and owner['node_uid'] == UID, 'another node owns maintenance')
    else:
        require(args.operation in ('backup', 'initialize'), 'initialize production ownership first')
        prerequisites(api)
        source = remote(args, "import json,subprocess;print(json.dumps(int(subprocess.check_output(['rpm','-E','%fedora']))))")
        require(source in (39, 41, 43), 'unreviewed production source release')
        owner = None
    # Keep an active hop bound to its original recovery point after the target boots.
    recovery_manifest = recovery(args, owner['source'] if owner else source,
                                 capture=args.operation == 'backup')
    if args.operation == 'backup':
        print(encoded(recovery_manifest));return
    if owner is None:
        owner = controller.acquire(NODE, source, {39: 41, 41: 43, 43: 44}[source], revision)
    public_keys = {}
    if args.operation in ('source-repositories', 'target-repositories'):
        records = json.loads(Path('metal/maintenance/fedora-upgrade-inputs.json').read_text())['keys']
        for release in (str(owner['source']), str(owner['target'])):
            record = records[release]
            answer = subprocess.check_output(['dig', '+noall', '+answer', record['dns'], 'OPENPGPKEY'], text=True)
            fields = answer.split()
            require(len(fields) >= 5 and fields[0].rstrip('.') == record['dns'] and
                    fields[2:4] == ['IN', 'OPENPGPKEY'], 'unexpected Fedora public-key DNS answer')
            raw = base64.b64decode(''.join(fields[4:]), validate=True)
            require(hashlib.sha256(raw).hexdigest() == record['sha256'], 'Fedora key fingerprint input changed')
            public_keys[release] = base64.b64encode(armor_public_key(raw)).decode()
    print(encoded(run_worker(args, api, owner, public_keys, recovery_manifest, bundle, precheck_proof)))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    try:
        main()
    finally:
        if ACTIVE_READER is not None:
            ACTIVE_READER.close()
