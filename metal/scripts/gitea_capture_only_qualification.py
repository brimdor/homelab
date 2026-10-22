"""Exercise capture-only native leases using empty, disconnected owned data."""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

import gitea_postgres_startup_guard as guard


recovery, common = guard.recovery, guard.recovery.common


def operation(work, volumes, run_id, image_id, mode):
    container = starter = controller = None
    try:
        container = common.docker(*recovery.arguments(work, volumes, run_id)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('capture-only synthetic container identity differs')
        recovery.require_container(common.inspect(container), work, volumes, run_id, image_id)
        common.docker('start', container)
        value = common.inspect(container)
        recovery.require_container(value, work, volumes, run_id, image_id)
        net = ['nsenter', '--target', str(value['State']['Pid']), '--net', '--']
        common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
            sum((json.loads(common.command([*net, 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
                 for family in ('-4', '-6')), []))
        if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('capture-only synthetic container can route to production')
        recovery.execute(container, '/bin/chmod', '2700', '/opt/bitnami/postgresql/tmp')
        starter = subprocess.Popen(['docker', 'exec', container, '/bin/bash', '-ceu', guard.STARTUP,
                                    'capture-only-synthetic-startup', '/bin/true'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        guard.wait_for(lambda: guard.phase(container) == b'waiting', 'capture-only native claim window missing')
        controller = subprocess.Popen(['docker', 'exec', '-i', container, '/bin/bash', '-ceu', guard.CAPTURE_CLAIM],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        match = re.fullmatch(rb'HOMELAB103:CLAIMED:([0-9]+)\n', controller.stdout.readline())
        if not match:
            raise RuntimeError('capture-only native claim handshake differs; output withheld')
        if (guard.phase(container) != b'waiting' or starter.poll() is not None or
                recovery.execute(container, '/usr/bin/flock', '--exclusive', '--nonblock',
                                 guard.STATE + '/lock', '/bin/true', allow_error=True).returncode != 1):
            raise RuntimeError('capture-only native lease does not exclude ordinary startup')
        if mode == 'controller-killed':
            recovery.execute(container, '/bin/kill', '-KILL', match[1].decode())
        elif mode == 'unexpected-input':
            controller.stdin.write(b'run\nSELECT 1;\n')
            controller.stdin.flush()
        output, errors = controller.communicate(timeout=20)
        expected = {'controller-eof': 0, 'controller-killed': 137, 'unexpected-input': 64}[mode]
        if controller.returncode != expected or output or errors:
            raise RuntimeError('capture-only native controller disposition differs; output withheld')
        output, errors = starter.communicate(timeout=20)
        if starter.returncode or output or errors or guard.phase(container) != b'normal':
            raise RuntimeError('capture-only native lease failed automatic startup release')
        recovery.execute(container, '/usr/bin/test', '!', '-e', guard.STATE + '/native-child')
        if sorted(p.name for p in (work / 'copy').iterdir()) != ['sentinel'] or (work / 'copy/sentinel').read_bytes() != b'unchanged\n':
            raise RuntimeError('capture-only synthetic data changed')
        return {'mode': mode, 'automatic_release': True, 'concurrent_startup_excluded': True,
                'sql_dispatch_absent': True, 'synthetic_data_unchanged': True}
    finally:
        for child in (controller, starter):
            if child:
                if child.poll() is None:
                    try:
                        child.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream and not stream.closed:
                        stream.close()
        if container:
            recovery.require_container(common.inspect(container), work, volumes, run_id, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned capture-only synthetic container remains')


def qualify(run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
        raise RuntimeError('another owned PostgreSQL qualification is active')
    before = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-capture-only-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'attempts': [], 'production_mutated': False,
              'native_database_startup_qualified_by_this_drill': False}
    previous_handlers = {}
    def interrupted(_number, _frame):
        raise RuntimeError('owned capture-only qualification interrupted')
    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_handlers[number] = signal.signal(number, interrupted)
        common.docker('pull', recovery.control.IMAGE)
        image = json.loads(common.docker('image', 'inspect', recovery.control.IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {recovery.control.IMAGE, recovery.control.IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', [])) or
                set(volumes) != {'/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d'}):
            raise RuntimeError('capture-only native PostgreSQL image differs')
        for number, mode in enumerate(('controller-eof', 'unexpected-input', 'controller-killed')):
            work = scratch / str(number)
            work.mkdir(mode=0o700)
            for source in recovery.mounts(work, volumes).values():
                Path(source).mkdir(mode=0o700)
                os.chown(source, 1001, 1001)
            (work / 'copy/sentinel').write_bytes(b'unchanged\n')
            result['attempts'].append(operation(work, volumes, run_id, image_id, mode))
        result['accepted'] = True
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
            raise RuntimeError('owned capture-only container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in before and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', recovery.control.IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused capture-only image remains')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'allocated_bytes_removed': allocated}
        recovery.retained.files.write_json(common.ROOT / ('gitea-capture-only-' + run_id + '.json'), result)
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
    return result
