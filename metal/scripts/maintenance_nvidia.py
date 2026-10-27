"""Exact signed NVIDIA repositories and native acceptance for Arcanine's OS hops."""

import hashlib
import re
import urllib.request

from maintenance_actor_hold import exclusive_file, require, safe


PROFILES = {
    41: {'version': '570.211.01', 'key': 'D42D0685.pub',
         'sha256': '27e46a2d43e125859fb8a62c3b75bf798aeb95fa6f7d9bf790c1167ed9a0b39c',
         'fingerprint': '610C7B14E068A878070DA4E99CD0A493D42D0685'},
    43: {'version': '595.112.07', 'key': '1940C73E.pub',
         'sha256': '95272017d499bb2380fd31f088c0bd74a8ebc00d2f14193dbdcf4438b3fddd1b',
         'fingerprint': '8033132AA30E535FF7F6059764E003B61940C73E'},
    44: {'version': '615.71.10', 'key': '73CD9B30.pub',
         'sha256': '9221458f62030a18d5a28eecf44496016ff9c11548492ac2ce428f75c7513cab',
         'fingerprint': '129994480EC63D2789BC98E490DFED2F73CD9B30'},
}
GPU = 'GPU-a45669eb-7817-bca9-6c78-d268e0750059'


def configure(directory, release, native):
    """Only the owned private reposdir changes; existing system repositories stay intact."""
    require(release in PROFILES, 'unreviewed NVIDIA target release')
    profile = PROFILES[release]
    base = 'https://developer.download.nvidia.com/compute/cuda/repos/fedora' + str(release) + '/x86_64/'
    path = directory / profile['key']
    safe(directory); safe(path)
    if not path.exists():
        with urllib.request.urlopen(base + profile['key'], timeout=45) as response:
            require(response.status == 200 and response.geturl() == base + profile['key'],
                    'NVIDIA key HTTPS origin differs')
            key = response.read(65537)
        require(0 < len(key) <= 65536 and hashlib.sha256(key).hexdigest() == profile['sha256'],
                'NVIDIA key differs from reviewed public fingerprint input')
        exclusive_file(path, key, 0o600)
    require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == profile['sha256'],
            'retained NVIDIA public key differs')
    native('rpmkeys', '--import', str(path))
    content = ('[maintenance-nvidia]\nname=Issue 103 signed NVIDIA Fedora ' + str(release) +
               '\nbaseurl=' + base + '\nenabled=1\ngpgcheck=1\nmodule_hotfixes=1\n' +
               'gpgkey=file://' + str(path) + '\nincludepkgs=*-' + profile['version'] +
               '-* nvidia-driver-selinux\nexclude=*.i686\n')
    repo = directory / 'nvidia.repo'; safe(repo)
    if not repo.exists():
        exclusive_file(repo, content.encode(), 0o600)
    require(repo.read_text() == content, 'NVIDIA repository configuration changed')
    return {'release': release, **profile, 'repos_sha256': hashlib.sha256(content.encode()).hexdigest()}


def downloaded(metadata, release):
    """The controller separately verifies every downloaded RPM's signature and hash."""
    profile = PROFILES[release]
    required = {'kmod-nvidia-open-dkms', 'nvidia-driver', 'nvidia-driver-cuda', 'nvidia-kmod-common'}
    selected = {}
    for name, version, edition in metadata:
        if name in required:
            require(name not in selected and version == profile['version'] and
                    edition == '1.fc' + str(release), 'NVIDIA target package identity differs')
            selected[name] = version
    require(set(selected) == required, 'offline target lacks the exact NVIDIA driver package set')
    return {'release': release, 'version': profile['version'], 'packages': sorted(selected)}


def runtime(native, release):
    """Require the real GPU, running kernel and installed open DKMS module to agree."""
    version = PROFILES[release]['version']
    require(native('rpm', '-E', '%fedora') == str(release), 'NVIDIA runtime Fedora release differs')
    kernel = native('uname', '-r')
    require('.fc' + str(release) + '.' in kernel, 'NVIDIA runtime kernel release differs')
    rows = native('nvidia-smi', '--query-gpu=uuid,pci.bus_id,name,driver_version,memory.total',
                  '--format=csv,noheader,nounits').splitlines()
    require(len(rows) == 1, 'GPU count changed')
    require([v.strip() for v in rows[0].split(',')] ==
            [GPU, '00000000:01:00.0', 'NVIDIA GeForce RTX 3090', version, '24576'],
            'original GPU or loaded driver differs')
    status = native('dkms', 'status')
    require(any(re.fullmatch(r'nvidia(?:-open)?/' + re.escape(version) + ', ' +
                            re.escape(kernel) + r', x86_64: installed', line)
                for line in status.splitlines()), 'current kernel NVIDIA DKMS build is not installed')
    modules = {}
    for name in ('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm'):
        fields = {field: native('modinfo', '-k', kernel, '-F', field, name)
                  for field in ('version', 'vermagic', 'license')}
        require(fields['version'] == version and fields['vermagic'].split()[0] == kernel and
                fields['license'] == 'Dual MIT/GPL', 'NVIDIA module build differs')
        modules[name] = fields
    loaded = native('nvidia-smi', '--query-gpu=uuid,driver_version', '--format=csv,noheader')
    require(loaded == GPU + ', ' + version, 'GPU runtime changed during module verification')
    return {'gpu': GPU, 'driver': version, 'kernel': kernel, 'modules': modules,
            'dkms_installed': True, 'native_nvml': True, 'cuda_execution_untested': True}
