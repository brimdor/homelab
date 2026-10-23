#!/usr/bin/env python3
"""Qualify native CephFS only inside the existing disconnected signed fixture."""

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

sys.path.insert(0, '/work')
from ceph_kernel_runtime import Runtime as KernelRuntime, manager_diagnostic  # noqa: E402
from ceph_runtime_qualification import block_identity  # noqa: E402


FILESYSTEM = 'qualificationfs'
MOUNTS = (Path('/mnt/qualification-cephfs-a'), Path('/mnt/qualification-cephfs-b'))


def owned_mount(value, target, fsid):
    rows = value.get('filesystems', [])
    source = 'filesystem@' + fsid + '.' + FILESYSTEM + '=/'
    if (len(rows) != 1 or rows[0].get('target') != str(target) or
            rows[0].get('fstype') != 'ceph' or rows[0].get('source') != source or
            not {'rw', 'ms_mode=secure'} <= set(rows[0].get('options', '').split(',')) or
            not rows[0].get('maj:min')):
        raise RuntimeError('native mount does not identify the exact owned secure filesystem')
    return {'target': str(target), 'source': source, 'fstype': 'ceph',
            'device': rows[0]['maj:min'], 'secure': True}


def filesystem_key_types(value):
    required = {'mds.a', 'client.filesystem'}
    selected = []
    for row in value['data']['secrets']:
        entity = row['entity']['type_str'] + '.' + row['entity']['id']
        if entity in required:
            selected.append((entity, row['auth']['key']['type_str']))
    if len(selected) != 2 or {entity for entity, _ in selected} != required or any(kind != 'aes256k' for _, kind in selected):
        raise RuntimeError('native MDS/filesystem client key type differs')
    return dict(selected)


CORPUS = '''import hashlib,json,os,pathlib,stat,sys
root=pathlib.Path(sys.argv[1])/'corpus';create=sys.argv[2]=='create'
if create:
 (root/'nested').mkdir(mode=0o750)
 for index in range(32):
  payload=hashlib.sha256(('CephFS103:'+str(index)).encode()).digest()*256
  with (root/'nested'/('file'+str(index).zfill(2))).open('xb')as output:
   os.fchmod(output.fileno(),0o640);output.write(payload);output.flush();os.fsync(output.fileno())
 (root/'nested/file00').rename(root/'renamed')
 os.link(root/'renamed',root/'hardlink');os.symlink('nested/file01',root/'symlink')
 os.setxattr(root/'renamed','user.qualification',b'Issue103 native CephFS')
 for directory in (root/'nested',root):
  descriptor=os.open(directory,os.O_DIRECTORY);os.fsync(descriptor);os.close(descriptor)
assert sorted(p.name for p in root.iterdir())==['hardlink','nested','renamed','symlink']
assert sorted(p.name for p in (root/'nested').iterdir())==['file'+str(i).zfill(2)for i in range(1,32)]
result=[]
for index in range(32):
 path=root/'renamed'if index==0 else root/'nested'/('file'+str(index).zfill(2))
 expected=hashlib.sha256(('CephFS103:'+str(index)).encode()).digest()*256
 assert path.read_bytes()==expected
 metadata=path.stat();assert (metadata.st_uid,metadata.st_gid,stat.S_IMODE(metadata.st_mode))==(1000,1000,0o640)
 assert metadata.st_nlink==(2 if index==0 else 1)
 result.append({'index':index,'bytes':len(expected),'sha256':hashlib.sha256(expected).hexdigest(),
                'inode':metadata.st_ino,'links':metadata.st_nlink,'uid':metadata.st_uid,'gid':metadata.st_gid,'mode':stat.S_IMODE(metadata.st_mode)})
assert (root/'hardlink').read_bytes()==(root/'renamed').read_bytes()
assert (root/'hardlink').stat().st_ino==(root/'renamed').stat().st_ino
assert (root/'symlink').is_symlink()and os.readlink(root/'symlink')=='nested/file01'
assert (root/'symlink').read_bytes()==(root/'nested/file01').read_bytes()
assert os.getxattr(root/'renamed','user.qualification')==b'Issue103 native CephFS'
assert (root.stat().st_uid,root.stat().st_gid,stat.S_IMODE(root.stat().st_mode))==(1000,1000,0o2770)
print(json.dumps({'files':result,'payload_bytes':32*8192,'rename_hardlink_symlink_xattr':True,'uid':os.geteuid(),'gid':os.getegid()}))
'''


