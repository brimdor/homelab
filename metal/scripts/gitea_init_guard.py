"""Qualify the existing Gitea image's temporary recovery initialization hold."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import gitea_git_recovery as git_recovery
import gitea_postgres_startup_guard as postgres


common = git_recovery.common
IMAGE = git_recovery.IMAGE
LABEL = 'io.eaglepass.gitea-init-guard'
STATE = '/tmp/maintenance-103-gitea'
# Share the reviewed retained-state checks, with Gitea's existing UID and flock.
STARTUP = postgres.STARTUP.replace(postgres.STATE, STATE).replace('1001:', '1000:').replace(
    'flock --exclusive 9', 'flock -x 9').replace('exec "$@"', 'exit 0')
CLAIM = '''umask 077
state=/tmp/maintenance-103-gitea
[[ ! -L "$state" && $(stat -c '%u:%a' "$state") == 1000:700 ]]
for name in lock phase; do
    [[ -f "$state/$name" && ! -L "$state/$name" && $(stat -c '%u:%a:%h' "$state/$name") == 1000:600:1 ]]
done
exec 9>"$state/lock"
flock -xn 9
[[ $(cat "$state/phase") == waiting ]]
(set -o noclobber; printf '%s\\n' "$BASHPID" > "$state/claimed")
printf 'HOMELAB103:CLAIMED:%s\\n' "$$"
IFS= read -r _ || exit 0
exit 64
'''


def execute(container, *args, check=True):
    common.require_no_logging(container)
    return common.docker('exec', container, *args, check=check)


def require_container(container, scratch, volumes, run_id, image_id):
    value = common.inspect(container)
    config, host = value['Config'], value['HostConfig']
    expected_mounts = {'/tmp': str(scratch / 'temp'), **{
        name: str(scratch / ('volume-' + str(n))) for n, name in enumerate(volumes)}}
    expected_host = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                     'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                     'PidMode': '', 'IpcMode': 'private', 'UTSMode': '', 'UsernsMode': '',
                     'PidsLimit': 128, 'Memory': 268435456, 'NanoCpus': 1000000000,
                     'LogConfig': {'Type': 'none', 'Config': {}}}
    mounts = value['Mounts']
    if (config['Image'] != IMAGE or value['Image'] != image_id or config['User'] != '1000:1000' or
            config['Entrypoint'] != ['/bin/bash'] or config['Cmd'] != ['-ceu', STARTUP] or
            config.get('Labels', {}).get(LABEL) != run_id or
            config.get('Healthcheck', {}).get('Test') != ['NONE'] or
            any(host.get(key) != item for key, item in expected_host.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(key) for key in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd', 'Tmpfs')) or
            len(mounts) != len(expected_mounts) or
            any(m.get('Type') != 'bind' or m['RW'] != (m['Destination'] == '/tmp') for m in mounts) or
            {m['Destination']: m['Source'] for m in mounts} != expected_mounts):
        raise RuntimeError('native Gitea initialization isolation differs')
    return value


def wait_for(check, message):
    deadline = time.monotonic() + 65
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(0.05)


def operation(scratch, volumes, run_id, image_id, mode):
    container = None
    controller = None
    args = ['create', '--label', LABEL + '=' + run_id, '--network=none', '--read-only',
            '--no-healthcheck', '--log-driver=none', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--user=1000:1000', '--pids-limit=128',
            '--memory=256m', '--cpus=1', '--mount', 'type=bind,source=' + str(scratch / 'temp') + ',target=/tmp']
    for n, name in enumerate(volumes):
        args.extend(['--mount', 'type=bind,source=' + str(scratch / ('volume-' + str(n))) +
                     ',target=' + name + ',readonly'])
    try:
        container = common.docker(*args, '--entrypoint=/bin/bash', IMAGE, '-ceu', STARTUP).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('native Gitea initialization container identity missing')
        require_container(container, scratch, volumes, run_id, image_id)
        common.docker('start', container)
        phase = lambda: execute(container, '/bin/cat', STATE + '/phase', check=False).stdout.strip()
        wait_for(lambda: phase() == b'waiting', 'native Gitea initialization claim window missing')
        if mode != 'controller-absent':
            controller = subprocess.Popen(['docker', 'exec', '-i', container, '/bin/bash', '-ceu', CLAIM],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            match = re.fullmatch(rb'HOMELAB103:CLAIMED:([0-9]+)\n', controller.stdout.readline())
            if not match:
                raise RuntimeError('native Gitea initialization claim failed; raw output discarded')
            refused = execute(container, '/usr/bin/flock', '-xn', STATE + '/lock', '/bin/true', check=False)
            if refused.returncode != 1 or phase() != b'waiting':
                raise RuntimeError('native Gitea initialization concurrent hold failed')
            if mode == 'controller-killed':
                execute(container, '/bin/kill', '-KILL', match[1].decode())
            elif mode == 'unexpected-input':
                controller.stdin.write(b'run\n')
                controller.stdin.flush()
            output, errors = controller.communicate()
            expected = {'controller-eof': 0, 'controller-killed': 137, 'unexpected-input': 64}[mode]
            if controller.returncode != expected or output or errors:
                raise RuntimeError('native Gitea initialization controller disposition differs')
        wait_for(lambda: not common.inspect(container)['State']['Running'], 'native Gitea initialization remained held')
        value = require_container(container, scratch, volumes, run_id, image_id)
        if value['State']['ExitCode'] or value['State'].get('OOMKilled') or (scratch / 'temp/maintenance-103-gitea/phase').read_bytes() != b'normal\n':
            raise RuntimeError('native Gitea initialization fallback failed')
        # An actual container restart retains the same simulated emptyDir binding.
        common.docker('start', container)
        wait_for(lambda: not common.inspect(container)['State']['Running'], 'retained native Gitea initialization remained held')
        value = require_container(container, scratch, volumes, run_id, image_id)
        if value['State']['ExitCode'] or value['State'].get('OOMKilled'):
            raise RuntimeError('retained native Gitea initialization restart failed')
        return {'mode': mode, 'automatic_init_completion': True, 'actual_container_restart': True,
                'retained_emptydir_binding': True, 'actual_kubernetes_restart_qualified': False}
    finally:
        if controller and controller.poll() is None:
            controller.communicate()
        if container:
            require_container(container, scratch, volumes, run_id, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned Gitea initialization container remains')


def qualify(run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('native Gitea initialization qualification already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-init-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'image': IMAGE, 'attempts': [], 'production_mutated': False}
    try:
        common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or IMAGE not in image.get('RepoDigests', []) or
                not set(volumes) <= {'/data', '/var/lib/gitea', '/etc/gitea'}):
            raise RuntimeError('exact native Gitea initialization image differs')
        for number, mode in enumerate(('controller-absent', 'controller-eof', 'controller-killed', 'unexpected-input')):
            work = scratch / str(number)
            work.mkdir(mode=0o700)
            (work / 'temp').mkdir(mode=0o700)
            os.chown(work / 'temp', 1000, 1000)
            for n in range(len(volumes)):
                (work / ('volume-' + str(n))).mkdir(mode=0o755)
            result['attempts'].append(operation(work, volumes, run_id, image_id, mode))
        result['accepted'] = True
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
            raise RuntimeError('owned initialization container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused initialization image remains')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'allocated_bytes_removed': allocated}
        git_recovery.retained.files.write_json(common.ROOT / ('gitea-init-' + run_id + '.json'), result)
    return result
