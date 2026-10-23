#!/usr/bin/env python3
"""Build the exact public NVIDIA615.71.10 source without installing modules."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


VERSION = '615.71.10'
KERNEL = '7.2.11-200.fc44.x86_64'
SOURCE_SHA256 = '9eb698055a9b395e76bc2191395f59fce3d686e370d797a5da37d3278aba1ef6'
SOURCE_URL = 'https://codeload.github.com/NVIDIA/open-gpu-kernel-modules/tar.gz/refs/tags/' + VERSION
SOURCE_ROOT = 'open-gpu-kernel-modules-' + VERSION


def source_members(archive):
    members = archive.getmembers()
    names = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or str(path) != member.name or
                not path.parts or path.parts[0] != SOURCE_ROOT or member.name in names or
                not (member.isfile() or member.isdir())):
            raise RuntimeError('foreign, duplicate or unsafe NVIDIA source member')
        names.add(member.name)
    if len(members) != 4642 or SOURCE_ROOT + '/Makefile' not in names:
        raise RuntimeError('NVIDIA source inventory differs')
    return members


def compiler_matches(config, compiler):
    matches = re.findall(r'^CONFIG_GCC_VERSION=([0-9]+)$', config, re.MULTILINE)
    if len(matches) != 1 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', compiler):
        raise RuntimeError('missing or ambiguous kernel/compiler version')
    major, minor, patch = map(int, compiler.split('.'))
    if int(matches[0]) != major * 10000 + minor * 100 + patch:
        raise RuntimeError('compiler differs from candidate kernel toolchain')


def run():
    def native(*arguments):
        return subprocess.check_output(arguments).decode().strip()

    assert native('hostname') == 'qualification-fedora44'
    assert native('uname', '-r') == KERNEL
    assert 'VERSION_ID=44' in Path('/etc/os-release').read_text()
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    assert native('id', '-u', 'fixture') == '1000' and native('id', '-g', 'fixture') == '1000'
    assert not list(Path('/dev').glob('nvidia*'))
    assert not any(p.read_text().strip() == '0x10de' for p in Path('/sys/bus/pci/devices').glob('*/vendor'))
    archive_path = Path('/run/qualification-nvidia-source.tar.gz')
    assert archive_path.is_file() and not archive_path.is_symlink()
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == SOURCE_SHA256
    config = Path('/usr/src/kernels') / KERNEL / '.config'
    compiler = native('gcc', '-dumpfullversion')
    compiler_matches(config.read_text(), compiler)
    root = Path('/work/qualification-nvidia')
    assert not root.exists() and not root.is_symlink()
    root.mkdir(parents=True, mode=0o755)
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = source_members(archive)
        for member in members:
            destination = root / member.name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o755)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with archive.extractfile(member) as source, destination.open('xb') as output:
                    import shutil
                    shutil.copyfileobj(source, output)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
    for path in [root, *root.rglob('*')]:
        os.chown(path, 1000, 1000)
    source = root / SOURCE_ROOT
    log = root / 'build.log'
    with log.open('xb') as output:
        result = subprocess.run(['sudo', '-u', 'fixture', '--', 'make', '-j2', 'modules',
                                 'KERNEL_UNAME=' + KERNEL], cwd=source, stdout=output, stderr=subprocess.STDOUT)
    raw = log.read_bytes()
    evidence = {'accepted': False, 'source_sha256': SOURCE_SHA256, 'driver': VERSION, 'kernel': KERNEL,
                'compiler': compiler, 'build_exit': result.returncode, 'build_log_sha256': hashlib.sha256(raw).hexdigest(),
                'build_log_bytes': len(raw), 'build_tail': raw[-16384:].decode(errors='replace'),
                'selinux_enforcing': True, 'no_gpu': True, 'modules_installed_or_loaded': False}
    if result.returncode == 0:
        modules = {}
        for name in ('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm', 'nvidia-peermem'):
            path = source / 'kernel-open' / (name + '.ko')
            assert path.is_file() and not path.is_symlink()
            fields = {field: native('modinfo', '-F', field, str(path)) for field in ('version', 'vermagic', 'license')}
            expected_license = 'Dual BSD/GPL' if name == 'nvidia-peermem' else 'Dual MIT/GPL'
            assert fields['version'] == VERSION and fields['vermagic'].split()[0] == KERNEL
            assert fields['license'] == expected_license
            modules[name] = {**fields, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        assert not list(Path('/sys/module').glob('nvidia*'))
        evidence.update(accepted=True, modules=modules)
    return evidence


if __name__ == '__main__':
    print(json.dumps(run()), flush=True)
