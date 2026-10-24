#!/usr/bin/env python3
"""Qualify signed NVIDIA615.71.10 package/DKMS installation without a GPU."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import signal

import fedora_ceph_repository as fedora_repository
from fedora_kernel_qualification import Qualification as Kernel, VERSION
from fedora_nvidia_kernel_qualification import package_plan, TARGETS as BUILD_TARGETS
import nvidia_package_repository as vendor
import nvidia_kernel_build as build


GUEST_ROOT = '/var/tmp/qualification-gpu-repos'
TARGETS = [*BUILD_TARGETS, 'nvidia-open-3:' + build.VERSION + '-1.fc44.noarch',
           'kmod-nvidia-open-dkms-3:' + build.VERSION + '-1.fc44.noarch']


def verify_repository_disk(mounts, roots):
    import re

    if (not isinstance(mounts, list) or not isinstance(roots, list) or
            len(mounts) != 1 or len(roots) != 1 or
            not isinstance(mounts[0], dict) or not isinstance(roots[0], dict)):
        raise RuntimeError('ambiguous native repository/root mount inventory')
    mount, root = mounts[0], roots[0]
    if any(not isinstance(row.get(field), str) for row in (mount, root)
           for field in ('source', 'fstype', 'maj:min')):
        raise RuntimeError('malformed native repository/root mount fields')
    sources = [re.fullmatch(r'(/dev/vda[1-9][0-9]*)(?:\[/[^\]\n]*\])?', row.get('source', ''))
               for row in (mount, root)]
    if (not all(sources) or sources[0][1] != sources[1][1] or
            root.get('fstype') not in ('btrfs', 'ext4', 'xfs') or
            mount.get('fstype') != root['fstype'] or
            not re.fullmatch(r'[0-9]+:[0-9]+', root.get('maj:min', '')) or
            mount.get('maj:min') != root['maj:min']):
        raise RuntimeError('native repository is not on the owned root disk')


def verify_key_listing(text, expected):
    import re

    rows = [line.split() for line in text.splitlines()]
    if (not re.fullmatch(r'[0-9a-f]{40}', expected, re.I) or len(rows) != 1 or
            len(rows[0]) < 2 or rows[0][0].lower() != expected.lower()):
        found = [row[0].lower() for row in rows if row and re.fullmatch(r'[0-9a-f]{40}', row[0], re.I)]
        raise RuntimeError('native NVIDIA imported-key inventory differs: ' + str(found))


def verify_signature_output(text, vendor=False):
    import re

    lines = [line.strip() for line in text.splitlines() if re.search(r'\bsignature(?:,|:)', line, re.I)]
    if not lines or any(not line.endswith(': OK') for line in lines):
        raise RuntimeError('native RPM signature verification missing or failed')
    if vendor and not any(re.search(r'key (?:ID|fingerprint:)\s*[0-9a-f]*73cd9b30:\s*OK$', line, re.I)
                          for line in lines):
        raise RuntimeError('native NVIDIA signature does not identify the pinned vendor key')


class Qualification(Kernel):
    def run(self):
        metadata_root = self.args.work_dir / 'gpu-package-repositories'
        metadata_root.mkdir(mode=0o700)
        repositories = {name: fedora_repository.mirror(metadata_root, name) for name in fedora_repository.BASES}
        repositories['nvidia-vendor'] = vendor.mirror(metadata_root)
        kernel = super().run()
        (self.root / 'kernel-result.json').write_text(json.dumps(kernel, indent=2))
        storage = self.guest('import os\n' + inspect.getsource(verify_repository_disk) + '\nrepository_path=' + repr(GUEST_ROOT) + '\n' + '''
repository=pathlib.Path(repository_path)
assert not any(p.is_symlink() for p in (repository,*repository.parents))
repository.mkdir(mode=0o700)
info=repository.stat();assert info.st_uid==0 and info.st_mode&0o777==0o700
mount=json.loads(native('findmnt','--json','--target',str(repository),'--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
root_mount=json.loads(native('findmnt','--json','--target','/','--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
verify_repository_disk(mount,root_mount)
space=os.statvfs(repository);assert space.f_bavail>0
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo','/mnt/qualification-repo')
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=install_weak_deps=False','--assumeyes','install','python3-libdnf5')
print(json.dumps({'signed_dvd_binding':native('rpm','-q','python3-libdnf5').strip(),
 'repository_path':str(repository),'mount':mount,'root_mount':root_mount,'available_bytes':space.f_bavail*space.f_frsize}))
''')
        (self.root / 'gpu-repository-storage.json').write_text(json.dumps(storage, indent=2))
        for name, value in repositories.items():
            for relative, digest in value['files'].items():
                self.transfer(metadata_root / name / relative, GUEST_ROOT + '/' + name + '/' + relative, digest)
        self.transfer(metadata_root / vendor.KEY, GUEST_ROOT + '/' + vendor.KEY, vendor.KEY_SHA256)
        planner = ('import libdnf5\n' + inspect.getsource(package_plan) + '\n' +
                   inspect.getsource(verify_signature_output) + '\n' + inspect.getsource(verify_key_listing) + '\n')
        selected = self.guest(planner + 'targets=' + repr(TARGETS) + '\n' +
                              'guest_root=' + repr(GUEST_ROOT) + '\nkey_sha=' + repr(vendor.KEY_SHA256) + '\n' +
                              'key_fingerprint=' + repr(vendor.KEY_FINGERPRINT) + '\n' + '''
key=pathlib.Path(guest_root)/'73CD9B30.pub';assert hashlib.sha256(key.read_bytes()).hexdigest()==key_sha
native('rpmkeys','--import',str(key))
verify_key_listing(native('rpmkeys','--list',key_fingerprint),key_fingerprint)
for name in ('ceph-base','ceph-updates','nvidia-vendor'):
 pathlib.Path('/etc/yum.repos.d/'+name+'.repo').write_text('['+name+']\\nname='+name+'\\nbaseurl=file://'+guest_root+'/'+name+'\\nenabled=0\\ngpgcheck=1\\n')
print(json.dumps(package_plan(libdnf5,targets,guest_root,include_vendor=True)))
''')
        (self.root / 'gpu-package-selection.json').write_text(json.dumps(selected, indent=2))
        transferred = []
        for url in sorted(set(selected['urls'])):
            if url.startswith('file://' + GUEST_ROOT + '/nvidia-vendor/'):
                name = 'nvidia-vendor'
                relative, digest = vendor.selection(url, repositories[name], GUEST_ROOT)
                package = metadata_root / name / relative
                vendor.fetch(relative, package, digest)
            else:
                name, relative, digest = fedora_repository.selection(url, repositories, GUEST_ROOT)
                package = metadata_root / name / relative
                fedora_repository.fetch(repositories[name]['base'], relative, package, digest)
            destination = GUEST_ROOT + '/' + name + '/' + relative
            self.transfer(package, destination, digest)
            transferred.append({'path': destination, 'sha256': digest})
        installed = self.guest(planner + 'packages_to_verify=' + repr(transferred) + '\ntargets=' + repr(TARGETS) +
                               '\nexpected_plan=' + repr(selected) + '\nguest_root=' + repr(GUEST_ROOT) + '\n' + '''
for item in packages_to_verify:
 path=pathlib.Path(item['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
 signature=native('rpmkeys','--checksig','--verbose',str(path))
 verify_signature_output(signature,vendor='/nvidia-vendor/' in str(path))
assert package_plan(libdnf5,targets,guest_root,include_vendor=True)==expected_plan
process=subprocess.run(['dnf5','--disable-repo=*','--enable-repo=ceph-base','--enable-repo=ceph-updates',
 '--enable-repo=nvidia-vendor','--setopt=plugins=False','--setopt=gpgcheck=True',
 '--setopt=install_weak_deps=False','--setopt=skip_broken=False','--setopt=skip_unavailable=False',
 '--assumeyes','install',*targets],capture_output=True)
output=process.stdout+process.stderr
print(json.dumps({'native_signed_install':process.returncode==0,'exit':process.returncode,
 'verified_packages':len(packages_to_verify),'log_bytes':len(output),
 'log_sha256':hashlib.sha256(output).hexdigest(),'tail':output[-12000:].decode(errors='replace')}))
''')
        (self.root / 'gpu-package-install.json').write_text(json.dumps(installed, indent=2))
        runtime_files = ['nvidia_kernel_build.py', 'nvidia_package_runtime.py']
        for name in runtime_files:
            path = Path(__file__).with_name(name)
            self.transfer(path, '/run/' + name, hashlib.sha256(path.read_bytes()).hexdigest())
        before = self.inspect_runtime()
        (self.root / 'gpu-package-before-reboot.json').write_text(json.dumps(before, indent=2))
        if not installed['native_signed_install'] or before.get('accepted') is not True:
            raise RuntimeError('native NVIDIA signed package/DKMS installation failed; diagnostics retained')
        previous = self.identity()
        after_boot = self.reboot(VERSION, previous)
        # /run is deliberately ephemeral; upload the exact public runtime again.
        for name in runtime_files:
            path = Path(__file__).with_name(name)
            self.transfer(path, '/run/' + name, hashlib.sha256(path.read_bytes()).hexdigest())
        after = self.inspect_runtime()
        (self.root / 'gpu-package-after-reboot.json').write_text(json.dumps(after, indent=2))
        if (after.get('accepted') is not True or
                any(before[key] != after[key] for key in ('packages', 'modules', 'firmware', 'dkms_status'))):
            raise RuntimeError('NVIDIA package/module/firmware state changed or failed after native reboot')
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'before': before, 'after': after,
                'before_boot': previous, 'after_boot': after_boot, 'transferred_packages': transferred,
                'vendor_key_sha256': vendor.KEY_SHA256,
                'vendor_key_fingerprint': vendor.KEY_FINGERPRINT,
                'metadata': {name: {'base': value['base'], 'files': value['files']} for name, value in repositories.items()},
                'gpu_operation_and_production_unqualified': True}

    def transfer(self, source, destination, digest):
        self.guest('directory=' + repr(str(Path(destination).parent)) + '\n'
                   "pathlib.Path(directory).mkdir(parents=True,exist_ok=True)\nprint('{}')\n")
        try:
            self.upload(source, destination, digest)
        except RuntimeError:
            evidence = {'destination': destination, 'source_bytes': source.stat().st_size}
            try:
                evidence['filesystem'] = self.guest('import os\ndirectory=' + repr(str(Path(destination).parent)) + '\n' + '''
space=os.statvfs(directory)
print(json.dumps({'available_bytes':space.f_bavail*space.f_frsize,'total_bytes':space.f_blocks*space.f_frsize,
 'mount':json.loads(native('findmnt','--json','--target',directory,'--output=TARGET,FSTYPE,MAJ:MIN'))['filesystems']}))
''')
            except Exception as diagnostic_error:
                evidence['diagnostic_error_type'] = type(diagnostic_error).__name__
            (self.root / 'gpu-package-upload-failure.json').write_text(json.dumps(evidence, indent=2))
            raise

    def inspect_runtime(self):
        return json.loads(self.command(self.ssh + ['sudo python3 -B /run/nvidia_package_runtime.py']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())

    def cancel(_number, _frame):
        raise RuntimeError('owned NVIDIA package qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'nvidia-package-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
