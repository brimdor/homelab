#!/usr/bin/env python3
"""Qualify signed Ceph20.2.4 and kernel RBD in a disconnected Fedora44 VM."""

import argparse
import hashlib
import json
from pathlib import Path
import signal

import fedora_ceph_repository as repository
from fedora_kernel_qualification import Qualification as Kernel


GUEST_ROOT = '/run/qualification-ceph-repos'
TARGETS = [name + '-2:20.2.4-1.fc44.x86_64' for name in
           ('ceph-common', 'ceph-mon', 'ceph-mgr', 'ceph-osd')]


class Qualification(Kernel):
    def run(self):
        metadata_root = self.args.work_dir / 'ceph-repositories'
        metadata_root.mkdir(mode=0o700)
        repositories = {name: repository.mirror(metadata_root, name) for name in repository.BASES}
        kernel = super().run()
        for name, value in repositories.items():
            directories = sorted({str(Path(relative).parent) for relative in value['files']})
            self.guest('directories=' + repr(directories) + '\nname=' + repr(name) + '\n' + '''
for directory in directories:pathlib.Path(''' + repr(GUEST_ROOT) + ''' ,name,directory).mkdir(parents=True,exist_ok=True)
print(json.dumps({'metadata_directories_ready':True}))
''')
            for relative, digest in value['files'].items():
                self.upload(metadata_root / name / relative, GUEST_ROOT + '/' + name + '/' + relative, digest)
        selected = self.guest('targets=' + repr(TARGETS) + '\n' + '''
mount=pathlib.Path('/mnt/qualification-repo')
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo',str(mount))
for name in ('ceph-base','ceph-updates'):
 pathlib.Path('/etc/yum.repos.d/'+name+'.repo').write_text('['+name+']\\nname='+name+'\\nbaseurl=file://''' + GUEST_ROOT + '''/'+name+'\\nenabled=0\\ngpgcheck=1\\n')
result=native('dnf5','--quiet','--disable-repo=*','--enable-repo=qualification',
              '--enable-repo=ceph-base','--enable-repo=ceph-updates','--setopt=install_weak_deps=False',
              'download','--resolve','--url',*targets)
urls=result.splitlines()
assert urls and all(url.startswith('file:///')for url in urls)
print(json.dumps({'urls':urls,'native_solver':True}))
''')
        transferred = []
        dvd_prefix = 'file:///mnt/qualification-repo/'
        for url in sorted(set(selected['urls'])):
            if url.startswith(dvd_prefix):
                repository.safe_path(url[len(dvd_prefix):], 'Packages')
                continue
            name, relative, digest = repository.selection(url, repositories, GUEST_ROOT)
            source = metadata_root / name / relative
            repository.fetch(repositories[name]['base'], relative, source, digest)
            destination = GUEST_ROOT + '/' + name + '/' + relative
            self.guest('directory=' + repr(str(Path(destination).parent)) + '\n' + '''
pathlib.Path(directory).mkdir(parents=True,exist_ok=True)
print(json.dumps({'package_directory_ready':True}))
''')
            self.upload(source, destination, digest)
            transferred.append({'path': destination, 'sha256': digest})
        installed = self.guest('packages=' + repr(transferred) + '\ntargets=' + repr(TARGETS) + '\n' + '''
for item in packages:
 path=pathlib.Path(item['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
 signature=native('rpmkeys','--checksig','--verbose',str(path))
 assert 'NOKEY' not in signature and 'NOT OK' not in signature and 'OK' in signature
native('dnf5','--disable-repo=*','--enable-repo=qualification','--enable-repo=ceph-base',
       '--enable-repo=ceph-updates','--setopt=gpgcheck=True','--setopt=install_weak_deps=False',
       '--assumeyes','install',*targets)
assert native('ceph','--version').startswith('ceph version 20.2.4 ')
assert all(native('rpm','-q','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',name)=='20.2.4-1.fc44.x86_64'
           for name in ('ceph-common','ceph-mon','ceph-mgr','ceph-osd'))
print(json.dumps({'native_signature_checked_inputs':len(packages),'native_signed_install':True,'version':'20.2.4-1.fc44.x86_64'}))
''')
        self.guest('''
root=pathlib.Path('/work');assert not root.exists();root.mkdir(mode=0o700)
print(json.dumps({'fresh_runtime_directory':True}))
''')
        source_files = {}
        for name in ('ceph_kernel_runtime.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py'):
            source = Path(__file__).with_name(name).resolve()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.upload(source, '/work/' + name, digest)
            source_files[name] = digest
        native = json.loads(self.command(self.ssh + ['sudo python3 -B /work/ceph_kernel_runtime.py']))
        self.identity()
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'native': native,
                'runtime_sources': source_files, 'metadata': {
                    name: {'base': value['base'], 'files': value['files']} for name, value in repositories.items()},
                'transferred_packages': transferred, 'production_or_nas_changes': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned Ceph kernel qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'ceph-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
