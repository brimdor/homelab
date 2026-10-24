#!/usr/bin/env python3
"""Qualify native Fedora39–41–43–44 upgrades only in an owned synthetic VM."""

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

import pycdlib
import yaml

from fedora_target_qualification import Qualification as Target, require_media, require_root
from fedora_upgrade_repository import RepositoryServer, mirror
from cephfs_kernel_runtime import CORPUS


HOSTNAME = 'qualification-fedora-upgrade'
MAINTENANCE = Path(__file__).resolve().parents[1] / 'maintenance'
GUEST = '''import hashlib,json,os,pathlib,socket,subprocess
assert os.geteuid()==0 and socket.gethostname()=='qualification-fedora-upgrade'
assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
def native(*args):
 result=subprocess.run(args,capture_output=True)
 if result.returncode:raise RuntimeError(json.dumps({'command':list(args),'exit':result.returncode,'stderr':result.stderr.decode(errors='replace')[-16000:]}))
 return result.stdout.decode()
'''


def require_hop(source, target):
    if (source, target) not in ((39, 41), (41, 43), (43, 44)):
        raise RuntimeError('foreign Fedora release hop')
    return '/usr/bin/dnf' if source == 39 else '/usr/bin/dnf5'


def require_checkpoint_state(current, expected):
    if (current['native'] != expected['native'] or current['corpus'] != expected['corpus'] or
            any(current['identity'][key] != expected['identity'][key]
                for key in ('machine', 'root_uuid', 'architecture', 'kernel'))):
        raise RuntimeError('restored checkpoint package, data or stable identity changed')


def armor_public_key(raw):
    # RPM4's public-key parser requires ASCII armor including its legacy CRC24.
    crc = 0xB704CE
    for value in raw:
        crc ^= value << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    checksum = base64.b64encode((crc & 0xFFFFFF).to_bytes(3, 'big'))
    return (b'-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n' + base64.encodebytes(raw) +
            b'=' + checksum + b'\n-----END PGP PUBLIC KEY BLOCK-----\n')


