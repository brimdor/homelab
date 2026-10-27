#!/usr/bin/env python3
"""Protect an exact existing recovery store on its accepted off-node receiver."""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from maintenance_production_node import remote, ssh
from maintenance_coordination import require


PROFILES = {
    'pikachu': {'source': 'pikachu', 'source_address': '10.0.20.14',
        'source_machine': '0a7daf8b33244d9d85f46223c3582da9',
        'source_root': '76e53a95-725a-4430-9d7b-a8db413f3997',
        'receiver': 'totodile', 'receiver_address': '10.0.20.17',
        'receiver_machine': '0f1915a59a124d999d8d68b53f406af1',
        'receiver_root': '489f1af8-5d55-4356-8d48-418fcb2069a2',
        'destination': '/var/lib/homelab-recovery/maintenance-103/pikachu-retained-recovery-20261026-a'},
    'growlithe': {'source': 'growlithe', 'source_address': '10.0.20.18',
        'source_machine': 'a26cbcc990c044dea41fbf4f957f453d',
        'source_root': '710e2dca-691e-4123-a867-4994b9c6e612',
        'receiver': 'charmander', 'receiver_address': '10.0.20.11',
        'receiver_machine': '58d682ccab5a4269acedc3cdf53e46dc',
        'receiver_root': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2',
        'destination': '/var/lib/homelab-recovery/maintenance-103/growlithe-retained-recovery-20261027-a'},
}

INVENTORY = r'''
import hashlib,json,os,pathlib,socket,stat,subprocess
assert os.geteuid()==0 and socket.gethostname()==%r
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
root=pathlib.Path('/var/lib/homelab-recovery/maintenance-103')
assert not any(p.is_symlink()for p in(root,*root.parents))
def inventory():
 entries=[];size=0;count=0
 for p in sorted(root.rglob('*')):
  v=p.lstat();assert stat.S_ISREG(v.st_mode)or stat.S_ISDIR(v.st_mode)
  entries.append((str(p.relative_to(root)),v.st_mode,v.st_size,v.st_mtime_ns,v.st_uid,v.st_gid))
  if stat.S_ISREG(v.st_mode):size+=v.st_size;count+=1
 return {'files':count,'bytes':size,'metadata_sha256':hashlib.sha256(json.dumps(entries,separators=(',',':')).encode()).hexdigest()}
'''
READBACK = r'''
import hashlib,json,os,pathlib,socket,stat,subprocess
assert os.geteuid()==0 and socket.gethostname()==%r
assert pathlib.Path('/etc/machine-id').read_text().strip()==%r
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==%r
root=pathlib.Path(%r)
assert not any(p.is_symlink()for p in(root,*root.parents))
if not(root/'verified.json').exists():print(json.dumps(None))
else:
 assert stat.S_IMODE(root.stat().st_mode)==0o700
 value=json.loads((root/'verified.json').read_bytes());archive=root/'retained-recovery.tar.gz'
 info=archive.lstat()
 assert stat.S_ISREG(info.st_mode)and stat.S_IMODE(info.st_mode)==0o600 and info.st_uid==0 and info.st_nlink==1
 assert stat.S_IMODE((root/'verified.json').stat().st_mode)==0o600
 digest=hashlib.sha256()
 with archive.open('rb')as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
 assert archive.stat().st_size==value['bytes']and digest.hexdigest()==value['sha256']
 print(json.dumps(value))
'''


def programs(node):
    require(node in PROFILES, 'unreviewed recovery source/receiver profile')
    profile = PROFILES[node]
    inventory = INVENTORY % (profile['source'], profile['source_machine'], profile['source_root'])
    readback = READBACK % (profile['receiver'], profile['receiver_machine'],
                          profile['receiver_root'], profile['destination'])
    return profile, inventory, readback


def verify(args, node='pikachu'):
    profile, inventory, readback = programs(node)
    value = remote(args, readback, profile['receiver_address'])
    require(value is not None, 'protect the existing recovery receiver before its update')
    current = remote(args, inventory + '\nprint(json.dumps(inventory()))', profile['source_address'])
    require(value['source_inventory'] == current, 'recovery source changed; review the protected copy')
    return value


def protect(args, node='pikachu'):
    profile, inventory, readback = programs(node)
    existing = remote(args, readback, profile['receiver_address'])
    if existing is not None:
        return verify(args, node)
    before = remote(args, inventory + '\nprint(json.dumps(inventory()))', profile['source_address'])
    source = inventory + '\nexpected=' + repr(before) + r'''
import subprocess
assert inventory()==expected
result=subprocess.run(['tar','--numeric-owner','--acls','--xattrs','--selinux','--one-file-system',
 '-I','gzip -1','-C','/var/lib/homelab-recovery','-cf','-','maintenance-103'])
assert result.returncode==0 and inventory()==expected
'''
    receiver = readback.split('if not(root/')[0] + r'''
import sys
assert root.parent.is_dir()and not any(p.is_symlink()for p in(root,*root.parents))
root.mkdir(mode=0o700)
partial=root/'retained-recovery.partial';digest=hashlib.sha256();size=0
with partial.open('xb')as f:
 os.fchmod(f.fileno(),0o600)
 for chunk in iter(lambda:sys.stdin.buffer.read(1024*1024),b''):
  space=os.statvfs(root);assert space.f_bavail>space.f_blocks//5,'receiver capacity guard'
  f.write(chunk);digest.update(chunk);size+=len(chunk)
 f.flush();os.fsync(f.fileno())
print(json.dumps({'bytes':size,'sha256':digest.hexdigest()}))
'''
    producer = subprocess.Popen(ssh(args, profile['source_address']) + ['python3 -B -c ' + shlex.quote(source)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = subprocess.Popen(ssh(args, profile['receiver_address']) + ['python3 -B -c ' + shlex.quote(receiver)],
                                stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    producer.stdout.close()
    try:
        output, _ = consumer.communicate()
        producer.wait()
        require(producer.returncode == consumer.returncode == 0,
                'recovery stream incomplete; preserve the protected partial and inspect before retry')
        value = json.loads(output)
        value.update(source_inventory=before, scope='entire-existing-' + node + '-maintenance-recovery-store')
        finalize = 'value=' + repr(value) + '\n' + readback.split('if not(root/')[0] + r'''
partial=root/'retained-recovery.partial';digest=hashlib.sha256()
with partial.open('rb')as f:
 for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
assert digest.hexdigest()==value['sha256']and partial.stat().st_size==value['bytes']
os.link(partial,root/'retained-recovery.tar.gz');partial.unlink()
with(root/'verified.json').open('x')as f:
 os.fchmod(f.fileno(),0o600);json.dump(value,f);f.flush();os.fsync(f.fileno())
fd=os.open(root,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps(value))
'''
        remote(args, finalize, profile['receiver_address'])
        return verify(args, node)
    finally:
        for child in (producer, consumer):
            if child.poll() is None:
                child.terminate();child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--node', choices=tuple(PROFILES), default='pikachu')
    args = parser.parse_args()
    for name in ('maintenance_receiver_protection', 'maintenance_production_node'):
        path = 'metal/scripts/' + name + '.py'
        require(Path(path).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + path]),
                'unpublished recovery source')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] == revision,
            'publish recovery source to Gitea master first')
    print(json.dumps(protect(args, args.node)))


if __name__ == '__main__':
    main()
