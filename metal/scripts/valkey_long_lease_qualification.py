"""Prove the reviewed finite capture lease on six isolated synthetic nodes."""

import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time
import traceback

import valkey_cluster_qualification as protocol
import valkey_cohort_point as cohort
import valkey_write_pause_qualification as write_pause


recovery, common = protocol.recovery, protocol.common


def run(run_id, observer):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    def interrupted(_number, _frame):
        raise RuntimeError('owned finite lease qualification interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
        raise RuntimeError('another owned Valkey operation is active')
    before = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + '-finite-lease-', dir=common.ROOT))
    scratch.chmod(0o700)
    identity, image_id = None, None
    result = {'accepted': False, 'run_id': run_id, 'synthetic_only': True, 'lease_ms': cohort.LEASE_MS}
    try:
        data = scratch / 'data'
        data.mkdir(mode=0o700)
        os.chown(data, 1001, 1001)
        for node in range(6):
            path = data / ('node-' + str(node))
            path.mkdir(mode=0o700)
            os.chown(path, 1001, 1001)
        common.docker('pull', recovery.IMAGE)
        image = json.loads(common.docker('image', 'inspect', recovery.IMAGE).stdout)[0]
        image_id = image['Id']
        mount = recovery.image_mount(image, recovery.IMAGE)
        identity = common.docker('create', '--network=none', '--read-only', '--cap-drop=ALL', '--user=1001:1001',
            '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=256', '--cpus=1', '--memory=1g',
            '--log-driver=none', '--label=' + recovery.LABEL + '=' + run_id,
            '--mount=type=bind,source=' + str(data) + ',target=' + mount,
            '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/bin/sh', recovery.IMAGE,
            '-c', 'exec sleep 2147483647').stdout.decode().strip()
        recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
        common.docker('start', identity)
        state = common.inspect(identity)
        recovery.require_isolation(state, scratch, run_id, mount)
        namespace = ['nsenter', '--target', str(state['State']['Pid']), '--net', '--']
        links = json.loads(common.command([*namespace, 'ip', '-j', 'address']).stdout)
        routes = sum((json.loads(common.command([*namespace, 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
                      for family in ('-4', '-6')), [])
        common.require_network(links, routes)
        if common.command([*namespace, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('owned finite lease fixture can route to production')
        if b'v=8.1.3' not in common.docker('exec', identity, 'valkey-server', '--version').stdout:
            raise RuntimeError('native finite lease version differs')
        cluster = protocol.Cluster(identity, mount)
        for node in range(6):
            cluster.start(node)
            assert cluster.cli(node, 'CLUSTER', 'SET-CONFIG-EPOCH', node + 1) == b'OK'
        for node, (lower, upper) in protocol.SLOTS.items():
            assert cluster.cli(node, 'CLUSTER', 'ADDSLOTSRANGE', lower, upper) == b'OK'
        for node in range(1, 6):
            assert cluster.cli(node, 'CLUSTER', 'MEET', '127.0.0.1', 17000) == b'OK'
        protocol.poll(lambda: all(recovery.info(cluster.cli(n, 'CLUSTER', 'INFO')).get('cluster_known_nodes') == '6'
                                 for n in range(6)), 'finite lease membership did not converge')
        for replica, master in protocol.REPLICAS.items():
            assert cluster.cli(replica, 'CLUSTER', 'REPLICATE', cluster.cli(master, 'CLUSTER', 'MYID').decode()) == b'OK'
        protocol.poll(cluster.healthy, 'finite lease fixture is unhealthy')
        for master in protocol.SLOTS:
            keys = protocol.fixture_keys(master)
            assert cluster.cli(4, 'EVAL', protocol.WRITE, len(keys), *keys) == b'fixture-created'
        cluster.verify()
        result['native_write_pause'] = write_pause.qualify(namespace, observer,
            protocol.fixture_keys(0)[0] + ':long-lease-expiry', owner_lease_ms=cohort.LEASE_MS)
        cluster.verify()
        result.update(accepted=True, image=recovery.IMAGE, nodes=6, synthetic_keys=450,
                      complete_fixture_unchanged=True, network_none=True, production_unroutable=True)
    except Exception as error:
        result.update(failure_class=type(error).__name__,
            failure_frames=[{'function': f.name, 'line': f.lineno} for f in traceback.extract_tb(error.__traceback__)])
        if isinstance(error, RuntimeError):
            result['failure_reason'] = str(error)
    finally:
        if identity:
            recovery.require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker('rm', '-f', identity)
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file())
        shutil.rmtree(scratch)
        removed = 0
        if image_id and image_id not in before and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', image_id)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('owned finite lease image remains')
            removed = 1
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'allocated_bytes_removed': allocated,
            'new_images_removed': removed,
            'owned_containers_absent': not common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip()}
    recovery.protected.write_json(common.ROOT / ('valkey-finite-lease-' + run_id + '-' + str(time.time_ns()) + '.json'), result)
    return result