class Qualification(Target):
    def __init__(self, args):
        require_root(args.work_dir)
        self.contract = json.loads((MAINTENANCE / 'fedora-upgrade-inputs.json').read_bytes())
        require_media(args.work_dir, args.cloud_image, self.contract['cloud']['sha256'])
        for release, record in self.contract['keys'].items():
            require_media(args.work_dir, args.keys_dir / ('fedora' + release + '.gpg'), record['sha256'])
        self.args = args
        self.root = args.work_dir / 'runtime'
        self.root.mkdir(mode=0o700)
        self.number = 0
        self.child = None
        self.ssh = None
        self.server = None
        self.server_thread = None
        self.checkpoint_states = {}
        self.result = {'accepted': False, 'stages': [], 'production_changes': False}

    def persist(self, stage, **values):
        self.result['stages'].append({'stage': stage, 'at_ns': time.time_ns(), **values})
        (self.root / 'upgrade-evidence.json').write_text(json.dumps(self.result, indent=2))

    def guest(self, script):
        return json.loads(self.command(self.ssh + ['sudo python3 -B -'], data=(GUEST + script).encode()))

    def prepare(self):
        info = json.loads(self.command([self.args.qemu_img, 'info', '--output=json', str(self.args.cloud_image)]))
        if info['format'] != 'qcow2' or any(key in info for key in ('backing-filename', 'data-file')):
            raise RuntimeError('Fedora39 image has external backing data')
        for name in ('login', 'host'):
            self.command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.root / name)])
        user = {'hostname': HOSTNAME, 'preserve_hostname': False, 'ssh_pwauth': False,
                'disable_root': True, 'ssh_deletekeys': False,
                'ssh_keys': {'ed25519_private': (self.root / 'host').read_text(),
                             'ed25519_public': (self.root / 'host.pub').read_text().strip()},
                'users': [{'name': 'fixture', 'uid': 1000, 'groups': ['wheel'], 'shell': '/bin/bash',
                           'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'lock_passwd': True,
                           'ssh_authorized_keys': [(self.root / 'login.pub').read_text().strip()]}],
                'package_update': False, 'package_upgrade': False}
        seed = self.root / 'seed.iso'
        iso = pycdlib.PyCdlib()
        try:
            iso.new(interchange_level=3, joliet=3, rock_ridge='1.09', vol_ident='CIDATA')
            for name, iso_name, raw in (
                ('user-data', 'USER_DAT', ('#cloud-config\n' + yaml.safe_dump(user)).encode()),
                ('meta-data', 'META_DAT', ('instance-id: ' + HOSTNAME + '\nlocal-hostname: ' + HOSTNAME + '\n').encode()),
            ):
                iso.add_fp(io.BytesIO(raw), len(raw), iso_path='/' + iso_name + '.;1',
                           rr_name=name, joliet_path='/' + name)
            for release in self.contract['keys']:
                name = 'fedora' + release + '.gpg'
                raw = (self.args.keys_dir / name).read_bytes()
                armored = armor_public_key(raw)
                iso.add_fp(io.BytesIO(armored), len(armored), iso_path='/' + name.upper() + ';1',
                           rr_name=name, joliet_path='/' + name)
            iso.write(str(seed))
        finally:
            iso.close()
        self.disk = self.root / 'disk.qcow2'
        self.command([self.args.qemu_img, 'create', '-f', 'qcow2', '-F', 'qcow2',
                      '-b', str(self.args.cloud_image), str(self.disk)])
        self.command([self.args.qemu_img, 'resize', str(self.disk), '40G'])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        known = self.root / 'known_hosts'
        known.write_text('[127.0.0.1]:' + str(port) + ' ' + (self.root / 'host.pub').read_text())
        common = ['-F', '/dev/null', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                  '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                  '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
                  '-o', 'ControlMaster=no', '-o', 'ControlPersist=no', '-o', 'IdentityAgent=none',
                  '-o', 'ConnectTimeout=60']
        self.ssh = ['ssh', *common, '-i', str(self.root / 'login'), '-p', str(port), 'fixture@127.0.0.1']
        (self.root / 'inventory.yml').write_text(yaml.safe_dump({'ssh': self.ssh, 'hostname': HOSTNAME}))
        self.server = RepositoryServer(self.args.work_dir / 'repositories')
        self.server_thread = threading.Thread(target=self.server.serve_forever, name='owned-fedora-upgrade-repository')
        self.server_thread.start()
        bridge = shlex.join([sys.executable, '-B', str(Path(__file__).with_name('fedora_upgrade_bridge.py')),
                             str(self.server.server_address[1])])
        serial = self.root / 'serial.log'
        serial.touch(mode=0o600, exist_ok=False)
        self.qemu_argv = [self.args.qemu, '-no-user-config', '-nodefaults', '-machine', 'q35',
            '-accel', 'tcg,thread=multi', '-cpu', 'max', '-smp', '2', '-m', '4096', '-display', 'none',
            '-monitor', 'none', '-serial', 'file:' + str(serial),
            '-drive', 'if=none,id=root,format=qcow2,file=' + str(self.disk),
            '-device', 'virtio-blk-pci,drive=root,serial=qualification-root,bootindex=1',
            '-drive', 'if=none,id=seed,format=raw,readonly=on,file=' + str(seed),
            '-device', 'virtio-blk-pci,drive=seed,serial=qualification-seed',
            '-netdev', 'user,id=fixture,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:' + str(port) + '-:22,'
                         'guestfwd=tcp:10.0.2.100:8080-cmd:' + bridge,
            '-device', 'virtio-net-pci,netdev=fixture,mac=52:54:00:10:03:39',
            '-object', 'rng-random,id=random,filename=/dev/urandom', '-device', 'virtio-rng-pci,rng=random']
        self.boot()

    def boot(self):
        if self.child is not None and self.child.poll() is None:
            raise RuntimeError('owned upgrade VM is already running')
        with (self.root / 'qemu.log').open('ab') as output:
            self.child = subprocess.Popen(self.qemu_argv, stdin=subprocess.DEVNULL, stdout=output,
                                          stderr=subprocess.STDOUT, start_new_session=True)

    def stop(self):
        process = subprocess.run(self.ssh + ['sudo systemctl poweroff'], capture_output=True)
        if process.returncode not in (0, 255):
            raise RuntimeError('owned upgrade VM shutdown command failed')
        if self.child.wait(timeout=1200) != 0:
            raise RuntimeError('owned upgrade VM did not shut down cleanly')

    def checkpoint(self, name, restore=False):
        if name not in ('release39', 'release41', 'release43', 'release44'):
            raise RuntimeError('foreign upgrade checkpoint')
        self.stop()
        self.command([self.args.qemu_img, 'snapshot', '-a' if restore else '-c', name, str(self.disk)])
        self.boot()
        self.wait_ready()

    def repositories(self, release):
        for kind in ('base', 'updates'):
            name = str(release) + '-' + kind
            if name not in self.server.repositories:
                value = mirror(self.server.root, name)
                self.server.repositories[name] = value
                self.persist('verified-repository', name=name, metadata=value['files'],
                             package_count=len(value['packages']))

    def configure(self):
        keys = {release: {**record, 'armored_sha256': hashlib.sha256(armor_public_key(
            (self.args.keys_dir / ('fedora' + release + '.gpg')).read_bytes())).hexdigest()}
            for release, record in self.contract['keys'].items()}
        return self.guest('keys=' + repr(keys) + '\n' + '''
seed=pathlib.Path('/mnt/qualification-upgrade-seed');seed.mkdir(mode=0o700)
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-seed',str(seed))
keydir=pathlib.Path('/var/lib/qualification-upgrade-keys');keydir.mkdir(mode=0o700)
for release,record in keys.items():
 raw=(seed/('fedora'+release+'.gpg')).read_bytes();assert hashlib.sha256(raw).hexdigest()==record['armored_sha256']
 path=keydir/('fedora'+release+'.gpg');path.write_bytes(raw);path.chmod(0o600)
 native('rpmkeys','--import',str(path))
repos=pathlib.Path('/var/tmp/qualification-upgrade-repos');repos.mkdir(mode=0o700)
urls=' '.join('file://'+str(keydir/('fedora'+release+'.gpg'))for release in keys)
for kind in ('base','updates'):
 (repos/(kind+'.repo')).write_text('[qualification-'+kind+']\\nname=qualification '+kind+'\\n'
  'baseurl=http://10.0.2.100:8080/$releasever-'+kind+'/\\nenabled=1\\ngpgcheck=1\\ngpgkey='+urls+'\\n')
pathlib.Path('/etc/dnf/dnf.conf').write_text('[main]\\ngpgcheck=True\\nlocalpkg_gpgcheck=True\\n'
 'install_weak_deps=False\\nkeepcache=True\\nmax_parallel_downloads=1\\nzchunk=False\\nreposdir='+str(repos)+'\\n')
native('systemctl','mask','dnf-automatic.timer','dnf5-automatic.timer')
pathlib.Path('/etc/sysctl.d/99-qualification-upgrade.conf').write_text('vm.swappiness=61\\n')
native('sysctl','-p','/etc/sysctl.d/99-qualification-upgrade.conf')
data=pathlib.Path('/var/tmp/qualification-upgrade-data');data.mkdir(mode=0o700);os.chown(data,1000,1000)
root=data/'corpus';root.mkdir(mode=0o2770);os.chown(root,1000,1000);root.chmod(0o2770)
print(json.dumps({'verified_public_keys':keys,'private_repository_configured':True,'updaters_held':True}))
''')

    def corpus(self, create=False):
        return json.loads(self.command(self.ssh + ['python3 -B - /var/tmp/qualification-upgrade-data ' +
                                                  ('create' if create else 'verify')], data=CORPUS.encode()))

    def state(self, release, corpus):
        identity = self.identity()
        native = self.guest('release=' + repr(release) + '\n' + '''
assert native('rpm','-E','%fedora').strip()==str(release)
assert ('VERSION_ID='+str(release))in pathlib.Path('/etc/os-release').read_text().splitlines()
assert native('sysctl','-n','vm.swappiness').strip()=='61'
for name in ('dnf-automatic.timer','dnf5-automatic.timer'):
 result=subprocess.run(['systemctl','is-enabled',name],capture_output=True)
 assert result.returncode==1 and result.stdout.strip()==b'masked'
kernel=native('uname','-r').strip();assert '.fc'+str(release)+'.'in kernel
assert native('rpm','-q','--qf','%{VERSION}-%{RELEASE}.%{ARCH}','kernel-core-'+kernel)==kernel
assert not native('rpm','-V','fedora-release-common','selinux-policy-targeted')
packages=native('rpm','-qa','--qf','%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\\n').splitlines()
print(json.dumps({'release':release,'enforcing':True,'kernel':kernel,'updaters_held':True,
 'package_inventory':sorted(packages),'sysctl':61}))
''')
        current = self.corpus()
        if current != corpus:
            raise RuntimeError('full release-upgrade corpus or metadata changed')
        return {'identity': identity, 'native': native, 'corpus': current}

    def signatures(self):
        return self.guest('''
roots=[pathlib.Path(value)for value in('/var/cache/dnf','/var/lib/dnf/system-upgrade','/usr/lib/sysimage/libdnf5/offline')]
rows=[]
for root in roots:
 for path in sorted(root.rglob('*.rpm'))if root.exists()else []:
  assert path.is_file()and not path.is_symlink()
  output=native('rpmkeys','--checksig','--verbose',str(path))
  assert 'NOKEY'not in output and 'NOT OK'not in output and 'BAD'not in output
  assert 'signature'in output.lower()and 'OK'in output
  digest=hashlib.sha256()
  with path.open('rb')as source:
   for block in iter(lambda:source.read(1048576),b''):digest.update(block)
  rows.append({'path':str(path),'sha256':digest.hexdigest(),'native_signature_verified':True})
assert rows
print(json.dumps({'packages':rows,'native_signature_verified':True}))
''')

    def filesystems(self):
        return self.guest('''
rows={}
for name in ('/','/var/cache/dnf','/var/tmp'):
 path=pathlib.Path(name);path.mkdir(parents=True,exist_ok=True)
 value=os.statvfs(path)
 rows[name]={'bytes':value.f_blocks*value.f_frsize,
  'available_bytes':value.f_bavail*value.f_frsize,'available_inodes':value.f_favail}
print(json.dumps(rows))
''')

    def offline(self, source, target):
        dnf = require_hop(source, target)
        self.repositories(source)
        self.persist('pre-source-upgrade-filesystems', release=source, filesystems=self.filesystems())
        self.command(self.ssh + ['sudo ' + dnf + ' -y --refresh upgrade'])
        if source == 39:
            self.command(self.ssh + ['sudo ' + dnf + ' -y install dnf-plugin-system-upgrade'])
        self.persist('source-release-updated', release=source, signatures=self.signatures())
        self.checkpoint('release' + str(source))
        self.checkpoint_states[source] = self.state(source, self.reference_corpus)
        before = self.identity()
        self.repositories(target)
        self.command(self.ssh + ['sudo ' + dnf + ' -y system-upgrade download --releasever=' + str(target)])
        self.persist('offline-upgrade-prepared', source=source, target=target, signatures=self.signatures())
        verb = 'system-upgrade' if source == 39 else 'offline'
        self.command(self.ssh + ['sudo systemd-run --on-active=2s --unit=qualification-upgrade-' + str(source) +
                                 '-' + str(target) + ' ' + dnf + ' ' + verb + ' reboot'])
        while True:
            self.wait_ready()
            current = self.guest('''
print(json.dumps({'release':int(native('rpm','-E','%fedora').strip()),
 'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'offline_pending':pathlib.Path('/system-update').is_symlink()}))
''')
            if current['release'] == target and current['boot'] != before['boot'] and not current['offline_pending']:
                break
            if current['boot'] != before['boot'] and not current['offline_pending']:
                raise RuntimeError('normal offline transaction returned without the target release')
            time.sleep(5)
        after = self.identity()
        if any(before[key] != after[key] for key in ('machine', 'root_uuid', 'architecture')):
            raise RuntimeError('release upgrade changed stable fixture identity')
        if self.server.errors:
            raise RuntimeError('verified repository transport reported a failure')

    def run(self):
        self.prepare()
        self.wait_ready()
        configured = self.configure()
        corpus = self.corpus(create=True)
        self.reference_corpus = corpus
        initial = self.state(39, corpus)
        self.persist('initial-native-fedora39', result=initial, configured=configured)
        for source, target in ((39, 41), (41, 43), (43, 44)):
            self.offline(source, target)
            current = self.state(target, corpus)
            if any(initial['identity'][key] != current['identity'][key]
                   for key in ('machine', 'root_uuid', 'architecture')):
                raise RuntimeError('release hop changed machine/root identity')
            self.persist('native-release-upgrade', source=source, target=target, result=current)
        self.checkpoint('release44')
        final = self.state(44, corpus)
        self.checkpoint('release43', restore=True)
        rollback = self.state(43, corpus)
        require_checkpoint_state(rollback, self.checkpoint_states[43])
        self.persist('actual-disk-rollback-to43', result=rollback)
        self.checkpoint('release44', restore=True)
        returned = self.state(44, corpus)
        require_checkpoint_state(returned, final)
        self.persist('actual-disk-return-to44', result=returned)
        self.result.update(accepted=True, strict_ssh_and_egress_checks=True, enforcing_all_stages=True,
                           source_supported_today=False, production_data_recovery_and_hardware_unqualified=True)
        (self.root / 'upgrade-result.json').write_text(json.dumps(self.result, indent=2))
        return self.result

    def cleanup(self):
        try:
            super().cleanup()
        finally:
            if self.server is not None:
                if self.server_thread is not None and self.server_thread.is_alive():
                    self.server.shutdown()
                self.server.server_close()
                if self.server_thread is not None:
                    self.server_thread.join(timeout=30)
                    if self.server_thread.is_alive():
                        raise RuntimeError('owned upgrade repository thread remains')
                (self.root / 'repository-requests.json').write_text(json.dumps(
                    {'requests': self.server.requests, 'errors': self.server.errors}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'keys-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())

    def cancel(_number, _frame):
        raise InterruptedError('owned Fedora release-upgrade fixture cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
