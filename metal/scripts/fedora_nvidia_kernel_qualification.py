#!/usr/bin/env python3
"""Qualify a public NVIDIA module build in the disconnected signed Fedora VM."""

import argparse
import hashlib
import json
from pathlib import Path
import signal
import tarfile

import fedora_ceph_repository as repository
from fedora_kernel_qualification import Qualification as Kernel, VERSION
import nvidia_kernel_build as build


GUEST_ROOT = '/run/qualification-nvidia-repos'
TARGETS = ['kernel-devel-' + VERSION, 'gcc', 'gcc-c++', 'make', 'binutils', 'elfutils-libelf-devel']


class Qualification(Kernel):
    def run(self):
        source = self.args.source_archive
        if (not source.is_file() or source.is_symlink() or
                hashlib.sha256(source.read_bytes()).hexdigest() != build.SOURCE_SHA256):
            raise RuntimeError('NVIDIA source archive identity differs')
        with tarfile.open(source, 'r:gz') as archive:
            build.source_members(archive)
        metadata_root = self.args.work_dir / 'nvidia-repositories'
        metadata_root.mkdir(mode=0o700)
        repositories = {name: repository.mirror(metadata_root, name) for name in repository.BASES}
        kernel = super().run()
        (self.root / 'kernel-result.json').write_text(json.dumps(kernel, indent=2))
        for name, value in repositories.items():
            for relative, digest in value['files'].items():
                destination = GUEST_ROOT + '/' + name + '/' + relative
                self.guest('directory=' + repr(str(Path(destination).parent)) + '\n'
                           "pathlib.Path(directory).mkdir(parents=True,exist_ok=True)\nprint('{}')\n")
                self.upload(metadata_root / name / relative, destination, digest)
        selected = self.guest('targets=' + repr(TARGETS) + '\n' + '''
for name in ('ceph-base','ceph-updates'):
 pathlib.Path('/etc/yum.repos.d/'+name+'.repo').write_text('['+name+']\\nname='+name+'\\nbaseurl=file://''' + GUEST_ROOT + '''/'+name+'\\nenabled=0\\ngpgcheck=1\\n')
urls=native('dnf5','--quiet','--disable-repo=*','--enable-repo=ceph-base','--enable-repo=ceph-updates',
            '--setopt=install_weak_deps=False','download','--resolve','--alldeps','--url',*targets).splitlines()
assert urls and all(url.startswith('file:///')for url in urls)
print(json.dumps({'urls':urls}))
''')
        (self.root / 'nvidia-package-selection.json').write_text(json.dumps(selected, indent=2))
        transferred = []
        for url in sorted(set(selected['urls'])):
            name, relative, digest = repository.selection(url, repositories, GUEST_ROOT)
            package = metadata_root / name / relative
            repository.fetch(repositories[name]['base'], relative, package, digest)
            destination = GUEST_ROOT + '/' + name + '/' + relative
            self.guest('directory=' + repr(str(Path(destination).parent)) + '\n'
                       "pathlib.Path(directory).mkdir(parents=True,exist_ok=True)\nprint('{}')\n")
            self.upload(package, destination, digest)
            transferred.append({'path': destination, 'sha256': digest})
        installed = self.guest('packages=' + repr(transferred) + '\ntargets=' + repr(TARGETS) + '\n' + '''
for item in packages:
 path=pathlib.Path(item['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
 signature=native('rpmkeys','--checksig','--verbose',str(path))
 assert 'NOKEY' not in signature and 'NOT OK' not in signature and 'OK' in signature
native('dnf5','--disable-repo=*','--enable-repo=ceph-base','--enable-repo=ceph-updates',
       '--setopt=gpgcheck=True','--setopt=install_weak_deps=False','--assumeyes','install',*targets)
assert native('rpm','-q','--qf','%{VERSION}-%{RELEASE}.%{ARCH}','kernel-devel')==version
print(json.dumps({'native_signed_install':True,'packages':len(packages),'kernel_devel':version}))
''')
        self.upload(source, '/run/qualification-nvidia-source.tar.gz', build.SOURCE_SHA256)
        runtime = Path(__file__).with_name('nvidia_kernel_build.py').resolve()
        runtime_hash = hashlib.sha256(runtime.read_bytes()).hexdigest()
        self.upload(runtime, '/run/qualification-nvidia-runtime.py', runtime_hash)
        result = json.loads(self.command(self.ssh + ['sudo python3 -B /run/qualification-nvidia-runtime.py']))
        (self.root / 'nvidia-build-result.json').write_text(json.dumps(result, indent=2))
        if result.get('accepted') is not True:
            raise RuntimeError('native NVIDIA module build failed; bounded build diagnostics retained')
        self.identity()
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'build': result,
                'runtime_sha256': runtime_hash, 'transferred_packages': transferred,
                'metadata': {name: {'base': value['base'], 'files': value['files']} for name, value in repositories.items()},
                'gpu_device_userspace_firmware_and_production_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir', 'source-archive'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())

    def cancel(_number, _frame):
        raise RuntimeError('owned NVIDIA kernel qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'nvidia-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
