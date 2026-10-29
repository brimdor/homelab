#!/usr/bin/env python3
"""Remove reviewed, completed node DNF caches; preserve recovery and native images."""

import argparse
import json
from pathlib import Path
import subprocess

from maintenance_coordination import JOURNAL, LOCK, require
from maintenance_production_node import remote


PROFILES = {
    'totodile': {
        'address': '10.0.20.17', 'machine': '0f1915a59a124d999d8d68b53f406af1',
        'root_uuid': '489f1af8-5d55-4356-8d48-418fcb2069a2',
        'owner': 'homelab-maintenance-103-65a44a0d-b0a2-48f2-af67-2ba0218af10c',
        'previous': 'b920e73259c0092cda9003c1156b15ae6aee628f65c2211b9e466147ae516135',
    },
    'pikachu': {
        'address': '10.0.20.14', 'machine': '0a7daf8b33244d9d85f46223c3582da9',
        'root_uuid': '76e53a95-725a-4430-9d7b-a8db413f3997',
        'owner': 'homelab-maintenance-103-ff28f905-dd10-4857-affb-a06f56240ca6',
        'previous': '87a1b876bbb3e583bb54b21d18d1bde19d78381009eb55f65e187f8f3cb5130a',
    },
}


PROGRAM = '''
import hashlib,json,os,pathlib,socket,subprocess
assert os.geteuid()==0 and socket.gethostname()==node
assert pathlib.Path('/etc/machine-id').read_text().strip()==profile['machine']
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==profile['root_uuid']
assert subprocess.check_output(['rpm','-E','%fedora'],text=True).strip()=='44'
assert subprocess.check_output(['getenforce'],text=True).strip()=='Enforcing'
state=pathlib.Path('/var/lib/homelab-maintenance')
assert not(state/'owner.json').exists()
release=state/'releases'/profile['owner']
assert sorted(p.name for p in release.iterdir())==[str(i).zfill(8)+'.json'for i in range(5)]
records=[json.loads(p.read_bytes())for p in sorted(release.iterdir())]
assert [v['kind']for v in records]==['header','host-intent','host-accepted','global-intent','global-accepted']
assert records[0]['owners']['global']['node']==node and records[0]['owners']['global']['target']==44
assert records[-1]['previous']==profile['previous']
previous=None
for index,record in enumerate(records):
 assert record['sequence']==index and record['previous']==previous
 previous=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert not pathlib.Path('/system-update').exists()and not pathlib.Path('/system-update').is_symlink()
assert subprocess.check_output(['/usr/bin/dnf5','offline','status'],text=True).strip()=='No offline transaction is stored.'
for path in pathlib.Path('/proc').iterdir():
 if not path.name.isdigit():continue
 try:argv=(path/'cmdline').read_bytes().split(bytes([0]))[:2]
 except FileNotFoundError:continue
 assert not any(os.path.basename(a)in(b'dnf',b'dnf4',b'dnf5',b'dnf-3',b'rpm',b'rpmdb',b'packagekitd',b'pkcon')for a in argv),'foreign package actor; never terminate'
protected=pathlib.Path('/var/lib/homelab-recovery/maintenance-103')
def evidence():
 return {str(p):[p.stat().st_size,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()if p.name=='verified.json'else None]for p in protected.rglob('*')if p.is_file()}
before=evidence();free_before=os.statvfs('/').f_bavail*os.statvfs('/').f_frsize
for tool,cache in(('/usr/bin/dnf5','/var/cache/libdnf5'),('/usr/bin/dnf-3','/var/cache/dnf')):
 path=pathlib.Path(cache)
 assert not any(p.is_symlink()for p in(path,*path.parents))
 assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',cache],text=True).strip()==profile['root_uuid']
 subprocess.run([tool,'--setopt=cachedir='+cache,'clean','all'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
assert evidence()==before,'protected recovery metadata changed'
free_after=os.statvfs('/').f_bavail*os.statvfs('/').f_frsize
print(json.dumps({'node':node,'free_before':free_before,'free_after':free_after,'reclaimed':free_after-free_before,'protected_files_unchanged':len(before),'scope':'DNF5 and legacy DNF cache only'}))
'''


def program(node):
    return 'node=' + repr(node) + '\nprofile=' + repr(PROFILES[node]) + '\n' + PROGRAM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', choices=tuple(PROFILES), default='totodile')
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--kubectl', required=True)
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    path = 'metal/scripts/maintenance_completed_caches.py'
    require(Path(path).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + path]),
            'published cleanup source required')
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] ==
            subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'publication differs')
    ds = json.loads(subprocess.check_output([args.kubectl, 'get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json']))
    annotations = ds['metadata'].get('annotations', {})
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            LOCK not in annotations and JOURNAL not in annotations, 'finish current owner before cache cleanup')
    print(json.dumps(remote(args, program(args.node), PROFILES[args.node]['address'])))


if __name__ == '__main__':
    main()
