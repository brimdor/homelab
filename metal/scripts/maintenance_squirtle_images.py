"""Read original, digest-identified image layers without changing NAS or Zot."""

import json
from pathlib import Path

from maintenance_production_node import remote


NAS = '10.0.40.3:/mnt/user/heartlib/zot-zot-nfs-pvc-pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6'
PV_UID = '81d390a2-71fd-48ac-ac2f-49df07bda484'
PVC_UID = '728fbc24-a589-483f-8833-855c863b4f04'
BLOBS = (
    ('pointsite-builder', '5795c4c15c82889983f7e595eb4b572d341a6673b1ebb5c05db4e83d78db25dd', 51671866),
    ('pointsite-builder', '57ea96ae99ab5e3b1f72b2fa1352bdc9b68efe256e2e6c92add771af6ce19fc1', 30189959),
    ('pointsite-builder', '76894cefd42f74c95d90eb8b2837559c43bf005399607f8e212242b80b0978d6', 1798782),
    ('tamalotl', 'f98470dd7d776898537d7d617841e85931a2879ac1af7afc4753c2423c0a4fa2', 3963773),
)

NATIVE = r'''
import hashlib,io,json,os,pathlib,socket,stat,subprocess,sys,tarfile,tempfile
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='76e53a95-725a-4430-9d7b-a8db413f3997'
assert os.readlink('/proc/self/ns/mnt')!=os.readlink('/proc/1/ns/mnt'),'private mount namespace required'
mount=pathlib.Path(tempfile.mkdtemp(prefix='maintenance103-readonly-zot-',dir='/run'))
'''
NAS_READ = NATIVE + r'''
receipt={'source':NAS,'pv_uid':PV_UID,'pvc_uid':PVC_UID,'readonly':True,'files':[],'accepted':False}
try:
 result=subprocess.run(['mount','-t','nfs','-o','ro,nosuid,nodev,noexec,nosharecache,vers=3,proto=tcp,nolock,soft,timeo=50,retrans=2,retry=0',NAS,str(mount)],capture_output=True)
 receipt['mount_exit']=result.returncode
 if result.returncode:
  receipt['error']='read-only source mount unavailable'
 else:
  view=json.loads(subprocess.check_output(['findmnt','--json','--mountpoint',str(mount),'-o','TARGET,SOURCE,FSTYPE,OPTIONS']))['filesystems']
  assert len(view)==1 and view[0]['source']==NAS and view[0]['fstype']=='nfs'
  assert {'ro','nosuid','nodev','noexec','nosharecache'}<=set(view[0]['options'].split(','))
  receipt['mount']=view[0]
  for repo,digest,size in BLOBS:
   path=mount/repo/'blobs/sha256'/digest
   try:
    assert not any(p.is_symlink()for p in(path,path.parent,path.parent.parent,path.parent.parent.parent))
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb')as source:
     before=os.fstat(source.fileno());assert stat.S_ISREG(before.st_mode)and before.st_size==size
     observed=hashlib.file_digest(source,'sha256').hexdigest();after=os.fstat(source.fileno())
     assert (before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino)
    assert observed==digest,'original blob digest mismatch'
    receipt['files'].append({'repo':repo,'digest':digest,'bytes':size,'verified':True})
   except FileNotFoundError:receipt['files'].append({'repo':repo,'digest':digest,'present':False})
  receipt['accepted']=all(v.get('verified')is True for v in receipt['files'])
finally:
 if os.path.ismount(mount):
  result=subprocess.run(['umount',str(mount)],capture_output=True)
  assert result.returncode==0,'owned private read-only mount cleanup failed'
 assert not os.path.ismount(mount)
 mount.rmdir();receipt['owned_mount_removed']=not mount.exists()
print(json.dumps(receipt))
'''

