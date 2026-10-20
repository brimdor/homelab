#!/usr/bin/env python3
"""Qualify native Ceph only in an owned disconnected synthetic container."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

import etcd_recovery as common


IMAGE = 'quay.io/ceph/ceph@sha256:09ee90f6f3e0c7b9954f71d214ee05e9bbaaaea3716b1dd619603283b829f8b8'
VOLUMES = {'/etc/ceph', '/var/lib/ceph', '/var/log/ceph', '/var/run/ceph', '/run/ceph'}
BLOCK_BYTES = 2 * 1024**3


def require_container(value, scratch, run_id, volumes):
    host = value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                'IpcMode': 'private', 'PidMode': '', 'UTSMode': '', 'UsernsMode': '',
                'Memory': 4 * 1024**3, 'NanoCpus': 2000000000, 'PidsLimit': 512,
                'Tmpfs': {'/run': 'rw,nosuid,nodev', '/tmp': 'rw,nosuid,nodev'}}
    labels = value['Config'].get('Labels', {})
    if (not set(volumes) <= VOLUMES or value['Config']['Image'] != IMAGE or
            labels.get('io.eaglepass.maintenance') != '103' or
            labels.get('io.eaglepass.recovery-run') != run_id or
            value['Config']['Hostname'] != 'ceph103-' + run_id or
            any(host.get(k) != v for k, v in expected.items()) or
            any(host.get(k) for k in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings')) or
            host.get('RestartPolicy', {}).get('Name') != 'no'):
        raise RuntimeError('synthetic Ceph container isolation changed')
    mounts = value.get('Mounts', [])
    expected_mounts = {(str(scratch), '/work', True)} | {
        (str(scratch / ('volume-' + str(n))), path, True) for n, path in enumerate(sorted(volumes))}
    if (len(mounts) != len(expected_mounts) or any(m.get('Type') != 'bind' for m in mounts) or
            {(m.get('Source'), m.get('Destination'), m.get('RW')) for m in mounts} != expected_mounts):
        raise RuntimeError('synthetic Ceph has an unexpected mount')


def block_identity(root):
    path = root / 'block'
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or
            metadata.st_size != BLOCK_BYTES or any(p.is_symlink() for p in (root, *root.parents))):
        raise RuntimeError('synthetic BlueStore block identity changed')
    return {'device': metadata.st_dev, 'inode': metadata.st_ino, 'bytes': metadata.st_size}


def sanitized(data):
    text = data.decode(errors='replace')[-2000:]
    return re.sub(r'[A-Za-z0-9+/]{28,}={0,2}', '[redacted]', text)


class Runtime:
    def __init__(self, root, run_id):
        if (root != Path('/work') or os.geteuid() != 0 or socket.gethostname() != 'ceph103-' + run_id or
                root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o700 or
                not re.search(r'(?m)^CapEff:\s+0+$', Path('/proc/self/status').read_text())):
            raise RuntimeError('internal runtime requires the exact capability-free fixture')
        self.root = root
        self.children = {}
        self.stage = 'initialize'
        self.conf = ['-c', str(root / 'ceph.conf')]
        self.admin = ['ceph', *self.conf, '-n', 'client.admin', '-k', str(root / 'admin.keyring')]

    def command(self, arguments, *, data=None, check=True):
        result = subprocess.run(arguments, input=data, capture_output=True, timeout=30)
        if check and result.returncode:
            raise RuntimeError(self.stage + ': ' + arguments[0] + ' exit ' + str(result.returncode) +
                               ': ' + sanitized(result.stderr))
        return result

    def ceph(self, *args):
        return self.command([*self.admin, *args]).stdout

    def start(self, kind, identity):
        log = (self.root / (kind + '.log')).open('ab')
        try:
            child = subprocess.Popen(['ceph-' + kind, *self.conf, '-i', identity, '-f',
                                      '--setuser=root', '--setgroup=root'], stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        self.children[kind] = child

    def running(self):
        for name, child in self.children.items():
            if child.poll() is not None:
                raise RuntimeError(self.stage + ': owned ' + name + ' exited ' + str(child.returncode) +
                                   ': ' + sanitized((self.root / (name + '.log')).read_bytes()))

    def stop(self, name):
        child = self.children.pop(name)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()

    def status(self):
        while True:
            self.running()
            result = self.command([*self.admin, 'status', '-f', 'json'], check=False)
            if result.returncode == 0:
                return json.loads(result.stdout)
            time.sleep(2)

    def steady(self):
        while True:
            value = self.status()
            osds = value.get('osdmap', {})
            pgs = value.get('pgmap', {}).get('pgs_by_state', [])
            if (value.get('mgrmap', {}).get('available') and osds.get('num_up_osds') == 1 and
                    osds.get('num_in_osds') == 1 and pgs and
                    all(p['state_name'] == 'active+clean' for p in pgs)):
                checks = value['health'].get('checks', {})
                if set(checks) - {'POOL_NO_REDUNDANCY'}:
                    raise RuntimeError('unexpected synthetic health checks: ' + ','.join(sorted(checks)))
                return {'status': value['health']['status'], 'checks': sorted(checks)}
            time.sleep(2)

    def key(self, name, key_type):
        path = self.root / (name + '.keyring')
        raw = self.ceph('auth', 'get-or-create', 'client.' + name, 'mon', 'allow r',
                        'osd', 'allow rw pool=qualification', '--key-type=' + key_type)
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def client(self, name, *args):
        return self.command(['rados', *self.conf, '-n', 'client.' + name,
                             '-k', str(self.root / (name + '.keyring')), '-p', 'qualification', *args]).stdout

    def run(self):
        if not self.command(['ceph', '--version']).stdout.startswith(b'ceph version 20.2.4 '):
            raise RuntimeError('candidate native version differs')
        self.stage = 'synthetic bootstrap'
        fsid = str(uuid.uuid4())
        conf = f'''[global]
fsid = {fsid}
mon host = [v2:127.0.0.1:13300,v1:127.0.0.1:13301]
auth cluster required = cephx
auth service required = cephx
auth client required = cephx
auth allow insecure global id reclaim = false
public addr = 127.0.0.1
cluster addr = 127.0.0.1
admin socket = /work/$name.asok
log file = /work/$name.native.log
log to stderr = true
crushtool = /usr/bin/crushtool
osd pool default size = 1
osd pool default min size = 1
mon allow pool size one = true
osd crush chooseleaf type = 0
[mon.a]
mon data = /work/mon
keyring = /work/mon.keyring
[mgr.a]
mgr data = /work/mgr
keyring = /work/mgr/keyring
[osd.0]
osd data = /work/osd
keyring = /work/osd/keyring
osd objectstore = bluestore
bluestore block path = /work/block
bluestore block create = false
bluestore block db create = false
bluestore block wal create = false
osd memory target = 536870912
osd op num shards = 2
osd op num threads per shard = 1
'''
        (self.root / 'ceph.conf').write_text(conf)
        for name in ('mon', 'mgr', 'osd'):
            (self.root / name).mkdir(mode=0o700)
        for name, entity, caps in (
            ('mon.keyring', 'mon.', ['--cap', 'mon', 'allow *']),
            ('admin.keyring', 'client.admin', ['--cap', 'mon', 'allow *', '--cap', 'osd', 'allow *',
                                             '--cap', 'mgr', 'allow *', '--cap', 'mds', 'allow *']),
        ):
            self.command(['ceph-authtool', str(self.root / name), '--create-keyring', '--gen-key',
                          '--key-type=aes256k', '-n', entity, *caps])
        self.command(['ceph-authtool', str(self.root / 'mon.keyring'), '--import-keyring',
                      str(self.root / 'admin.keyring')])
        self.command(['monmaptool', '--create', '--fsid', fsid, '--addv', 'a',
                      '[v2:127.0.0.1:13300,v1:127.0.0.1:13301]', str(self.root / 'monmap')])
        self.command(['ceph-mon', *self.conf, '-i', 'a', '--mkfs', '--monmap', str(self.root / 'monmap'),
                      '--keyring', str(self.root / 'mon.keyring'), '--setuser=root', '--setgroup=root'])
        self.start('mon', 'a')
        self.status()
        mgr = self.ceph('auth', 'get-or-create', 'mgr.a', 'mon', 'allow profile mgr',
                       'osd', 'allow *', 'mds', 'allow *', '--key-type=aes256k')
        (self.root / 'mgr/keyring').write_bytes(mgr)
        self.start('mgr', 'a')
        self.command(['ceph-authtool', str(self.root / 'osd/keyring'), '--create-keyring', '--gen-key',
                      '--key-type=aes256k', '-n', 'osd.0', '--cap', 'mon', 'allow profile osd',
                      '--cap', 'osd', 'allow *', '--cap', 'mgr', 'allow profile osd'])
        secret = self.command(['ceph-authtool', str(self.root / 'osd/keyring'), '-n', 'osd.0', '-p']).stdout.strip().decode()
        osd_uuid = str(uuid.uuid4())
        new = self.root / 'osd-new.json'
        new.write_text(json.dumps({'cephx_secret': secret}))
        new.chmod(0o600)
        if self.ceph('osd', 'new', osd_uuid, '-i', str(new)).strip() != b'0':
            raise RuntimeError('synthetic OSD id differs')
        new.unlink()
        with (self.root / 'block').open('xb') as output:
            output.truncate(BLOCK_BYTES)
        before = block_identity(self.root)
        self.command(['ceph-osd', *self.conf, '-i', '0', '--mkfs', '--osd-uuid', osd_uuid,
                      '--setuser=root', '--setgroup=root'])
        self.ceph('osd', 'crush', 'add', 'osd.0', '1.0', 'root=default', 'host=qualification')
        self.start('osd', '0')
        self.ceph('osd', 'pool', 'create', 'qualification', '8')
        self.ceph('osd', 'pool', 'application', 'enable', 'qualification', 'rados')
        self.stage = 'ordinary client I/O'
        health = self.steady()
        payload = b'maintenance103 synthetic Ceph native qualification\n' * 127
        (self.root / 'payload').write_bytes(payload)
        self.key('ordinary', 'aes256k')
        self.client('ordinary', 'put', 'fixture', '/work/payload')
        def read(name):
            self.client(name, 'get', 'fixture', '/work/readback')
            if (self.root / 'readback').read_bytes() != payload:
                raise RuntimeError('native synthetic payload differs')
        read('ordinary')
        self.stage = 'same-block OSD restart'
        self.stop('osd')
        self.start('osd', '0')
        self.steady()
        if block_identity(self.root) != before or (self.root / 'osd/fsid').read_text().strip() != osd_uuid:
            raise RuntimeError('OSD restart changed synthetic data identity')
        read('ordinary')
        self.stage = 'explicit AES256K client rotation'
        old = (self.root / 'ordinary.keyring').read_bytes()
        retired = self.root / 'retired.keyring'
        retired.write_bytes(old)
        retired.chmod(0o600)
        self.ceph('auth', 'rotate', 'client.ordinary', '--key-type=aes256k')
        self.key('ordinary', 'aes256k')
        if (self.root / 'ordinary.keyring').read_bytes() == old:
            raise RuntimeError('synthetic client key did not rotate')
        denied = self.command(['rados', *self.conf, '-n', 'client.ordinary', '-k', str(retired),
                               '-p', 'qualification', 'stat', 'fixture'], check=False)
        if denied.returncode == 0 or not any(message in denied.stderr.lower() for message in
                                            (b'permission denied', b'operation not permitted')):
            raise RuntimeError('retired synthetic key lacks explicit fresh-authentication refusal')
        read('ordinary')
        self.stage = 'AES256K ordinary client'
        self.key('modern', 'aes256k')
        read('modern')
        final_health = self.steady()
        return {'accepted': True, 'version': '20.2.4', 'synthetic_fsid': fsid,
                'synthetic_osd_uuid': osd_uuid, 'block_identity_preserved': True,
                'payload_sha256': hashlib.sha256(payload).hexdigest(), 'payload_bytes': len(payload),
                'aes256k_client_io': True, 'aes256k_client_rotation_io': True,
                'legacy_aes_client_compatibility_unqualified': True,
                'retired_client_key_fresh_authentication_refused': True,
                'initial_health': health, 'final_health': final_health,
                'production_data_or_credentials': False, 'rook_csi_core_rotation_unqualified': True}


def qualify(run_id, source, common_source):
    common.require_host('totodile')
    common.private_root()
    if common.docker('ps', '--all', '--quiet', '--filter=label=io.eaglepass.maintenance=103').stdout.strip():
        raise RuntimeError('another owned fixture is active; leave it alone')
    if shutil.disk_usage(common.ROOT).free <= BLOCK_BYTES:
        raise RuntimeError('insufficient actual capacity for the synthetic block')
    scratch = Path(tempfile.mkdtemp(prefix=run_id + '-ceph-', dir=common.ROOT))
    scratch.chmod(0o700)
    before_images = set(common.docker('image', 'ls', '--no-trunc', '-q').stdout.decode().split())
    container = image_id = None
    volumes = []
    result = {'accepted': False, 'run_id': run_id, 'image': IMAGE}
    def cancel(_number, _frame):
        raise InterruptedError('owned Ceph qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = image['Id']
        capacity = shutil.disk_usage(scratch)
        if capacity.free / capacity.total <= 0.30:
            raise RuntimeError('synthetic monitor filesystem crosses its native 30-percent warning threshold')
        volumes = sorted(image['Config'].get('Volumes') or {})
        if image['Architecture'] != 'amd64' or image['Os'] != 'linux' or not set(volumes) <= VOLUMES:
            raise RuntimeError('candidate platform or declared volumes changed')
        for n, _ in enumerate(volumes):
            (scratch / ('volume-' + str(n))).mkdir(mode=0o700)
        (scratch / 'ceph_runtime_qualification.py').write_text(source)
        (scratch / 'etcd_recovery.py').write_text(common_source)
        args = ['create', '--network=none', '--read-only', '--cap-drop=ALL',
                '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=512',
                '--cpus=2', '--memory=4g', '--hostname=ceph103-' + run_id,
                '--label=io.eaglepass.maintenance=103', '--label=io.eaglepass.recovery-run=' + run_id,
                '--mount=type=bind,source=' + str(scratch) + ',target=/work',
                '--tmpfs=/run:rw,nosuid,nodev', '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/bin/sh']
        for n, path in enumerate(volumes):
            args.append('--mount=type=bind,source=' + str(scratch / ('volume-' + str(n))) + ',target=' + path)
        container = common.docker(*args, IMAGE, '-c', 'exec sleep 2147483647').stdout.decode().strip()
        if not re.fullmatch(r'[a-f0-9]{64}', container):
            raise RuntimeError('invalid owned container identity')
        require_container(common.inspect(container), scratch, run_id, volumes)
        common.docker('start', container)
        state = common.inspect(container)
        require_container(state, scratch, run_id, volumes)
        pid = str(state['State']['Pid'])
        common.require_network(json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'link']).stdout),
                               json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'route']).stdout))
        if common.command(['nsenter', '-t', pid, '-n', 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
            raise RuntimeError('synthetic Ceph has a production route')
        output = common.docker('exec', container, 'python3', '-B', '/work/ceph_runtime_qualification.py',
                               '--internal-runtime', '--run-id', run_id, check=False)
        result.update(json.loads(output.stdout))
        if output.returncode or not result.get('accepted'):
            raise RuntimeError('native Ceph runtime refused acceptance')
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id, volumes)
            common.docker('rm', '--force', '--volumes', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned Ceph container remains')
        if image_id and image_id not in before_images:
            if common.docker('ps', '--all', '--quiet', '--filter=ancestor=' + image_id).stdout.strip():
                raise RuntimeError('new image has another consumer; retained')
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', IMAGE, check=False).returncode == 0:
                raise RuntimeError('new unused Ceph image remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError('owned synthetic Ceph data remains')
        result.update(owned_container_absent=True, scratch_removed=True, allocated_bytes_removed=allocated)
        print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=common.run_identifier, required=True)
    parser.add_argument('--internal-runtime', action='store_true')
    args = parser.parse_args()
    if not args.internal_runtime:
        qualify(args.run_id, Path(__file__).read_text(), Path(common.__file__).read_text())
        return
    runtime = Runtime(Path('/work'), args.run_id)
    def cancel(_number, _frame):
        raise InterruptedError('owned native Ceph runtime cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = runtime.run()
    except Exception as error:
        result = {'accepted': False, 'stage': runtime.stage, 'error': str(error)}
    finally:
        for name in list(reversed(runtime.children)):
            runtime.stop(name)
    print(json.dumps(result), flush=True)
    if not result['accepted']:
        sys.exit(1)


if __name__ == '__main__':
    main()
