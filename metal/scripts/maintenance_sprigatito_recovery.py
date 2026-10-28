#!/usr/bin/env python3
"""Exact Sprigatito configuration recovery; no node or OSD state changes."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile

from maintenance_coordination import require
import maintenance_production_node as production


NODE = 'sprigatito'
ADDRESS = '10.0.20.20'
UID = '5d80125d-4228-47dd-b19c-ca86f7d4316c'
MAC = '4c:cc:6a:34:dc:6d'
IDENTITY = {'machine': 'e5796c3018b6448eae0c69405926317e',
            'root_uuid': 'c27f6613-788e-4d00-802c-5b84a730a631'}
POINT = '/var/lib/homelab-recovery/maintenance-103/sprigatito-fedora39-config-20261028-a'
OSD_DIRECTORY = 'var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_ce0a1b10-f169-401b-801c-df3cc7748051'
RECEIVER = {'machine': '58d682ccab5a4269acedc3cdf53e46dc',
            'root_uuid': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2'}


def member_name(value):
    path = PurePosixPath(value)
    require(value and path.parts and not path.is_absolute() and '..' not in path.parts and
            str(path) == value.rstrip('/'), 'unsafe configuration archive path')
    return path


def reconstruct(archive, parent):
    """Restore files before links so links cannot redirect any payload write."""
    require(not any(p.is_symlink() for p in (parent, *parent.parents)),
            'unsafe reconstruction ancestry')
    root = Path(tempfile.mkdtemp(prefix='sprigatito-config-restore-', dir=parent))
    root.chmod(0o700)
    digest, files, links, total = hashlib.sha256(), 0, 0, 0
    try:
        with tarfile.open(archive, 'r:') as saved:
            members = saved.getmembers()
            by_name = {}
            for member in members:
                member_name(member.name)
                require(member.isdir() or member.isfile() or member.issym() or member.islnk(),
                        'special file in configuration archive')
                if member.name in by_name:
                    require(member.isdir() and by_name[member.name].get_info() == member.get_info(),
                            'conflicting duplicate configuration member')
                by_name[member.name] = member
            for name in by_name:
                for ancestor in PurePosixPath(name).parents:
                    if str(ancestor) in by_name:
                        require(by_name[str(ancestor)].isdir(), 'archive payload beneath a link or file')
            size = sum(m.size for m in by_name.values() if m.isfile())
            usage = shutil.disk_usage(parent)
            require(usage.free - size > usage.total // 5, 'receiver reconstruction capacity guard')
            for name, member in sorted(by_name.items()):
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if member.isdir():
                    destination.mkdir(exist_ok=True, mode=0o700)
                elif member.isfile():
                    content_hash = hashlib.sha256()
                    with saved.extractfile(member) as source, destination.open('xb') as target:
                        os.fchmod(target.fileno(), 0o600)
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            target.write(chunk)
                            content_hash.update(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    require(destination.stat().st_size == member.size, 'restored configuration size differs')
                    readback = hashlib.sha256()
                    with destination.open('rb') as restored:
                        for chunk in iter(lambda: restored.read(1024 * 1024), b''):
                            readback.update(chunk)
                    require(readback.digest() == content_hash.digest(), 'restored configuration content differs')
                    digest.update(json.dumps([name, member.size, readback.hexdigest()]).encode())
                    files += 1
                    total += member.size
            for name, member in sorted(by_name.items()):
                destination = root / name
                if member.issym():
                    os.symlink(member.linkname, destination)
                    require(os.readlink(destination) == member.linkname, 'restored symlink differs')
                    links += 1
                elif member.islnk():
                    target = member_name(member.linkname)
                    require(str(target) in by_name and by_name[str(target)].isfile(),
                            'hardlink target is not a restored regular file')
                    os.link(root / str(target), destination, follow_symlinks=False)
                    require(destination.stat().st_ino == (root / str(target)).stat().st_ino,
                            'restored hardlink differs')
                    links += 1
                if member.issym() or member.islnk():
                    digest.update(json.dumps([name, member.linkname, member.type.decode()]).encode())
            for name, member in sorted(by_name.items(), key=lambda pair: len(PurePosixPath(pair[0]).parts), reverse=True):
                destination = root / name
                os.chown(destination, member.uid, member.gid, follow_symlinks=False)
                if not member.issym():
                    os.chmod(destination, member.mode)
                actual = destination.lstat()
                require((actual.st_uid, actual.st_gid) == (member.uid, member.gid) and
                        (member.issym() or stat.S_IMODE(actual.st_mode) == member.mode),
                        'restored configuration ownership or mode differs')
                digest.update(json.dumps([name, member.uid, member.gid, member.mode,
                                          sorted(member.pax_headers.items())]).encode())
            require(files > 0, 'empty configuration recovery')
            return {'regular_files': files, 'links': links, 'payload_bytes': total,
                    'restored_content_sha256': digest.hexdigest()}
    finally:
        shutil.rmtree(root)
        require(not root.exists(), 'private configuration reconstruction cleanup failed')


def backup(args):
    native = production.remote(args, '''
import json,os,pathlib,socket,subprocess
P=pathlib.Path
assert os.geteuid()==0 and socket.gethostname()=='sprigatito'
assert P('/etc/machine-id').read_text().strip()=='e5796c3018b6448eae0c69405926317e'
assert '4c:cc:6a:34:dc:6d'in{p.read_text().strip()for p in P('/sys/class/net').glob('*/address')}
disks=json.loads(subprocess.check_output(['lsblk','-b','-J','-o','NAME,SIZE,SERIAL,PARTUUID'],text=True))
disk=next(d for d in disks['blockdevices']if d['name']=='sda')
assert disk['serial']=='DI0403Y002080'and disk['size']==512110190592
assert {p['name']:p['partuuid']for p in disk['children']}=={
 'sda1':'7a137097-0224-47c7-94fd-07554b4b2ae6',
 'sda2':'3318f778-614d-4a51-8598-854df4d1ae06',
 'sda3':'75944ab8-2af9-4622-af67-c41d61977f4f'}
root=P('/var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_ce0a1b10-f169-401b-801c-df3cc7748051')
assert not root.is_symlink()and os.readlink(root/'block')=='/dev/sda3'
assert(root/'whoami').read_text().strip()=='7'
assert(root/'fsid').read_text().strip()=='ce0a1b10-f169-401b-801c-df3cc7748051'
assert(root/'ceph_fsid').read_text().strip()=='13c20377-d801-43f9-aebd-59f62df5dad1'
print(json.dumps({'disk_serial':disk['serial'],'partitions_verified':True,'osd7_verified':True}))
''', ADDRESS)
    production.NODE, production.ADDRESS, production.UID, production.MAC = NODE, ADDRESS, UID, MAC
    production.IDENTITY, production.BACKUPS = dict(IDENTITY), {39: POINT}
    production.RECEIVER, production.RECEIVER_ADDRESS = 'charmander', '10.0.20.11'
    production.RECEIVER_IDENTITY = dict(RECEIVER)
    production.OSD_RECOVERY[NODE] = (OSD_DIRECTORY, '/dev/sda3')
    manifest = production.recovery(args, 39, capture=True)
    source = Path(__file__).read_text()
    # Load only this published reconstruction implementation on the protected receiver.
    implementation = source[source.index('def member_name('):source.index('\ndef backup(')]
    program = ('import hashlib,json,os,pathlib,shutil,socket,stat,subprocess,tarfile,tempfile\n'
               'from pathlib import Path,PurePosixPath\n'
               'def require(condition,message):\n if not condition:raise RuntimeError(message)\n' +
               implementation + '\n' +
               'assert os.geteuid()==0 and socket.gethostname()=="charmander"\n' +
               'assert Path("/etc/machine-id").read_text().strip()==' + repr(RECEIVER['machine']) + '\n' +
               'assert subprocess.check_output(["findmnt","-n","-o","UUID","/"],text=True).strip()==' + repr(RECEIVER['root_uuid']) + '\n' +
               'point=Path(' + repr(POINT) + ');manifest=' + repr(manifest) + '\n' +
               'result=reconstruct(point/"node-config.tar",point)\n' +
               'result.update(archive_sha256=manifest["sha256"],node_uid=manifest["node_uid"],reconstruction_removed=True)\n' +
               'receipt=point/"restore-accepted.json"\n' +
               'if receipt.exists():assert json.loads(receipt.read_text())==result\n' +
               'else:\n with receipt.open("x")as f:\n  os.fchmod(f.fileno(),0o600);json.dump(result,f);f.flush();os.fsync(f.fileno())\n' +
               'print(json.dumps({"capture":manifest,"restore":result}))\n')
    result = production.remote(args, program, '10.0.20.11')
    result['native_identity'] = native
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup'])
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master' and
            subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip() ==
            'git@git.eaglepass.io:ops/homelab.git', 'canonical branch and origin required')
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0]
            == revision, 'publish exact recovery source before operation')
    for name in ('maintenance_sprigatito_recovery', 'maintenance_production_node', 'maintenance_coordination'):
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == subprocess.check_output(['git', 'show', revision + ':' + str(path)]),
                'unpublished recovery implementation')
    print(json.dumps(backup(args), sort_keys=True))


if __name__ == '__main__':
    main()
