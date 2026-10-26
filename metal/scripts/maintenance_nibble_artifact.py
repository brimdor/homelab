#!/usr/bin/env python3
"""Recover exact reviewed retained OCI images without writing the NAS registry."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess

from maintenance_coordination import JOURNAL, Kubectl, Ownership, require
from maintenance_production_node import remote, ssh


PROFILES = {
    'nibble': {
        'image': '10.0.20.11:32309/nibble:issue-26-prod',
        'digest': 'sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46',
        'config': 'sha256:c5041e29afd7b0b6ac5e6adb59d5abb063358af0ea59688071721ecb7d0325d7',
        'blobs': 14,
        'recovery': '/var/lib/homelab-recovery/maintenance-103/nibble-image-bd302668-local-export',
        'artifact': 'maintenance103-nibble-bd302668.tar',
    },
    'pointview': {
        'image': '10.0.20.11:32309/pointview@sha256:ee4876e6add9b45af87dd94af9fb9cd0cfca5d7f673e215c456f341983bb7113',
        'declared': '10.0.20.11:32309/pointview:d377729@sha256:ee4876e6add9b45af87dd94af9fb9cd0cfca5d7f673e215c456f341983bb7113',
        'digest': 'sha256:ee4876e6add9b45af87dd94af9fb9cd0cfca5d7f673e215c456f341983bb7113',
        'config': 'sha256:58fae48064aae9440e847719c22cc4443fe06dca4d6c4a426cfa66bfc7739a66',
        'blobs': 17,
        'source': '10.0.20.17',
        'target': '10.0.20.18',
        'target_host': 'growlithe',
        'target_uid': '50f95b8f-4117-4c1e-84bc-266c5b23bffb',
        'target_machine': 'a26cbcc990c044dea41fbf4f957f453d',
        'target_root': '710e2dca-691e-4123-a867-4994b9c6e612',
        'source_host': 'totodile',
        'source_machine': '0f1915a59a124d999d8d68b53f406af1',
        'source_root': '489f1af8-5d55-4356-8d48-418fcb2069a2',
        'recovery': '/var/lib/homelab-recovery/maintenance-103/pointview-image-ee4876e6-complete-export',
        'artifact': 'maintenance103-pointview-ee4876e6.tar',
    },
    'pages-canary': {
        'image': '10.0.20.11:32309/pages:2026-07-13-v1-canary',
        'digest': 'sha256:b2bc2a7eaaad23fb8b6a079a6dca521dd92555f4bd540c1b1d099400f4ac0eb3',
        'config': 'sha256:65850e052c7d484c0e58a506792a084acf490cd4a1966daf87736001ff17de95',
        'blobs': 25,
        'recovery': '/var/lib/homelab-recovery/maintenance-103/pages-canary-image-b2bc2a7e-local-export',
        'artifact': 'maintenance103-pages-canary-b2bc2a7e.tar',
    },
}
SOURCE = '10.0.20.14'
TARGET = '10.0.20.17'

SOURCE_PROGRAM = '''
import json,pathlib,socket,subprocess,os
assert os.geteuid()==0 and socket.gethostname()==SOURCE_HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==SOURCE_MACHINE
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==SOURCE_ROOT
images=json.loads(subprocess.check_output(['/usr/local/bin/k3s','crictl','images','-o','json']))['images']
matches=[i for i in images if IMAGE in i.get('repoTags',[]) or IMAGE==ALIAS and ALIAS in i.get('repoDigests',[])]
assert len(matches)==1 and ALIAS in matches[0]['repoDigests'] and matches[0]['id']==CONFIG
# Use the synchronous client exporter; retain the rejected transfer-API archive separately.
os.execv('/usr/local/bin/k3s',['k3s','ctr','-n','k8s.io','images','export','--local','--platform','linux/amd64','-',IMAGE])
'''

RECEIVE_PROGRAM = '''
import hashlib,json,os,pathlib,socket,subprocess,sys,tarfile
assert os.geteuid()==0 and socket.gethostname()==TARGET_HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==TARGET_MACHINE
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==TARGET_ROOT
root=pathlib.Path(RECOVERY)
for parent in(root.parent.parent,root.parent):
 assert not any(p.is_symlink()for p in(parent,*parent.parents))
 if not parent.exists():parent.mkdir(mode=0o700)
 assert parent.is_dir()and parent.stat().st_uid==0 and not parent.stat().st_mode&0o022
 assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(parent)],text=True).strip()==TARGET_ROOT
images=pathlib.Path('/var/lib/rancher/k3s/agent/images')
for path in (root,images):
 assert not any(p.is_symlink()for p in(path,*path.parents))
 assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(path.parent)],text=True).strip()==TARGET_ROOT
assert not root.exists(),'existing recovery intent; observe only, never overwrite'
assert not images.exists() or images.is_dir()
final=images/ARTIFACT
assert not final.exists()
root.mkdir(mode=0o700)
for path in (root,root.parent):
 directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY);os.fsync(directory);os.close(directory)
archive=root/'image.tar'
with archive.open('xb')as output:
 os.fchmod(output.fileno(),0o600)
 h=hashlib.sha256();size=0
 while True:
  chunk=sys.stdin.buffer.read(1024*1024)
  if not chunk:break
  output.write(chunk);h.update(chunk);size+=len(chunk)
 output.flush();os.fsync(output.fileno())
assert size>0
with tarfile.open(archive,'r:')as tar:
 entries=tar.getmembers();names=[e.name for e in entries]
 assert len(names)==len(set(names))
 allowed={'index.json','oci-layout','manifest.json'}
 blobs={}
 for entry in entries:
  if entry.isdir():
   assert entry.name in ('blobs','blobs/sha256');continue
  assert entry.isfile() and (entry.name in allowed or entry.name.startswith('blobs/sha256/'))
  if entry.name.startswith('blobs/sha256/'):
   digest=entry.name.removeprefix('blobs/sha256/')
   assert len(digest)==64 and all(c in '0123456789abcdef'for c in digest)
   stream=tar.extractfile(entry);check=hashlib.sha256()
   for chunk in iter(lambda:stream.read(1024*1024),b''):check.update(chunk)
   assert check.hexdigest()==digest
   blobs['sha256:'+digest]=entry.size
 index=json.load(tar.extractfile('index.json'))
 assert len(index['manifests'])==1 and index['manifests'][0]['digest']==DIGEST
 manifest=json.load(tar.extractfile('blobs/sha256/'+DIGEST.split(':')[1]))
 assert manifest['schemaVersion']==2 and 'manifests'not in manifest and manifest['config']['digest']==CONFIG
 expected={DIGEST:len(tar.extractfile('blobs/sha256/'+DIGEST.split(':')[1]).read())}
 for descriptor in [manifest['config'],*manifest['layers']]:expected[descriptor['digest']]=descriptor['size']
 assert blobs==expected and len(blobs)==BLOB_COUNT
record={'image':IMAGE,'digest':DIGEST,'archive_sha256':h.hexdigest(),'archive_bytes':size,'blobs':blobs,'target':TARGET_HOST,'archive':str(archive),'native_import':str(final)}
with(root/'verified.json').open('x')as output:
 os.fchmod(output.fileno(),0o600);json.dump(record,output);output.flush();os.fsync(output.fileno())
# The retained archive and K3s import entry share one durable root-filesystem inode.
images.mkdir(mode=0o700,exist_ok=True)
os.link(archive,final)
for path in (root,images):
 directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY);os.fsync(directory);os.close(directory)
print(json.dumps(record))
'''

REGISTER_PROGRAM = '''
import hashlib,json,os,pathlib,socket,subprocess
assert os.geteuid()==0 and socket.gethostname()==TARGET_HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==TARGET_MACHINE
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==TARGET_ROOT
root=pathlib.Path(RECOVERY)
assert not any(p.is_symlink()for p in(root,*root.parents))
record=json.loads((root/'verified.json').read_bytes());archive=root/'image.tar'
assert record['digest']==DIGEST and record['image']==IMAGE and archive.stat().st_size==record['archive_bytes']
with archive.open('rb')as source:assert hashlib.file_digest(source,'sha256').hexdigest()==record['archive_sha256']
native=pathlib.Path(record['native_import']);assert native.samefile(archive)
prefix=['/usr/local/bin/k3s','ctr','-n','k8s.io','images']
alias=ALIAS
def rows(reference):
 return subprocess.check_output(prefix+['list','name=='+reference],text=True).splitlines()[1:]
def exact(reference):
 matches=rows(reference)
 assert len(matches)==1 and matches[0].split()[0]==reference and matches[0].split()[2]==DIGEST
 return matches[0]
assert 'io.cri-containerd.pinned=pinned'in exact(IMAGE)
intent=root/'digest-registration.json'
if IMAGE==alias:
 assert 'io.cri-containerd.pinned=pinned'in exact(alias)
 print(json.dumps({'alias':alias,'native_import_accepted':True,'mutation_performed':False}))
elif intent.exists():
 assert json.loads(intent.read_bytes())=={'image':IMAGE,'digest':DIGEST,'alias':alias,'archive_sha256':record['archive_sha256']}
 exact(alias)
 print(json.dumps({'alias':alias,'already_observed':True,'mutation_performed':False}))
else:
 assert not rows(alias),'foreign digest registration; inspect before changing'
 with intent.open('x')as output:
  os.fchmod(output.fileno(),0o600)
  json.dump({'image':IMAGE,'digest':DIGEST,'alias':alias,'archive_sha256':record['archive_sha256']},output)
  output.flush();os.fsync(output.fileno())
 directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY);os.fsync(directory);os.close(directory)
 # Native Create preserves the exact descriptor and labels; never use --force.
 subprocess.run(prefix+['tag','--local',IMAGE,alias],check=True,stdout=subprocess.PIPE)
 assert 'io.cri-containerd.pinned=pinned'in exact(alias)
 print(json.dumps({'alias':alias,'registration_accepted':True,'mutation_performed':True}))
'''



BASE_LAYERS = (
    ('sha256:b623269625fa50efaed58431bcf95ba7d8bc11d5d48d6ea77941a8b9a82764d4', 30190329),
    ('sha256:0a43925a970bc92e3c311426f82bad9dc0cdfe4f69efd7be82033e0bbb275e35', 51672843),
    ('sha256:a324de66f53f2f1f9a002ee9ace90d15ffdb6b06cb7bfba1d52b6e012f969b00', 1798795),
)
BASE_SOURCE = """
import os,pathlib,socket,subprocess
assert os.geteuid()==0 and socket.gethostname()=='charmander'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='58d682ccab5a4269acedc3cdf53e46dc'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='4a64a6d6-e982-4694-aa03-ad5f317b3ab2'
os.execv('/usr/local/bin/k3s',['k3s','ctr','-n','k8s.io','content','get',BLOB])
"""
BASE_RECEIVER = """
import hashlib,json,os,pathlib,socket,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0f1915a59a124d999d8d68b53f406af1'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='489f1af8-5d55-4356-8d48-418fcb2069a2'
root=pathlib.Path('/var/lib/homelab-recovery/maintenance-103/pointview-base-'+BLOB.split(':')[1])
assert not any(p.is_symlink()for p in(root,*root.parents))
assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(root.parent)],text=True).strip()=='489f1af8-5d55-4356-8d48-418fcb2069a2'
assert not root.exists(),'existing blob recovery intent; observe only'
root.mkdir(mode=0o700);archive=root/'blob';h=hashlib.sha256();size=0
with archive.open('xb')as output:
 os.fchmod(output.fileno(),0o600)
 while True:
  chunk=sys.stdin.buffer.read(1024*1024)
  if not chunk:break
  output.write(chunk);h.update(chunk);size+=len(chunk)
 output.flush();os.fsync(output.fileno())
