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


def replica_state(value, rows, active, fsid):
    if (active not in ({0, 1, 2}, {0, 1}, {0, 2}, {1, 2}) or
            value.get('fsid') != fsid or len(rows) != 3 or
            {row['osd'] for row in rows} != {0, 1, 2}):
        raise RuntimeError('replicated synthetic cluster inventory changed')
    pgs = value.get('pgmap', {}).get('pgs_by_state', [])
    if (any((row['up'], row['in']) != ((1, 1) if row['osd'] in active else (0, 0)) for row in rows) or
            not value.get('mgrmap', {}).get('available') or not pgs or
            any(row['state_name'] != 'active+clean' for row in pgs)):
        return False
    if value['health']['status'] != 'HEALTH_OK' or value['health'].get('checks'):
        raise RuntimeError('replicated steady state has health findings')
    return True


def replica_placement(mapping, name, active):
    acting = mapping.get('acting')
    if (mapping.get('pool') != 'qualification' or mapping.get('objname') != name or
            not isinstance(acting, list) or len(acting) != 2 or len(set(acting)) != 2 or
            not set(acting) <= active or mapping.get('up') != acting):
        raise RuntimeError('replicated object placement differs')
    return set(acting)


def replica_health_diagnostic(value, pools):
    health = value['health']
    codes = sorted(health.get('checks', {}))
    if (health['status'] not in ('HEALTH_OK', 'HEALTH_WARN', 'HEALTH_ERR') or len(codes) > 64 or
            any(not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', code) for code in codes) or
            len(pools) > 8):
        raise RuntimeError('synthetic health diagnostic shape changed')
    policies = []
    for pool in pools:
        if (not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', pool['pool_name']) or
                any(type(pool[key]) is not int or pool[key] < 0 for key in ('pool_id', 'size', 'min_size'))):
            raise RuntimeError('synthetic pool diagnostic shape changed')
        policies.append({key: pool[key] for key in ('pool_name', 'pool_id', 'size', 'min_size')})
    return {'health_status': health['status'], 'health_codes': codes, 'pool_policies': policies}


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

    def start(self, kind, identity, *, env=None):
        name = kind if kind != 'osd' or identity == '0' else 'osd.' + identity
        if name in self.children:
            raise RuntimeError('owned native child already exists')
        log = (self.root / (name + '.log')).open('ab')
        try:
            child = subprocess.Popen(['ceph-' + kind, *self.conf, '-i', identity, '-f',
                                      '--setuser=root', '--setgroup=root'], stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True, env=env)
        finally:
            log.close()
        self.children[name] = child

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
            if (value.get('mgrmap', {}).get('available') and osds.get('num_up_osds') == self.expected_osds and
                    osds.get('num_in_osds') == self.expected_osds and pgs and
                    all(p['state_name'] == 'active+clean' for p in pgs)):
                checks = value['health'].get('checks', {})
                allowed = {'POOL_NO_REDUNDANCY'} if self.expected_osds == 1 else set()
                if set(checks) - allowed or (self.expected_osds == 3 and value['health']['status'] != 'HEALTH_OK'):
                    raise RuntimeError('unexpected synthetic health checks: ' + ','.join(sorted(checks)))
                if self.expected_osds == 3:
                    self.replica_diagnostic = replica_health_diagnostic(
                        value, json.loads(self.ceph('osd', 'pool', 'ls', 'detail', '-f', 'json')))
                    if any((pool['size'], pool['min_size']) != (2, 2)
                           for pool in self.replica_diagnostic['pool_policies']):
                        raise RuntimeError('replicated bootstrap pool policy differs')
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

    def rotate_keyring(self, entity, original, destination):
        old = self.command(['ceph-authtool', str(original), '-n', entity, '-p']).stdout.strip()
        raw = self.ceph('auth', 'rotate', entity, '--key-type=aes256k')
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        new = self.command(['ceph-authtool', str(destination), '-n', entity, '-p']).stdout.strip()
        if not old or not new or old == new:
            raise RuntimeError('synthetic ' + entity + ' key did not rotate')

    def rotate_core(self):
        self.stage = 'AES256K monitor rotation'
        self.rotate_keyring('mon.', self.root / 'mon.keyring', self.root / 'rotated-mon.keyring')
        self.stop('mon')
        self.start('mon', 'a')
        self.steady()
        for kind, identity in (('mgr', 'a'), ('osd', '0')):
            self.stage = 'AES256K ' + kind + ' rotation'
            self.stop(kind)
            if kind == 'osd':
                self.ceph('osd', 'down', identity)
            keyring = self.root / kind / 'keyring'
            self.rotate_keyring(kind + '.' + identity, keyring, keyring)
            self.start(kind, identity)
            self.steady()
        self.stage = 'AES256K administrator rotation'
        emergency = self.ceph('auth', 'get-or-create', 'client.emergency', 'mon', 'allow *',
                              '--key-type=aes256k')
        path = self.root / 'emergency.keyring'
        path.write_bytes(emergency)
        path.chmod(0o600)
        self.command(['ceph', *self.conf, '-n', 'client.emergency', '-k', str(path), 'status'])
        retired = self.root / 'retired-admin.keyring'
        retired.write_bytes((self.root / 'admin.keyring').read_bytes())
        retired.chmod(0o600)
        self.rotate_keyring('client.admin', self.root / 'admin.keyring', self.root / 'admin.keyring')
        self.status()
        denied = self.command(['ceph', *self.conf, '-n', 'client.admin', '-k', str(retired),
                               'status'], check=False)
        if denied.returncode == 0 or not any(message in denied.stderr.lower() for message in
                                            (b'permission denied', b'operation not permitted')):
            raise RuntimeError('retired synthetic admin key lacks explicit authentication refusal')

    def bootstrap_replicas(self, original_uuid, original_block):
        """Create extra owned OSDs before any qualification I/O."""
        self.stage = 'three synthetic OSD bootstrap'
        identities = {0: (self.root, self.root / 'osd', original_uuid, original_block)}
        for number in (1, 2):
            root = self.root / ('osd' + str(number))
            root.mkdir(mode=0o700)
            block_root = self.root / ('block-store' + str(number))
            block_root.mkdir(mode=0o700)
            with (block_root / 'block').open('xb') as output:
                output.truncate(BLOCK_BYTES)
            before = block_identity(block_root)
            with (self.root / 'ceph.conf').open('a') as output:
                output.write(f'\n[osd.{number}]\nosd data = {root}\nkeyring = {root}/keyring\n'
                             f'osd objectstore = bluestore\nbluestore block path = {block_root}/block\n'
                             'bluestore block create = false\nbluestore block db create = false\n'
                             'bluestore block wal create = false\nosd memory target = 536870912\n'
                             'osd op num shards = 2\nosd op num threads per shard = 1\n')
            entity = 'osd.' + str(number)
            self.command(['ceph-authtool', str(root / 'keyring'), '--create-keyring', '--gen-key',
                          '--key-type=aes256k', '-n', entity, '--cap', 'mon', 'allow profile osd',
                          '--cap', 'osd', 'allow *', '--cap', 'mgr', 'allow profile osd'])
            (root / 'keyring').chmod(0o600)
            secret = self.command(['ceph-authtool', str(root / 'keyring'), '-n', entity, '-p']).stdout.strip().decode()
            osd_uuid = str(uuid.uuid4())
            new = root / 'new.json'
            new.write_text(json.dumps({'cephx_secret': secret}))
            new.chmod(0o600)
            if self.ceph('osd', 'new', osd_uuid, '-i', str(new)).strip() != str(number).encode():
                raise RuntimeError('additional synthetic OSD id differs')
            new.unlink()
            self.command(['ceph-osd', *self.conf, '-i', str(number), '--mkfs', '--osd-uuid', osd_uuid,
                          '--setuser=root', '--setgroup=root'])
            self.ceph('osd', 'crush', 'add', entity, '1.0', 'root=default', 'host=qualification')
            self.start('osd', str(number))
            identities[number] = (block_root, root, osd_uuid, before)
        return identities

    def replicated(self, fsid, identities):
        """Exercise synthetic replica-two evacuation/rejoin, never host failure."""
        self.stage = 'replicated initial convergence'
        payloads = {f'replica-{number:03d}': hashlib.sha256(str(number).encode()).digest() * 512
                    for number in range(64)}

        def verify_identity():
            for root, data, osd_uuid, before in identities.values():
                if block_identity(root) != before or (data / 'fsid').read_text().strip() != osd_uuid:
                    raise RuntimeError('replicated synthetic block or OSD identity changed')

        def converge(active):
            while True:
                value = self.status()
                rows = json.loads(self.ceph('osd', 'dump', '-f', 'json'))['osds']
                self.replica_diagnostic = replica_health_diagnostic(
                    value, json.loads(self.ceph('osd', 'pool', 'ls', 'detail', '-f', 'json')))
                if replica_state(value, rows, active, fsid):
                    pool = json.loads(self.ceph('osd', 'pool', 'get', 'qualification', 'all', '-f', 'json'))
                    if pool.get('size') != 2 or pool.get('min_size') != 2:
                        raise RuntimeError('replicated pool policy differs')
                    verify_identity()
                    return {'health': value['health']['status'], 'active_osds': sorted(active),
                            'size': 2, 'min_size': 2}
                time.sleep(2)

        def verify_objects(active):
            used = set()
            for name, payload in payloads.items():
                self.client('ordinary', 'get', name, '/work/readback')
                if (self.root / 'readback').read_bytes() != payload:
                    raise RuntimeError('replicated synthetic object bytes differ')
                mapping = json.loads(self.ceph('osd', 'map', 'qualification', name, '-f', 'json'))
                used.update(replica_placement(mapping, name, active))
            if used != active:
                raise RuntimeError('synthetic objects do not cover every active OSD')

        stages = [converge({0, 1, 2})]
        for name, payload in payloads.items():
            (self.root / 'replica-payload').write_bytes(payload)
            self.client('ordinary', 'put', name, '/work/replica-payload')
        verify_objects({0, 1, 2})
        for number in (0, 1, 2):
            self.stage = 'synthetic OSD evacuation ' + str(number)
            self.stop('osd' if number == 0 else 'osd.' + str(number))
            self.ceph('osd', 'down', str(number))
            self.ceph('osd', 'out', str(number))
            active = {0, 1, 2} - {number}
            stages.append({'removed_osd': number, **converge(active)})
            verify_objects(active)
            self.stage = 'same-block synthetic OSD rejoin ' + str(number)
            self.start('osd', str(number))
            self.ceph('osd', 'in', str(number))
            stages.append({'returned_osd': number, **converge({0, 1, 2})})
            verify_objects({0, 1, 2})
        verify_identity()
        return {'accepted': True, 'objects': len(payloads), 'bytes_per_object': 16384,
                'manifest_sha256': hashlib.sha256(common.canonical({
                    name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()})).hexdigest(),
                'stages': stages, 'same_block_identities': True,
                'host_failure_or_continuous_degraded_io_qualified': False}

    def class_configuration(self):
        return ''

    def run(self, replicated=False):
        if not self.command(['ceph', '--version']).stdout.startswith(b'ceph version 20.2.4 '):
            raise RuntimeError('candidate native version differs')
        self.stage = 'synthetic bootstrap'
        self.expected_osds = 3 if replicated else 1
        copies = 2 if replicated else 1
        fsid = str(uuid.uuid4())
        conf = f'''[global]
{self.class_configuration()}fsid = {fsid}
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
osd pool default size = {copies}
osd pool default min size = {copies}
mon allow pool size one = {'false' if replicated else 'true'}
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
        identities = self.bootstrap_replicas(osd_uuid, before) if replicated else None
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
        self.rotate_core()
        if block_identity(self.root) != before or (self.root / 'osd/fsid').read_text().strip() != osd_uuid:
            raise RuntimeError('core rotation changed synthetic data identity')
        read('ordinary')
        read('modern')
        final_health = self.steady()
        replication = self.replicated(fsid, identities) if replicated else None
        return {'accepted': True, 'version': '20.2.4', 'synthetic_fsid': fsid,
                'synthetic_osd_uuid': osd_uuid, 'block_identity_preserved': True,
                'payload_sha256': hashlib.sha256(payload).hexdigest(), 'payload_bytes': len(payload),
                'aes256k_client_io': True, 'aes256k_client_rotation_io': True,
                'legacy_aes_client_compatibility_unqualified': True,
                'retired_client_key_fresh_authentication_refused': True,
                'native_aes256k_core_and_admin_rotation_io': True,
                'retired_admin_key_fresh_authentication_refused': True,
                'legacy_service_ticket_transition_unqualified': True,
                'initial_health': health, 'single_osd_final_health': None if replicated else final_health,
                'bootstrap_osds': self.expected_osds, 'bootstrap_pool_size': copies,
                'final_health': {'status': 'HEALTH_OK', 'checks': []} if replication else final_health,
                'production_data_or_credentials': False, 'rook_csi_core_rotation_unqualified': True,
                'replica_two_evacuation_rejoin': replication}


def qualify(run_id, source, common_source, replicated=False):
    common.require_host('totodile')
    common.private_root()
    if common.docker('ps', '--all', '--quiet', '--filter=label=io.eaglepass.maintenance=103').stdout.strip():
        raise RuntimeError('another owned fixture is active; leave it alone')
    if shutil.disk_usage(common.ROOT).free <= BLOCK_BYTES * (3 if replicated else 1):
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
        extra = ['--replicated'] if replicated else []
        output = common.docker('exec', container, 'python3', '-B', '/work/ceph_runtime_qualification.py',
                               '--internal-runtime', '--run-id', run_id, *extra, check=False)
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
    parser.add_argument('--replicated', action='store_true')
    args = parser.parse_args()
    if not args.internal_runtime:
        qualify(args.run_id, Path(__file__).read_text(), Path(common.__file__).read_text(), args.replicated)
        return
    runtime = Runtime(Path('/work'), args.run_id)
    def cancel(_number, _frame):
        raise InterruptedError('owned native Ceph runtime cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = runtime.run(args.replicated)
    except Exception as error:
        result = {'accepted': False, 'stage': runtime.stage, 'error': str(error)}
        if hasattr(runtime, 'replica_diagnostic'):
            result['replica_diagnostic'] = runtime.replica_diagnostic
    finally:
        for name in list(reversed(runtime.children)):
            runtime.stop(name)
    print(json.dumps(result), flush=True)
    if not result['accepted']:
        sys.exit(1)


if __name__ == '__main__':
    main()