class Runtime(KernelRuntime):
    def mount_state(self, target):
        result = self.command(['findmnt', '--json', '--mountpoint', str(target),
                               '--output=TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN'], check=False)
        if result.returncode == 1 and not result.stdout.strip():
            return None
        if result.returncode:
            raise RuntimeError('native mount inventory failed')
        return owned_mount(json.loads(result.stdout), target, self.fsid)

    def filesystem_identity(self):
        value = json.loads(self.ceph('fs', 'dump', '--format=json'))
        rows = value['filesystems']
        if len(rows) != 1 or rows[0]['mdsmap']['fs_name'] != FILESYSTEM:
            raise RuntimeError('synthetic filesystem inventory changed')
        row = rows[0]
        return {'fsid': self.status()['fsid'], 'fscid': row['id'],
                'metadata_pool': row['mdsmap']['metadata_pool'],
                'data_pools': row['mdsmap']['data_pools'], 'block': block_identity(self.root)}

    def mds_ready(self):
        while True:
            self.running()
            value = json.loads(self.ceph('fs', 'dump', '--format=json'))
            rows = value['filesystems']
            if len(rows) != 1 or rows[0]['mdsmap']['fs_name'] != FILESYSTEM:
                raise RuntimeError('owned filesystem missing or foreign')
            mds = rows[0]['mdsmap']
            active = list(mds['info'].values())
            if (len(active) == 1 and active[0]['name'] == 'a' and active[0]['rank'] == 0 and
                    active[0]['state'] == 'up:active' and mds['in'] == [0] and len(mds['up']) == 1):
                self.steady()
                return
            time.sleep(2)

    def mount_pair(self, secret):
        if not secret.is_file() or secret.is_symlink() or stat.S_IMODE(secret.stat().st_mode) != 0o600:
            raise RuntimeError('private synthetic secretfile differs')
        rows = []
        for target in MOUNTS:
            if self.mount_state(target) is not None:
                raise RuntimeError('mountpoint already occupied')
            self.command(['mount', '-t', 'ceph', 'filesystem@' + self.fsid + '.' + FILESYSTEM + '=/',
                          str(target), '-o', 'mon_addr=127.0.0.1:13300,secretfile=' + str(secret) +
                          ',noshare,ms_mode=secure'])
            rows.append(self.mount_state(target))
        if rows[0]['device'] == rows[1]['device']:
            raise RuntimeError('noshare aliases unexpectedly share a superblock')
        return rows

    def unmounts(self):
        for target in reversed(MOUNTS):
            if self.mount_state(target) is not None:
                self.command(['umount', str(target)])
                if self.mount_state(target) is not None:
                    raise RuntimeError('owned kernel mount remains')

    def corpus(self, target, create=False):
        return json.loads(self.command(['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
                                        'python3', '-B', '-c', CORPUS, str(target),
                                        'create' if create else 'verify']).stdout)

    def locked_alias(self):
        holder = "import fcntl,sys;f=open(sys.argv[1],'r+b');fcntl.flock(f,fcntl.LOCK_EX);print('LOCKED',flush=True);sys.stdin.buffer.read(1)"
        prefix = ['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups', 'python3', '-B', '-c']
        child = subprocess.Popen([*prefix, holder, str(MOUNTS[0] / 'corpus/renamed')],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if not select.select([child.stdout], [], [], 30)[0] or child.stdout.readline() != b'LOCKED\n':
                raise RuntimeError('owned native lock holder did not acquire lock')
            contender = '''import fcntl,sys
with open(sys.argv[1],'r+b')as source:
 try:fcntl.flock(source,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:print('EXCLUDED')
 else:raise RuntimeError('separate kernel client did not exclude lock')
'''
            if self.command([*prefix, contender, str(MOUNTS[1] / 'corpus/renamed')]).stdout.strip() != b'EXCLUDED':
                raise RuntimeError('native alias lock exclusion missing')
            child.communicate(input=b'x', timeout=10)
            if child.returncode:
                raise RuntimeError('owned lock holder failed')
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate()

    def cephfs_io(self):
        self.stage = 'native secure AES256K kernel CephFS'
        self.fsid = self.status()['fsid']
        if json.loads(self.ceph('fs', 'dump', '--format=json'))['filesystems']:
            raise RuntimeError('preexisting CephFS inventory')
        if any(path.exists() or path.is_symlink() for path in MOUNTS):
            raise RuntimeError('synthetic mountpoint already exists')
        for path in MOUNTS:
            path.mkdir(mode=0o700)
        try:
            mds = self.root / 'mds'
            mds.mkdir(mode=0o700)
            (mds / 'keyring').write_bytes(self.ceph('auth', 'get-or-create', 'mds.a', 'mon', 'allow profile mds',
                    'mgr', 'allow profile mds', 'osd', 'allow rw tag cephfs *=*', 'mds', 'allow', '--key-type=aes256k'))
            (mds / 'keyring').chmod(0o600)
            with (self.root / 'ceph.conf').open('a') as output:
                output.write('\n[mds.a]\nmds data = /work/mds\nkeyring = /work/mds/keyring\nmds cache memory limit = 268435456\n')
            for pool in ('qualificationfs_metadata', 'qualificationfs_data'):
                self.ceph('osd', 'pool', 'create', pool, '4')
            self.ceph('fs', 'new', FILESYSTEM, 'qualificationfs_metadata', 'qualificationfs_data')
            self.ceph('fs', 'set', FILESYSTEM, 'standby_count_wanted', '0')
            self.start('mds', 'a')
            self.mds_ready()
            before = self.filesystem_identity()
            keyring = self.root / 'filesystem.keyring'
            keyring.write_bytes(self.ceph('auth', 'get-or-create', 'client.filesystem',
                    'mon', 'allow r fsname=' + FILESYSTEM, 'mds', 'allow rw fsname=' + FILESYSTEM,
                    'osd', 'allow rw tag cephfs data=' + FILESYSTEM, '--key-type=aes256k'))
            keyring.chmod(0o600)
            secret = self.root / 'filesystem.secret'
            secret.write_bytes(self.command(['ceph-authtool', str(keyring), '-n', 'client.filesystem', '-p']).stdout)
            secret.chmod(0o600)
            filesystem_key_types(json.loads(self.ceph('auth', 'dump-keys', '--format=json')))
            mounts = self.mount_pair(secret)
            corpus = MOUNTS[0] / 'corpus'
            corpus.mkdir(mode=0o2770)
            os.chown(corpus, 1000, 1000)
            corpus.chmod(0o2770)
            original = self.corpus(MOUNTS[0], create=True)
            if self.corpus(MOUNTS[1]) != original:
                raise RuntimeError('complete alias corpus differs')
            self.locked_alias()
            self.unmounts()
            self.stop('mds')
            self.start('mds', 'a')
            self.mds_ready()
            self.mount_pair(secret)
            if any(self.corpus(target) != original for target in MOUNTS):
                raise RuntimeError('complete post-MDS-restart corpus differs')
            self.unmounts()
            retired = self.root / 'retired-filesystem.secret'
            retired.write_bytes(secret.read_bytes())
            retired.chmod(0o600)
            self.rotate_keyring('client.filesystem', keyring, keyring)
            denied = self.command(['mount', '-t', 'ceph', 'filesystem@' + self.fsid + '.' + FILESYSTEM + '=/',
                    str(MOUNTS[0]), '-o', 'mon_addr=127.0.0.1:13300,secretfile=' + str(retired) +
                    ',noshare,ms_mode=secure,mount_timeout=10'], check=False)
            if (denied.returncode == 0 or self.mount_state(MOUNTS[0]) is not None or
                    not any(message in denied.stderr.lower() for message in
                            (b'permission denied', b'operation not permitted'))):
                raise RuntimeError('retired CephFS key lacks explicit fresh-authentication refusal')
            secret.write_bytes(self.command(['ceph-authtool', str(keyring), '-n', 'client.filesystem', '-p']).stdout)
            self.mount_pair(secret)
            key_types = filesystem_key_types(json.loads(self.ceph('auth', 'dump-keys', '--format=json')))
            if (any(self.corpus(target) != original for target in MOUNTS) or
                    self.filesystem_identity() != before or Path('/sys/fs/selinux/enforce').read_text().strip() != '1'):
                raise RuntimeError('native data, filesystem identity or enforcement changed')
            self.unmounts()
            return {'accepted': True, 'filesystem': before, 'initial_mounts': mounts, 'complete_corpus': original,
                    'mds_restart': True, 'retired_key_fresh_mount_refused': True, 'client_rotation': True, 'key_types': key_types,
                    'separate_client_lock_exclusion': True, 'selinux_enforcing': True, 'mounts_absent': True,
                    'single_osd_and_mds_only': True, 'csi_ha_production_nas_unqualified': True}
        finally:
            self.unmounts()
            for path in MOUNTS:
                path.rmdir()


def main():
    runtime = Runtime()
    def cancel(_number, _frame):
        raise InterruptedError('owned CephFS kernel fixture cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        print(json.dumps({'modern_rados': runtime.run(), 'kernel_rbd': runtime.kernel_io(),
                          'kernel_cephfs': runtime.cephfs_io()}), flush=True)
    except Exception as error:
        failure = {'accepted': False, 'stage': runtime.stage, 'error_type': type(error).__name__}
        try:
            failure['manager_diagnostic'] = manager_diagnostic(runtime)
        except Exception as diagnostic_error:
            failure['diagnostic_error'] = type(diagnostic_error).__name__
        print(json.dumps(failure), flush=True)
        raise
    finally:
        for name in list(reversed(runtime.children)):
            runtime.stop(name)


if __name__ == '__main__':
    main()
