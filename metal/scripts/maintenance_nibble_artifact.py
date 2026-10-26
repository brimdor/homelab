#!/usr/bin/env python3
"""Recover Nibble's exact retained OCI image without writing the NAS registry."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess

from maintenance_coordination import require
from maintenance_production_node import ssh


DIGEST = 'sha256:bd302668a32803da79db8dc178cf93b0c05cd6f48766acca0bf5075cddd53d46'
IMAGE = '10.0.20.11:32309/nibble:issue-26-prod'
SOURCE = '10.0.20.14'
TARGET = '10.0.20.17'
RECOVERY = '/var/lib/homelab-recovery/maintenance-103/nibble-image-bd302668'

SOURCE_PROGRAM = '''
import json,pathlib,socket,subprocess,os
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
images=json.loads(subprocess.check_output(['/usr/local/bin/k3s','crictl','images','-o','json']))['images']
matches=[i for i in images if IMAGE in i.get('repoTags',[])]
assert len(matches)==1 and '10.0.20.11:32309/nibble@'+DIGEST in matches[0]['repoDigests']
os.execv('/usr/local/bin/k3s',['k3s','ctr','-n','k8s.io','images','export','--platform','linux/amd64','-',IMAGE])
'''

RECEIVE_PROGRAM = '''
import hashlib,json,os,pathlib,socket,subprocess,sys,tarfile
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0f1915a59a124d999d8d68b53f406af1'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='489f1af8-5d55-4356-8d48-418fcb2069a2'
root=pathlib.Path(RECOVERY)
images=pathlib.Path('/var/lib/rancher/k3s/agent/images')
for path in (root,images):
 assert not any(p.is_symlink()for p in(path,*path.parents))
 assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(path.parent)],text=True).strip()=='489f1af8-5d55-4356-8d48-418fcb2069a2'
assert not root.exists(),'existing recovery intent; observe only, never overwrite'
assert not images.exists() or images.is_dir()
final=images/'maintenance103-nibble-bd302668.tar'
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
 assert manifest['schemaVersion']==2 and 'manifests'not in manifest
 expected={DIGEST:len(tar.extractfile('blobs/sha256/'+DIGEST.split(':')[1]).read())}
 for descriptor in [manifest['config'],*manifest['layers']]:expected[descriptor['digest']]=descriptor['size']
 assert blobs==expected and len(blobs)==14
record={'image':IMAGE,'digest':DIGEST,'archive_sha256':h.hexdigest(),'archive_bytes':size,'blobs':blobs,'target':'totodile','archive':str(archive),'native_import':str(final)}
with(root/'verified.json').open('x')as output:
 os.fchmod(output.fileno(),0o600);json.dump(record,output);output.flush();os.fsync(output.fileno())
# The retained archive and K3s import entry share one durable root-filesystem inode.
images.mkdir(mode=0o700,exist_ok=True)
os.link(archive,final)
for path in (root,images):
 directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY);os.fsync(directory);os.close(directory)
print(json.dumps(record))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--kubectl', required=True)
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

    node = get('get', 'node', 'pikachu')
    require(node['metadata']['uid'] == '7ec4e786-0b5d-416d-9284-8eac993635bf' and
            node['spec'].get('unschedulable') is True, 'exact Pikachu cordon required')
    target = get('get', 'node', 'totodile')
    require(target['metadata']['uid'] == '83e0e536-e94a-45a1-8dfb-1cedac1e9bd7' and
            not target['spec'].get('unschedulable') and any(c['type'] == 'Ready' and c['status'] == 'True'
            for c in target['status']['conditions']), 'accepted receiver is not ready')
    ds = get('get', 'daemonset', 'kured', '-n', 'kured')
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1',
            'Kured controller identity differs')
    owner = json.loads(ds['metadata']['annotations']['weave.works/kured-node-lock'])
    require(owner['nodeID'] == 'homelab-maintenance-103-6f78a7a1-d165-430e-bde4-b85894582e77',
            'active maintenance owner differs')
    ceph = json.loads(subprocess.check_output([args.kubectl, 'exec', '-n', 'rook-ceph',
        'deploy/rook-ceph-tools', '--', 'ceph', 'health', '-f', 'json']))
    require(ceph['status'] == 'HEALTH_OK', 'Ceph not HEALTH_OK')
    bindings = 'IMAGE=' + repr(IMAGE) + '\nDIGEST=' + repr(DIGEST) + '\nRECOVERY=' + repr(RECOVERY) + '\n'
    source = subprocess.Popen(ssh(args, SOURCE) + ['python3 -B -c ' +
        shlex.quote(bindings + SOURCE_PROGRAM)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        receiver = subprocess.run(ssh(args, TARGET) + ['python3 -B -c ' +
            shlex.quote(bindings + RECEIVE_PROGRAM)], stdin=source.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        source.stdout.close()
        error = source.stderr.read()
        status = source.wait()
        require(status == 0 and receiver.returncode == 0,
                'artifact transfer failed; observe retained intent: ' +
                error.decode()[-1000:] + receiver.stderr.decode()[-1000:])
        print(json.dumps(json.loads(receiver.stdout)))
    finally:
        if source.poll() is None:
            source.terminate()
            source.wait()


if __name__ == '__main__':
    main()
