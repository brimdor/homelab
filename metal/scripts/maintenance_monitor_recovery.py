"""Preserve the exact cold original monitor store before any OS transaction."""

import json
import shlex
import subprocess

from maintenance_coordination import require


FSID = '13c20377-d801-43f9-aebd-59f62df5dad1'
NODE_UID = '9108f105-f73d-41bb-891f-ac2db6658714'
POD_UID = 'a2fcc6c8-0c41-4cb4-91d3-3ff2d875b76d'
IDENTITY = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
            'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}
ROOT = '/var/lib/homelab-recovery/maintenance-103/charmander-mon-h-20261026-a'
RECEIVER = '10.0.20.18'

PROFILES = {
    'bulbasaur': {'node_uid': 'b921073c-822a-4b74-80ed-563fec33d6ab',
                 'pod_uid': 'e50b3ade-b7c3-4a61-ab4d-d3a918530d0e',
                 'identity': {'machine': 'f61201c3e2ba4b8cbd31e09f77da2ad0',
                              'root_uuid': '2c59d1d1-d2d8-420e-b3a5-d87eb0437823'},
                 'root': '/var/lib/homelab-recovery/maintenance-103/bulbasaur-mon-l-20261028-a',
                 'address': '10.0.20.13', 'monitor': 'l', 'survivors': {'o', 'p'},
                 'receiver': '10.0.20.11', 'receiver_node': 'charmander',
                 'receiver_identity': IDENTITY},
    'charmander': {'node_uid': NODE_UID, 'pod_uid': POD_UID, 'identity': IDENTITY,
                  'root': ROOT, 'address': '10.0.20.11', 'monitor': 'h', 'survivors': {'l', 'n'},
                  'receiver': RECEIVER, 'receiver_node': 'growlithe',
                  'receiver_identity': {'machine': 'a26cbcc990c044dea41fbf4f957f453d',
                      'root_uuid': '710e2dca-691e-4123-a867-4994b9c6e612'}},
    'arcanine': {'node_uid': '88aa2572-09df-40b9-8a00-960e9682917c',
                'pod_uid': 'bc113cbd-a8a8-4b2c-a85f-7da4fe180e83',
                'identity': {'machine': 'd877c676fcc2434f9a169f8dc0594676',
                             'root_uuid': 'd5ffa207-0e76-47a7-a941-1829732d3bc6'},
                'root': '/var/lib/homelab-recovery/maintenance-103/arcanine-mon-n-20261027-a',
                'address': '10.0.20.19', 'monitor': 'n', 'survivors': {'l', 'o'},
                'receiver': '10.0.20.11', 'receiver_node': 'charmander',
                'receiver_identity': IDENTITY},
}


def profile_for(node):
    require(node in PROFILES, 'unreviewed cold monitor profile')
    return PROFILES[node]


def guard(node, pods, status, target='charmander'):
    """The planned single-monitor outage permits recovery reads, never OS work."""
    profile = profile_for(target)
    health = status.get('health', {})
    osds = status.get('osdmap', {})
    groups = status.get('pgmap', {}).get('pgs_by_state', [])
    require(node['metadata']['name'] == target and node['metadata']['uid'] == profile['node_uid'] and
            node['spec'].get('unschedulable') is True and
            not node['metadata'].get('deletionTimestamp'), 'cold recovery target or cordon differs')
    require(not any(p['metadata']['uid'] == profile['pod_uid'] or
                    p['spec'].get('nodeName') == target and
                    p['metadata'].get('labels', {}).get('app') == 'rook-ceph-mon' for p in pods),
            'original monitor Pod remains or another monitor occupies the target')
    require(status.get('fsid') == FSID and profile['survivors'] <= set(status.get('quorum_names', [])) and
            profile['monitor'] not in status.get('quorum_names', []) and
            set(health.get('checks', {})) <= {'MON_DOWN'} and
            health.get('status') == ('HEALTH_WARN' if health.get('checks') else 'HEALTH_OK') and
            osds.get('num_osds') == osds.get('num_up_osds') == osds.get('num_in_osds') == 5 and
            groups and all(g['state_name'] == 'active+clean' for g in groups),
            'surviving monitor quorum, OSDs or PGs are unsafe')


RECEIVER_IDENTITY = r'''
import hashlib,json,os,pathlib,socket,stat,subprocess,sys,tarfile
assert os.geteuid()==0 and socket.gethostname()==RECEIVER_NODE
assert pathlib.Path('/etc/machine-id').read_text().strip()==RECEIVER_IDENTITY['machine']
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==RECEIVER_IDENTITY['root_uuid']
root=pathlib.Path(ROOT)
assert not any(p.is_symlink()for p in(root,*root.parents))
assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(root.parent)],text=True).strip()==RECEIVER_IDENTITY['root_uuid']
def check(path):
 info=path.stat();assert stat.S_ISREG(info.st_mode)and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1
 digest=hashlib.sha256()
 with path.open('rb')as source:
  for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
 count=0;store=False
 with tarfile.open(path,'r:')as archive:
  for entry in archive:
   name=pathlib.PurePosixPath(entry.name)
   assert not name.is_absolute()and '..'not in name.parts and name.parts[0]=='mon-'+MONITOR
   assert entry.isfile()or entry.isdir()or entry.islnk()
   if entry.islnk():
    link=pathlib.PurePosixPath(entry.linkname)
    assert not link.is_absolute()and '..'not in link.parts and link.parts[0]=='mon-'+MONITOR
   store|=name.parts[:3]==('mon-'+MONITOR,'data','store.db');count+=1
 assert count>0 and store
 return {'sha256':digest.hexdigest(),'bytes':path.stat().st_size,'members':count}
'''

