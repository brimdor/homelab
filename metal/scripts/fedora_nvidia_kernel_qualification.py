#!/usr/bin/env python3
"""Qualify a public NVIDIA module build in the disconnected signed Fedora VM."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import signal
import tarfile

import fedora_ceph_repository as repository
from fedora_kernel_qualification import Qualification as Kernel, VERSION
import nvidia_kernel_build as build


GUEST_ROOT = '/run/qualification-nvidia-repos'
TARGETS = ['kernel-devel-' + VERSION, 'gcc', 'gcc-c++', 'make', 'binutils', 'elfutils-libelf-devel']


def package_plan(libdnf5, targets, guest_root, include_vendor=False):
    """Resolve the full installation, including installed reverse dependents."""
    from pathlib import PurePosixPath
    import re

    base = libdnf5.base.Base()
    base.load_config()
    config = base.get_config()
    config.plugins = False
    config.install_weak_deps = False
    config.gpgcheck = True
    config.skip_broken = False
    config.skip_unavailable = False
    base.setup()
    sack = base.get_repo_sack()
    repositories = ('ceph-base', 'ceph-updates', 'nvidia-vendor') if include_vendor else ('ceph-base', 'ceph-updates')
    for name in repositories:
        repo_config = sack.create_repo(name).get_config()
        repo_config.baseurl = ['file://' + guest_root + '/' + name]
        repo_config.enabled = True
        repo_config.gpgcheck = True
    sack.load_repos()
    goal = libdnf5.base.Goal(base)
    for target in targets:
        goal.add_rpm_install(target)
    transaction = goal.resolve()
    if transaction.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
        raise RuntimeError('native NVIDIA install solver reported problems')
    actions = libdnf5.transaction
    incoming = (actions.TransactionItemAction_INSTALL, actions.TransactionItemAction_UPGRADE)
    allowed = (*incoming, actions.TransactionItemAction_REPLACED, actions.TransactionItemAction_REASON_CHANGE)
    rows, replaced, expected_replaced = [], set(), set()
    for item in transaction.get_transaction_packages():
        action, package = item.get_action(), item.get_package()
        if action not in allowed or package.get_arch() not in ('x86_64', 'noarch'):
            raise RuntimeError('unsafe native NVIDIA package action or architecture')
        row = {'nevra': package.get_nevra(), 'action': actions.transaction_item_action_to_string(action)}
        if action in incoming:
            name, location = package.get_repo_id(), package.get_location()
            path = PurePosixPath(location)
            shape = (len(path.parts) == 1 and location.endswith('.rpm') if name == 'nvidia-vendor' else
                     len(path.parts) >= 2 and path.parts[0] == 'Packages')
            if (name not in repositories or path.is_absolute() or
                    '..' in path.parts or str(path) != location or not shape or
                    not re.fullmatch(r'[A-Za-z0-9._/+~^:-]+', location)):
                raise RuntimeError('foreign or unsafe native NVIDIA package location')
            row['url'] = 'file://' + guest_root + '/' + name + '/' + location
            expected_replaced.update(old.get_nevra() for old in item.get_replaces())
        elif action == actions.TransactionItemAction_REPLACED:
            replaced.add(package.get_nevra())
        rows.append(row)
    if not rows or replaced != expected_replaced or not any('url' in row for row in rows):
        raise RuntimeError('empty or unexplained native NVIDIA replacement transaction')
    rows.sort(key=lambda row: (row['nevra'], row['action']))
    if len({(row['nevra'], row['action']) for row in rows}) != len(rows):
        raise RuntimeError('duplicate native NVIDIA transaction item')
    return {'transaction': rows, 'urls': sorted(row['url'] for row in rows if 'url' in row)}


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
        self.guest('''
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo','/mnt/qualification-repo')
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=install_weak_deps=False','--assumeyes','install','python3-libdnf5')
print(json.dumps({'signed_dvd_python_binding':native('rpm','-q','python3-libdnf5').strip()}))
''')
        for name, value in repositories.items():
            for relative, digest in value['files'].items():
                destination = GUEST_ROOT + '/' + name + '/' + relative
                self.guest('directory=' + repr(str(Path(destination).parent)) + '\n'
                           "pathlib.Path(directory).mkdir(parents=True,exist_ok=True)\nprint('{}')\n")
                self.upload(metadata_root / name / relative, destination, digest)
        planner = 'import libdnf5\n' + inspect.getsource(package_plan) + '\n'
        selected = self.guest(planner + 'targets=' + repr(TARGETS) + '\n' + '''
for name in ('ceph-base','ceph-updates'):
 pathlib.Path('/etc/yum.repos.d/'+name+'.repo').write_text('['+name+']\\nname='+name+'\\nbaseurl=file://''' + GUEST_ROOT + '''/'+name+'\\nenabled=0\\ngpgcheck=1\\n')
print(json.dumps(package_plan(libdnf5,targets,''' + repr(GUEST_ROOT) + ''')))
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
        installed = self.guest(planner + 'packages=' + repr(transferred) + '\ntargets=' + repr(TARGETS) +
                               '\nexpected_plan=' + repr(selected) + '\n' + '''
for item in packages:
 path=pathlib.Path(item['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
 signature=native('rpmkeys','--checksig','--verbose',str(path))
 assert 'NOKEY' not in signature and 'NOT OK' not in signature and 'OK' in signature
assert package_plan(libdnf5,targets,''' + repr(GUEST_ROOT) + ''')==expected_plan
native('dnf5','--disable-repo=*','--enable-repo=ceph-base','--enable-repo=ceph-updates',
       '--setopt=plugins=False','--setopt=gpgcheck=True','--setopt=install_weak_deps=False',
       '--setopt=skip_broken=False','--setopt=skip_unavailable=False','--assumeyes','install',*targets)
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
