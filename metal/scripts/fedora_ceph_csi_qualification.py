#!/usr/bin/env python3
"""Add actual native Ceph CSI mounts to the signed disconnected Fedora profile."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import signal

import fedora_target_qualification as fedora
from fedora_ceph_kernel_qualification import Qualification as Ceph, TARGETS
from fedora_nfs_csi_qualification import archive_identity, POLICY
from fedora_nvidia_package_qualification import verify_repository_disk, verify_signature_output
from maintenance_combined_qualification import K3S, AIRGAP, SELINUX_KEY
from ceph_csi_native_contract import reviewed_objects


ASSETS = '/var/tmp/qualification-ceph-csi-assets'
MAINTENANCE = Path(__file__).resolve().parents[1] / 'maintenance'


class Qualification(Ceph):
    targets = [*TARGETS, 'ceph-mds-2:20.2.4-1.fc44.x86_64']

    def __init__(self, args):
        fedora.require_root(args.work_dir)
        if (not args.assets_dir.is_absolute() or not args.assets_dir.is_relative_to(args.work_dir) or
                any(path.is_symlink() for path in (args.assets_dir, *args.assets_dir.parents))):
            raise RuntimeError('native Ceph CSI assets outside the owned fixture')
        self.records = json.loads((MAINTENANCE / 'ceph-csi-native-images.json').read_bytes())
        bundle = json.loads((MAINTENANCE / 'ceph-csi-native-bundle.json').read_bytes())
        self.objects = reviewed_objects(bundle, self.records)
        self.assets = {'k3s': K3S, 'airgap.tar.zst': AIRGAP, 'policy.rpm': POLICY, 'rancher-public.key': SELINUX_KEY}
        for index, record in enumerate(self.records):
            path = args.assets_dir / ('image-' + str(index) + '.tar')
            if not path.is_file() or path.is_symlink():
                raise RuntimeError('native Ceph CSI OCI asset is not an owned regular file')
            self.assets[path.name] = archive_identity(path, record)
        for name, digest in self.assets.items():
            fedora.require_media(args.work_dir, args.assets_dir / name, digest)
        super().__init__(args)

    def native_runtime(self):
        storage = self.guest('import os\n' + inspect.getsource(verify_repository_disk) +
                             '\nassets_path=' + repr(ASSETS) + '\n' + '''
assets=pathlib.Path(assets_path)
assert not any(path.is_symlink()for path in(assets,*assets.parents))
assets.mkdir(mode=0o700)
assert assets.stat().st_uid==0 and assets.stat().st_mode&0o777==0o700
mount=json.loads(native('findmnt','--json','--target',str(assets),'--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
root=json.loads(native('findmnt','--json','--target','/','--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
verify_repository_disk(mount,root)
space=os.statvfs(assets);assert space.f_bavail>0
print(json.dumps({'mount':mount,'root_mount':root,'available_bytes':space.f_bavail*space.f_frsize}))
''')
        (self.root / 'ceph-csi-storage.json').write_text(json.dumps(storage, indent=2))
        for name, digest in self.assets.items():
            self.upload(self.args.assets_dir / name, ASSETS + '/' + name, digest)
        payload = self.root / 'ceph-csi-input.json'
        payload.write_text(json.dumps({'records': self.records, 'objects': self.objects, 'assets': self.assets}))
        self.upload(payload, ASSETS + '/input.json', hashlib.sha256(payload.read_bytes()).hexdigest())
        installed = self.guest(inspect.getsource(verify_signature_output) + '\nassets_path=' + repr(ASSETS) + '\n' + '''
assets=pathlib.Path(assets_path)
native('rpmkeys','--import',str(assets/'rancher-public.key'))
signature=native('rpmkeys','--checksig','--verbose',str(assets/'policy.rpm'))
verify_signature_output(signature)
assert 'e257814a' in signature.lower()
assert native('rpm','-qp','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',str(assets/'policy.rpm'))=='1.6-1.el9.noarch'
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=localpkg_gpgcheck=True','--setopt=install_weak_deps=False','--assumeyes','install',
       'container-selinux',str(assets/'policy.rpm'))
assert not native('rpm','-V','container-selinux','k3s-selinux')
assert any(line.split()[:2]==['200','k3s']for line in native('semodule','--list=full').splitlines())
print(json.dumps({'signed_policy_and_dependencies':True,'policy':'1.6-1.el9.noarch','enforcing':True}))
''')
        (self.root / 'ceph-csi-policy.json').write_text(json.dumps(installed, indent=2))
        files = {}
        for name in ('ceph_kernel_runtime.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py',
                     'cephfs_kernel_runtime.py', 'ceph_csi_native_contract.py', 'nfs_csi_native_runtime.py',
                     'cilium_native_runtime.py', 'ceph_csi_native_runtime.py'):
            source = Path(__file__).with_name(name)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = '/work/' + name if name in (
                'ceph_kernel_runtime.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py') else ASSETS + '/' + name
            self.upload(source, destination, digest)
            files[name] = digest
        result = json.loads(self.command(self.ssh + ['sudo python3 -B ' + ASSETS + '/ceph_csi_native_runtime.py']))
        (self.root / 'ceph-csi-native.json').write_text(json.dumps(result, indent=2))
        if result.get('accepted') is not True:
            raise RuntimeError('native Ceph CSI refused; inspect retained result')
        return result, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir', 'assets-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())

    def cancel(_number, _frame):
        raise RuntimeError('owned native Ceph CSI qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'ceph-csi-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