READBACK = RECEIVER_IDENTITY + r'''
if not(root/'verified.json').exists():print(json.dumps(None))
else:
 assert root.stat().st_uid==0 and stat.S_IMODE(root.stat().st_mode)==0o700
 record=json.loads((root/'verified.json').read_bytes())
 assert record['fsid']==FSID and record['node_uid']==NODE_UID and record['pod_uid']==POD_UID and record['identity']==IDENTITY
 assert record['archive']==check(root/'monitor.tar')
 print(json.dumps(record))
'''

SOURCE = r'''
import fcntl,json,os,pathlib,socket,stat,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()==NODE
assert pathlib.Path('/etc/machine-id').read_text().strip()==IDENTITY['machine']
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==IDENTITY['root_uuid']
state=pathlib.Path('/var/lib/homelab-maintenance')
lock=os.open(state/'controller.lock',os.O_RDWR|os.O_NOFOLLOW)
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def cold():
 assert json.loads((state/'owner.json').read_bytes())=={'version':1,'owner':OWNER['owner'],'identity':IDENTITY,'revision':OWNER['revision']}
 root=pathlib.Path('/var/lib/rook')/('mon-'+MONITOR)
 assert not any(p.is_symlink()for p in(root,*root.parents))and(root/'data/store.db').is_dir()
 assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(root)],text=True).strip()==IDENTITY['root_uuid']
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:command=(p/'comm').read_text().strip()
  except FileNotFoundError:continue
  assert command!='ceph-mon','monitor is not cold'
cold()
result=subprocess.run(['tar','--numeric-owner','--acls','--xattrs','--selinux','--one-file-system','-C','/var/lib/rook','-cf','-','mon-'+MONITOR])
assert result.returncode==0,'cold archive stream failed'
cold()
'''

RECEIVE = RECEIVER_IDENTITY + r'''
assert root.parent.is_dir()and root.parent.stat().st_uid==0 and not root.parent.stat().st_mode&0o022
assert not root.exists(),'existing cold recovery intent; observe only'
root.mkdir(mode=0o700)
with(root/'intent.json').open('x')as target:
 os.fchmod(target.fileno(),0o600);json.dump(OWNER,target);target.flush();os.fsync(target.fileno())
with(root/'monitor.partial').open('xb')as target:
 os.fchmod(target.fileno(),0o600)
 while True:
  chunk=sys.stdin.buffer.read(1024*1024)
  if not chunk:break
  space=os.statvfs(root);assert space.f_bavail>space.f_blocks//5,'receiver capacity guard'
  target.write(chunk)
 target.flush();os.fsync(target.fileno())
print(json.dumps(check(root/'monitor.partial')))
'''


def bindings(node='charmander'):
    profile = profile_for(node)
    return ''.join(k + '=' + repr(v) + '\n' for k, v in {
        'ROOT': profile['root'], 'FSID': FSID, 'NODE_UID': profile['node_uid'],
        'POD_UID': profile['pod_uid'], 'IDENTITY': profile['identity'], 'NODE': node,
        'MONITOR': profile['monitor'], 'RECEIVER_NODE': profile['receiver_node'],
        'RECEIVER_IDENTITY': profile['receiver_identity']}.items())


def verify(args, node='charmander'):
    from maintenance_production_node import remote
    record = remote(args, bindings(node) + READBACK, profile_for(node)['receiver'])
    require(record is not None, 'protect the cold original monitor store before package work')
    return record


def preserve(args, api, controller, owner, node='charmander'):
    from maintenance_production_node import remote, ssh
    profile = profile_for(node)
    require(owner['node'] == node and owner['node_uid'] == profile['node_uid'] and
            owner['source'] == 39 and owner['target'] == 41, 'cold recovery owner differs')
    def current():
        require(controller.resume(owner['owner']) == owner, 'cold recovery global owner changed')
        guard(api.call('get', 'node', node, '-o', 'json'),
              api.call('get', 'pods', '-n', 'rook-ceph', '-o', 'json')['items'],
              api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'status', '-f', 'json'), target=node)
    current()
    existing = remote(args, bindings(node) + READBACK, profile['receiver'])
    if existing is not None:
        require(existing['owner'] == owner, 'cold recovery belongs to another owner')
        return existing
    prefix = bindings(node) + 'OWNER=' + repr(owner) + '\n'
    producer = subprocess.Popen(ssh(args, profile['address']) + ['python3 -B -c ' + shlex.quote(prefix + SOURCE)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = subprocess.Popen(ssh(args, profile['receiver']) + ['python3 -B -c ' + shlex.quote(prefix + RECEIVE)],
                                stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    producer.stdout.close()
    try:
        output, error = consumer.communicate()
        producer.wait()
        require(producer.returncode == consumer.returncode == 0,
                'cold stream failed; protected partial retained: ' + producer.stderr.read().decode()[-700:] + error.decode()[-700:])
        archive = json.loads(output)
        current()
        record = {'fsid': FSID, 'node_uid': profile['node_uid'], 'pod_uid': profile['pod_uid'],
                  'identity': profile['identity'], 'owner': owner, 'archive': archive}
        finalize = RECEIVER_IDENTITY + '\nrecord=' + repr(record) + r'''
assert check(root/'monitor.partial')==record['archive']
os.link(root/'monitor.partial',root/'monitor.tar');(root/'monitor.partial').unlink()
with(root/'verified.json').open('x')as target:
 os.fchmod(target.fileno(),0o600);json.dump(record,target);target.flush();os.fsync(target.fileno())
fd=os.open(root,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps(record))
'''
        remote(args, bindings(node) + finalize, profile['receiver'])
        require(verify(args, node=node) == record, 'cold archive final readback differs')
        return record
    finally:
        for child in (producer, consumer):
            if child.poll() is None:
                child.terminate();child.wait()
