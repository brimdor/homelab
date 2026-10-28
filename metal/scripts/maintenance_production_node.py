#!/usr/bin/env python3
"""Issue 103 production controller: exact reviewed worker identities, existing secure access.

The workstation retains Kubernetes credentials. The root SSH child calls back over
its existing protected stdio channel for fresh API observations and mutations.
"""

import argparse
import base64
import hashlib
import importlib.util
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
MAC = '6c:4b:90:5b:a3:56'
RECEIVER = 'pikachu'
RECEIVER_ADDRESS = '10.0.20.14'
RECEIVER_IDENTITY = {'machine': '0a7daf8b33244d9d85f46223c3582da9', 'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997'}
DS_UID = '4abc4fee-c3be-440e-8945-34bb3fb15ce1'
IDENTITY = {'machine': '0f1915a59a124d999d8d68b53f406af1',
            'root_uuid': '489f1af8-5d55-4356-8d48-418fcb2069a2'}
BACKUPS = {39: '/var/lib/homelab-recovery/maintenance-103/totodile-config-20261026-a',
           41: '/var/lib/homelab-recovery/maintenance-103/totodile-fedora41-config-20261026-a',
           43: '/var/lib/homelab-recovery/maintenance-103/totodile-fedora43-config-20261026-a',
           44: '/var/lib/homelab-recovery/maintenance-103/totodile-fedora44-config-20261026-a'}
SECURITY_BACKUPS = {node: '/var/lib/homelab-recovery/maintenance-103/' + node +
                    '-fedora44-seccomp-config-20261027-a' for node in ('totodile', 'pikachu')}
MODULES = ('maintenance_coordination', 'maintenance_actor_hold', 'maintenance_hop_journal',
           'maintenance_package_dispatch', 'maintenance_node_drain',
           'maintenance_node_scheduling', 'maintenance_kured_20261026', 'maintenance_safe_release',
           'maintenance_host_security', 'maintenance_init_socket', 'maintenance_cuda', 'maintenance_nvidia',
           'maintenance_rpmfusion')
OSD_RECOVERY = {
    'arcanine': (('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_a527115d-9f22-48cc-a718-4f30bdb64399', '/dev/sda3'),
                 ('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_38cfd0d6-ace5-4bc2-972a-0315835b3b92', '/dev/sdb')),
    'cyndaquil': ('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_1c69c51e-b0da-42ee-bd34-581361740a02', '/dev/sda3'),
    'growlithe': ('var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_e7ccd0a2-4d7a-41bb-aac9-5464abe2ba85', '/dev/nvme0n1p1'),
}
ACTIVE_READER = None
ACTIVE_ARGS = None


def select_node(node):
    global NODE, ADDRESS, UID, MAC, IDENTITY, BACKUPS, RECEIVER, RECEIVER_ADDRESS, RECEIVER_IDENTITY
    if node == 'totodile':
        return
    if node == 'bulbasaur':
        NODE, ADDRESS, UID, MAC = ('bulbasaur', '10.0.20.13',
            'b921073c-822a-4b74-80ed-563fec33d6ab', '00:23:24:e2:0d:ea')
        IDENTITY = {'machine': 'f61201c3e2ba4b8cbd31e09f77da2ad0',
                    'root_uuid': '2c59d1d1-d2d8-420e-b3a5-d87eb0437823'}
        RECEIVER, RECEIVER_ADDRESS = 'charmander', '10.0.20.11'
        RECEIVER_IDENTITY = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
                             'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/bulbasaur-fedora' +
                   str(release) + '-config-20261028-a' for release in (39, 41, 43, 44)}
        return
    if node == 'arcanine':
        NODE, ADDRESS, UID, MAC = ('arcanine', '10.0.20.19',
            '88aa2572-09df-40b9-8a00-960e9682917c', '4c:cc:6a:3d:e5:3f')
        IDENTITY = {'machine': 'd877c676fcc2434f9a169f8dc0594676',
                    'root_uuid': 'd5ffa207-0e76-47a7-a941-1829732d3bc6'}
        RECEIVER, RECEIVER_ADDRESS = 'charmander', '10.0.20.11'
        RECEIVER_IDENTITY = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
                             'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/arcanine-fedora' +
                   str(release) + '-config-20261027-a' for release in (39, 41, 43, 44)}
        return
    if node == 'growlithe':
        NODE, ADDRESS, UID, MAC = ('growlithe', '10.0.20.18',
            '50f95b8f-4117-4c1e-84bc-266c5b23bffb', '6c:4b:90:5b:6e:6d')
        IDENTITY = {'machine': 'a26cbcc990c044dea41fbf4f957f453d',
                    'root_uuid': '710e2dca-691e-4123-a867-4994b9c6e612'}
        RECEIVER, RECEIVER_ADDRESS = 'charmander', '10.0.20.11'
        RECEIVER_IDENTITY = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
                             'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/growlithe-fedora' +
                   str(release) + '-config-20261027-a' for release in (39, 41, 43, 44)}
        return
    if node == 'cyndaquil':
        NODE, ADDRESS, UID, MAC = ('cyndaquil', '10.0.20.16',
            '6a26f4ed-68e6-4681-baf9-47660549c4fb', '6c:4b:90:5f:8e:43')
        IDENTITY = {'machine': '51140709f60f45c1bcd0edfa23dba2ef',
                    'root_uuid': 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/cyndaquil-fedora' +
                   str(release) + '-config-20261027-a' for release in (39, 41, 43, 44)}
        # Preserve the failed role-mismatch capture; never overwrite its nonempty partial.
        BACKUPS[39] = '/var/lib/homelab-recovery/maintenance-103/cyndaquil-fedora39-config-20261027-b'
        return
    if node == 'charmander':
        NODE, ADDRESS, UID, MAC = ('charmander', '10.0.20.11',
            '9108f105-f73d-41bb-891f-ac2db6658714', '00:23:24:b0:ff:03')
        IDENTITY = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
                    'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/charmander-fedora' +
                   str(release) + '-config-20261026-a' for release in (39, 41, 43, 44)}
        return
    if node == 'squirtle':
        NODE, ADDRESS, UID, MAC = ('squirtle', '10.0.20.12',
            '10951ffe-dd31-4c38-b854-67f3a011458c', '00:23:24:e2:1f:a1')
        IDENTITY = {'machine': '90c7f1d7caea486d9dc9bdbb4ec5ae21',
                    'root_uuid': 'eea5afa0-dbb6-43f5-abe6-f1be801fb03a'}
        BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/squirtle-fedora' +
                   str(release) + '-config-20261026-a' for release in (39, 41, 43, 44)}
        return
    require(node == 'pikachu', 'worker profile is not reviewed')
    RECEIVER, RECEIVER_ADDRESS, RECEIVER_IDENTITY = NODE, ADDRESS, dict(IDENTITY)
    NODE, ADDRESS, UID, MAC = ('pikachu', '10.0.20.14',
        '7ec4e786-0b5d-416d-9284-8eac993635bf', 'e0:4f:43:24:0b:53')
    IDENTITY = {'machine': '0a7daf8b33244d9d85f46223c3582da9',
                'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997'}
    BACKUPS = {release: '/var/lib/homelab-recovery/maintenance-103/pikachu-' +
        ('config' if release == 39 else 'fedora' + str(release) + '-config') + '-20261026-a'
        for release in (39, 41, 43, 44)}


