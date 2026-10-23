#!/usr/bin/env python3
"""Qualify native NFS3/4.1 in the signed disconnected Fedora44 kernel fixture."""

import argparse
import hashlib
import json
from pathlib import Path
import signal

from fedora_kernel_qualification import Qualification as Kernel, VERSION


class Qualification(Kernel):
    def runtime(self, phase):
        result = json.loads(self.command(self.ssh + ['sudo python3 -B /work/nfs_kernel_runtime.py ' + phase]))
        (self.root / ('nfs-' + phase + '.json')).write_text(json.dumps(result, indent=2))
        return result

    def run(self):
        kernel = super().run()
        (self.root / 'kernel-result.json').write_text(json.dumps(kernel, indent=2))
        installed = self.guest('''
mount=pathlib.Path('/mnt/qualification-repo')
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo',str(mount))
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=install_weak_deps=False','--assumeyes','install','nfs-utils')
assert not native('rpm','-V','nfs-utils')
root=pathlib.Path('/work');assert not root.exists();root.mkdir(mode=0o700)
print(json.dumps({'signed_offline_install':True,'nfs_utils':native('rpm','-q','nfs-utils').strip()}))
''')
        source = Path(__file__).with_name('nfs_kernel_runtime.py').resolve()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.upload(source, '/work/nfs_kernel_runtime.py', digest)
        prepared = self.runtime('prepare')
        initial = self.runtime('exercise')
        before = self.identity()
        after = self.reboot(VERSION, before)
        restored = self.runtime('verify')
        cleaned = self.runtime('cleanup')
        if (initial.get('accepted') is not True or restored.get('accepted') is not True or
                not all(cleaned.values())):
            raise RuntimeError('native NFS acceptance or cleanup incomplete')
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'prepared': prepared,
                'initial': initial, 'before': before, 'after': after, 'restored': restored,
                'cleanup': cleaned, 'runtime_sha256': digest, 'production_or_nas_changes': False,
                'csi_container_domains_separate_host_recovery_and_nas_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned native NFS qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'nfs-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
