#!/usr/bin/env python3
"""Qualify a natural CephX transition using exclusively synthetic old state."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
import time
import uuid

import ceph_runtime_qualification as modern
import etcd_recovery as common


BASELINE = 'quay.io/ceph/ceph@sha256:716b9433f2a76d5985868017f97e7ba5969b689f045ef992608bb8331f6b5d75'
AUTH_FINDINGS = {'AUTH_INSECURE_SERVICE_KEY_TYPE', 'AUTH_INSECURE_SERVICE_TICKETS',
                 'AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE', 'AUTH_INSECURE_CLIENT_KEY_TYPE',
                 'AUTH_INSECURE_KEYS_ALLOWED', 'AUTH_INSECURE_KEYS_CREATABLE'}
CORE = {'mon.', 'mgr.a', 'osd.0', 'client.admin'}


def key_types(value):
    """Retain types only; native credentials and capabilities stay in memory."""
    data = value['data']
    entities = {}
    rotating = {}
    for row in data['secrets']:
        entity = row['entity']['type_str'] + '.' + row['entity']['id']
        kind = row['auth']['key']['type_str']
        if (not re.fullmatch(r'[a-z]+\.[A-Za-z0-9_.*-]*', entity) or
                entity in entities or kind not in {'aes', 'aes256k'}):
            raise RuntimeError('ambiguous or unsupported synthetic authentication metadata')
        entities[entity] = kind
    for row in data['rotating_secrets']:
        entity = row['entity']['type_str'] + '.' + row['entity']['id']
        keys = row['secrets']['keys']
        types = [key['expiring_key']['key']['type_str'] for key in keys]
        if (not re.fullmatch(r'[a-z]+\.[A-Za-z0-9_.*-]*', entity) or
                entity in rotating or not types or len({key['id'] for key in keys}) != len(keys) or
                any(kind not in {'aes', 'aes256k'} for kind in types)):
            raise RuntimeError('ambiguous or unsupported synthetic service metadata')
        rotating[entity] = types
    # Native mon. initially lives in the keyring, outside the ordinary auth database.
    if not (CORE - {'mon.'}) | {'client.ordinary'} <= entities.keys() or not rotating:
        raise RuntimeError('synthetic authentication metadata is incomplete ' +
                           json.dumps({'entities': entities, 'rotating': rotating}, sort_keys=True))
    return {'entities': entities, 'rotating': rotating}


def require_container(value, image, scratch, run_id, volumes):
    if image not in (BASELINE, modern.IMAGE) or value['Config']['Image'] != image:
        raise RuntimeError('transition artifact identity changed')
    # Reuse every established isolation check after checking this phase's exact artifact.
    isolation = copy.deepcopy(value)
    isolation['Config']['Image'] = modern.IMAGE
    modern.require_container(isolation, scratch, run_id, volumes)


class Runtime(modern.Runtime):
    def __init__(self, root, run_id):
        super().__init__(root, run_id)
        self.expected_osds = 1

    def steady(self):
        while True:
            value = self.status()
            if (value.get('mgrmap', {}).get('available') and
                    value.get('osdmap', {}).get('num_up_osds') == 1 and
                    value.get('osdmap', {}).get('num_in_osds') == 1 and
                    value.get('pgmap', {}).get('pgs_by_state') and
                    all(row['state_name'] == 'active+clean' for row in value['pgmap']['pgs_by_state'])):
                checks = set(value['health'].get('checks', {}))
                if checks - AUTH_FINDINGS - {'POOL_NO_REDUNDANCY'}:
                    raise RuntimeError('unexpected transition health findings: ' + ','.join(sorted(checks)))
                if (self.root / 'baseline.json').exists():
                    self.verify()
                return {'status': value['health']['status'], 'checks': sorted(checks)}
            time.sleep(2)

    def identity(self):
        return {'block': modern.block_identity(self.root),
                'osd_uuid': (self.root / 'osd/fsid').read_text().strip(),
                'fsid': self.status()['fsid'],
                'client_sha256': hashlib.sha256((self.root / 'ordinary.keyring').read_bytes()).hexdigest()}

    def monitor_key_hash(self):
        key = self.command(['ceph-authtool', str(self.root / 'mon.keyring'), '-n', 'mon.', '-p']).stdout.strip()
        if not key or self.ceph('auth', 'get-key', 'mon.').strip() != key:
            raise RuntimeError('native monitor keyring and active authentication differ')
        return hashlib.sha256(key).hexdigest()

    def rotate_keyring(self, entity, original, destination):
        if entity == 'mon.':
            if original != self.root / 'mon.keyring' or destination != self.root / 'rotated-mon.keyring':
                raise RuntimeError('unexpected monitor rotation paths')
            # Restart must read the returned key, including when the original was an extra secret.
            destination = original
        super().rotate_keyring(entity, original, destination)

    def verify(self):
        expected = json.loads((self.root / 'baseline.json').read_bytes())
        if self.identity() != expected['identity']:
            raise RuntimeError('synthetic state or retained client identity changed')
        self.client('ordinary', 'get', 'fixture', '/work/readback')
        payload = (self.root / 'readback').read_bytes()
        if len(payload) != expected['payload_bytes'] or hashlib.sha256(payload).hexdigest() != expected['payload_sha256']:
            raise RuntimeError('complete transition object differs')

    def bootstrap(self):
        self.stage = 'authentic20.2.1 baseline'
        if not self.command(['ceph', '--version']).stdout.startswith(b'ceph version 20.2.1 '):
            raise RuntimeError('baseline version differs')
        if {p.name for p in self.root.iterdir()} != {
                'ceph_legacy_transition.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py'}:
            raise RuntimeError('baseline directory is not fresh')
        fsid = str(uuid.uuid4())
        (self.root / 'ceph.conf').write_text(f'''[global]
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
''')
        for name in ('mon', 'mgr', 'osd'):
            (self.root / name).mkdir(mode=0o700)
        for name, entity, caps in (
            ('mon.keyring', 'mon.', ['--cap', 'mon', 'allow *']),
            ('admin.keyring', 'client.admin', ['--cap', 'mon', 'allow *', '--cap', 'osd', 'allow *',
                                             '--cap', 'mgr', 'allow *', '--cap', 'mds', 'allow *']),
            ('osd/keyring', 'osd.0', ['--cap', 'mon', 'allow profile osd', '--cap', 'osd', 'allow *',
                                    '--cap', 'mgr', 'allow profile osd']),
        ):
            self.command(['ceph-authtool', str(self.root / name), '--create-keyring', '--gen-key',
                          '-n', entity, *caps])
        self.command(['ceph-authtool', str(self.root / 'mon.keyring'), '--import-keyring',
                      str(self.root / 'admin.keyring')])
        self.command(['monmaptool', '--create', '--fsid', fsid, '--addv', 'a',
                      '[v2:127.0.0.1:13300,v1:127.0.0.1:13301]', str(self.root / 'monmap')])
        self.command(['ceph-mon', *self.conf, '-i', 'a', '--mkfs', '--monmap', str(self.root / 'monmap'),
                      '--keyring', str(self.root / 'mon.keyring'), '--setuser=root', '--setgroup=root'])
        self.start('mon', 'a')
        self.status()
        (self.root / 'mgr/keyring').write_bytes(self.ceph('auth', 'get-or-create', 'mgr.a', 'mon',
                                                      'allow profile mgr', 'osd', 'allow *', 'mds', 'allow *'))
        self.start('mgr', 'a')
        secret = self.command(['ceph-authtool', str(self.root / 'osd/keyring'), '-n', 'osd.0', '-p']).stdout.strip().decode()
        new = self.root / 'osd-new.json'
        new.write_text(json.dumps({'cephx_secret': secret}))
        new.chmod(0o600)
        osd_uuid = str(uuid.uuid4())
        if self.ceph('osd', 'new', osd_uuid, '-i', str(new)).strip() != b'0':
            raise RuntimeError('baseline OSD identity differs')
        new.unlink()
        with (self.root / 'block').open('xb') as output:
            output.truncate(modern.BLOCK_BYTES)
        self.command(['ceph-osd', *self.conf, '-i', '0', '--mkfs', '--osd-uuid', osd_uuid,
                      '--setuser=root', '--setgroup=root'])
        self.ceph('osd', 'crush', 'add', 'osd.0', '1.0', 'root=default', 'host=qualification')
        self.start('osd', '0')
        self.ceph('osd', 'pool', 'create', 'qualification', '8')
        self.ceph('osd', 'pool', 'application', 'enable', 'qualification', 'rados')
        self.steady()
        client = self.ceph('auth', 'get-or-create', 'client.ordinary', 'mon', 'allow r',
                           'osd', 'allow rw pool=qualification')
        (self.root / 'ordinary.keyring').write_bytes(client)
        (self.root / 'ordinary.keyring').chmod(0o600)
        payload = b'Issue103 natural legacy CephX transition\n' * 4096
        (self.root / 'payload').write_bytes(payload)
        self.client('ordinary', 'put', 'fixture', '/work/payload')
        result = {'identity': self.identity(), 'payload_bytes': len(payload),
                  'payload_sha256': hashlib.sha256(payload).hexdigest(),
                  'monitor_key_sha256': self.monitor_key_hash()}
        (self.root / 'baseline.json').write_text(json.dumps(result))
        self.verify()
        return {'baseline_native_io': True, **result}

    def transition(self):
        self.stage = '20.2.4 same-state startup'
        if not self.command(['ceph', '--version']).stdout.startswith(b'ceph version 20.2.4 '):
            raise RuntimeError('transition version differs')
        for kind, name in (('mon', 'a'), ('mgr', 'a'), ('osd', '0')):
            self.start(kind, name)
        initial_health = self.steady()
        self.verify()
        before = key_types(json.loads(self.ceph('auth', 'dump-keys', '--format=json')))
        if any(before['entities'][entity] != 'aes' for entity in (CORE - {'mon.'}) | {'client.ordinary'}):
            raise RuntimeError('baseline credentials were not naturally legacy AES')
        original = json.loads((self.root / 'baseline.json').read_bytes())
        if self.monitor_key_hash() != original['monitor_key_sha256']:
            raise RuntimeError('original20.2.1 native monitor key changed before rotation')
        if not any('aes' in kinds for kinds in before['rotating'].values()):
            raise RuntimeError('initial legacy rotating service keys were not observed')
        self.rotate_core()
        if self.monitor_key_hash() == original['monitor_key_sha256']:
            raise RuntimeError('native monitor authentication key did not change')
        self.verify()
        self.ceph('mon', 'set', 'auth_service_cipher', 'aes256k')
        monmap = json.loads(self.ceph('mon', 'dump', '--format=json'))
        if monmap['auth_service_cipher']['name'] != 'aes256k':
            raise RuntimeError('native service cipher differs')
        started = time.time()
        observations = []
        self.transition_progress = {'initial_health': initial_health, 'initial_types': before,
                                    'observations': observations}
        while True:
            health = self.steady()
            self.verify()
            current = key_types(json.loads(self.ceph('auth', 'dump-keys', '--format=json')))
            observations.append({'elapsed_seconds': round(time.time() - started),
                                 'health': health, 'key_types': current})
            (self.root / 'transition-progress.json').write_text(json.dumps(self.transition_progress))
            if (any(current['entities'][entity] != 'aes256k' for entity in CORE) or
                    current['entities']['client.ordinary'] != 'aes' or
                    {'AUTH_INSECURE_SERVICE_KEY_TYPE', 'AUTH_INSECURE_SERVICE_TICKETS'} & set(health['checks'])):
                raise RuntimeError('core migration incomplete or retained client type changed')
            if all(kind == 'aes256k' for kinds in current['rotating'].values() for kind in kinds):
                if 'AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE' in health['checks']:
                    raise RuntimeError('native rotating-key warning contradicts metadata')
                break
            time.sleep(60)
        return {'natural_legacy_transition': True, 'initial_health': initial_health,
                'initial_types': before, 'observations': observations, 'same_state_and_complete_io': True,
                'retained_aes_client_unchanged': True, 'service_cipher': 'aes256k',
                'warnings_preserved': True, 'production_ha_rook_csi_cephfs_unqualified': True}


def qualify(run_id, sources):
    names = {'ceph_legacy_transition.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py'}
    if set(sources) != names or any(not isinstance(value, str) or not value for value in sources.values()):
        raise RuntimeError('transition source bundle differs')
    common.require_host('totodile')
    common.private_root()
    if common.docker('ps', '--all', '--quiet', '--filter=label=io.eaglepass.maintenance=103').stdout.strip():
        raise RuntimeError('another owned fixture is active; leave it alone')
    if shutil.disk_usage(common.ROOT).free <= modern.BLOCK_BYTES:
        raise RuntimeError('insufficient actual synthetic capacity')
    scratch = Path(tempfile.mkdtemp(prefix=run_id + '-legacy-', dir=common.ROOT))
    scratch.chmod(0o700)
    before_images = set(common.docker('image', 'ls', '--no-trunc', '-q').stdout.decode().split())
    owned_images = {}
    container = None
    volumes = []
    result = {'accepted': False, 'run_id': run_id, 'baseline_image': BASELINE, 'target_image': modern.IMAGE}
    try:
        for name, source in sources.items():
            (scratch / name).write_text(source)
        for phase, image in (('baseline', BASELINE), ('transition', modern.IMAGE)):
            common.docker('pull', image)
            metadata = json.loads(common.docker('image', 'inspect', image).stdout)[0]
            owned_images[image] = metadata['Id']
            capacity = shutil.disk_usage(scratch)
            if capacity.free / capacity.total <= 0.30:
                raise RuntimeError('synthetic monitor filesystem crosses its native warning threshold')
            volumes = sorted(metadata['Config'].get('Volumes') or {})
            if metadata['Architecture'] != 'amd64' or metadata['Os'] != 'linux' or not set(volumes) <= modern.VOLUMES:
                raise RuntimeError('transition platform or image volumes changed')
            for n, _ in enumerate(volumes):
                (scratch / ('volume-' + str(n))).mkdir(mode=0o700, exist_ok=True)
            args = ['create', '--network=none', '--read-only', '--cap-drop=ALL',
                    '--security-opt=no-new-privileges:true', '--ipc=private', '--pids-limit=512',
                    '--cpus=2', '--memory=4g', '--hostname=ceph103-' + run_id,
                    '--label=io.eaglepass.maintenance=103', '--label=io.eaglepass.recovery-run=' + run_id,
                    '--mount=type=bind,source=' + str(scratch) + ',target=/work',
                    '--tmpfs=/run:rw,nosuid,nodev', '--tmpfs=/tmp:rw,nosuid,nodev', '--entrypoint=/bin/sh']
            for n, path in enumerate(volumes):
                args.append('--mount=type=bind,source=' + str(scratch / ('volume-' + str(n))) + ',target=' + path)
            container = common.docker(*args, image, '-c', 'exec sleep 2147483647').stdout.decode().strip()
            if not re.fullmatch('[a-f0-9]{64}', container):
                raise RuntimeError('invalid transition container identity')
            require_container(common.inspect(container), image, scratch, run_id, volumes)
            common.docker('start', container)
            state = common.inspect(container)
            require_container(state, image, scratch, run_id, volumes)
            pid = str(state['State']['Pid'])
            common.require_network(json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'link']).stdout),
                                   json.loads(common.command(['nsenter', '-t', pid, '-n', 'ip', '-j', 'route']).stdout))
            output = common.docker('exec', container, 'python3', '-B', '/work/ceph_legacy_transition.py',
                                   '--internal-runtime', phase, '--run-id', run_id, check=False)
            value = json.loads(output.stdout)
            result[phase] = value
            if output.returncode or not value.get('accepted'):
                raise RuntimeError('native legacy phase refused acceptance')
            require_container(common.inspect(container), image, scratch, run_id, volumes)
            common.docker('rm', '--force', '--volumes', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('phase container remains')
            container = None
        result['accepted'] = True
    finally:
        if container:
            require_container(common.inspect(container), image, scratch, run_id, volumes)
            common.docker('rm', '--force', '--volumes', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned transition container remains')
        for image, identity in owned_images.items():
            if identity not in before_images:
                if common.docker('ps', '--all', '--quiet', '--filter=ancestor=' + identity).stdout.strip():
                    raise RuntimeError('new image has another consumer; retained')
                common.docker('image', 'rm', image)
                if common.docker('image', 'inspect', image, check=False).returncode == 0:
                    raise RuntimeError('new unused transition image remains')
        allocated = sum(p.stat().st_blocks * 512 for p in scratch.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(scratch)
        if scratch.exists():
            raise RuntimeError('owned transition data remains')
        result.update(owned_containers_absent=True, scratch_removed=True, allocated_bytes_removed=allocated)
        print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=common.run_identifier, required=True)
    parser.add_argument('--internal-runtime', choices=('baseline', 'transition'))
    args = parser.parse_args()
    def cancel(_number, _frame):
        raise InterruptedError('owned legacy transition cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    if args.internal_runtime is None:
        qualify(args.run_id, {name: Path(__file__).with_name(name).read_text() for name in
                             ('ceph_legacy_transition.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py')})
        return
    runtime = Runtime(Path('/work'), args.run_id)
    try:
        value = runtime.bootstrap() if args.internal_runtime == 'baseline' else runtime.transition()
        result = {'accepted': True, **value}
    except Exception as error:
        result = {'accepted': False, 'stage': runtime.stage, 'error': str(error)}
        if hasattr(runtime, 'transition_progress'):
            result['transition_progress'] = runtime.transition_progress
    finally:
        for name in list(reversed(runtime.children)):
            runtime.stop(name)
    print(json.dumps(result), flush=True)
    if not result['accepted']:
        sys.exit(1)


if __name__ == '__main__':
    main()
