"""Exact signed NVIDIA repositories and native acceptance for the reviewed GPU nodes' OS hops."""

import hashlib
import os
from pathlib import Path
import stat
import re
import urllib.request

from maintenance_actor_hold import exclusive_file, fsync_directory, require, safe
from maintenance_hop_journal import canonical, checksum
from maintenance_node_drain import private_json
from maintenance_cuda import compute


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
GPU_NODES = {
    'arcanine': ('88aa2572-09df-40b9-8a00-960e9682917c', GPU, 'NVIDIA GeForce RTX 3090', '24576'),
    'sprigatito': ('5d80125d-4228-47dd-b19c-ca86f7d4316c', 'GPU-d65b16cd-87c2-860c-a210-271e7d3a13d0', 'NVIDIA GeForce GTX 1650', '4096'),
}


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


def runtime(native, release, node='arcanine'):
    """Require the real GPU, running kernel and installed open DKMS module to agree."""
    require(node in GPU_NODES, 'unreviewed GPU node')
    _, gpu, gpu_name, memory = GPU_NODES[node]
    version = PROFILES[release]['version']
    require(native('rpm', '-E', '%fedora') == str(release), 'NVIDIA runtime Fedora release differs')
    kernel = native('uname', '-r')
    require('.fc' + str(release) + '.' in kernel, 'NVIDIA runtime kernel release differs')
    rows = native('nvidia-smi', '--query-gpu=uuid,pci.bus_id,name,driver_version,memory.total',
                  '--format=csv,noheader,nounits').splitlines()
    require(len(rows) == 1, 'GPU count changed')
    require([v.strip() for v in rows[0].split(',')] ==
            [gpu, '00000000:01:00.0', gpu_name, version, memory],
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
    require(loaded == gpu + ', ' + version, 'GPU runtime changed during module verification')
    return {'gpu': gpu, 'driver': version, 'kernel': kernel, 'modules': modules,
            'dkms_installed': True, 'native_nvml': True, 'cuda_execution': compute() if node == 'arcanine' else compute(node=node)}


PERMANENT_REPOSITORY = Path('/etc/yum.repos.d/cuda-fedora.repo')
PERMANENT_OLD_SHA256 = '8dadb9d9bd101737001b65006cc282872005e1da9f282436550a5a2c08a9ee16'
PERMANENT_CONTENT = (b'[cuda-fedora44-x86_64]\nname=cuda-fedora44-x86_64\n'
                     b'baseurl=https://developer.download.nvidia.com/compute/cuda/repos/fedora44/x86_64\n'
                     b'enabled=1\ngpgcheck=1\n'
                     b'gpgkey=https://developer.download.nvidia.com/compute/cuda/repos/fedora44/x86_64/73CD9B30.pub\n')
PERMANENT_SHA256 = 'e1fdc2735f1d899e12be5bc8b6d1882b55053afc7a87d07dc6af982e730bf0dd'


def regular_digest(path, mode):
    safe(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_gid == os.getegid() and info.st_nlink == 1 and
            stat.S_IMODE(info.st_mode) == mode and 0 < info.st_size < 65536,
            'permanent NVIDIA repository input metadata differs')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def permanent_inputs(journal, native):
    owner = private_json(journal.path / '00000000.json')['owners']['global']
    require(owner['owner'] == journal.token and owner['node'] in GPU_NODES and owner['node_uid'] == GPU_NODES[owner['node']][0] and (owner['source'], owner['target']) == (43, 44),
            'permanent NVIDIA repository requires the exact final GPU-node owner')
    require(native('rpm', '-E', '%fedora') == '44', 'permanent NVIDIA repository requires Fedora 44')
    key = journal.hold.state / ('fedora-repositories-44-' + owner['owner']) / PROFILES[44]['key']
    require(regular_digest(key, 0o600) == PROFILES[44]['sha256'], 'retained NVIDIA 44 key differs')
    fingerprints = {line.split()[0].lower() for line in native('rpmkeys', '--list').splitlines() if line.split()}
    require(PROFILES[44]['fingerprint'].lower() in fingerprints,
            'reviewed NVIDIA 44 signing key is not imported')
    require(hashlib.sha256(PERMANENT_CONTENT).hexdigest() == PERMANENT_SHA256,
            'official NVIDIA 44 repository definition differs')
    return owner, journal.hold.state / ('nvidia-repository-' + owner['owner'] + '.json')


def permanent_repository(journal, native):
    """Read-only final gate: exact permanent provider and its original recovery binding."""
    owner, intent = permanent_inputs(journal, native)
    record = private_json(intent)
    require(set(record) == {'owner', 'identity', 'recovery_sha256', 'original', 'desired_sha256', 'key_sha256'} and
            record['owner'] == owner and record['identity'] == journal.hold.identity() and
            checksum(record['recovery_sha256']) and
            hashlib.sha256(record['original'].encode()).hexdigest() == PERMANENT_OLD_SHA256 and
            record['desired_sha256'] == PERMANENT_SHA256 and record['key_sha256'] == PROFILES[44]['sha256'],
            'permanent NVIDIA repository intent differs')
    require(regular_digest(PERMANENT_REPOSITORY, 0o644) == PERMANENT_SHA256,
            'permanent NVIDIA repository differs from Fedora 44')
    expected = {'intent_sha256': hashlib.sha256(canonical(record)).hexdigest(),
                'repository_sha256': PERMANENT_SHA256, 'key_sha256': PROFILES[44]['sha256']}
    accepted = intent.with_name('nvidia-repository-accepted-' + owner['owner'] + '.json')
    require(private_json(accepted) == expected, 'permanent NVIDIA repository acceptance differs')
    return expected


def persist_repository(journal, native, recovery):
    """Replace only the exact old provider, once; interrupted intents permit observation."""
    with journal.hold.serialized():
        owner, intent = permanent_inputs(journal, native)
        require(journal.owners(idle=True)['global'] == owner, 'current NVIDIA repository owner differs')
        state = journal.read()
        require(not state['pending'] and state['completed'] == [
            'cordon', 'drain', 'prepare_source', 'download_release', 'offline_transaction',
            'trusted_reconnect', 'verify_infrastructure'], 'permanent NVIDIA repository phase differs')
        require(recovery['source_release'] == 44 and recovery['identity'] == journal.hold.identity() and
                checksum(recovery['sha256']), 'fresh Fedora 44 recovery binding differs')
        safe(intent)
        if not intent.exists():
            require(regular_digest(PERMANENT_REPOSITORY, 0o644) == PERMANENT_OLD_SHA256,
                    'original Fedora 39 NVIDIA repository changed')
            record = {'owner': owner, 'identity': journal.hold.identity(), 'recovery_sha256': recovery['sha256'],
                      'original': PERMANENT_REPOSITORY.read_text(), 'desired_sha256': PERMANENT_SHA256,
                      'key_sha256': PROFILES[44]['sha256']}
            exclusive_file(intent, canonical(record), 0o600)
            temporary = PERMANENT_REPOSITORY.with_name('.nvidia-repository-' + owner['owner'])
            safe(temporary)
            exclusive_file(temporary, PERMANENT_CONTENT, 0o644)
            try:
                journal.owners(idle=True)
                require(regular_digest(PERMANENT_REPOSITORY, 0o644) == PERMANENT_OLD_SHA256,
                        'original NVIDIA repository changed before atomic replacement')
                os.replace(temporary, PERMANENT_REPOSITORY); fsync_directory(PERMANENT_REPOSITORY.parent)
            finally:
                if temporary.exists():temporary.unlink(); fsync_directory(temporary.parent)
        record = private_json(intent)
        require(set(record) == {'owner', 'identity', 'recovery_sha256', 'original', 'desired_sha256', 'key_sha256'} and
                record['owner'] == owner and record['identity'] == journal.hold.identity() and
                record['recovery_sha256'] == recovery['sha256'] and
                hashlib.sha256(record['original'].encode()).hexdigest() == PERMANENT_OLD_SHA256 and
                record['desired_sha256'] == PERMANENT_SHA256 and record['key_sha256'] == PROFILES[44]['sha256'],
                'retained NVIDIA repository recovery differs')
        require(regular_digest(PERMANENT_REPOSITORY, 0o644) == PERMANENT_SHA256,
                'permanent NVIDIA replacement intent exists; observe only, never replay')
        accepted = intent.with_name('nvidia-repository-accepted-' + owner['owner'] + '.json')
        safe(accepted)
        if not accepted.exists():
            journal.owners(idle=True)
            exclusive_file(accepted, canonical({'intent_sha256': hashlib.sha256(canonical(record)).hexdigest(),
                'repository_sha256': PERMANENT_SHA256, 'key_sha256': PROFILES[44]['sha256']}), 0o600)
        return permanent_repository(journal, native)
