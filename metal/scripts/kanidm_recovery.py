"""Prove native offline Kanidm recovery using only copied protected files."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from collections import Counter
from copy import deepcopy
import time

import pointguide_files_recovery as retained


common = retained.common
IMAGE = 'docker.io/kanidm/server@sha256:d0ff76d6ec6d292d5710bd6ec801d9d5ccf12e3cdcdfe4d122efa5a351a97cbe'
POINT = common.ROOT / 'kanidm-retained-files-20261020-1702'
CHECKSUM = 'a9a9edcf2300fa7558cfb82c3f9625c1db08cc635a411f6963ba7e8ea049c99a'
LABEL = 'io.eaglepass.kanidm-recovery'


def fingerprint(value):
    expected = {'version', 'db_s_uuid', 'db_d_uuid', 'db_ts_max', 'keyhandles', 'repl_meta', 'entries'}
    if (not isinstance(value, dict) or set(value) != expected or value['version'] != '1.10' or
            not isinstance(value['entries'], list) or not value['entries'] or
            any(not isinstance(entry, dict) for entry in value['entries'])):
        raise RuntimeError('native Kanidm backup format differs')
    digest = hashlib.sha256()
    # Native database IDs may change on restore; preserve every full entry and duplicate.
    for record in sorted(common.canonical(entry) for entry in value['entries']):
        digest.update(len(record).to_bytes(8, 'big'))
        digest.update(record)
    metadata = {key: value[key] for key in expected - {'entries'}}
    return {'entries': len(value['entries']), 'entries_sha256': digest.hexdigest(),
            'metadata_sha256': hashlib.sha256(common.canonical(metadata)).hexdigest(),
            'metadata_fields': {key: hashlib.sha256(common.canonical(item)).hexdigest()
                                for key, item in metadata.items()}}


def backup_value(path):
    limit = retained.available_memory() // 4
    if path.stat().st_size >= limit:
        raise RuntimeError('native Kanidm backup exceeds actual available RAM')
    with path.open('rb') as source:
        compressed = source.read(2) == b'\x1f\x8b'
    with (gzip.open(path, 'rb') if compressed else path.open('rb')) as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError('expanded native Kanidm backup exceeds actual available RAM')
    return json.loads(data)


def backup_fingerprint(path):
    return fingerprint(backup_value(path))


def backup_differences(original, restored):
    def index(value):
        result = {}
        for entry in value['entries']:
            item = entry['ent']['V3']
            identity = common.canonical(item['attrs']['uuid'])
            if identity in result or any(not re.fullmatch('[a-z][a-z0-9_]*', key) for key in item['attrs']):
                raise RuntimeError('native Kanidm diagnostic entry identity/schema differs')
            result[identity] = item
        return result
    before, after = index(original), index(restored)
    changed = Counter()
    states = 0
    for identity in before.keys() & after.keys():
        left, right = before[identity], after[identity]
        states += left['changestate'] != right['changestate']
        for key in left['attrs'].keys() | right['attrs'].keys():
            if common.canonical(left['attrs'].get(key)) != common.canonical(right['attrs'].get(key)):
                changed[key] += 1
    return {'removed_entries': len(before.keys() - after.keys()),
            'added_entries': len(after.keys() - before.keys()),
            'changed_entry_states': states, 'changed_attribute_counts': dict(changed)}


def validate_native_restore(original, restored, started_ns, ended_ns, expected_changes=92):
    def duration(value):
        if (not isinstance(value, dict) or set(value) != {'secs', 'nanos'} or
                any(type(item) is not int or item < 0 for item in value.values()) or value['nanos'] >= 10**9):
            raise RuntimeError('native Kanidm duration differs')
        return value['secs'] * 10**9 + value['nanos']

    old_max, new_max = duration(original['db_ts_max']), duration(restored['db_ts_max'])
    if not old_max < started_ns <= new_max <= ended_ns:
        raise RuntimeError('native Kanidm restore clock interval differs: ' + json.dumps({
            'start_minus_original_ns': started_ns - old_max,
            'new_minus_start_ns': new_max - started_ns, 'end_minus_new_ns': ended_ns - new_max}))

    def fresh(cid):
        if (not isinstance(cid, dict) or set(cid) != {'s', 't'} or cid['s'] != original['db_s_uuid'] or
                not started_ns <= duration(cid['t']) <= new_max):
            raise RuntimeError('native Kanidm new change identity differs')

    def index(value):
        result = {}
        for entry in value['entries']:
            if set(entry) != {'ent'} or set(entry['ent']) != {'V3'}:
                raise RuntimeError('native Kanidm restored entry version differs')
            item = entry['ent']['V3']
            if set(item) != {'attrs', 'changestate'}:
                raise RuntimeError('native Kanidm restored entry fields differ')
            identity = common.canonical(item['attrs']['uuid'])
            if identity in result:
                raise RuntimeError('native Kanidm duplicate restored identity')
            result[identity] = item
        return result

    normalized = deepcopy(restored)
    before, after = index(original), index(normalized)
    if before.keys() != after.keys():
        raise RuntimeError('native Kanidm restored entry identities differ')
    changed = 0
    for identity, left in before.items():
        right = after[identity]
        if common.canonical(left) == common.canonical(right):
            continue
        left_attrs, right_attrs = left['attrs'], right['attrs']
        if (left_attrs.keys() != right_attrs.keys() or
                any(common.canonical(left_attrs[key]) != common.canonical(right_attrs[key])
                    for key in left_attrs if key != 'last_modified_cid')):
            raise RuntimeError('native Kanidm restored attribute data differs')
        value = right_attrs['last_modified_cid']
        if not isinstance(value, dict) or set(value) != {'CI'} or len(value['CI']) != 1:
            raise RuntimeError('native Kanidm last modified identity differs')
        cid = value['CI'][0]
        fresh(cid)
        if set(left['changestate']) != {'V1Live'} or set(right['changestate']) != {'V1Live'}:
            raise RuntimeError('native Kanidm changed entry is not live')
        old_state, new_state = left['changestate']['V1Live'], right['changestate']['V1Live']
        if (set(old_state) != {'at', 'changes'} or set(new_state) != {'at', 'changes'} or
                common.canonical(old_state['at']) != common.canonical(new_state['at']) or
                old_state['changes'].keys() != new_state['changes'].keys()):
            raise RuntimeError('native Kanidm original change history differs')
        changes = [key for key in old_state['changes']
                   if common.canonical(old_state['changes'][key]) != common.canonical(new_state['changes'][key])]
        if not changes or any(common.canonical(new_state['changes'][key]) != common.canonical(cid) for key in changes):
            raise RuntimeError('native Kanidm attribute change identities differ')
        right_attrs['last_modified_cid'] = deepcopy(left_attrs['last_modified_cid'])
        right['changestate'] = deepcopy(left['changestate'])
        changed += 1
    if changed != expected_changes:
        raise RuntimeError('native Kanidm startup change count differs')

    def ruv(value):
        if set(value) != {'V1'} or set(value['V1']) != {'ruv'} or not isinstance(value['V1']['ruv'], list):
            raise RuntimeError('native Kanidm replication format differs')
        records = {common.canonical(item): item for item in value['V1']['ruv']}
        if len(records) != len(value['V1']['ruv']):
            raise RuntimeError('native Kanidm duplicate replication point')
        return records
    old_ruv, new_ruv = ruv(original['repl_meta']), ruv(restored['repl_meta'])
    if not old_ruv.keys() <= new_ruv.keys():
        raise RuntimeError('native Kanidm original replication history missing')
    added = new_ruv.keys() - old_ruv.keys()
    if not added:
        raise RuntimeError('native Kanidm startup replication point missing')
    for key in added:
        fresh(new_ruv[key])
    normalized['db_ts_max'] = deepcopy(original['db_ts_max'])
    normalized['repl_meta'] = deepcopy(original['repl_meta'])
    if fingerprint(normalized) != fingerprint(original):
        raise RuntimeError('native Kanidm complete normalized fingerprint differs')
    return {'data_equal': True, 'all_original_runtime_metadata_accounted_for': True,
            'validated_startup_entries': changed, 'validated_new_replication_points': len(added),
            'normalized_fingerprint': fingerprint(normalized)}


def arguments(scratch, run_id, operation):
    return ['create', '--label', LABEL + '=' + run_id, '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=1000:1000',
            '--pids-limit=128', '--memory=1g', '--cpus=1',
            '--tmpfs=/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=1777',
            '--mount', 'type=bind,source=' + str(scratch) + ',target=/data',
            '--entrypoint=/sbin/kanidmd', IMAGE, '--config-path=/data/offline.toml', 'database', *operation]


def require_container(value, scratch, run_id, operation, image_id):
    config, host = value['Config'], value['HostConfig']
    expected = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
                'UTSMode': '', 'UsernsMode': '', 'PidsLimit': 128, 'Memory': 1073741824,
                'NanoCpus': 1000000000,
                'Tmpfs': {'/tmp': 'rw,nosuid,nodev,uid=1000,gid=1000,mode=1777'}}
    if (config['Image'] != IMAGE or value['Image'] != image_id or config['User'] != '1000:1000' or
            config['Entrypoint'] != ['/sbin/kanidmd'] or
            config['Cmd'] != ['--config-path=/data/offline.toml', 'database', *operation] or
            config.get('Labels', {}).get(LABEL) != run_id or
            any(host.get(key) != expected_value for key, expected_value in expected.items()) or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            any(host.get(key) for key in ('CapAdd', 'Devices', 'DeviceRequests', 'PortBindings', 'GroupAdd')) or
            len(value['Mounts']) != 1 or value['Mounts'][0].get('Type') != 'bind' or
            not value['Mounts'][0]['RW'] or value['Mounts'][0]['Source'] != str(scratch) or
            value['Mounts'][0]['Destination'] != '/data'):
        raise RuntimeError('native Kanidm copy isolation differs')


def operation(scratch, run_id, args, marker, image_id):
    container = None
    try:
        container = common.docker(*arguments(scratch, run_id, args)).stdout.decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', container):
            raise RuntimeError('native Kanidm container identity missing')
        require_container(common.inspect(container), scratch, run_id, args, image_id)
        response = common.docker('start', '--attach', container, check=False)
        value = common.inspect(container)
        require_container(value, scratch, run_id, args, image_id)
        state = value['State']
        output = response.stdout + response.stderr
        if (response.returncode or state['Running'] or state['ExitCode'] != 0 or state.get('OOMKilled') or
                marker not in output or re.search(rb'\bERROR\b', output)):
            diagnostic = POINT / ('native-failure-' + run_id + '-' + uuid.uuid4().hex + '.log')
            descriptor = os.open(diagnostic, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'wb') as target:
                target.write(output)
                target.flush()
                os.fsync(target.fileno())
            raise RuntimeError('native Kanidm ' + args[0] + ' failed: ' + json.dumps({
                'exit': state['ExitCode'], 'transport': response.returncode, 'oom': state.get('OOMKilled'),
                'required_marker': marker.decode(), 'marker_present': marker in output,
                'output_sha256': hashlib.sha256(output).hexdigest(), 'output_bytes': len(output),
                'protected_private_diagnostic': str(diagnostic)}))
        return {'operation': args[0], 'exit': 0, 'marker_present': True,
                'output_sha256': hashlib.sha256(output).hexdigest()}
    finally:
        if container:
            require_container(common.inspect(container), scratch, run_id, args, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned Kanidm container remains')


def config(root, database):
    path = root / 'offline.toml'
    # The shared config builder requires paths; offline database commands never open TLS files.
    # Explicit native minimum avoids auto-sizing against a fresh database before schema setup.
    path.write_text('db_path = "/data/' + database + '"\ndomain = "auth.eaglepass.io"\n'
                    'db_arc_size = 2048\n'
                    'origin = "https://auth.eaglepass.io"\n'
                    'tls_chain = "/data/offline-unused.crt"\n'
                    'tls_key = "/data/offline-unused.key"\n')
    path.chmod(0o600)
    os.chown(path, 1000, 1000)


def restore(run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    value = retained.verify(POINT, CHECKSUM, 'kanidm')
    retained.require_capacity(common.ROOT, value['tree'], 6)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('owned Kanidm recovery already active')
    if shutil.disk_usage(common.ROOT).free <= sum(r.get('bytes', 0) for r in value['tree'].values()) * 6:
        raise RuntimeError('actual native Kanidm copy capacity insufficient')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='kanidm-native-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'manifest_sha256': CHECKSUM, 'image': IMAGE, 'operations': []}
    try:
        common.docker('pull', IMAGE)
        image = json.loads(common.docker('image', 'inspect', IMAGE).stdout)[0]
        image_id = image['Id']
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {IMAGE, IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', []))):
            raise RuntimeError('exact native Kanidm image differs')
        for number in range(2):
            root = scratch / str(number)
            retained.materialize(POINT, root, value)
            for parent, directories, files in os.walk(root, followlinks=False):
                os.chown(parent, 1000, 1000)
                for name in directories + files:
                    os.chown(Path(parent) / name, 1000, 1000, follow_symlinks=False)
            config(root, 'kanidm.db')
            run = lambda args, marker: operation(root, run_id, args, marker, image_id)
            result['operations'].append(run(['backup', '--compression=gzip', '/data/original.json.gz'], b'Backup success!'))
            before = backup_fingerprint(root / 'original.json.gz')
            result['operations'].append(run(['verify'], b'Verification passed!'))
            config(root, 'restored.db')
            started_ns = time.time_ns()
            result['operations'].append(run(['restore', '/data/original.json.gz'], b'Restore Success!'))
            result['operations'].append(run(['verify'], b'Verification passed!'))
            result['operations'].append(run(['backup', '--compression=gzip', '/data/restored.json.gz'], b'Backup success!'))
            ended_ns = time.time_ns()
            after = backup_fingerprint(root / 'restored.json.gz')
            result.setdefault('comparisons', []).append({'original': before, 'restored': after})
            if after != before:
                result['differences'] = backup_differences(backup_value(root / 'original.json.gz'),
                                                          backup_value(root / 'restored.json.gz'))
                transformed = validate_native_restore(backup_value(root / 'original.json.gz'),
                                                      backup_value(root / 'restored.json.gz'), started_ns, ended_ns)
                result.setdefault('startup_transformations', []).append(transformed)
            if number and result['fingerprint'] != before:
                raise RuntimeError('independent native Kanidm recoveries differ')
            result['fingerprint'] = before
        result.update(accepted=True, native_data_equal_startup_metadata_validated=True, independent_restores=2,
                      network='none', live_admin_socket_not_accessed=True, login_not_attempted=True,
                      tls_secrets_and_public_sso_unqualified=True)
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
            raise RuntimeError('owned Kanidm recovery container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused Kanidm recovery image remains')
        retained.verify(POINT, CHECKSUM, 'kanidm')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'protected_original_unchanged': True, 'allocated_bytes_removed': allocated}
        retained.files.write_json(POINT / ('native-offline-restore-' + run_id + '.json'), result)
    return result
