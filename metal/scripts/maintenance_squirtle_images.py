"""Read original, digest-identified image layers without changing NAS or Zot."""

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

NAS_READ = r'''
import hashlib,json,os,pathlib,socket,stat,subprocess,tempfile
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='76e53a95-725a-4430-9d7b-a8db413f3997'
assert os.readlink('/proc/self/ns/mnt')!=os.readlink('/proc/1/ns/mnt'),'private mount namespace required'
mount=pathlib.Path(tempfile.mkdtemp(prefix='maintenance103-readonly-zot-',dir='/run'))
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


def inspect_nas(args):
    bindings = 'NAS=' + repr(NAS) + '\nPV_UID=' + repr(PV_UID) + '\nPVC_UID=' + repr(PVC_UID) + '\nBLOBS=' + repr(BLOBS) + '\n'
    argv = ['unshare', '--mount', '--propagation', 'private', 'python3', '-B', '-c', bindings + NAS_READ]
    wrapper = ('import json,subprocess\nr=subprocess.run(' + repr(argv) +
               ',capture_output=True)\nassert r.returncode==0,"private read-only source observation failed"\nprint(r.stdout.decode())')
    return remote(args, wrapper, '10.0.20.14')