assert size==SIZE and h.hexdigest()==BLOB.split(':')[1]
prefix=['/usr/local/bin/k3s','ctr','-n','k8s.io','content']
with archive.open('rb')as source:
 subprocess.run(prefix+['ingest','--expected-size',str(SIZE),'--expected-digest',BLOB,'maintenance103-pointview-'+BLOB.split(':')[1]],stdin=source,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
child=subprocess.Popen(prefix+['get',BLOB],stdout=subprocess.PIPE,stderr=subprocess.PIPE);check=hashlib.sha256();observed=0
for chunk in iter(lambda:child.stdout.read(1024*1024),b''):check.update(chunk);observed+=len(chunk)
child.stderr.read();assert child.wait()==0 and observed==SIZE and check.hexdigest()==BLOB.split(':')[1]
record={'digest':BLOB,'bytes':size,'sha256':h.hexdigest(),'native_readback_verified':True,'source':'charmander','target':'totodile'}
with(root/'verified.json').open('x')as output:
 os.fchmod(output.fileno(),0o600);json.dump(record,output);output.flush();os.fsync(output.fileno())
for path in(root,root.parent):
 directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY);os.fsync(directory);os.close(directory)
print(json.dumps(record))
"""


def stream(args, source_address, source_program, receiver_program, target_address=TARGET):
    source = subprocess.Popen(ssh(args, source_address) + ['python3 -B -c ' + shlex.quote(source_program)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        receiver = subprocess.run(ssh(args, target_address) + ['python3 -B -c ' + shlex.quote(receiver_program)],
                                 stdin=source.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        source.stdout.close()
        error = source.stderr.read()
        status = source.wait()
        require(status == 0 and receiver.returncode == 0,
                'artifact transfer failed; observe retained intent: ' +
                error.decode()[-1000:] + receiver.stderr.decode()[-1000:])
        return json.loads(receiver.stdout)
    finally:
        if source.poll() is None:
            source.terminate()
            source.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--register-digest', action='store_true')
    parser.add_argument('--recover-base-layers', action='store_true')
    parser.add_argument('--image', choices=tuple(PROFILES), default='nibble')
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    require(subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master',
            'master required')
    require(subprocess.check_output(['git', 'show', 'HEAD:metal/scripts/maintenance_nibble_artifact.py']) ==
            Path(__file__).read_bytes(), 'published source required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] ==
            head, 'canonical publication differs')

    def get(*argv):
        return json.loads(subprocess.check_output([args.kubectl, *argv, '-o', 'json']))

    profile = PROFILES[args.image]
    node = get('get', 'node', 'pikachu')
    require(node['metadata']['uid'] == '7ec4e786-0b5d-416d-9284-8eac993635bf' and
            (node['spec'].get('unschedulable') is True or args.image == 'pointview' and
             not node['spec'].get('unschedulable') and any(c['type'] == 'Ready' and c['status'] == 'True'
             for c in node['status']['conditions'])), 'exact Pikachu maintenance state required')
    target = get('get', 'node', profile.get('target_host', 'totodile'))
    require(target['metadata']['uid'] == profile.get('target_uid', '83e0e536-e94a-45a1-8dfb-1cedac1e9bd7') and
            not target['spec'].get('unschedulable') and any(c['type'] == 'Ready' and c['status'] == 'True'
            for c in target['status']['conditions']), 'accepted receiver is not ready')
    ds = get('get', 'daemonset', 'kured', '-n', 'kured')
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1',
            'Kured controller identity differs')
    owner = json.loads(ds['metadata']['annotations']['weave.works/kured-node-lock'])
    if args.image == 'pointview':
        saved = json.loads(ds['metadata']['annotations'][JOURNAL])
        nodes = get('get', 'nodes')['items']
        active = Ownership(Kubectl(args.kubectl), ds['metadata']['uid'],
            {n['metadata']['name']: n['metadata']['uid'] for n in nodes}).resume(saved['owner'])
        require(active['node'] == 'pikachu' and active['node_uid'] == node['metadata']['uid'] and
                owner['nodeID'] == active['owner'] and
                (active['source'], active['target']) in ((39, 41), (41, 43), (43, 44)),
                'reviewed Pikachu maintenance owner differs')
    else:
        require(owner['nodeID'] == 'homelab-maintenance-103-6f78a7a1-d165-430e-bde4-b85894582e77',
                'active maintenance owner differs')
    ceph = json.loads(subprocess.check_output([args.kubectl, 'exec', '-n', 'rook-ceph',
        'deploy/rook-ceph-tools', '--', 'ceph', 'health', '-f', 'json']))
    require(ceph['status'] == 'HEALTH_OK', 'Ceph not HEALTH_OK')
    namespaces = ('pointview', 'pointview-canary') if args.image == 'pointview' else (args.image,)
    expected = {profile.get('declared', profile['image']), profile['image'] + '@' + profile['digest']}
    for namespace in namespaces:
        deployment = get('get', 'deployment', namespace, '-n', namespace)
        require(sum(c['image'] in expected for c in deployment['spec']['template']['spec']['containers']) == 1,
                'declared application artifact changed')
    values = {'IMAGE': profile['image'], 'DIGEST': profile['digest'], 'CONFIG': profile['config'],
              'RECOVERY': profile['recovery'], 'ARTIFACT': profile['artifact'],
              'BLOB_COUNT': profile['blobs'],
              'TARGET_HOST': profile.get('target_host', 'totodile'),
              'TARGET_MACHINE': profile.get('target_machine', '0f1915a59a124d999d8d68b53f406af1'),
              'TARGET_ROOT': profile.get('target_root', '489f1af8-5d55-4356-8d48-418fcb2069a2'),
              'SOURCE_HOST': profile.get('source_host', 'pikachu'),
              'SOURCE_MACHINE': profile.get('source_machine', '0a7daf8b33244d9d85f46223c3582da9'),
              'SOURCE_ROOT': profile.get('source_root', '76e53a95-725a-4430-9d7b-a8db413f3997'),
              'ALIAS': profile['image'] if '@' in profile['image'] else profile['image'].rsplit(':', 1)[0] + '@' + profile['digest']}
    bindings = ''.join(name + '=' + repr(value) + '\n' for name, value in values.items())
    if args.register_digest:
        print(json.dumps(remote(args, bindings + REGISTER_PROGRAM, profile.get('target', TARGET))))
        return
    if args.recover_base_layers:
        require(args.image == 'pointview', 'base recovery is PointView only')
        for digest, size in BASE_LAYERS:
            values = 'BLOB=' + repr(digest) + '\nSIZE=' + repr(size) + '\n'
            print(json.dumps(stream(args, '10.0.20.11', values + BASE_SOURCE, values + BASE_RECEIVER)), flush=True)
        return
    print(json.dumps(stream(args, profile.get('source', SOURCE),
                            bindings + SOURCE_PROGRAM, bindings + RECEIVE_PROGRAM, profile.get('target', TARGET))))


if __name__ == '__main__':
    main()
