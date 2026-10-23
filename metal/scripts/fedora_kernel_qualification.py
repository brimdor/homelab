#!/usr/bin/env python3
"""Qualify signed Fedora44 kernel installation and boot rollback offline."""

import argparse
import json
import os
from pathlib import Path
import signal

import fedora_target_qualification as fedora
from maintenance_combined_qualification import Qualification as Combined


VERSION = '7.2.11-200.fc44.x86_64'
PACKAGES = {'kernel-7.2.11-200.fc44.x86_64.rpm': '50c56584bda33b48eb47a86961397e3675b828cead25af7c9f3650e94a919d76', 'kernel-core-7.2.11-200.fc44.x86_64.rpm': '6c993e04efdc0d45ae0e2542e045c37450a53ea968416c2e936eca5351988b24', 'kernel-modules-7.2.11-200.fc44.x86_64.rpm': '5be4c1bf1464aa4fd4289345038c83ca861b41ee788f45766f26ddcf56664c71', 'kernel-modules-core-7.2.11-200.fc44.x86_64.rpm': '5c3d413174778693568a672167d92f60021d7c9b6e4810d90d4ad780f7bc7ce7', 'kernel-modules-extra-7.2.11-200.fc44.x86_64.rpm': '52f1fe520663c17fd7ff4c4d8b738573d38e53680b71b592db673a8a6b3af203'}


class Qualification(fedora.Qualification):
    # Reuse the existing hash-checked, strict-SSH asset transport.
    upload = Combined.upload

    def __init__(self, args):
        for name, digest in PACKAGES.items():
            fedora.require_media(args.work_dir, args.kernel_dir / name, digest)
        super().__init__(args)

    def guest(self, body):
        header = 'version=' + repr(VERSION) + '\npackages=' + repr(PACKAGES) + '\n' + '''import pathlib,subprocess,json,hashlib
assert subprocess.check_output(['hostname']).strip()==b'qualification-fedora44'
assert 'VERSION_ID=44' in pathlib.Path('/etc/os-release').read_text()
assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
def native(*args):
 result=subprocess.run(args,capture_output=True)
 if result.returncode:raise RuntimeError('offline kernel command failed '+json.dumps({'command':list(args),'exit':result.returncode,'stderr':result.stderr.decode(errors='replace')[-1500:]}))
 return result.stdout.decode()
'''
        return json.loads(self.command(self.ssh + ['sudo python3 -B -'], data=(header + body).encode()))

    def reboot(self, expected, previous):
        play = self.root / 'kernel-reboot.yml'
        play.write_text('- hosts: fixture\n  gather_facts: false\n  become: true\n  tasks:\n'
                        '    - ansible.builtin.reboot:\n        reboot_timeout: 1200\n'
                        '        connect_timeout: 10\n        post_reboot_delay: 0\n')
        env = {**os.environ, 'ANSIBLE_CONFIG': str(Path('metal/maintenance/ansible.cfg').resolve()),
               'ANSIBLE_COLLECTIONS_PATH': str(self.args.collection_dir), 'ANSIBLE_HOST_KEY_CHECKING': 'True',
               'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp'),
               'ANSIBLE_SSH_ARGS': '-o ControlMaster=no -o ControlPersist=no'}
        self.command([str(self.args.ansible_playbook), '-i', str(self.root / 'inventory.yml'),
                      str(play), '--limit', 'fixture'], env=env)
        current = self.identity()
        if (current['kernel'] != expected or current['boot'] == previous['boot'] or
                any(current[key] != previous[key] for key in ('machine', 'root_uuid', 'architecture'))):
            raise RuntimeError('native kernel boot or preserved identity differs')
        self.guest('''
assert native('grubby','--default-kernel').strip()=='/boot/vmlinuz-'+native('uname','-r').strip()
result=subprocess.run(['systemctl','is-enabled','dnf5-automatic.timer'],capture_output=True)
assert result.returncode==1 and result.stdout.strip()==b'masked'
assert native('sysctl','-n','vm.swappiness').strip()=='61'
print(json.dumps({'enforcing':True,'updater_held':True,'sysctl_preserved':True}))
''')
        return current

    def run(self):
        primitive = super().run()
        before = self.identity()
        if before['kernel'] == VERSION:
            raise RuntimeError('fixture already runs the candidate kernel')
        self.command(self.ssh + ['sudo mkdir -m 0700 /run/qualification-kernel'])
        for name, digest in PACKAGES.items():
            self.upload(self.args.kernel_dir / name, '/run/qualification-kernel/' + name, digest)
        installed = self.guest('''
assets=pathlib.Path('/run/qualification-kernel')
assert set(p.name for p in assets.iterdir())==set(packages)
old=native('uname','-r').strip();assert old!=version
assert pathlib.Path('/boot/vmlinuz-'+old).is_file()
for name,digest in packages.items():
 path=assets/name;assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
 signature=native('rpmkeys','--checksig','--verbose',str(path))
 assert 'NOKEY' not in signature and 'NOT OK' not in signature and 'OK' in signature
 assert native('rpm','-qp','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',str(path))==version
mount=pathlib.Path('/mnt/qualification-repo');assert mount.is_dir()
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo',str(mount))
native('/usr/bin/dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=localpkg_gpgcheck=True','--setopt=install_weak_deps=False','--assumeyes','install',
       *(str(assets/name)for name in sorted(packages)))
assert native('grubby','--default-kernel').strip()=='/boot/vmlinuz-'+version
assert pathlib.Path('/boot/vmlinuz-'+old).is_file()
assert pathlib.Path('/boot/initramfs-'+version+'.img').is_file()
print(json.dumps({'native_signatures_verified':len(packages),'signed_offline_install':True,'old_kernel_retained':old,'default_kernel':version}))
''')
        updated = self.reboot(VERSION, before)
        modules = self.guest('''
native('modprobe','--all','rbd','ceph','nfs','overlay','br_netfilter')
modules={name:native('modinfo','-F','vermagic',name).strip()for name in ('rbd','ceph','nfs','overlay','br_netfilter')}
assert all(value.split()[0]==version for value in modules.values())
print(json.dumps({'native_modules_loaded':modules,'kernel_client_io_unqualified':True}))
''')
        self.guest('old=' + repr(before['kernel']) + '\n' + '''
native('grubby','--set-default','/boot/vmlinuz-'+old)
assert native('grubby','--default-kernel').strip()=='/boot/vmlinuz-'+old
print(json.dumps({'rollback_selected':old}))
''')
        rollback = self.reboot(before['kernel'], updated)
        self.guest('''
native('grubby','--set-default','/boot/vmlinuz-'+version)
assert native('grubby','--default-kernel').strip()=='/boot/vmlinuz-'+version
print(json.dumps({'candidate_reselected':version}))
''')
        final = self.reboot(VERSION, rollback)
        return {'accepted': True, 'primitive': primitive, 'before': before, 'updated': updated,
                'rollback': rollback, 'final': final, 'installed': installed, 'modules': modules,
                'selinux_enforcing_all_stages': True, 'strict_ssh_and_egress_checks_all_boots': True,
                'production_changes': False, 'release_upgrade_gpu_csi_and_data_recovery_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned kernel qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
