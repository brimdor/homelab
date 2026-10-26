#!/usr/bin/env python3
"""Protect Pikachu's existing recovery store on the accepted Totodile worker."""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from maintenance_production_node import remote, ssh
from maintenance_coordination import require


DESTINATION = '/var/lib/homelab-recovery/maintenance-103/pikachu-retained-recovery-20261026-a'
SOURCE = '/var/lib/homelab-recovery/maintenance-103'
INVENTORY = r'''
import hashlib,json,os,pathlib,socket,stat
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
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
import hashlib,json,os,pathlib,socket,stat
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0f1915a59a124d999d8d68b53f406af1'
root=pathlib.Path(DESTINATION)
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
'''.replace('DESTINATION', repr(DESTINATION))


def verify(args):
    value = remote(args, READBACK, '10.0.20.17')
    require(value is not None, 'protect the existing recovery receiver before its update')
    current = remote(args, INVENTORY + '\nprint(json.dumps(inventory()))', '10.0.20.14')
    require(value['source_inventory'] == current, 'recovery source changed; review the protected copy')
    return value


def protect(args):
    existing = remote(args, READBACK, '10.0.20.17')
    if existing is not None:
        return verify(args)
    before = remote(args, INVENTORY + '\nprint(json.dumps(inventory()))', '10.0.20.14')
    source = INVENTORY + '\nexpected=' + repr(before) + r'''
import subprocess
assert inventory()==expected
result=subprocess.run(['tar','--numeric-owner','--acls','--xattrs','--selinux','--one-file-system',
 '-I','gzip -1','-C','/var/lib/homelab-recovery','-cf','-','maintenance-103'])
assert result.returncode==0 and inventory()==expected
'''
    receiver = r'''
import hashlib,json,os,pathlib,socket,stat,sys
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0f1915a59a124d999d8d68b53f406af1'
root=pathlib.Path(DESTINATION)
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
'''.replace('DESTINATION', repr(DESTINATION))
    producer = subprocess.Popen(ssh(args, '10.0.20.14') + ['python3 -B -c ' + shlex.quote(source)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = subprocess.Popen(ssh(args, '10.0.20.17') + ['python3 -B -c ' + shlex.quote(receiver)],
                                stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    producer.stdout.close()
    try:
        output, _ = consumer.communicate()
        producer.wait()
        require(producer.returncode == consumer.returncode == 0,
                'recovery stream incomplete; preserve the protected partial and inspect before retry')
        value = json.loads(output)
        value.update(source_inventory=before, scope='entire-existing-pikachu-maintenance-recovery-store')
        finalize = 'value=' + repr(value) + '\n' + READBACK.split('if not(root/')[0] + r'''
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
        remote(args, finalize, '10.0.20.17')
        return verify(args)
    finally:
        for child in (producer, consumer):
            if child.poll() is None:
                child.terminate();child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    args = parser.parse_args()
    for name in ('maintenance_receiver_protection', 'maintenance_production_node'):
        path = 'metal/scripts/' + name + '.py'
        require(Path(path).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + path]),
                'unpublished recovery source')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] == revision,
            'publish recovery source to Gitea master first')
    print(json.dumps(protect(args)))


if __name__ == '__main__':
    main()