NAS_EXPORT = NATIVE + r'''
try:
 result=subprocess.run(['mount','-t','nfs','-o','ro,nosuid,nodev,noexec,nosharecache,vers=3,proto=tcp,nolock,soft,timeo=50,retrans=2,retry=0',NAS,str(mount)],capture_output=True)
 assert result.returncode==0,'read-only source mount unavailable'
 view=json.loads(subprocess.check_output(['findmnt','--json','--mountpoint',str(mount),'-o','SOURCE,FSTYPE,OPTIONS']))['filesystems']
 assert len(view)==1 and view[0]['source']==NAS and view[0]['fstype']=='nfs'
 assert {'ro','nosuid','nodev','noexec','nosharecache'}<=set(view[0]['options'].split(','))
 root=mount/REPOSITORY/'blobs/sha256'
 def opened(digest):
  path=root/digest.split(':')[1]
  assert not any(p.is_symlink()for p in(path,root,root.parent,root.parent.parent))
  return os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb')
 with opened(DIGEST)as source:raw=source.read(2*1024*1024+1)
 assert hashlib.sha256(raw).hexdigest()==DIGEST.split(':')[1]
 manifest=json.loads(raw)
 assert manifest['schemaVersion']==2 and manifest['config']['digest']==CONFIG
 descriptors=[{'digest':DIGEST,'size':len(raw)},manifest['config'],*manifest['layers']]
 assert len({v['digest']for v in descriptors})==BLOB_COUNT
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|')as archive:
  def add(name,content):
   entry=tarfile.TarInfo(name);entry.size=len(content);entry.mode=0o644
   archive.addfile(entry,io.BytesIO(content))
  add('oci-layout',b'{"imageLayoutVersion":"1.0.0"}')
  index={'schemaVersion':2,'manifests':[{'mediaType':manifest['mediaType'],'digest':DIGEST,'size':len(raw),
   'platform':{'architecture':'amd64','os':'linux'},'annotations':{'org.opencontainers.image.ref.name':IMAGE}}]}
  add('index.json',json.dumps(index,separators=(',',':')).encode())
  class CheckedReader:
   def __init__(self,source):self.source=source;self.digest=hashlib.sha256();self.bytes=0
   def read(self,size):
    chunk=self.source.read(size);self.digest.update(chunk);self.bytes+=len(chunk);return chunk
  for descriptor in descriptors:
   with opened(descriptor['digest'])as source:
    before=os.fstat(source.fileno());assert stat.S_ISREG(before.st_mode)and before.st_size==descriptor['size']
    reader=CheckedReader(source);entry=tarfile.TarInfo('blobs/sha256/'+descriptor['digest'].split(':')[1]);entry.size=descriptor['size'];entry.mode=0o644
    archive.addfile(entry,reader);after=os.fstat(source.fileno())
    assert reader.bytes==descriptor['size']and reader.digest.hexdigest()==descriptor['digest'].split(':')[1]
    assert (before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino)
finally:
 if os.path.ismount(mount):
  result=subprocess.run(['umount',str(mount)],capture_output=True)
  assert result.returncode==0,'owned private read-only mount cleanup failed'
 assert not os.path.ismount(mount)
 mount.rmdir()
'''


def profiles():
    return json.loads(Path('metal/maintenance/squirtle-image-recovery.json').read_text())


def bindings(key):
    profile = profiles()[key]
    values = {'NAS': NAS, 'PV_UID': PV_UID, 'PVC_UID': PVC_UID,
              'REPOSITORY': profile['image'].split('/', 1)[1].split('@')[0],
              'IMAGE': profile['image'] if '@' in profile['declared'] else profile['declared'],
              'DIGEST': profile['digest'], 'CONFIG': profile['config'], 'BLOB_COUNT': profile['blobs'],
              'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/squirtle-image-' + key + '-' + profile['digest'][7:15],
              'ARTIFACT': 'maintenance103-squirtle-' + key + '-' + profile['digest'][7:15] + '.tar',
              'TARGET_HOST': 'pikachu', 'TARGET_MACHINE': '0a7daf8b33244d9d85f46223c3582da9',
              'TARGET_ROOT': '76e53a95-725a-4430-9d7b-a8db413f3997', 'ALIAS': profile['image']}
    return ''.join(name + '=' + repr(value) + '\n' for name, value in values.items())


def preserve(args, key):
    from maintenance_nibble_artifact import RECEIVE_PROGRAM, stream
    source = bindings(key) + NAS_EXPORT
    argv = ['unshare', '--mount', '--propagation', 'private', 'python3', '-B', '-c', source]
    wrapper = 'import os\nos.execvp("unshare",' + repr(argv) + ')'
    return stream(args, '10.0.20.14', wrapper, bindings(key) + RECEIVE_PROGRAM, '10.0.20.14')


def register(args, key):
    from maintenance_nibble_artifact import REGISTER_PROGRAM
    return remote(args, bindings(key) + REGISTER_PROGRAM, '10.0.20.14')


def inspect_nas(args):
    bindings = 'NAS=' + repr(NAS) + '\nPV_UID=' + repr(PV_UID) + '\nPVC_UID=' + repr(PVC_UID) + '\nBLOBS=' + repr(BLOBS) + '\n'
    argv = ['unshare', '--mount', '--propagation', 'private', 'python3', '-B', '-c', bindings + NAS_READ]
    wrapper = ('import json,subprocess\nr=subprocess.run(' + repr(argv) +
               ',capture_output=True)\nassert r.returncode==0,"private read-only source observation failed"\nprint(r.stdout.decode())')
    return remote(args, wrapper, '10.0.20.14')