def ssh(args, address=None):
    address = ADDRESS if address is None else address
    return ['ssh', '-i', args.identity, '-o', 'IdentitiesOnly=yes',
            '-o', 'UserKnownHostsFile=' + args.known_hosts, '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UpdateHostKeys=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            'root@' + address]


def remote(args, program, address=None):
    result = subprocess.run(ssh(args, address) + ['python3 -B -'], input=program.encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode == 0, 'protected remote operation failed: ' + result.stderr.decode()[-1500:])
    return json.loads(result.stdout)


def recovery(args, source, capture=False):
    require(source in BACKUPS, 'unreviewed recovery source release')
    backup = BACKUPS[source]
    osd_recovery = {node: entries if node == 'arcanine' else (entries,)
                    for node, entries in OSD_RECOVERY.items()}
    control_plane = None
    if NODE in ('squirtle', 'charmander', 'bulbasaur'):
        from maintenance_control_plane import recovery as control_plane_recovery
        control_plane = control_plane_recovery(args, source, capture, node=NODE)
    receiver_name, receiver_address, receiver_identity = RECEIVER, RECEIVER_ADDRESS, RECEIVER_IDENTITY
    if (NODE == 'pikachu' and source in (43, 44) or
            NODE == 'squirtle' and source in (41, 43, 44) or NODE in ('charmander', 'cyndaquil')):
        receiver_name, receiver_address = 'growlithe', '10.0.20.18'
        receiver_identity = {'machine': 'a26cbcc990c044dea41fbf4f957f453d',
                             'root_uuid': '710e2dca-691e-4123-a867-4994b9c6e612'}
    if NODE == 'pikachu' and source == 44 and BACKUPS[44] == SECURITY_BACKUPS[NODE]:
        receiver_name, receiver_address = 'cyndaquil', '10.0.20.16'
        receiver_identity = {'machine': '51140709f60f45c1bcd0edfa23dba2ef',
                             'root_uuid': 'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8'}
    readback = """
import hashlib,json,os,pathlib,socket,stat,subprocess,tarfile
assert os.geteuid()==0 and socket.gethostname()==%r
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
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
 osd_recovery=%r
 if value.get('node')in osd_recovery:
  for prefix,block in osd_recovery[value['node']]:
   with tarfile.open(archive)as saved:
    entries=[m for m in saved if m.name==prefix or m.name.startswith(prefix+'/')]
    members={m.name:m for m in entries};assert len(members)==len(entries)
    assert set(members)=={prefix,*[prefix+'/'+n for n in ('block','ceph_fsid','fsid','keyring','ready','require_osd_release','type','whoami')]}
    assert members[prefix].isdir()and members[prefix+'/block'].issym()and members[prefix+'/block'].linkname==block
    assert all(m.isreg()for n,m in members.items()if n not in(prefix,prefix+'/block'))
 print(json.dumps(value))
""" % (receiver_name, receiver_identity['machine'], receiver_identity['root_uuid'], backup, osd_recovery)
    existing = remote(args, readback, receiver_address)
    if existing is not None:
        require(existing['identity'] == IDENTITY and existing['node_uid'] == UID and
                existing.get('source_release', 39) == source, 'recovery identity or source changed')
        if control_plane is not None:
            require(existing.get('control_plane_recovery') == control_plane,
                    'configuration archive is not bound to the protected consistent etcd snapshot')
        return existing
    require(capture, 'capture protected target configuration before production ownership')
    source_program = """
import os,pathlib,socket,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()==%r
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
assert int(subprocess.check_output(['rpm','-E','%%fedora']))==%r
assert %r in{p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
pid=subprocess.check_output(['systemctl','show','k3s','-p','MainPID','--value'],text=True).strip()
argv=(pathlib.Path('/proc')/pid/'cmdline').read_bytes().split(bytes([0]))
etcd=pathlib.Path('/var/lib/rancher/k3s/server/db/etcd')
listeners=subprocess.check_output(['ss','-H','-lnt'],text=True)
if %r:
 assert argv[0]in(b'k3s server',b'k3s-server',b'/usr/local/bin/k3s server')or len(argv)>1 and argv[1]==b'server'
 assert etcd.is_dir()and any(':2379'in line for line in listeners.splitlines())
else:
 assert argv[0]in(b'k3s agent',b'k3s-agent',b'/usr/local/bin/k3s agent')or len(argv)>1 and argv[1]==b'agent'
 assert not etcd.exists()or {p.name for p in etcd.iterdir()}<={'name'}
 assert not any(':2379'in line or ':2380'in line for line in listeners.splitlines())
command=['tar','--numeric-owner','--acls','--xattrs','--selinux','--one-file-system',
 '--exclude=var/lib/rancher/k3s/agent/containerd','--exclude=var/lib/rancher/k3s/agent/images',
 '-C','/','-cf','-','etc','boot','boot/efi','usr/local/bin/k3s','var/lib/rancher/k3s/agent']
server=pathlib.Path('/var/lib/rancher/k3s/server')
assert not server.is_symlink()
if server.exists():
 assert server.is_dir()
 command.append('var/lib/rancher/k3s/server')
else:assert not %r,'control-plane recovery requires its server directory'
if %r:
 command.insert(1,'--exclude=var/lib/rancher/k3s/server/db')
 command.append('var/lib/homelab-recovery/maintenance-103')
for prefix,block in %r:
 command.append(prefix)
sys.exit(subprocess.run(command).returncode)
""" % (NODE, IDENTITY['machine'], IDENTITY['root_uuid'], source, MAC, NODE in ('squirtle', 'charmander', 'bulbasaur'), NODE in ('squirtle', 'charmander', 'bulbasaur'), NODE in ('squirtle', 'charmander', 'bulbasaur'), osd_recovery.get(NODE, ()))
    receiver = """
import hashlib,json,os,pathlib,socket,stat,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()==%r
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
root=pathlib.Path(%r)
assert not any(p.is_symlink()for p in(root,*root.parents))
for parent in (root.parent.parent,root.parent):
 assert not any(p.is_symlink()for p in(parent,*parent.parents))
 if not parent.exists():parent.mkdir(mode=0o700)
 assert parent.is_dir()and parent.stat().st_uid==0 and not parent.stat().st_mode&0o022
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
""" % (receiver_name, receiver_identity['machine'], receiver_identity['root_uuid'], backup)
    producer = subprocess.Popen(ssh(args) + ['python3 -B -c ' + shlex.quote(source_program)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = subprocess.Popen(ssh(args, receiver_address) + ['python3 -B -c ' + shlex.quote(receiver)],
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
        if control_plane is not None:
            manifest.update(control_plane_recovery=control_plane,
                            recovery_scope='configuration-boot-server-identity-retained-material-with-separate-consistent-etcd')
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
        remote(args, finalize, receiver_address)
        return remote(args, readback, receiver_address)
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
 assert os.geteuid()==0 and socket.gethostname()==expected_node and result==expected_identity
 assert expected_mac in {p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
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
 def completed_cuda(self,ref):return rpc('completed_cuda',ref=ref)
 def drain_controllers(self):
  return{(v['kind'],v['metadata']['namespace'],v['metadata']['name']):v for v in rpc('drain_controllers')}
api=API();controller=coord.Ownership(api,expected_ds_uid,node_uids)
assert controller.resume(owner['owner'])==owner
hold=actors.Hold(actors.Systemd(),identity,lambda token:controller.resume(token)==owner)
root=hold.state
def evidence():return rpc('prerequisites')
def prerequisites(value):
 return lambda step,digest:evidence()==value and digest==drain.hashed(value)
def final_security():
 if owner['target']!=44:return None
 assert api.call('get','node',expected_node,'-o','json')['status']['nodeInfo']['bootID']==pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Node readiness belongs to an earlier boot'
 assert native('getenforce')=='Enforcing'and pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1','final target requires actual SELinux enforcement'
 assert 'SELINUX=enforcing'in pathlib.Path('/etc/selinux/config').read_text().splitlines(),'SELinux enforcement is not persistent'
 assert not {'selinux=0','enforcing=0'}.intersection(pathlib.Path('/proc/cmdline').read_text().split()),'kernel overrides SELinux enforcement'
 if expected_node in('charmander','cyndaquil','growlithe','arcanine','bulbasaur')or owner['source']==owner['target']==44:
  pods=api.call('get','pods','-n','loki','--field-selector','spec.nodeName='+expected_node,'-o','json')['items']
  agents=[p for p in pods if any(c['name']=='alloy'for c in p['spec']['containers'])]
  assert len(agents)==1,'existing Alloy acceptance process absent or ambiguous'
  agent=agents[0];container=next(c for c in agent['spec']['containers']if c['name']=='alloy')
  assert not agent['metadata'].get('deletionTimestamp')and any(c['type']=='Ready'and c['status']=='True'for c in agent['status']['conditions'])
  assert not agent['spec'].get('securityContext',{}).get('seccompProfile')and not container.get('securityContext',{}).get('seccompProfile')
  assert not container.get('securityContext',{}).get('privileged',False),'privileged process cannot prove kubelet default'
  sys.modules['maintenance_host_security'].seccomp_default(native,agent['metadata']['uid'])
 journal=hops.Journal(controller,hold,owner['owner'])
 if expected_node=='arcanine':sys.modules['maintenance_nvidia'].permanent_repository(journal,native)
 return sys.modules['maintenance_host_security'].acceptance(journal,native,identity)
if operation in('restore-scheduling','resolve-scheduling-precheck','accept-applications','release','resolve-release-precheck'):final_security()
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
if operation in('release','resolve-release-precheck'):
 release=sys.modules['maintenance_safe_release'].Release(hops.Journal(controller,hold,owner['owner']))
 value=rpc('applications');digest=drain.hashed(value)
 def safe_release(header,observed_digest):
  final_security()
  if observed_digest!=digest or identity()!=header['owners']['host']['identity']:return False
  current=rpc('applications') # This call freshly validates every runtime and exact Job owner UID.
  directory=root/('release-evidence-'+owner['owner']);actors.safe(directory)
  if not directory.exists():directory.mkdir(mode=0o700);actors.fsync_directory(root)
  proof={'owner':owner['owner'],'identity':identity(),'health':current}
  path=directory/(drain.hashed(proof)+'.json')
  if not path.exists():actors.exclusive_file(path,hops.canonical(proof),0o600)
  assert path.read_bytes()==hops.canonical(proof)
  return True
 if operation=='resolve-release-precheck':
  with hold.serialized():
   state=release.read();assert state['kinds']==list(sys.modules['maintenance_safe_release'].KINDS[:4])
   assert precheck_proof['owner']==owner['owner'] and not release.host_held(state['header']) and release.global_held(state['header'])
   assert state['head_sha256']==precheck_proof['release_head_sha256']
   release.verified(state,digest,safe_release)
   dispatch=root/('release-predispatch-recovery-'+owner['owner']+'.json')
   actors.exclusive_file(dispatch,hops.canonical({'proof':precheck_proof,'state_head':state['head_sha256'],'fresh_evidence_sha256':digest}),0o600)
   def verified_first_dispatch(current):
    return current==state['header']['owners']['global'] and release.read()==state and not release.host_held(state['header']) and release.verified(state,digest,safe_release)
   controller.release(owner['owner'],verified_first_dispatch)
 if not release.path.exists():release.prepare(digest,safe_release)
 status=release.observe(digest,safe_release)
 if status['state']['kinds']==['header']:status=release.release_host(digest,safe_release)
 if status['state']['kinds']==list(sys.modules['maintenance_safe_release'].KINDS[:3]):
  status=release.release_global(digest,safe_release)
 print(json.dumps({'result':status}),flush=True)
elif operation=='nvidia-repository':
 assert expected_node=='arcanine'
 current_node=api.call('get','node',expected_node,'-o','json')
 assert current_node['spec'].get('unschedulable')is True
 assert current_node['status']['nodeInfo']['bootID']==pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 evidence()
 journal=hops.Journal(controller,hold,owner['owner'])
 result=sys.modules['maintenance_nvidia'].persist_repository(journal,native,recovery_manifest)
 print(json.dumps({'result':result}),flush=True)
elif operation in('security-tools', 'observe-security-tools', 'security-policy','observe-security-policy','security-relabel','security-enforce', 'security-gds', 'security-firmware', 'observe-security-firmware', 'security-firmware-reboot','observe-host-security'):
 current_node=api.call('get','node',expected_node,'-o','json')
 assert current_node['spec'].get('unschedulable')is True
 assert current_node['status']['nodeInfo']['bootID']==pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Node readiness belongs to an earlier boot'
 if operation not in('observe-security-tools','observe-security-policy','observe-security-firmware','observe-host-security'):evidence()
 journal=hops.Journal(controller,hold,owner['owner'])
 result=(sys.modules['maintenance_host_security'].facts(native)if operation=='observe-host-security'else
  sys.modules['maintenance_host_security'].execute(operation,journal,native,identity,recovery_manifest))
 print(json.dumps({'result':result}),flush=True)
elif operation in('recover-pending-kanidm','recover-pending-outline'):
 assert expected_node=='pikachu' and owner['owner']=='homelab-maintenance-103-6f78a7a1-d165-430e-bde4-b85894582e77'
 profiles={
  'recover-pending-kanidm':('kanidm','platform/kanidm','kanidm','kanidm-0','ec5c8370-616e-40a4-8fc3-6615c25113f3','c967eb10-6452-4803-ab18-fb09210daa66','data-kanidm-0','cd728e28-34e1-4373-8c8d-65a314b758ad','c4a539ff-4ec2-4313-a053-29df5340615c'),
  'recover-pending-outline':('outline','apps/outline','outline-postgres','outline-postgres-0','32d5c378-0d90-4ae2-8266-dc6af20c3ccb','c361fc29-fa98-425e-8551-df21704e2c87','outline','36cb3442-3bf9-4ccd-a7be-4edd211f361a','409b7753-b5c5-424b-8709-643290566685')}
 namespace,app_path,sts_name,pod_name,pod_uid,sts_uid,claim_name,claim_uid,pv_uid=profiles[operation]
 journal=hops.Journal(controller,hold,owner['owner'])
 with hold.serialized():
  journal.owners(idle=True)
  assert api.call('get','node','pikachu','-o','json')['spec'].get('unschedulable')is True
  assert rpc('ceph_health')['status']=='HEALTH_OK'
  app=api.call('get','application',namespace,'-n','argocd','-o','json')
  assert app['status']['sync']['status']=='Synced' and app['spec']['source']['path']==app_path
  sts=api.call('get','statefulset',sts_name,'-n',namespace,'-o','json')
  assert sts['metadata']['uid']==sts_uid and sts['status']['observedGeneration']==sts['metadata']['generation']
  assert not sts['spec']['template']['spec'].get('nodeSelector') and sts['status']['currentRevision']!=sts['status']['updateRevision']
  assert sts['spec']['updateStrategy']['type']=='RollingUpdate' and sts['spec']['updateStrategy'].get('rollingUpdate',{}).get('partition')==0
  pod=api.call('get','pod',pod_name,'-n',namespace,'-o','json');meta=pod['metadata']
  assert meta['uid']==pod_uid and not meta.get('deletionTimestamp')
  assert pod['status']['phase']=='Pending' and not pod['spec'].get('nodeName') and not pod['status'].get('containerStatuses')
  assert pod['spec']['nodeSelector']=={'kubernetes.io/hostname':'pikachu'} and meta['labels']['controller-revision-hash']==sts['status']['currentRevision']
  assert len(meta['ownerReferences'])==1 and meta['ownerReferences'][0]['controller']is True and meta['ownerReferences'][0]['uid']==sts['metadata']['uid']
  claim=api.call('get','persistentvolumeclaim',claim_name,'-n',namespace,'-o','json')
  volume=api.call('get','persistentvolume',claim['spec']['volumeName'],'-o','json')
  assert claim['metadata']['uid']==claim_uid and claim['status']['phase']=='Bound'
  assert volume['metadata']['uid']==pv_uid and volume['spec']['claimRef']['uid']==claim['metadata']['uid']
  eviction={'apiVersion':'policy/v1','kind':'Eviction','metadata':{'namespace':namespace,'name':pod_name},
   'deleteOptions':{'preconditions':{'uid':meta['uid'],'resourceVersion':meta['resourceVersion']}}}
  record={'owner':owner['owner'],'pod_uid':meta['uid'],'claim_uid':claim['metadata']['uid'],'pv_uid':volume['metadata']['uid'],
   'current_revision':sts['status']['currentRevision'],'update_revision':sts['status']['updateRevision'],'eviction':eviction}
  path=root/(namespace+'-pending-replacement-'+meta['uid']+'.json')
  assert not path.exists(),'replacement intent exists; observe only, never replay'
  assert controller.resume(owner['owner'])==owner
  actors.exclusive_file(path,hops.canonical(record),0o600)
  response=api.call('create','--raw=/api/v1/namespaces/'+namespace+'/pods/'+pod_name+'/eviction','-f','-',data=hops.canonical(eviction))
  assert response.get('kind')=='Status' and response.get('status')=='Success','replacement uncertain; observe only'
  actors.exclusive_file(root/(path.stem+'-accepted.json'),hops.canonical({'intent_sha256':drain.hashed(record),'response':response}),0o600)
 print(json.dumps({'result':{'eviction_accepted':True,'pod_uid':meta['uid'],'original_storage_preserved':True}}),flush=True)
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
 elif operation=='repair-init-socket-policy':
  result=sys.modules['maintenance_init_socket'].execute(journal,native,identity,recovery_manifest)
 elif operation in('cordon','restore-scheduling','resolve-scheduling-precheck'):
  step='restore_scheduling'if operation=='resolve-scheduling-precheck'else operation.replace('-','_')
  path=root/(step+'-'+owner['owner']+'.json');worker=scheduling.Scheduling(journal,api)
  value=evidence();verify=prerequisites(value);digest=drain.hashed(value)
  original=json.loads((root/('cordon-'+owner['owner']+'.json')).read_bytes())if step=='restore_scheduling'else None
  if not path.exists():actors.exclusive_file(path,hops.canonical(worker.plan(step,original)),0o600)
  plan=json.loads(path.read_bytes())
  dispatched=False
  if operation=='resolve-scheduling-precheck':
   worker.dispatch(plan,drain.hashed(plan),digest,verify,precheck_proof=precheck_proof)
   dispatched=True
  elif not state['pending']:
   assert step==hops.steps(owner)[len(state['completed'])];worker.dispatch(plan,drain.hashed(plan),digest,verify)
   dispatched=True
  # This OSD can return only after uncordon; accept its intent on a later healthy observation.
  if dispatched and expected_node in('cyndaquil','growlithe','arcanine') and step=='restore_scheduling':
   result={'accepted':False,'pending':journal.inspect()['pending'],'scheduling_patch_dispatched':True}
  else:result=worker.observe(plan,digest,verify)
 elif operation in('security-default','observe-security-default'):
  assert owner['node']in('totodile','pikachu')and owner['source']==owner['target']==44
  assert api.call('get','node',expected_node,'-o','json')['spec'].get('unschedulable')is True
  value=evidence();digest=drain.hashed(value);verify=prerequisites(value)
  security=sys.modules['maintenance_host_security']
  if operation=='security-default':
   assert state['pending']is None and state['completed']==['cordon','drain']
   proof=security.default_plan(journal,native,identity,recovery_manifest)
   state=journal.begin('security_default',drain.hashed(proof),digest,verify)
   result=security.default_dispatch(journal,native,identity,recovery_manifest,proof)
  else:
   assert state['pending']and state['pending']['step']=='security_default'
   result=final_security()
   journal.accept(state['pending']['sha256'],drain.hashed(result),lambda step,h:step=='security_default'and h==drain.hashed(result)and evidence()==value)
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
   if expected_node=='arcanine':value['gpu']=sys.modules['maintenance_nvidia'].runtime(native,owner['target'])
  else:value['prerequisites']=evidence()
  digest=drain.hashed(value)
  def verified_observation(step_name,observed_digest):
   if step_name!=step or observed_digest!=digest or identity()!=value['identity']:return False
   if step=='trusted_reconnect':return evidence()==value['prerequisites']
   return rpc('applications'if step=='accept_applications'else'infrastructure')==value['runtime']and(expected_node!='arcanine'or sys.modules['maintenance_nvidia'].runtime(native,owner['target'])==value['gpu'])
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
  removed=(lambda ref:rpc('removed_completed_job',ref=ref))if expected_node=='charmander'and owner['owner']=='homelab-maintenance-103-8dba9073-c2fc-4941-a6d2-1228086bd554'else None
  if expected_node=='growlithe'and owner['owner']=='homelab-maintenance-103-44e0fa41-4b7e-4ba2-bb2e-370e59f61876':
   removed=lambda ref:rpc('removed_versa_canary',ref=ref)
  result=worker.advance(digest,verify,removed)
  if result.get('queued')and expected_node in('cyndaquil','growlithe','arcanine'):
   ref=result['queued'];osds={'cyndaquil':(1,),'growlithe':(6,),'arcanine':(2,8)}[expected_node]
   if ref['namespace']=='rook-ceph'and ref['controller']['kind']=='ReplicaSet'and any(ref['controller']['name'].startswith('rook-ceph-osd-'+str(osd)+'-')for osd in osds):
    result['owned_osd_protection']=rpc('await_osd_protection',ref=ref)
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
  if expected_node=='arcanine'and int(release)>39:
   result['nvidia']=sys.modules['maintenance_nvidia'].configure(directory,int(release),native)
   result['rpmfusion']=sys.modules['maintenance_rpmfusion'].configure(directory,int(release),native)
   result['openh264']=sys.modules['maintenance_rpmfusion'].configure_openh264(directory,int(release),native)
 elif operation in('repair-rpmfusion-download','repair-openh264-download'):
  result=sys.modules['maintenance_rpmfusion'].repair(journal,native,evidence,
   kind='openh264'if operation=='repair-openh264-download'else'rpmfusion')
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
     signed=[];target_release=False;target_kernel=False;package_metadata=[]
     for path in files:
      assert path.is_file()and not path.is_symlink()
      output=native('rpmkeys','--checksig','--verbose',str(path))
      assert all(v not in output for v in('NOKEY','NOT OK','BAD'))and 'signature'in output.lower()and 'OK'in output
      metadata=native('rpm','-qp','--qf','%{NAME} %{VERSION} %{RELEASE}',str(path)).split();package_metadata.append(metadata)
      target_release=target_release or metadata[0]=='fedora-release-common'and metadata[1]==str(owner['target'])
      target_kernel=target_kernel or metadata[0]=='kernel-core'and '.fc'+str(owner['target'])in metadata[2]
      digest=hashlib.sha256()
      with path.open('rb')as source:
       for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
      signed.append([path.name,digest.hexdigest()])
     assert target_release and target_kernel
     if expected_node=='arcanine':
      receipt['nvidia']=sys.modules['maintenance_nvidia'].downloaded(package_metadata,owner['target'])
      receipt['download_recovery']=sys.modules['maintenance_rpmfusion'].accepted(journal,native)
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
   before_path=root/('before-offline-'+owner['owner']+'.json');actors.safe(before_path)
   if before_path.exists():
    info=before_path.stat()
    assert info.st_uid==os.geteuid() and info.st_nlink==1 and info.st_mode&0o777==0o600
    assert before_path.read_bytes()==hops.canonical(before),'pre-dispatch boot identity changed; never replay'
   else:actors.exclusive_file(before_path,hops.canonical(before),0o600)
  value=evidence();pending=journal.begin(step,drain.hashed(command),drain.hashed(value),prerequisites(value))
  with hold.serialized():
   assert journal.read()==pending;journal.owners(idle=True)
   native(*command)
  result={'dispatched':True,'command':command,'pending':pending['pending']}
 else:raise RuntimeError('unreviewed operation')
 print(json.dumps({'result':result}),flush=True)
'''


def pending_on_maintained_node(api, item, node):
    """Only an unscheduled replacement of this exact target-pinned controller."""
    meta, template = item['metadata'], item['spec']['template']['spec']
    pods = api.call('get', 'pods', '-n', meta['namespace'], '-o', 'json')['items']
    selector = item['spec']['selector'].get('matchLabels', {})
    pods = [p for p in pods if selector and all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())]
    if len(pods) != 1:
        return False
    pod = pods[0]
    if (pod['status']['phase'] != 'Pending' or pod['metadata'].get('deletionTimestamp') or
            pod['status'].get('containerStatuses') or pod['status'].get('initContainerStatuses') or
            pod['spec'].get('nodeName') or pod['spec'].get('nodeSelector') != template.get('nodeSelector') or
            template.get('nodeSelector', {}).get('kubernetes.io/hostname') != node):
        return False
    owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller') is True]
    if len(owners) != 1 or not owners[0].get('uid'):
        return False
    owner = owners[0]
    if item['kind'] == 'StatefulSet':
        return owner['kind'] == 'StatefulSet' and owner['uid'] == meta['uid'] and owner['name'] == meta['name']
    if item['kind'] != 'Deployment' or owner['kind'] != 'ReplicaSet':
        return False
    replica = api.call('get', 'replicaset', owner['name'], '-n', meta['namespace'], '-o', 'json')
    parents = [o for o in replica['metadata'].get('ownerReferences', []) if o.get('controller') is True]
    return (replica['metadata']['uid'] == owner['uid'] and not replica['metadata'].get('deletionTimestamp') and
            len(parents) == 1 and parents[0]['kind'] == 'Deployment' and
            parents[0]['uid'] == meta['uid'] and parents[0]['name'] == meta['name'])


def pending_postgres_dependent(api, item, owner):
    """Observe only the approved Versa pair's expected shared-DB maintenance outage."""
    contracts = {
        'versa': ('c7202fda-0426-463e-b426-5b14f6743a4b', 40,
                  '91bb775bcccc5360d8909d0253ad971bb91fc3731d17e0c9f812db73a8ed653e',
                  '40207d9c-5d2d-41d6-974b-d94554533e43', 'cyndaquil',
                  'versa-c4cd76876', '06d0d8fd-4fd8-4979-8528-1b31c64e127a'),
        'versa-canary': ('72b69cae-fea1-4b99-ae0c-c515851cfac0', 132,
                         '92307b8f0e1555a430ac80fd82917e32a4db98428227ecf4df3506d00e3a2ace',
                         'a64b0886-fb7e-4e1b-b9f1-185e759525de', 'charmander',
                         'versa-canary-5c57fb798b', 'e5342b06-6ffe-4b84-97d5-011e74c40de7'),
    }
    meta = item['metadata']; namespace = meta['namespace']
    if (owner.get('owner') != 'homelab-maintenance-103-1c844363-2bac-4e15-90f5-6139f5624d5c' or
            namespace not in contracts or meta['name'] != namespace or item['kind'] != 'Deployment'):
        return None
    uid, generation, template, pod_uid, node, replica_name, replica_uid = contracts[namespace]
    require(meta['uid'] == uid and meta['generation'] == generation and not meta.get('deletionTimestamp') and
            item['spec'].get('replicas', 1) == 1 and
            hashlib.sha256(encoded(item['spec']['template']).encode()).hexdigest() == template,
            'approved dependent deployment changed')
    database = api.call('get', 'deployment', 'postgres', '-n', 'postgres', '-o', 'json')
    require(database['metadata']['uid'] == '9a7e7dcd-2302-401e-be49-af545ac06f9b' and
            database['metadata']['generation'] == 15 and
            hashlib.sha256(encoded(database['spec']['template']).encode()).hexdigest() ==
            '0f663742d95bb476040309324e2354ab6ee7ec3231ecf03f1a618bc4ee5bfab7' and
            pending_on_maintained_node(api, database, 'totodile'), 'expected database downtime differs')
    database_pods = api.call('get', 'pods', '-n', 'postgres', '-o', 'json')['items']
    require(any(p['metadata']['uid'] == '5fd59434-bdbc-47fa-9e8e-8eef5021f58e' and
                p['status']['phase'] == 'Pending' and not p['spec'].get('nodeName')
                for p in database_pods), 'database pending replacement changed')
    pods = api.call('get', 'pods', '-n', namespace, '-o', 'json')['items']
    require(len(pods) == 1, 'dependent Pod membership changed')
    pod = pods[0]; owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(pod['metadata']['uid'] == pod_uid and pod['spec'].get('nodeName') == node and
            not pod['metadata'].get('deletionTimestamp') and pod['status']['phase'] == 'Running' and
            len(owners) == 1 and owners[0]['kind'] == 'ReplicaSet' and
            owners[0]['name'] == replica_name and owners[0]['uid'] == replica_uid,
            'approved dependent Pod changed')
    replica = api.call('get', 'replicaset', replica_name, '-n', namespace, '-o', 'json')
    parents = [o for o in replica['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(replica['metadata']['uid'] == replica_uid and not replica['metadata'].get('deletionTimestamp') and
            len(parents) == 1 and parents[0]['kind'] == 'Deployment' and parents[0]['uid'] == uid,
            'dependent controller ownership changed')
    states = pod['status'].get('containerStatuses', [])
    init = pod['status'].get('initContainerStatuses', [])
    digest = 'sha256:a2b42b994c1e2a65373cdcdda7556a6a801c517c4bd56d3693f89f4c073be33d'
    require(len(states) == 2 and {c['name'] for c in states} == {'web', 'worker'} and
            len(init) == 1 and init[0]['name'] == 'migrate' and
            init[0]['state'].get('terminated', {}).get('exitCode') == 0 and
            all(c['imageID'].endswith('@' + digest) and c['restartCount'] == 0 for c in states + init) and
            all(c.get('started') and 'running' in c['state'] and
                (not c['ready'] if c['name'] == 'web' else c['ready']) for c in states),
            'dependent has an unexpected runtime failure')
    program = ('const h=await fetch(`http://${process.env.HOSTNAME}:3000/healthz`);'
               'const hj=await h.json();const r=await fetch(`http://${process.env.HOSTNAME}:3000/readyz`);'
               'const rj=await r.json();console.log(JSON.stringify({'
               'host:new URL(process.env.DATABASE_URL).hostname,health:h.status,ok:hj.ok,'
               'readiness:r.status,ready:rj.ready}));')
    proof = api.call('exec', '-n', namespace, pod['metadata']['name'], '-c', 'web', '--',
                     'node', '--input-type=module', '-e', program)
    require(proof == {'host': 'postgres.postgres.svc.cluster.local', 'health': 200, 'ok': True,
                      'readiness': 503, 'ready': False}, 'dependent failure is not the expected database outage')
    return {'deployment_uid': uid, 'pod_uid': pod_uid, 'database_pending_uid':
            '5fd59434-bdbc-47fa-9e8e-8eef5021f58e', 'proof': proof}


def prerequisites(api):
    if NODE == 'bulbasaur':
        protected_registry(api)
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    require(len(nodes) == 9 and any(n['metadata']['uid'] == UID and n['metadata']['name'] == NODE for n in nodes),
            'production node membership differs')
    for node in nodes:
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        require(conditions.get('Ready') == 'True' and all(conditions.get(k) == 'False'
                for k in ('DiskPressure', 'MemoryPressure', 'PIDPressure')), 'node health is not green')
    osd_gate = None
    if NODE in OSD_RECOVERY:
        from maintenance_osd_host import observe
        osd_gate = observe(api, node=NODE)
        health = {'status': osd_gate['scope']}
    else:
        health = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                          'ceph', 'health', '-f', 'json')
        require(health['status'] == 'HEALTH_OK', 'Ceph is not HEALTH_OK')
    exceptions = []
    ds = api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')
    raw_owner = ds['metadata'].get('annotations', {}).get(JOURNAL)
    security_followup = False
    dependency_outages = []
    if raw_owner is not None:
        candidate = json.loads(raw_owner)
        if candidate.get('source') == candidate.get('target') == 44:
            verified_owner = Ownership(api, DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes}).resume(candidate['owner'])
            security_followup = (NODE in ('totodile', 'pikachu') and verified_owner['node'] == NODE and
                                 next(n for n in nodes if n['metadata']['name'] == NODE)['spec'].get('unschedulable') is True)
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
            # Only the exact freshly validated OSD may wait for this cordoned host.
            if osd_gate and meta['uid'] in osd_gate.get('managed_deployment_uids', [osd_gate.get('managed_deployment_uid')]):
                exceptions.append(meta['uid'])
                continue
            # These node-local Rook observers return only after the node is uncordoned.
            if (meta['namespace'] == 'rook-ceph' and pinned.get('kubernetes.io/hostname') == NODE and
                    (meta['name'].startswith('rook-ceph-crashcollector-') or
                     meta['name'].startswith('rook-ceph-exporter-'))):
                exceptions.append(meta['uid'])
                continue
            if security_followup and pinned.get('kubernetes.io/hostname') == NODE and desired == 1:
                # Authorized node downtime ends on uncordon; never excuse a failing runtime.
                if pending_on_maintained_node(api, item, NODE):
                    exceptions.append(meta['uid'])
                    continue
            if security_followup:
                dependent = pending_postgres_dependent(api, item, verified_owner)
                if dependent:
                    dependency_outages.append(dependent)
                    continue
            raise RuntimeError('controller unready: ' + meta['namespace'] + '/' + meta['name'])
    result = {'node_uids': {n['metadata']['name']: n['metadata']['uid'] for n in nodes},
              'ceph': health['status'], 'controllers_ready_except_target_observers': not dependency_outages}
    if dependency_outages:
        result['expected_dependency_outages'] = sorted(dependency_outages, key=lambda p: p['deployment_uid'])
    if osd_gate is not None:
        result['osd_host'] = osd_gate
    if NODE in ('squirtle', 'charmander', 'bulbasaur'):
        from maintenance_control_plane import observe
        quorum = observe(ACTIVE_ARGS)
        result['etcd'] = {'members': sorted(m['ID'] for m in quorum['members']['members']),
                          'cluster_id': quorum['status'][0]['Status']['header']['cluster_id'],
                          'leader': quorum['status'][0]['Status']['leader']}
    return result


def protected_registry(api):
    """Bulbasaur maintenance must preserve the existing NAS-backed registry process."""
    pods = api.call('get', 'pods', '-n', 'zot', '-o', 'json')['items']
    require(len(pods) == 1, 'protected registry Pod membership changed')
    pod = pods[0]
    require(pod['metadata']['uid'] == 'ee41a015-dec7-47d4-89ac-54ed8100d7fc' and
            pod['spec'].get('nodeName') == 'charmander' and not pod['metadata'].get('deletionTimestamp') and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status'].get('conditions', [])),
            'protected registry moved, restarted or is unready')
    containers = pod['status'].get('containerStatuses', [])
    require(len(containers) == 1 and containers[0]['name'] == 'zot' and containers[0].get('ready') is True and
            containers[0].get('restartCount') == 0 and containers[0].get('containerID') ==
            'containerd://c64893596b9e9f4444cf89a84dfd0c8de029bad82f637a0a777f149092d42078',
            'protected registry container identity changed')
    claim = api.call('get', 'pvc', 'zot-nfs-pvc', '-n', 'zot', '-o', 'json')
    volume = api.call('get', 'pv', 'pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6', '-o', 'json')
    require(claim['metadata']['uid'] == '728fbc24-a589-483f-8833-855c863b4f04' and
            claim['spec']['volumeName'] == volume['metadata']['name'] and claim['status']['phase'] == 'Bound' and
            volume['metadata']['uid'] == '81d390a2-71fd-48ac-ac2f-49df07bda484' and
            volume['spec']['claimRef']['uid'] == claim['metadata']['uid'] and
            volume['spec']['persistentVolumeReclaimPolicy'] == 'Retain' and volume['spec'].get('nfs') == {
                'server': '10.0.40.3',
                'path': '/mnt/user/heartlib/zot-zot-nfs-pvc-pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6'},
            'protected registry storage identity changed')
    return {'pod_uid': pod['metadata']['uid'], 'node': 'charmander', 'restarts': 0}


def completed_job_pod(api, pod):
    """Use CORE's existing evidence parsers; completion alone is insufficient."""
    meta, spec, status = pod['metadata'], pod['spec'], pod.get('status', {})
    require(status.get('phase') == 'Succeeded' and not meta.get('deletionTimestamp') and
            spec.get('restartPolicy') in ('Never', 'OnFailure'), 'unproven completed Pod')
    module_spec = importlib.util.spec_from_file_location('maintenance_core_evidence',
        Path(__file__).resolve().parents[2] / 'scripts/homelab-health.py')
    core = importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(core)
    if any(o.get('kind') == 'ClusterPolicy' for o in meta.get('ownerReferences', [])):
        node = api.call('get', 'node', NODE, '-o', 'json')
        require(spec.get('nodeName') == NODE and node['metadata']['uid'] == UID and
                not node['metadata'].get('deletionTimestamp'), 'completed validator target identity differs')
        row = {'namespace': meta['namespace'], 'name': meta['name'], 'node_in_active_inventory': True,
               'containers': core.container_evidence(spec, status, 'containers'),
               'init_containers': core.container_evidence(spec, status, 'initContainers')}
        validators = api.call('get', 'daemonsets', '-n', 'gpu-operator', '-o', 'json')['items']
        require(core.cuda_completion_proven(pod, row, validators), 'completed CUDA validator is unproven')
        policy = api.call('get', 'clusterpolicy', 'cluster-policy', '-o', 'json')
        require(policy['metadata']['uid'] == meta['ownerReferences'][0]['uid'] and
                not policy['metadata'].get('deletionTimestamp'), 'CUDA ClusterPolicy was replaced or deleted')
        return {'pod_uid': meta['uid'], 'cluster_policy_uid': policy['metadata']['uid']}
    owners = [o for o in meta.get('ownerReferences', []) if o.get('kind') == 'Job' and
              o.get('controller') is True and isinstance(o.get('uid'), str) and o['uid']]
    require(len(owners) == 1, 'completed Pod lacks one controlling Job UID')
    owner = owners[0]
    job = api.call('get', 'job', owner['name'], '-n', meta['namespace'], '-o', 'json')
    require(job['metadata']['uid'] == owner['uid'] and not job['metadata'].get('deletionTimestamp'),
            'completed Pod Job identity differs')
    evidence = core.job_evidence(job)
    require(evidence['complete'] or evidence['active'] > 0 and not evidence['terminal_failed'],
            'completed Pod Job is neither complete nor active and nonfailed')
    containers = core.container_evidence(spec, status, 'containers')
    initializers = core.container_evidence(spec, status, 'initContainers')
    require(all(c['state'] == 'terminated' and c['exit_code'] == 0 for c in containers) and
            all(c['state'] == 'terminated' and (c['sidecar_init'] or c['exit_code'] == 0)
                for c in initializers), 'completed Pod containers did not legitimately succeed')
    return {'pod_uid': meta['uid'], 'job_uid': owner['uid']}


def pointview_baseline(api, application):
    """Keep four proven earlier image-pull failures visible during Pikachu OS hops only."""
    namespace = application['metadata']['name']
    profiles = {
        'pointview': {
            'retention': ('5e2e2097-b4bb-421f-ac3d-c0237991c7a1', 'eede725c-f9c0-438c-8593-5c9e155acc61'),
            'triage': ('cfb8a9b7-284e-4fa3-9e63-93883c37ab46', '50610e53-b900-46b3-8955-c11bd602b567')},
        'pointview-canary': {
            'retention': ('c72903d7-1682-4f22-8a84-697c4661e9c4', 'd98b2b80-4695-468c-946b-7b52edacbd6e'),
            'triage': ('b72b5495-5494-4ac0-b9c2-0dbf3a4d07c0', '6527a8a7-896d-4b83-b12f-44b75fac4ab2')},
    }
    require(namespace in profiles and application['status']['health']['status'] == 'Degraded' and
            not application['status'].get('conditions'), 'unreviewed application degradation')
    expected = profiles[namespace]
    jobs = api.call('get', 'jobs', '-n', namespace, '-o', 'json')['items']
    failures = []
    for job in jobs:
        status, meta = job.get('status', {}), job['metadata']
        if not any(c['type'] == 'Failed' and c['status'] == 'True' for c in status.get('conditions', [])):
            require(not status.get('active') and not status.get('failed'), 'new PointView job activity or failure')
            continue
        kind = next((kind for kind, (uid, _) in expected.items() if uid == meta['uid']), None)
        require(kind is not None and not meta.get('deletionTimestamp') and not status.get('active') and
                meta['creationTimestamp'] < '2026-10-26T11:23:00Z' and
                any(o.get('kind') == 'CronJob' and o.get('controller') is True and
                    o.get('uid') == expected[kind][1] for o in meta.get('ownerReferences', [])) and
                any(c['type'] == 'Failed' and c['status'] == 'True' and c.get('reason') == 'DeadlineExceeded'
                    for c in status.get('conditions', [])), 'PointView baseline Job identity or failure changed')
        failures.append(meta['uid'])
    require(set(failures) == {uid for uid, _ in expected.values()}, 'PointView baseline failure set changed')
    pods = api.call('get', 'pods', '-n', namespace, '-o', 'json')['items']
    require(pods, 'PointView workload evidence absent')
    for pod in pods:
        if pod.get('status', {}).get('phase') == 'Succeeded':
            completed_job_pod(api, pod)
        else:
            require(not pod['metadata'].get('deletionTimestamp') and
                    pod['status'].get('phase') == 'Running' and
                    any(c['type'] == 'Ready' and c['status'] == 'True'
                        for c in pod['status'].get('conditions', [])) and
                    len(pod['status'].get('containerStatuses', [])) == len(pod['spec']['containers']) and
                    all(c.get('ready') for c in pod['status'].get('containerStatuses', [])),
                    'new PointView Pod finding')
    return {'application': namespace, 'failed_job_uids': sorted(failures),
            'disposition': 'INCOMPLETE: preexisting image pull failures; final acceptance still blocked'}


def infrastructure(api, applications=False, intermediate_pikachu=False):
    result = prerequisites(api)
    pods = api.call('get', 'pods', '-A', '--field-selector', 'spec.nodeName=' + NODE, '-o', 'json')['items']
    cilium, completed_jobs = [], []
    expected_csi = {'rook-ceph.rbd.csi.ceph.com-nodeplugin',
                    'rook-ceph.cephfs.csi.ceph.com-nodeplugin'}
    daemonsets = api.call('get', 'daemonsets', '-n', 'rook-ceph', '-o', 'json')['items']
    csi_owners = {d['metadata']['uid']: d['metadata']['name'] for d in daemonsets
                  if d['metadata']['name'] in expected_csi and not d['metadata'].get('deletionTimestamp')}
    require(set(csi_owners.values()) == expected_csi, 'expected Rook CSI controllers absent')
    csi = {}
    for pod in pods:
        meta, status = pod['metadata'], pod.get('status', {})
        if status.get('phase') == 'Succeeded':
            completed_jobs.append(completed_job_pod(api, pod))
            continue
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
    result.update(cilium_uid=cilium[0]['metadata']['uid'], csi_uids=sorted(csi.values()), target_pods_ready=True,
                  completed_jobs=sorted(completed_jobs, key=lambda item: item['pod_uid']))
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
        require(apps and all(a.get('status', {}).get('sync', {}).get('status') == 'Synced' for a in apps),
                'Argo application sync incomplete')
        findings = []
        for application in apps:
            if application['status'].get('health', {}).get('status') != 'Healthy':
                require(intermediate_pikachu and NODE == 'pikachu', 'Argo application recovery incomplete')
                findings.append(pointview_baseline(api, application))
        result['applications_synced_healthy'] = sorted(a['metadata']['name'] for a in apps
            if a['status'].get('health', {}).get('status') == 'Healthy')
        if findings:
            result['unresolved_preexisting_findings'] = sorted(findings, key=lambda item: item['application'])
    return result


def removed_completed_job(api, ref):
    """Observe only the reviewed successful Strata Job retired by CronJob history."""
    from maintenance_node_drain import hashed
    path = Path('metal/maintenance/charmander-completed-job-removal.json')
    require(path.read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + str(path)]),
            'completed removal profile must be published')
    profile = json.loads(path.read_bytes())
    require(ref == profile['ref'], 'unreviewed missing Pod; no external completion allowance')
    pods = api.call('get', 'pods', '-n', 'strata', '-o', 'json')['items']
    jobs = api.call('get', 'jobs', '-n', 'strata', '-o', 'json')['items']
    require(not any(p['metadata']['uid'] == ref['uid'] or p['metadata']['name'] == ref['name'] for p in pods)
            and not any(j['metadata']['uid'] == ref['controller']['uid'] or
                        j['metadata']['name'] == ref['controller']['name'] for j in jobs),
            'reviewed Pod or Job still exists or name was reused')
    cron = api.call('get', 'cronjob', 'strata-backup', '-n', 'strata', '-o', 'json')
    require(cron['metadata']['uid'] == profile['cron_uid'] and not cron['metadata'].get('deletionTimestamp')
            and hashlib.sha256(json.dumps(cron['spec'], sort_keys=True).encode()).hexdigest() == profile['cron_spec'],
            'original CronJob history policy changed')
    recovery = profile['recovery']
    job = next((j for j in jobs if j['metadata']['uid'] == recovery['job_uid']), None)
    pod = next((p for p in pods if p['metadata']['uid'] == recovery['pod_uid']), None)
    require(job is not None and pod is not None and not job['metadata'].get('deletionTimestamp')
            and job['status'].get('succeeded') == 1 and not job['status'].get('active')
            and not job['status'].get('failed') and
            any(c['type'] == 'Complete' and c['status'] == 'True' for c in job['status'].get('conditions', []))
            and job['status'].get('completionTime') == recovery['completion_time']
            and cron['status'].get('lastSuccessfulTime', '') >= recovery['completion_time'],
            'reviewed ordinary recovery Job is not successfully complete')
    owners = job['metadata'].get('ownerReferences', [])
    require(len(owners) == 1 and owners[0].get('controller') is True and
            owners[0].get('kind') == 'CronJob' and owners[0].get('uid') == profile['cron_uid'],
            'recovery Job has foreign owner')
    # Reuse the full Job/Pod completion contract, including ordinary init containers.
    completion = completed_job_pod(api, pod)
    states = pod['status'].get('containerStatuses', [])
    require(completion['job_uid'] == recovery['job_uid'] and len(states) == 1 and
            states[0]['imageID'].endswith('@' + recovery['image_digest']) and states[0]['restartCount'] == 0,
            'original recovery image did not complete normally')
    return {'kind': 'successful-job-removal', 'pod_uid': ref['uid'], 'job_uid': ref['controller']['uid'],
            'prior_success_sha256': hashed(profile['prior_success']),
            'recovery_sha256': hashed({'completion': completion, 'recovery': recovery,
                                       'cron_uid': cron['metadata']['uid'], 'cron_spec': profile['cron_spec']})}


def run_worker(args, api, owner, public_keys, recovery_manifest, bundle, precheck_proof=None):
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    program = ('bundle=' + repr(bundle) + '\nexpected_identity=' + repr(IDENTITY) +
               '\nexpected_node=' + repr(NODE) + '\nexpected_mac=' + repr(MAC) + '\nexpected_ds_uid=' + repr(DS_UID) + '\nowner=' + repr(owner) +
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
                elif request['rpc'] == 'await_osd_protection':
                    require(args.operation == 'drain' and NODE in OSD_RECOVERY,
                            'unreviewed OSD protection wait caller')
                    from maintenance_osd_host import wait_for_protection
                    value = wait_for_protection(api, NODE, owner, request['ref'])
                elif request['rpc'] == 'removed_completed_job':
                    require(args.operation == 'drain' and NODE == 'charmander' and
                            owner['owner'] == 'homelab-maintenance-103-8dba9073-c2fc-4941-a6d2-1228086bd554' and
                            (owner['source'], owner['target']) == (39, 41), 'unreviewed external completion caller')
                    value = removed_completed_job(api, request['ref'])
                elif request['rpc'] == 'removed_versa_canary':
                    require(args.operation == 'drain' and NODE == 'growlithe' and
                            owner['owner'] == 'homelab-maintenance-103-44e0fa41-4b7e-4ba2-bb2e-370e59f61876' and
                            (owner['source'], owner['target']) == (39, 41), 'unreviewed relocation caller')
                    from maintenance_growlithe_relocation import observe
                    value = observe(api, request['ref'])
                elif request['rpc'] == 'ceph_health':
                    require(args.operation in ('recover-pending-kanidm', 'recover-pending-outline'),
                            'unreviewed Ceph health caller')
                    value = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'health', '-f', 'json')
                elif request['rpc'] in ('infrastructure', 'applications'):
                    value = infrastructure(api, applications=request['rpc'] == 'applications',
                        intermediate_pikachu=NODE == 'pikachu' and
                        (owner['source'], owner['target']) in ((39, 41), (41, 43)))
                elif request['rpc'] == 'completed_cuda':
                    require(args.operation == 'drain' and NODE == 'arcanine', 'unreviewed CUDA drain observer')
                    ref = request['ref']
                    require(ref['namespace'] == 'gpu-operator', 'foreign CUDA namespace')
                    pod = api.call('get', 'pod', ref['name'], '-n', 'gpu-operator', '-o', 'json')
                    from maintenance_node_drain import hashed
                    require(pod['metadata']['uid'] == ref['uid'] and hashed(pod['spec']) == ref['spec_sha256'],
                            'completed CUDA Pod changed before observation')
                    value = completed_job_pod(api, pod)
                    require('cluster_policy_uid' in value, 'Job completion cannot authorize a ClusterPolicy Pod')
                    value['spec_sha256'] = hashed(pod['spec'])
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
                        if argv[1:3] not in (['daemonset', 'kured'], ['node', NODE]):
                            require(args.operation in ('release', 'resolve-release-precheck') and
                                    len(argv) == 8 and argv[1] == 'node' and
                                    argv[2] in {n['metadata']['name'] for n in nodes} and
                                    argv[3:5] == ['--type=json', '--patch'] and argv[6:] == ['-o', 'json'],
                                    'unreviewed patch target')
                            actual = api.call('get', 'node', argv[2], '-o', 'json')['metadata']
                            pointer = '/metadata/annotations/weave.works~1kured-reboot-in-progress'
                            require(json.loads(argv[5]) == [
                                {'op': 'test', 'path': '/metadata/uid', 'value': actual['uid']},
                                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': actual['resourceVersion']},
                                {'op': 'test', 'path': pointer, 'value': actual.get('annotations', {}).get(
                                    'weave.works/kured-reboot-in-progress')},
                                {'op': 'remove', 'path': pointer}], 'unreviewed queued-request patch')
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


def scheduling_precheck_failure(node, raw, prior_source):
    """Accept only the captured Bulbasaur callback exit before its first API patch."""
    require(node == 'bulbasaur' and hashlib.sha256(raw).hexdigest() ==
            'a4287afe3e7c8650f852e0ee7bea6229e018cbd0e2f979400b9cf091f7b37684',
            'scheduling pre-dispatch failure receipt differs')
    failure = json.loads(raw)
    require(failure['exit'] == 1 and failure['output'] == '' and
            'maintenance_node_scheduling.py", line 89, in dispatch' in failure['error'] and
            failure['error'].endswith('AssertionError: controller unready: strata/strata\n\n'),
            'failure does not prove the reviewed scheduling pre-dispatch exit')
    dispatch = prior_source[prior_source.index('    def dispatch('):prior_source.index('    def observe(')]
    require(prior_source.splitlines()[88].strip().startswith('actors.require(verify_prerequisites(') and
            dispatch.index('actors.require(verify_prerequisites(') < dispatch.index('result = self.api.call('),
            'original scheduling failure does not precede its first API mutation')
    return {'owner': 'homelab-maintenance-103-4b2620db-57a7-4630-b3c5-e1c5f036edfa',
            'intent_sha256': 'ebac45bc6623f463f910ffa672e801bd02e10377acf2dbfe8bf99ea74a4748b8',
            'failure_sha256': hashlib.sha256(raw).hexdigest()}


def main():
    global ACTIVE_READER, ACTIVE_ARGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'monitor-backup', 'security-backup', 'initialize', 'inspect', 'cordon', 'drain', 'observe-package',
                                             'source-repositories', 'target-repositories', 'prepare-source',
                                             'download-release', 'offline-transaction', 'observe-offline',
                                             'trusted-reconnect', 'verify-infrastructure', 'restore-scheduling', 'resolve-scheduling-precheck',
                                             'accept-applications', 'release', 'resolve-release-precheck', 'resolve-drain-precheck', 'recover-pending-kanidm', 'recover-pending-outline',
                                             'nvidia-repository', 'repair-rpmfusion-download', 'repair-openh264-download', 'repair-offline-repositories', 'repair-init-socket-policy', 'security-default', 'observe-security-default', 'security-tools', 'observe-security-tools', 'security-policy', 'observe-security-policy', 'security-relabel', 'security-enforce', 'security-gds', 'security-firmware', 'observe-security-firmware', 'security-firmware-reboot', 'observe-host-security'])
    parser.add_argument('--node', choices=('totodile', 'pikachu', 'squirtle', 'charmander', 'cyndaquil', 'growlithe', 'arcanine', 'bulbasaur'), default='totodile')
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--failure-receipt')
    args = parser.parse_args()
    ACTIVE_ARGS = args
    select_node(args.node)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    published_tip = subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0]
    require(published_tip == revision, 'publish reviewed source before production use')
    bundle = {}
    for name in (*MODULES, 'maintenance_production_node', 'maintenance_api_reader', 'fedora_public_key', 'maintenance_receiver_protection', 'maintenance_control_plane', 'maintenance_monitor_recovery', 'etcd_recovery', 'maintenance_osd_host'):
        relative = 'metal/scripts/' + name + '.py'
        published = subprocess.check_output(['git', 'show', revision + ':' + relative])
        require(Path(relative).read_bytes() == published, 'unpublished controller source: ' + relative)
        if name in MODULES:
            bundle[name] = published.decode()
    if NODE in OSD_RECOVERY:
        from maintenance_osd_host import native_identity
        native_identity(args, node=NODE)
    core_path = 'scripts/homelab-health.py'
    require(Path(core_path).read_bytes() == subprocess.check_output(['git', 'show', revision + ':' + core_path]),
            'unpublished CORE completion evidence parser')
    precheck_proof = None
    if args.operation == 'resolve-scheduling-precheck':
        require(args.failure_receipt, 'exact captured scheduling pre-dispatch failure is required')
        prior = subprocess.check_output(['git', 'show',
            'cfabcc5a7e3e97c5bcff8241f43ac7dc35a858ba:metal/scripts/maintenance_node_scheduling.py'], text=True)
        precheck_proof = scheduling_precheck_failure(NODE, Path(args.failure_receipt).read_bytes(), prior)
    if args.operation == 'resolve-release-precheck':
        require(args.failure_receipt, 'exact captured release pre-dispatch failure is required')
        raw = Path(args.failure_receipt).read_bytes()
        profiles = {
            'totodile': ('d9bdfaf4ec423a08ea9fbb247631b6618c74f4858f1b664f70aa6e1ea38976e8',
                '630caadf53b29ca6efc20061630aacf3da24e847', 250,
                'RuntimeError: current safe release evidence refused\n\n',
                'homelab-maintenance-103-65a44a0d-b0a2-48f2-af67-2ba0218af10c',
                'b920e73259c0092cda9003c1156b15ae6aee628f65c2211b9e466147ae516135'),
            'pikachu': ('0a5cc76e6406d657deffc9a94e19cf1510f8d268eb90c8a30bcb987204f0d26a',
                '2ae6c68ccce3ec45bf196037277c243a93132a12', 280,
                'AssertionError: target node Pod is not ready: postgres/postgres-threads-backup-29883940-9ddl4\n\n',
                'homelab-maintenance-103-32c03081-4e9e-4c7e-9167-93cc2133fc27',
                'e9d6d639cbe7515069711332f6a7af3672435d4d0648cbc6124d0fb8253da2a0'),
        }
        failure_sha, prior_revision, failed_line, ending, failed_owner, release_head = profiles[NODE]
        require(hashlib.sha256(raw).hexdigest() == failure_sha, 'release failure receipt differs')
        failure = json.loads(raw)
        require(failure['exit'] == 1 and failure['output'] == '' and
                ('maintenance_coordination.py", line ' + str(failed_line) + ', in release') in failure['error'] and
                failure['error'].endswith(ending),
                'failure does not prove the reviewed pre-dispatch exit')
        prior = subprocess.check_output(['git', 'show',
            prior_revision + ':metal/scripts/maintenance_coordination.py'], text=True)
        release_source = prior[prior.index('    def release('):prior.index('\n\ndef main():')]
        mutation_positions = [release_source.index(call) for call in
            ('self.clear_queued_requests(', 'self.patch(ds, {LOCK:') if call in release_source]
        require(prior.splitlines()[failed_line - 1].strip().startswith('require(verify_safe_release(') and
                mutation_positions and release_source.index('require(verify_safe_release(') < min(mutation_positions),
                'original release failure does not precede its first mutation')
        precheck_proof = {'owner': failed_owner, 'failure_sha256': failure_sha, 'release_head_sha256': release_head}
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
    if NODE == 'bulbasaur':
        protected_registry(api)
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
        require(source in (39, 41, 43) or NODE in SECURITY_BACKUPS and source == 44,
                'unreviewed production source release')
        owner = None
    if NODE in SECURITY_BACKUPS and (owner['source'] if owner else source) == 44:
        BACKUPS[44] = SECURITY_BACKUPS[NODE]
    if NODE == 'growlithe' and owner is None:
        from maintenance_receiver_protection import verify
        verify(args, node=NODE)
    # Keep an active hop bound to its original recovery point after the target boots.
    recovery_manifest = recovery(args, owner['source'] if owner else source,
                                 capture=args.operation == 'backup')
    if args.operation == 'monitor-backup':
        require(NODE in ('charmander', 'arcanine', 'bulbasaur') and owner is not None, 'exact owned monitor target required')
        from maintenance_monitor_recovery import preserve
        print(encoded(preserve(args, api, controller, owner, node=NODE)));return
    if NODE == 'charmander' and args.operation in ('source-repositories', 'prepare-source',
                                                  'download-release', 'offline-transaction'):
        from maintenance_monitor_recovery import verify
        verify(args)
    if NODE == 'arcanine' and args.operation in ('source-repositories', 'prepare-source',
                                                'download-release', 'offline-transaction', 'repair-rpmfusion-download', 'repair-openh264-download'):
        from maintenance_monitor_recovery import verify
        verify(args, node=NODE)
    if NODE == 'bulbasaur' and args.operation in ('source-repositories', 'prepare-source',
                                                'download-release', 'offline-transaction'):
        from maintenance_monitor_recovery import verify
        verify(args, node=NODE)
    if args.operation in ('nvidia-repository', 'security-tools', 'observe-security-tools', 'security-policy', 'observe-security-policy', 'security-relabel','security-enforce', 'security-gds', 'security-firmware', 'observe-security-firmware', 'security-firmware-reboot','observe-host-security'):
        recovery_manifest = recovery(args, 44, capture=False)
    if args.operation == 'security-backup':
        require(owner is not None and owner['source'] == 43 and owner['target'] == 44,
                'final host-security recovery requires the active 43-to-44 owner')
        print(encoded(recovery(args, 44, capture=True)));return
    if args.operation == 'backup':
        if NODE == 'pikachu':
            from maintenance_receiver_protection import verify
            verify(args, node='pikachu-security-20261027' if source == 44 else NODE)
        print(encoded(recovery_manifest));return
    if owner is None and NODE == 'pikachu':
        from maintenance_receiver_protection import verify
        verify(args, node='pikachu-security-20261027' if source == 44 else NODE)
    if owner is None:
        owner = controller.acquire(NODE, source, {39: 41, 41: 43, 43: 44, 44: 44}[source], revision)
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
