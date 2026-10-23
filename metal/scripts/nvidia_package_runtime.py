#!/usr/bin/env python3
"""Inspect installed vendor DKMS/modules/libraries in a device-free Fedora VM."""

import ctypes
import hashlib
import json
from pathlib import Path
import re
import subprocess

from nvidia_kernel_build import KERNEL, VERSION, compiler_matches


def run():
    def native(*args):
        return subprocess.check_output(args, stderr=subprocess.PIPE).decode().strip()

    assert native('hostname') == 'qualification-fedora44'
    assert native('uname', '-r') == KERNEL
    assert Path('/sys/fs/selinux/enforce').read_text().strip() == '1'
    assert not any(p.read_text().strip() == '0x10de' for p in Path('/sys/bus/pci/devices').glob('*/vendor'))
    compiler = native('gcc', '-dumpfullversion')
    compiler_matches((Path('/usr/src/kernels') / KERNEL / '.config').read_text(), compiler)
    status = native('dkms', 'status', '-m', 'nvidia', '-v', VERSION, '-k', KERNEL)
    assert re.fullmatch(r'nvidia/' + re.escape(VERSION) + ', ' + re.escape(KERNEL) +
                        r', x86_64: installed', status), status
    packages = {}
    for line in native('rpm', '-qa', '--qf', '%{NAME} %{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n').splitlines():
        name, edition = line.split()
        if name.startswith(('nvidia-', 'libnvidia-')) or name == 'kmod-nvidia-open-dkms':
            assert name not in packages and edition.startswith('3:' + VERSION + '-'), (name, edition)
            packages[name] = edition
    assert {'nvidia-open', 'kmod-nvidia-open-dkms', 'nvidia-kmod-common', 'nvidia-driver-cuda',
            'nvidia-driver', 'nvidia-driver-libs'} <= packages.keys()
    modules = {}
    module_root = (Path('/usr/lib/modules') / KERNEL).resolve(strict=True)
    for name in ('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm', 'nvidia-peermem'):
        filename = Path(native('modinfo', '-k', KERNEL, '-F', 'filename', name))
        resolved = filename.resolve(strict=True)
        assert resolved.is_relative_to(module_root) and resolved.is_file()
        fields = {field: native('modinfo', '-k', KERNEL, '-F', field, name)
                  for field in ('version', 'vermagic', 'license')}
        assert fields['version'] == VERSION and fields['vermagic'].split()[0] == KERNEL
        assert fields['license'] == ('Dual BSD/GPL' if name == 'nvidia-peermem' else 'Dual MIT/GPL')
        modules[name] = {**fields, 'path': str(resolved), 'sha256': hashlib.sha256(resolved.read_bytes()).hexdigest()}
    firmware = {}
    root = Path('/usr/lib/firmware/nvidia') / VERSION
    for name in ('gsp_ga10x.bin', 'gsp_tu10x.bin', 'ucodes_ga10x.bin', 'ucodes_tu10x.bin'):
        path = root / name
        assert path.is_file() and not path.is_symlink()
        assert native('rpm', '-qf', '--qf', '%{NAME} %{VERSION}', str(path)) == 'nvidia-kmod-common ' + VERSION
        firmware[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    libraries = ['libcuda.so.1', 'libnvidia-ml.so.1', 'libnvidia-encode.so.1']
    for library in libraries:
        ctypes.CDLL(library, mode=ctypes.RTLD_GLOBAL)
    initramfs = Path('/boot/initramfs-' + KERNEL + '.img')
    assert initramfs.is_file() and not initramfs.is_symlink()
    return {'accepted': True, 'kernel': KERNEL, 'driver': VERSION, 'compiler': compiler,
            'packages': packages, 'dkms_status': status, 'modules': modules, 'firmware': firmware,
            'native_library_loading': libraries, 'selinux_enforcing': True, 'no_gpu': True,
            'loaded_modules': sorted(p.name for p in Path('/sys/module').glob('nvidia*')),
            'initramfs_sha256': hashlib.sha256(initramfs.read_bytes()).hexdigest(),
            'device_execution_unqualified': True}


def evidence():
    try:
        return run()
    except Exception as error:
        result = {'accepted': False, 'error': type(error).__name__ + ': ' + str(error)[:2000]}
        logs = {}
        root = Path('/var/lib/dkms/nvidia') / VERSION
        if root.is_dir() and not root.is_symlink():
            for path in root.rglob('make.log'):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
                    raw = path.read_bytes()
                    logs[str(path)] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                                       'tail': raw[-12000:].decode(errors='replace')}
        result['dkms_build_logs'] = logs
        return result


if __name__ == '__main__':
    print(json.dumps(evidence()), flush=True)
