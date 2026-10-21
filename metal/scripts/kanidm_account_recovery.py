"""Approved Issue 103 recovery; never display credentials or native output."""

from copy import deepcopy
from datetime import datetime
import json
import http.cookiejar
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request

import kanidm_recovery as native


ITEM = 'uccubcgzmubsxpkcklknbd434a'
VAULT = '4uaua4a45yuhnwhehp5bwylmti'
LABEL = 'io.eaglepass.kanidm-account-rehearsal'


def require_password_only_admin(backup):
    try:
        matches = [e['ent']['V3']['attrs'] for e in backup['entries']
                   if e['ent']['V3']['attrs'].get('name') == {'N8': ['admin']}]
        assert len(matches) == 1
        account = matches[0]
        assert not account.get('passkeys') and not account.get('account_expire')
        credential = account['primary_credential']
        assert set(credential) == {'CR'} and len(credential['CR']) == 1
        credential = credential['CR'][0]
        assert credential['t'] == 'primary'
        assert credential['d']['type_'] in {'V2Pw', 'V2GPw'}
    except (AssertionError, KeyError, TypeError):
        raise RuntimeError('administrator is not the qualified password-only recovery target') from None


def verify_https_login(password):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cookies))
    token = None
    result = {'origin': 'https://auth.eaglepass.io', 'tls_verified': True, 'redirects_allowed': False}

    def request(path, payload=None):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        try:
            with opener.open(urllib.request.Request(result['origin'] + path, data=body,
                                                   headers=headers), timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError('normal Kanidm HTTPS status differs')
                raw = response.read(1048577)
        except urllib.error.HTTPError as error:
            raise RuntimeError('normal Kanidm HTTPS refused: HTTP ' + str(error.code)) from None
        if len(raw) > 1048576:
            raise RuntimeError('normal Kanidm response exceeds bound')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise RuntimeError('normal Kanidm response is not JSON') from None

    try:
        init = request('/v1/auth', {'step': {'init': 'admin'}})
        if init.get('state') != {'choose': ['password']}:
            raise RuntimeError('existing administrator password mechanism differs')
        begin = request('/v1/auth', {'step': {'begin': 'password'}})
        if begin.get('state') != {'continue': ['password']}:
            raise RuntimeError('existing administrator continuation differs')
        auth = request('/v1/auth', {'step': {'cred': {'password': password}}})
        state = auth.get('state', {})
        if set(state) != {'success'} or not isinstance(state['success'], str) or not state['success']:
            raise RuntimeError('normal administrator authentication did not succeed')
        token = state['success']
        who = request('/v1/self')
        if who.get('youare', {}).get('attrs', {}).get('name') != ['admin']:
            raise RuntimeError('normal authenticated account identity differs')
        result.update(password_login=True, authenticated_self_is_existing_admin=True)
    finally:
        try:
            if token:
                request('/v1/logout')
                result['session_logout'] = True
        finally:
            token = None
            cookies.clear()
    return result


def decode_password(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        password = value['output']
        if (set(value) != {'status', 'output'} or value['status'] != 'ok' or
                not isinstance(password, str) or not 16 <= len(password) <= 256 or
                any(not 33 <= ord(c) <= 126 for c in password)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise RuntimeError('native recovery response refused; raw output discarded') from None
    return password


def replace_password(item, password):
    decode_password(json.dumps({'status': 'ok', 'output': password}))
    fields = item.get('fields', [])
    if (item.get('id') != ITEM or item.get('vault', {}).get('id') != VAULT or
            item.get('category') != 'LOGIN' or item.get('passkeys') or
            any('passkey' in key.lower() for key in item) or
            [f.get('value') for f in fields if f.get('purpose') == 'USERNAME'] != ['admin'] or
            len([f for f in fields if f.get('purpose') == 'PASSWORD']) != 1):
        raise RuntimeError('existing vault account contract differs')
    output = deepcopy(item)
    field = next(f for f in output['fields'] if f.get('purpose') == 'PASSWORD')
    if field.get('id') != 'password' or field.get('type') != 'CONCEALED':
        raise RuntimeError('existing vault password field differs')
    field['value'] = password
    return output


def verify_vault(before, after, password):
    expected = replace_password(before, password)
    after = deepcopy(after)
    original = next(f for f in before['fields'] if f.get('purpose') == 'PASSWORD')
    field = next(f for f in expected['fields'] if f.get('purpose') == 'PASSWORD')
    # The native CLI appends the old password; preserve every existing history entry.
    if original['value'] != password:
        details = field.setdefault('password_details', {})
        history = details.get('history', [])
        if not isinstance(history, list) or any(not isinstance(x, str) for x in history):
            raise RuntimeError('existing vault password history differs')
        details['history'] = [*history, original['value']]
    # Native edit updates only these provider-managed revision fields.
    for value in (expected, after):
        for key in ('version', 'updated_at', 'last_edited_by'):
            value.pop(key, None)
    if expected != after:
        raise RuntimeError('vault readback differs; do not repeat native recovery')


def account_changes(before, after, started_ns, ended_ns):
    def index(value):
        result = {}
        for entry in value['entries']:
            attrs = entry['ent']['V3']['attrs']
            identity = native.common.canonical(attrs['uuid'])
            if identity in result:
                raise RuntimeError('duplicate account identity')
            result[identity] = attrs
        return result
    left, right = index(before), index(after)
    if left.keys() != right.keys():
        raise RuntimeError('account identities changed')
    changes = []
    for identity, original in left.items():
        updated = right[identity]
        for key in original.keys() | updated.keys():
            if key == 'last_modified_cid' or original.get(key) == updated.get(key):
                continue
            if (original.get('name') != {'N8': ['admin']} or
                    original.get('passkeys') or original.get('account_expire') or
                    key not in {'primary_credential', 'account_valid_from'}):
                name = original.get('name')
                raise RuntimeError('unapproved account attribute change: ' + json.dumps({
                    'attribute': key if re.fullmatch('[a-z][a-z0-9_]*', key) else 'UNRECOGNIZED',
                    'admin_name_match': name == {'N8': ['admin']},
                    'admin_name_structure': sorted(name) if isinstance(name, dict) and
                    all(re.fullmatch('[A-Za-z_]+', k) for k in name) else type(name).__name__,
                    'name_contains_admin_literal': 'admin' in str(name),
                    'existing_passkeys': bool(original.get('passkeys')),
                    'existing_expiry': bool(original.get('account_expire'))}))
            changes.append(key)
            if key == 'account_valid_from':
                try:
                    value = updated[key]
                    assert set(value) == {'DT'} and len(value['DT']) == 1
                    timestamp = datetime.fromisoformat(value['DT'][0].replace('Z', '+00:00'))
                    assert timestamp.tzinfo is not None
                    assert started_ns <= int(timestamp.timestamp() * 10**9) <= ended_ns
                except (ValueError, TypeError, KeyError, AssertionError):
                    raise RuntimeError('native account validity is outside measured recovery interval') from None
    if set(changes) != {'primary_credential', 'account_valid_from'} or len(changes) != 2:
        raise RuntimeError('expected single existing administrator credential change missing')
    return {'all_entry_identities_preserved': True, 'only_admin_native_recovery_fields_changed': True,
            'admin_changed_fields': sorted(changes), 'no_existing_admin_passkeys_or_expiry_removed': True,
            'native_validity_within_measured_interval': True}


def server_arguments(root, run_id, operation):
    if operation not in {'server', 'cert-generate'}:
        raise RuntimeError('unapproved rehearsal operation')
    args = native.arguments(root, run_id, [])
    args[-1] = operation
    return [args[0], '--label', LABEL + '=' + run_id, *args[1:]]


def require_server(container, root, run_id, image_id, operation='server'):
    expected = native.arguments(root, run_id, [])
    value = deepcopy(container)
    if (operation not in {'server', 'cert-generate'} or
            value['Config']['Cmd'] != ['--config-path=/data/offline.toml', operation] or
            value['Config'].get('Labels', {}).get(LABEL) != run_id or
            value['HostConfig'].get('LogConfig') != {'Type': 'none', 'Config': {}}):
        raise RuntimeError('isolated account rehearsal server differs')
    value['Config']['Cmd'] = expected[expected.index(native.IMAGE) + 1:]
    value['Config']['Labels'][native.LABEL] = run_id
    native.require_container(value, root, run_id, [], image_id)


def rehearse(point, checksum, run_id):
    common, retained = native.common, native.retained
    common.require_host('pikachu')
    common.private_root()
    common.run_identifier(run_id)
    value = retained.verify(point, checksum, 'kanidm')
    retained.require_capacity(common.ROOT, value['tree'], 4)
    if common.docker('ps', '-aq', '--filter=label=' + LABEL).stdout.strip():
        raise RuntimeError('account rehearsal already active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='kanidm-account-rehearsal-', dir=common.ROOT))
    container = image_id = None
    result = {'accepted': False, 'manifest_sha256': checksum}
    try:
        common.docker('pull', native.IMAGE)
        image = json.loads(common.docker('image', 'inspect', native.IMAGE).stdout)[0]
        image_id = image['Id']
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {native.IMAGE, native.IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', []))):
            raise RuntimeError('account rehearsal image platform differs')
        root = scratch / 'copy'
        retained.materialize(point, root, value)
        for parent, directories, files in os.walk(root, followlinks=False):
            os.chown(parent, 1000, 1000)
            for name in directories + files:
                os.chown(Path(parent) / name, 1000, 1000, follow_symlinks=False)
        native.config(root, 'kanidm.db')
        native.operation(root, run_id, ['backup', '--compression=gzip', '/data/before.json.gz'],
                         b'Backup success!', image_id)
        before = native.backup_value(root / 'before.json.gz')
        require_password_only_admin(before)
        tls = root / 'synthetic-tls'
        tls.mkdir(mode=0o700)
        os.chown(tls, 1000, 1000)
        config = root / 'offline.toml'
        config.write_text('db_path="/data/kanidm.db"\ndb_arc_size=2048\n'
                          'domain="auth.eaglepass.io"\norigin="https://auth.eaglepass.io"\n'
                          'bindaddress="127.0.0.1:8443"\nadminbindpath="/data/rehearsal.sock"\n'
                          'tls_chain="/data/synthetic-tls/rehearsal.crt"\n'
                          'tls_key="/data/synthetic-tls/rehearsal.key"\n')
        # Use the exact daemon's native generator; no host package or real TLS key.
        args = server_arguments(root, run_id, 'cert-generate')
        generator = common.docker(*args).stdout.decode().strip()
        try:
            require_server(common.inspect(generator), root, run_id, image_id, 'cert-generate')
            response = common.docker('start', '--attach', generator, check=False)
            state = common.inspect(generator)['State']
            if response.returncode or state['Running'] or state['ExitCode'] or state.get('OOMKilled'):
                raise RuntimeError('native synthetic certificate generation failed')
            for name in ('rehearsal.key', 'rehearsal.crt'):
                path = tls / name
                if not path.is_file() or path.is_symlink() or not path.stat().st_size:
                    raise RuntimeError('native synthetic TLS material missing')
        finally:
            require_server(common.inspect(generator), root, run_id, image_id, 'cert-generate')
            common.docker('rm', '-f', generator)
            if common.docker('inspect', generator, check=False).returncode == 0:
                raise RuntimeError('owned synthetic TLS generator remains')
        args = server_arguments(root, run_id, 'server')
        container = common.docker(*args).stdout.decode().strip()
        require_server(common.inspect(container), root, run_id, image_id)
        started_ns = time.time_ns()
        common.docker('start', container)
        while not (root / 'rehearsal.sock').exists():
            if not common.inspect(container)['State']['Running']:
                raise RuntimeError('native rehearsal server exited; raw logs unavailable by design')
            time.sleep(0.2)
        response = common.docker('exec', container, '/sbin/kanidmd',
                                 '--config-path=/data/offline.toml', 'scripting',
                                 'recover-account', 'admin', check=False)
        if response.returncode:
            raise RuntimeError('native rehearsal recovery failed; raw output discarded')
        decode_password(response.stdout)
        require_server(common.inspect(container), root, run_id, image_id)
        common.docker('stop', '--time=30', container)
        if common.inspect(container)['State']['Running']:
            raise RuntimeError('native rehearsal did not stop')
        native.config(root, 'kanidm.db')
        native.operation(root, run_id, ['backup', '--compression=gzip', '/data/after.json.gz'],
                         b'Backup success!', image_id)
        result.update(account_changes(before, native.backup_value(root / 'after.json.gz'),
                                      started_ns, time.time_ns()))
        result.update(accepted=True, existing_admin_recovered_in_copy=True, network='none',
                      logging='none', original_not_mounted=True, original_admin_password_only=True)
    finally:
        if container:
            require_server(common.inspect(container), root, run_id, image_id)
            common.docker('rm', '-f', container)
            if common.docker('inspect', container, check=False).returncode == 0:
                raise RuntimeError('owned account rehearsal container remains')
        if common.docker('ps', '-aq', '--filter=label=' + native.LABEL).stdout.strip():
            raise RuntimeError('owned native operation remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', native.IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused account rehearsal image remains')
        retained.verify(point, checksum, 'kanidm')
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'protected_original_unchanged': True, 'allocated_bytes_removed': allocated}
        retained.files.write_json(point / ('account-rehearsal-' + run_id + '.json'), result)
    return result


def recover(point, checksum, rehearsal_id, restore_id):
    """Return a secret to a RAM-only caller after durable protected retention."""
    retained, common = native.retained, native.common
    common.require_host('pikachu')
    common.private_root()
    if point.parent != common.ROOT:
        raise RuntimeError('approved protected destination differs')
    retained.verify(point, checksum, 'kanidm')
    restore = json.loads((point / ('native-offline-restore-' + restore_id + '.json')).read_bytes())
    if (not restore.get('accepted') or restore.get('manifest_sha256') != checksum or
            not restore.get('native_data_equal_startup_metadata_validated') or
            restore.get('independent_restores') != 2 or
            not restore.get('cleanup', {}).get('protected_original_unchanged')):
        raise RuntimeError('fresh native restore qualification missing')
    proof = json.loads((point / ('account-rehearsal-' + rehearsal_id + '.json')).read_bytes())
    if (not proof.get('accepted') or proof.get('manifest_sha256') != checksum or
            not proof.get('only_admin_native_recovery_fields_changed') or
            not proof.get('original_admin_password_only') or
            not proof.get('cleanup', {}).get('scratch_absent')):
        raise RuntimeError('approved account rehearsal proof missing')
    retained.source_identity('kanidm')
    started = point / 'account-recovery-started.json'
    # Exclusive intent prevents a repeated reset after an uncertain transport outcome.
    retained.files.write_json(started, {'account': 'admin', 'manifest_sha256': checksum})
    cid = retained.PROFILES['kanidm']['runtime'][0]['container_id']
    response = common.command(['/usr/local/bin/k3s', 'crictl', 'exec', cid, '/sbin/kanidmd',
                               '--config-path=/data/server.toml', 'scripting',
                               'recover-account', 'admin'], check=False)
    if response.returncode:
        raise RuntimeError('native account recovery uncertain; inspect protected intent, never blind retry')
    password = decode_password(response.stdout)
    path = point / 'admin-recovered-password.json'
    retained.files.write_json(path, {'status': 'ok', 'output': password})
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != 0:
        raise RuntimeError('protected recovered credential permissions differ')
    descriptor = os.open(point, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    retained.source_identity('kanidm')
    return password
