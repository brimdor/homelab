"""Check historical Gitea Git objects using two isolated, read-only copies."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import uuid

import pointguide_files_recovery as retained


common = retained.common
IMAGE = 'docker.gitea.com/gitea@sha256:4c4256497e2e237ddebdd30986c7ce52cb6f936b3e90c34bb9f4665714599f62'
POINT = common.ROOT / 'gitea-shared-files-20261020-1618'
CHECKSUM = 'b79a3e19b3bd44c9b74a0a36228362fccd329bfaad184b73ad447ae160ecbaeb'
LABEL = 'io.eaglepass.gitea-git-recovery'
ROOTS = {
    '1855456346d71943f90d47359f395af19176093945b3c2fab44f81616c61db3e',
    'e6986a7d75fae3ee9d7ab4e2e8d61e82b27fa2038f4673e2956ae5c25644b2e1',
    '03f5bfa96eadc3dedc547e448fd6f7ea6f30f3f40c7e84e25b2c1e0c90d735b2',
}
ENV = {
    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
    'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0', 'LC_ALL': 'C',
}
PREFIX = ['-c', 'core.hooksPath=/dev/null', '-c', 'protocol.allow=never']
TMPFS = {'/tmp': 'rw,nosuid,nodev,uid=1000,gid=1000,mode=1777'}


def discover(tree):
    roots = sorted(str(PurePosixPath(name).parent) for name, record in tree.items()
                   if PurePosixPath(name).name == 'HEAD' and record['kind'] == 'file' and
                   all(tree.get(str(PurePosixPath(name).parent / child), {}).get('kind') == 'directory'
                       for child in ('objects', 'refs')))
    if len(roots) != 3 or {hashlib.sha256(name.encode()).hexdigest() for name in roots} != ROOTS:
        raise RuntimeError('protected Git repository identity differs')
    for root in roots:
        if root in ('.', '') or PurePosixPath(root).is_absolute() or '..' in PurePosixPath(root).parts:
            raise RuntimeError('unsafe protected Git repository path')
        for name, record in tree.items():
            if not name.startswith(root + '/'):
                continue
            relative = name[len(root) + 1:]
            if (record['kind'] == 'symlink' or relative in {
                    'objects/info/alternates', 'objects/info/http-alternates', 'shallow', 'commondir'} or
                    relative.endswith('.promisor') or relative == 'refs/replace' or
                    relative.startswith('refs/replace/')):
                raise RuntimeError('unsupported protected Git object storage or reference')
        if tree.get(root + '/config', {}).get('kind') != 'file':
            raise RuntimeError('protected Git configuration missing')
    return roots


def check_config(raw):
    if not raw.endswith(b'\0'):
        raise RuntimeError('native Git configuration framing differs')
    values = {}
    for record in raw[:-1].split(b'\0'):
        key, separator, value = record.partition(b'\n')
        if not separator or not (key in {
                b'core.bare', b'core.filemode', b'core.repositoryformatversion', b'receive.denycurrentbranch'} or
                re.fullmatch(rb'remote\.[A-Za-z0-9._-]+\.(url|push|mirror)', key)):
            raise RuntimeError('unreviewed native Git configuration key')
        if key in values and not key.endswith(b'.push'):
            raise RuntimeError('duplicate native Git configuration key')
        values[key] = value
        if key.endswith(b'.mirror') and value != b'true':
            raise RuntimeError('native Git mirror setting differs')
    if (values.get(b'core.bare') != b'true' or values.get(b'core.repositoryformatversion') != b'0' or
            values.get(b'core.filemode') not in (b'true', b'false')):
        raise RuntimeError('native Git bare repository format differs')


def references(raw):
    names = set()
    for record in raw.splitlines():
        fields = record.split(b'\0')
        if (len(fields) != 3 or not fields[0].startswith(b'refs/') or
                fields[0].startswith(b'refs/replace/') or fields[0] in names or
                not re.fullmatch(rb'[a-f0-9]{40}', fields[1]) or
                fields[2] not in (b'commit', b'tree', b'blob', b'tag')):
            raise RuntimeError('native Git reference format or replacement differs')
        names.add(fields[0])
    if not names:
        raise RuntimeError('native Git repository has no recovered references')
    return {'references': len(names), 'sha256': hashlib.sha256(raw).hexdigest()}


def mounts(scratch, volumes):
    return {**{'/recovered': str(scratch / 'copy')},
            **{name: str(scratch / ('volume-' + str(n))) for n, name in enumerate(volumes)}}


def arguments(scratch, volumes, run_id, args):
    result = ['create', '--label', LABEL + '=' + run_id, '--network=none', '--read-only', '--no-healthcheck',
              '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=1000:1000',
              '--workdir=/tmp', '--pids-limit=128', '--memory=1g', '--cpus=1',
              '--tmpfs=/tmp:' + TMPFS['/tmp']]
    for name, value in ENV.items():
        result.extend(['--env', name + '=' + value])
    for destination, source in mounts(scratch, volumes).items():
        result.extend(['--mount', 'type=bind,source=' + source + ',target=' + destination + ',readonly'])
    return [*result, '--entrypoint=/usr/bin/git', IMAGE, *PREFIX, *args]


def require_container(value, scratch, volumes, run_id, args, image_id):
    config, host = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000, 'Tmpfs': TMPFS}
    environment = dict(item.split('=', 1) for item in config.get('Env', []))
    actual_mounts = value['Mounts']
    if (config['Image'] != IMAGE or value['Image'] != image_id or config['User'] != '1000:1000' or
            config['Entrypoint'] != ['/usr/bin/git'] or config['Cmd'] != [*PREFIX, *args] or
            config.get('WorkingDir') != '/tmp' or config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Healthcheck', {}).get('Test') != ['NONE'] or
            any(environment.get(key) != item for key, item in ENV.items()) or
            any(key.startswith('GIT_') and key not in ENV for key in environment) or
            any(host.get(key) != item for key, item in expected.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(key) for key in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd')) or
            len(actual_mounts) != len(mounts(scratch, volumes)) or
            any(item.get('Type') != 'bind' or item['RW'] for item in actual_mounts) or
            {item['Destination']: item['Source'] for item in actual_mounts} != mounts(scratch, volumes)):
        raise RuntimeError('native Git copied-data isolation differs')


def operation(scratch, volumes, run_id, args, image_id):
    container = None
    try:
        container = common.docker(*arguments(scratch, volumes, run_id, args)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('native Git container identity missing')
        require_container(common.inspect(container), scratch, volumes, run_id, args, image_id)
        response = common.docker('start', '--attach', container, check=False)
        value = common.inspect(container)
        require_container(value, scratch, volumes, run_id, args, image_id)
        state = value['State']
        if (response.returncode or state['Running'] or state['ExitCode'] or state.get('OOMKilled') or
                response.stderr or ('fsck' in args and response.stdout)):
            output = response.stdout + response.stderr
            diagnostic = POINT / ('git-failure-' + run_id + '-' + uuid.uuid4().hex + '.log')
            descriptor = os.open(diagnostic, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'wb') as target:
                target.write(output)
                target.flush()
                os.fsync(target.fileno())
            raise RuntimeError('native Git check failed: ' + json.dumps({
                'exit': state['ExitCode'], 'transport': response.returncode, 'oom': state.get('OOMKilled'),
                'output_bytes': len(output), 'output_sha256': hashlib.sha256(output).hexdigest(),
                'protected_private_diagnostic': str(diagnostic)}))
        return response.stdout
    finally:
        if container:
            require_container(common.inspect(container), scratch, volumes, run_id, args, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned Git recovery container remains')


def restore(run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    value = retained.verify(POINT, CHECKSUM, 'gitea')
    roots = discover(value['tree'])
    retained.require_capacity(common.ROOT, value['tree'], 2)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned Git recovery already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-git-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'manifest_sha256': CHECKSUM, 'image': IMAGE, 'copies': []}
    try:
        common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                IMAGE not in image.get('RepoDigests', []) or
                not set(volumes) <= {'/data', '/var/lib/gitea', '/etc/gitea'}):
            raise RuntimeError('exact native Git image or declared volumes differ')
        retained.require_capacity(common.ROOT, value['tree'], 2)
        for number in range(2):
            work = scratch / str(number)
            work.mkdir(mode=0o700)
            retained.materialize(POINT, work / 'copy', value)
            for source in mounts(work, volumes).values():
                if source != str(work / 'copy'):
                    Path(source).mkdir(mode=0o755)
            run = lambda args: operation(work, volumes, run_id, args, image_id)
            version = run(['--version'])
            if not re.fullmatch(rb'git version [0-9]+\.[0-9]+\.[0-9]+(?:\.[A-Za-z0-9.-]+)?\n', version):
                raise RuntimeError('native Git version output differs')
            result['git_version'] = version.decode().strip()
            checks = {}
            for root in roots:
                location = '/recovered/' + root
                check_config(run(['config', '--no-includes', '--file', location + '/config', '--null', '--list']))
                run(['--git-dir=' + location, 'fsck', '--full', '--strict', '--no-dangling'])
                refs = references(run(['--git-dir=' + location, 'for-each-ref', '--sort=refname',
                                       '--format=%(refname)%00%(objectname)%00%(objecttype)']))
                checks[hashlib.sha256(root.encode()).hexdigest()] = {'strict_fsck_exit': 0, **refs}
            if retained.snapshot(work / 'copy')[0] != value['tree']:
                raise RuntimeError('native Git changed copied bytes or metadata')
            if number and result['copies'][0] != checks:
                raise RuntimeError('independent native Git reference fingerprints differ')
            result['copies'].append(checks)
        result.update(accepted=True, independent_restores=2, network='none', copied_data_read_only=True,
                      live_source_not_accessed=True, sql_auth_lfs_hooks_and_service_unqualified=True)
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
            raise RuntimeError('owned Git recovery container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused Git recovery image remains')
        retained.verify(POINT, CHECKSUM, 'gitea')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'protected_original_unchanged': True, 'allocated_bytes_removed': allocated}
        retained.files.write_json(POINT / ('git-native-restore-' + run_id + '.json'), result)
    return result
