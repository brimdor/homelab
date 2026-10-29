#!/usr/bin/env python3
"""Qualify the minimal CPython BLAKE2 CPU-dispatch repair on Sprigatito."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ARCHIVE_SHA = 'c2215904f02b175596dc49351585104f4bc20341e1c47378b26a2c274360ce73'
HEADERS_SHA = '579237b12bf4416bc9f5b6733d24e3f93c583f1bc283ec2514b9d296a2bd13bf'
MODULE_SHA = '7523638132c313eb5b8a5bca62bef4b5a403312718fc7585863230d231f70047'
ORIGINAL_SHA = 'c7a10238137f151fb9e8fa5394167344c0db695ba15d2923dabc99785a7e0729'
CANDIDATE_SHA = '920605c9fff6f3249aa0be069efdc44a0f14ea5e57688a3f5d5e89a6e654e872'
RECOVERY = '/var/lib/homelab-recovery/maintenance-103/sprigatito-python-blake2-20261029-a'
PATCH_FROM = '''    flags->avx = (ecx1 & ECX_AVX) != 0;

    flags->avx2 = (ebx7 & EBX_AVX2) != 0;'''
PATCH_TO = '''#if defined(__x86_64__) && defined(__GNUC__)
    // GCC checks operating-system XSAVE support as well as hardware CPUID.
    flags->avx = __builtin_cpu_supports("avx") != 0;
    flags->avx2 = __builtin_cpu_supports("avx2") != 0;
#else
    flags->avx = (ecx1 & ECX_AVX) != 0;

    flags->avx2 = (ebx7 & EBX_AVX2) != 0;
#endif'''


def patched(source):
    if hashlib.sha256(source).hexdigest() != MODULE_SHA or source.count(PATCH_FROM.encode()) != 1:
        raise RuntimeError('exact official CPython module required')
    return source.replace(PATCH_FROM.encode(), PATCH_TO.encode())


def vectors():
    """Compare independent installed implementations, including streaming and tree parameters."""
    result = []
    for name, width in (('blake2b', 64), ('blake2s', 32)):
        for size in (0, 1, 63, 64, 127, 128, 129, 1024, 1048576):
            data = (bytes(range(256)) * ((size + 255) // 256))[:size]
            for options in ({}, {'digest_size': 1}, {'key': bytes(range(width))},
                            {'digest_size': width // 2, 'salt': b'salt', 'person': b'personal',
                             'fanout': 2, 'depth': 2, 'leaf_size': 4096, 'node_offset': 7,
                             'node_depth': 1, 'inner_size': width // 2, 'last_node': True}):
                constructor = getattr(hashlib, name)
                direct = constructor(data, **options).hexdigest()
                if hashlib.new(name, data, **options).hexdigest() != direct:
                    raise RuntimeError('hashlib named constructor differs')
                streaming = constructor(**options)
                for offset in range(0, size, 37):
                    streaming.update(data[offset:offset + 37])
                if streaming.hexdigest() != direct or streaming.copy().digest() != bytes.fromhex(direct):
                    raise RuntimeError('streaming or copy digest differs')
                result.append(direct)
    return result


def metadata(path):
    import os
    import stat

    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError('single regular extension required')
    return {'uid': info.st_uid, 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode),
            'mtime_ns': info.st_mtime_ns,
            'xattrs': {key: os.getxattr(path, key).hex() for key in os.listxattr(path)}}


def atomic_copy(source, target, attributes):
    import os
    import tempfile

    descriptor, name = tempfile.mkstemp(prefix='.maintenance103-blake2-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(source.read_bytes())
            output.flush()
            os.fchown(output.fileno(), attributes['uid'], attributes['gid'])
            os.fchmod(output.fileno(), attributes['mode'])
            for key in os.listxattr(temporary):
                if key not in attributes['xattrs']:
                    os.removexattr(temporary, key)
            for key, value in attributes['xattrs'].items():
                os.setxattr(temporary, key, bytes.fromhex(value))
            os.utime(temporary, ns=(attributes['mtime_ns'], attributes['mtime_ns']))
            os.fsync(output.fileno())
        if metadata(temporary) != attributes:
            raise RuntimeError('replacement metadata differs')
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def install(target, candidate, recovery, verify, revision):
    """Caller holds controller and RPM POSIX transaction locks throughout."""
    import os
    import maintenance_actor_hold as actors

    actors.safe(target)
    actors.safe(recovery)
    actors.require(hashlib.sha256(target.read_bytes()).hexdigest() == ORIGINAL_SHA and
                   hashlib.sha256(candidate.read_bytes()).hexdigest() == CANDIDATE_SHA,
                   'qualified original or candidate identity differs')
    attributes = metadata(target)
    actors.require(attributes['uid'] == os.geteuid() and not attributes['mode'] & 0o022,
                   'extension ownership is unsafe')
    recovery.mkdir(mode=0o700)
    original = recovery / 'original.so'
    atomic_copy(target, original, attributes)
    actors.require(hashlib.sha256(original.read_bytes()).hexdigest() == ORIGINAL_SHA and
                   metadata(original) == attributes, 'protected original differs')
    manifest = {'version': 1, 'target': str(target), 'metadata': attributes,
                'original_sha256': ORIGINAL_SHA, 'candidate_sha256': CANDIDATE_SHA,
                'source_sha256': ARCHIVE_SHA, 'revision': revision}
    actors.exclusive_file(recovery / 'manifest.json', json.dumps(manifest, sort_keys=True).encode(), 0o600)
    try:
        atomic_copy(candidate, target, attributes)
        actors.require(hashlib.sha256(target.read_bytes()).hexdigest() == CANDIDATE_SHA and
                       metadata(target) == attributes, 'installed candidate differs')
        verify()
        actors.exclusive_file(recovery / 'vectors-accepted.json', b'{"vectors":72}', 0o600)
    except BaseException:
        atomic_copy(original, target, attributes)
        actors.require(hashlib.sha256(target.read_bytes()).hexdigest() == ORIGINAL_SHA and
                       metadata(target) == attributes, 'automatic rollback verification failed')
        actors.exclusive_file(recovery / 'rolled-back.json', b'{"original_restored":true}', 0o600)
        raise
    return manifest


def native(context):
    import fcntl
    import os
    import signal
    import shutil
    import socket
    import stat
    import tarfile
    import tempfile
    import urllib.request

    import maintenance_actor_hold as actors

    def call(*args, **kwargs):
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   **{k: v for k, v in kwargs.items() if k != 'input'})
        try:
            stdout, stderr = process.communicate(kwargs.get('input'))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        if process.returncode:
            raise RuntimeError('BLAKE2 qualification command failed: ' + repr(args[:3]) +
                               ' exit ' + str(process.returncode) + ': ' +
                               stderr.decode(errors='replace')[-2500:])
        return stdout

    def interrupted(_number, _frame):
        raise InterruptedError('owned BLAKE2 qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)

    actors.require(os.geteuid() == 0 and socket.gethostname() == 'sprigatito' and
        Path('/etc/machine-id').read_text().strip() == 'e5796c3018b6448eae0c69405926317e' and
        call('findmnt', '-n', '-o', 'UUID', '/').strip() == b'c27f6613-788e-4d00-802c-5b84a730a631' and
        Path('/proc/sys/kernel/random/boot_id').read_text().strip() == context['boot'] and
        call('rpm', '-q', 'python3-libs').strip() == b'python3-libs-3.14.8-1.fc44.x86_64' and
        call('rpm', '-E', '%fedora').strip() == b'44' and
        call('getenforce').strip() == b'Enforcing' and
        Path('/sys/devices/system/cpu/vulnerabilities/gather_data_sampling').read_text().strip() ==
        'Mitigation: AVX disabled, no microcode', 'exact mitigated host and Python required')
    import _blake2
    original = Path(_blake2.__file__)
    actors.safe(original)
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    if context['rollback']:
        hold = actors.Hold(actors.Systemd(), lambda: None, lambda owner: False)
        lock_path = Path('/usr/lib/sysimage/rpm/.rpm.lock')
        actors.safe(lock_path)
        with hold.serialized(), os.fdopen(os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW), 'r+b') as lock:
            actors.require(not hold.marker.exists(), 'another maintenance owner exists')
            info = os.fstat(lock.fileno())
            actors.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1,
                           'unsafe RPM transaction lock')
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            actors.require(os.stat(lock_path).st_ino == info.st_ino, 'RPM lock inode changed')
            recovery = Path(RECOVERY)
            actors.safe(recovery)
            manifest = json.loads((recovery / 'manifest.json').read_bytes())
            backup = recovery / 'original.so'
            actors.safe(backup)
            actors.require(manifest['target'] == str(original) and
                           hashlib.sha256(original.read_bytes()).hexdigest() == CANDIDATE_SHA and
                           hashlib.sha256(backup.read_bytes()).hexdigest() == ORIGINAL_SHA and
                           metadata(backup) == manifest['metadata'], 'exact rollback identity differs')
            atomic_copy(backup, original, manifest['metadata'])
            actors.require(hashlib.sha256(original.read_bytes()).hexdigest() == ORIGINAL_SHA and
                           metadata(original) == manifest['metadata'], 'rollback acceptance failed')
            actors.exclusive_file(recovery / 'ansible-rolled-back.json', b'{"original_restored":true}', 0o600)
        return {'rolled_back': True, 'original_sha256': ORIGINAL_SHA}
    call('rpm', '-V', 'python3-libs')
    hold = actors.Hold(actors.Systemd(), lambda: None, lambda owner: False)
    root = Path(tempfile.mkdtemp(prefix='maintenance103-blake2-', dir='/var/tmp'))
    try:
        with hold.serialized():
            actors.require(not hold.marker.exists(), 'another native maintenance owner exists')
            archive = root / 'Python-3.14.8.tar.xz'
            with urllib.request.urlopen('https://www.python.org/ftp/python/3.14.8/Python-3.14.8.tar.xz',
                                        timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
            actors.require(hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA,
                           'official source archive checksum differs')
            source = root / 'source'
            source.mkdir()
            with tarfile.open(archive, 'r:xz') as contents:
                for member in contents.getmembers():
                    path = Path(member.name)
                    actors.require(path.parts[0] == 'Python-3.14.8' and '..' not in path.parts,
                                   'unsafe source archive path')
                    if member.isfile() and path.parts[1] in ('Include', 'Modules'):
                        target = source.joinpath(*path.parts[1:])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(contents.extractfile(member).read())
            module = source / 'Modules/blake2module.c'
            module.write_bytes(patched(module.read_bytes()))
            call('dnf', '--setopt=cachedir=' + str(root / 'cache'), '--setopt=logdir=' + str(root / 'log'),
                 '--setopt=persistdir=' + str(root / 'state'), '--disable-repo=*',
                 '--enable-repo=fedora', '--enable-repo=updates', 'download', '--destdir=' + str(root),
                 'python3-devel-3.14.8-1.fc44.x86_64')
            headers = root / 'python3-devel-3.14.8-1.fc44.x86_64.rpm'
            actors.require(hashlib.sha256(headers.read_bytes()).hexdigest() == HEADERS_SHA,
                           'signed development headers differ')
            signature = call('rpmkeys', '--checksig', str(headers)).decode()
            actors.require('digests signatures OK' in signature, 'header package signature not verified')
            payload = call('rpm2cpio', str(headers))
            names = call('cpio', '-t', input=payload).decode().splitlines()
            actors.require(all(not Path(name).is_absolute() and '..' not in Path(name).parts
                               for name in names), 'unsafe development header path')
            extracted = root / 'headers'
            extracted.mkdir()
            call('cpio', '-id', '--no-absolute-filenames', './usr/include/*', input=payload, cwd=extracted)
            actors.require(not any(p.is_symlink() for p in extracted.rglob('*')),
                           'development headers contain unreviewed links')
            include = extracted / 'usr/include/python3.14'
            common = ['nice', '-n', '19', 'gcc', '-c', '-O2', '-fPIC', '-fexceptions',
                      '-ffile-prefix-map=' + str(root) + '=/homelab-python-blake2',
                      '-fcf-protection', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=3',
                      '-D_BSD_SOURCE', '-D_DEFAULT_SOURCE', '-I' + str(include),
                      '-I' + str(include / 'internal'), '-I' + str(source / 'Modules'),
                      '-I' + str(source / 'Modules/_hacl'), '-I' + str(source / 'Modules/_hacl/include'),
                      '-I/usr/include/python3.14']
            units = [('blake2module.c', []), ('_hacl/Hacl_Hash_Blake2b.c', []),
                     ('_hacl/Hacl_Hash_Blake2s.c', []),
                     ('_hacl/Lib_Memzero0.c', []),
                     ('_hacl/Hacl_Hash_Blake2s_Simd128.c',
                      ['-msse', '-msse2', '-msse3', '-msse4.1', '-msse4.2', '-DHACL_CAN_COMPILE_VEC128']),
                     ('_hacl/Hacl_Hash_Blake2b_Simd256.c', ['-mavx2', '-DHACL_CAN_COMPILE_VEC256'])]
            objects = []
            for index, (name, flags) in enumerate(units):
                obj = root / (str(index) + '.o')
                call(*common, *flags, str(source / 'Modules' / name), '-o', str(obj))
                objects.append(str(obj))
            candidate = root / original.name
            call('gcc', '-shared', '-Wl,-z,relro,-z,now,-z,noexecstack', *objects, '-o', str(candidate))
            # A fresh child loads only the candidate extension, never the installed one.
            probe = ('import resource,importlib.util,sys,json\n'
                     'resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
                     'spec=importlib.util.spec_from_file_location("_blake2",' + repr(str(candidate)) + ')\n'
                     'module=importlib.util.module_from_spec(spec);sys.modules["_blake2"]=module\n'
                     'spec.loader.exec_module(module)\nimport hashlib\n' +
                     context['vectors_source'] + '\nprint(json.dumps(vectors()))\n')
            actual = json.loads(call('/usr/bin/python3', '-I', '-B', '-c', probe))
            actors.require(actual == context['reference_vectors'], 'candidate BLAKE2 reference vectors differ')
            actors.require(hashlib.sha256(original.read_bytes()).hexdigest() == before,
                           'installed Python extension changed during qualification')
            result = {'qualified': True, 'vectors': len(actual), 'installed_extension_unchanged': True,
                      'original_sha256': before, 'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
                      'source_sha256': ARCHIVE_SHA, 'headers_sha256': HEADERS_SHA,
                      'patch_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
                      'gds_avx_disabled_retained': True, 'installed': False}
            if context['apply']:
                lock_path = Path('/usr/lib/sysimage/rpm/.rpm.lock')
                actors.safe(lock_path)
                descriptor = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    info = os.fstat(descriptor)
                    actors.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                                   info.st_nlink == 1, 'unsafe RPM transaction lock')
                    # RPM 6 uses whole-file POSIX F_SETLK, not BSD flock.
                    fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    actors.require(os.stat(lock_path).st_ino == info.st_ino and not hold.marker.exists(),
                                   'transaction lock or maintenance owner changed')
                    contender = ('import os,fcntl\nf=open("/usr/lib/sysimage/rpm/.rpm.lock","r+b")\n'
                                 'try: fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
                                 'except BlockingIOError: print("blocked")\n'
                                 'else: raise RuntimeError("RPM transaction exclusion failed")\n')
                    actors.require(call('/usr/bin/python3', '-I', '-B', '-c', contender).strip() == b'blocked',
                                   'RPM POSIX lock contention was not proven')
                    def installed_vectors():
                        probe = ('import resource,json,hashlib,selinux\n'
                                 'resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n' +
                                 context['vectors_source'] + '\nprint(json.dumps(vectors()))\n')
                        actors.require(json.loads(call('/usr/bin/python3', '-I', '-B', '-c', probe)) ==
                                       context['reference_vectors'], 'installed stdlib acceptance failed')
                    parent = Path(RECOVERY).parent
                    actors.safe(parent)
                    actors.require(parent.stat().st_uid == 0 and not parent.stat().st_mode & 0o022 and
                                   call('findmnt', '-n', '-o', 'UUID', '-T', str(parent)).strip() ==
                                   b'c27f6613-788e-4d00-802c-5b84a730a631',
                                   'protected recovery must remain on exact local root')
                    install(original, candidate, Path(RECOVERY), installed_vectors, context['revision'])
                    result.update(installed=True, installed_extension_unchanged=False,
                                  recovery=RECOVERY, rpm_posix_transaction_lock=True)
                finally:
                    os.close(descriptor)
    finally:
        shutil.rmtree(root)
    result['scratch_removed'] = not root.exists()
    return result


def main():
    import inspect
    from maintenance_coordination import require
    import maintenance_production_node as production

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('identity', 'known-hosts', 'kubectl'):
        parser.add_argument('--' + name, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master' and
            subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip() ==
            'git@git.eaglepass.io:ops/homelab.git' and subprocess.check_output([
                'git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] == revision,
            'publish the exact BLAKE2 qualification before execution')
    bundle = {}
    for name in ('maintenance_actor_hold', 'maintenance_production_node', 'maintenance_python_blake2'):
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == subprocess.check_output(['git', 'show', revision + ':' + str(path)]),
                'unpublished BLAKE2 qualification dependency')
        if name == 'maintenance_actor_hold':
            bundle[name] = path.read_text()
    api = production.Kubectl(args.kubectl)
    node = api.call('get', 'node', 'sprigatito', '-o', 'json')
    ds = api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')
    require(node['metadata']['uid'] == '5d80125d-4228-47dd-b19c-ca86f7d4316c' and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']) and
            production.JOURNAL not in ds['metadata'].get('annotations', {}), 'node or maintenance identity differs')
    context = {'boot': node['status']['nodeInfo']['bootID'], 'reference_vectors': vectors(),
               'vectors_source': inspect.getsource(vectors), 'apply': args.apply,
               'rollback': args.rollback, 'revision': revision}
    source = Path(__file__).read_text().split('\ndef main(')[0]
    program = 'import sys,types\nbundle=' + repr(bundle) + '\n'
    program += 'for name,code in bundle.items():\n m=types.ModuleType(name);sys.modules[name]=m;exec(compile(code,name,"exec"),m.__dict__)\n'
    program += source + '\nprint(json.dumps(native(' + repr(context) + ')))'
    result = production.remote(args, program, '10.0.20.20')
    if args.apply:
        import os
        import re

        environment = os.environ.copy()
        environment.update({'ANSIBLE_CONFIG': str(Path('metal/maintenance/ansible.cfg').resolve()),
            'ANSIBLE_HOST_KEY_CHECKING': 'True', 'ANSIBLE_REMOTE_USER': 'root',
            'ANSIBLE_PRIVATE_KEY_FILE': args.identity,
            'ANSIBLE_SSH_ARGS': '-o UserKnownHostsFile=' + args.known_hosts +
                ' -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o BatchMode=yes'
                ' -o IdentitiesOnly=yes -o ControlMaster=no'})
        try:
            accepted = subprocess.run(['/Users/chris/.local/bin/ansible-playbook', '-i',
                'metal/inventories/prod.yml', 'metal/nodes.yml', '--limit', 'sprigatito',
                '--tags', 'gpu_container_access'], env=environment, capture_output=True, text=True)
            summary = re.search(r'^sprigatito\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)',
                                accepted.stdout, re.MULTILINE)
            require(accepted.returncode == 0 and summary is not None and int(summary[1]) >= 2 and
                    tuple(map(int, summary.groups()[1:])) == (0, 0, 0),
                    'Ansible fact gathering or idempotent GPU acceptance failed: ' +
                    accepted.stdout[-2500:] + accepted.stderr[-1000:])
            result['ansible_facts_and_gpu_idempotence'] = True
        except BaseException:
            rollback_context = dict(context, apply=False, rollback=True)
            rollback_program = program[:program.rfind('\nprint(json.dumps(native(')]
            rollback_program += '\nprint(json.dumps(native(' + repr(rollback_context) + ')))'
            production.remote(args, rollback_program, '10.0.20.20')
            raise
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
