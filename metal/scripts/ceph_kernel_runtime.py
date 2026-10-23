#!/usr/bin/env python3
"""Exercise kernel RBD only inside the exact disconnected Fedora44 fixture."""

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess

from ceph_runtime_qualification import Runtime as ModernRuntime, sanitized


VERSION = '7.2.11-200.fc44.x86_64'


def owned_mapping(device, mappings):
    if (not re.fullmatch(r'/dev/rbd[0-9]+', device) or not isinstance(mappings, list) or len(mappings) != 1 or
            mappings[0].get('pool') != 'qualification' or mappings[0].get('name') != 'kernel' or
            mappings[0].get('device') != device):
        raise RuntimeError('kernel mapping does not identify the owned synthetic RBD')
    return device


class Runtime(ModernRuntime):
    def __init__(self):
        root = Path('/work')
        if (os.geteuid() != 0 or socket.gethostname() != 'qualification-fedora44' or
                subprocess.check_output(['uname', '-r']).decode().strip() != VERSION or
                'VERSION_ID=44' not in Path('/etc/os-release').read_text() or
                Path('/sys/fs/selinux/enforce').read_text().strip() != '1' or
                root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != 0o700 or
                set(p.name for p in root.iterdir()) !=
                {'ceph_kernel_runtime.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py'} or
                Path('/etc/ceph/ceph.conf').exists() or
                list(Path('/var/lib/ceph').glob('**/keyring'))):
            raise RuntimeError('native kernel runtime requires the exact fresh enforcing VM')
        for address in ('10.0.20.50', '1.1.1.1'):
            try:
                with socket.create_connection((address, 443), timeout=2):
                    pass
            except OSError:
                pass
            else:
                raise RuntimeError('native kernel fixture has an external route')
        self.root = root
        self.children = {}
        self.stage = 'initialize'
        self.conf = ['-c', str(root / 'ceph.conf')]
        self.admin = ['ceph', *self.conf, '-n', 'client.admin', '-k', str(root / 'admin.keyring')]

    def mappings(self):
        return json.loads(self.command(['rbd', 'device', 'list', '--format=json']).stdout)

    def start(self, kind, identity):
        environment = None
        if kind == 'mgr':
            if identity != 'a':
                raise RuntimeError('foreign synthetic manager identity')
            # libcephsqlite opens an independent RADOS connection, outside daemon CLI parsing.
            environment = os.environ | {'CEPH_CONF': '/work/ceph.conf',
                                        'CEPH_KEYRING': '/work/mgr/keyring',
                                        'CEPH_ARGS': '--name=mgr.a --debug-cephsqlite=10/10'}
        super().start(kind, identity, env=environment)

    def kernel_io(self):
        self.stage = 'native manager database check'
        self.ceph('device', 'check-health')
        self.steady()
        self.stage = 'native AES256K kernel RBD I/O'
        if self.mappings():
            raise RuntimeError('preexisting native RBD mapping')
        self.ceph('osd', 'pool', 'application', 'enable', 'qualification', 'rbd')
        admin = ['rbd', *self.conf, '-n', 'client.admin', '-k', str(self.root / 'admin.keyring')]
        self.command([*admin, 'pool', 'init', 'qualification'])
        self.command([*admin, 'create', 'qualification/kernel', '--size=32M', '--image-feature=layering'])
        image = json.loads(self.command([*admin, 'info', 'qualification/kernel', '--format=json']).stdout)
        if not image.get('id') or image['size'] != 32 * 1024**2:
            raise RuntimeError('synthetic RBD image identity differs')
        keyring = self.root / 'kernel.keyring'
        keyring.write_bytes(self.ceph('auth', 'get-or-create', 'client.kernel', 'mon', 'profile rbd',
                                     'osd', 'profile rbd pool=qualification', '--key-type=aes256k'))
        keyring.chmod(0o600)
        payload = hashlib.sha256(b'Issue103 owned native kernel block').digest() * 32768
        device = None
        stages = []
        try:
            for stage in ('initial', 'remap', 'rotated'):
                if stage == 'rotated':
                    retired = self.root / 'retired-kernel.keyring'
                    retired.write_bytes(keyring.read_bytes())
                    retired.chmod(0o600)
                    self.rotate_keyring('client.kernel', keyring, keyring)
                    denied = self.command(['rbd', *self.conf, '--id=kernel', '--keyring=' + str(retired),
                                           'device', 'map', 'qualification/kernel', '--device-type=krbd',
                                           '--options=noshare,mount_timeout=10'], check=False)
                    if (denied.returncode == 0 or self.mappings() or
                            not any(message in denied.stderr.lower() for message in
                                    (b'permission denied', b'operation not permitted'))):
                        raise RuntimeError('retired kernel key lacks explicit fresh-authentication refusal')
                candidate = self.command(['rbd', *self.conf, '--id=kernel', '--keyring=' + str(keyring),
                                          'device', 'map', 'qualification/kernel', '--device-type=krbd',
                                          '--options=noshare']).stdout.decode().strip()
                device = owned_mapping(candidate, self.mappings())
                if not stat.S_ISBLK(Path(device).stat().st_mode):
                    raise RuntimeError('owned RBD mapping is not a block device')
                current = json.loads(self.command([*admin, 'info', 'qualification/kernel', '--format=json']).stdout)
                if current['id'] != image['id'] or current['size'] != image['size']:
                    raise RuntimeError('synthetic RBD identity changed')
                with open(device, 'r+b', buffering=0) as block:
                    if stage == 'initial':
                        if block.write(payload) != len(payload):
                            raise RuntimeError('short synthetic kernel write')
                        os.fsync(block.fileno())
                        block.seek(0)
                    if block.read(len(payload)) != payload:
                        raise RuntimeError('complete synthetic kernel payload differs')
                self.command(['rbd', 'device', 'unmap', device])
                device = None
                if self.mappings():
                    raise RuntimeError('owned kernel mapping remains after unmap')
                stages.append(stage)
            self.steady()
            if Path('/sys/fs/selinux/enforce').read_text().strip() != '1':
                raise RuntimeError('native enforcement changed')
            return {'accepted': True, 'kernel': VERSION, 'image_id': image['id'], 'stages': stages,
                    'payload_bytes': len(payload), 'payload_sha256': hashlib.sha256(payload).hexdigest(),
                    'modern_auth_only': True, 'native_krbd': True, 'mapping_absent': True,
                    'retired_key_fresh_kernel_auth_refused': True,
                    'csi_cephfs_legacy_transition_production_unqualified': True}
        finally:
            if device is not None:
                self.command(['rbd', 'device', 'unmap', device])


def sqlite_messages(data):
    """Select bounded public SQLite errors from this synthetic manager only."""
    selected = []
    for line in data.decode(errors='replace').splitlines():
        if 'cephsqlite:' not in line:
            continue
        message = line[line.index('cephsqlite:'):]
        if any(term in message.lower() for term in ('keyring', 'secret', 'password', 'token', 'private key')):
            continue
        selected.append(sanitized(message[:1024].encode()))
    return selected[-48:]


def class_messages(data):
    """Select only public lock/RBD class-loading evidence from owned OSD logs."""
    selected = []
    pattern = (r'(_load_class (?:lock|rbd)(?:\s|$)|'
               r'_load_class could (?:not stat|not open) class [A-Za-z0-9_./-]*libcls_(?:lock|rbd)\.so|'
               r'class (?:lock|rbd) (?:open|method))')
    for line in data.decode(errors='replace').splitlines():
        match = re.search(pattern, line)
        if not match:
            continue
        message = line[match.start():]
        if any(term in message.lower() for term in ('keyring', 'secret', 'password', 'token', 'private key')):
            continue
        selected.append(sanitized(message[:1024].encode()))
    return selected[-32:]


def manager_native_diagnostic(runtime, result=None):
    if result is None:
        result = {}
    logs = []
    result['logs'] = logs
    for name in ('mgr.log', 'mgr.a.native.log'):
        path = runtime.root / name
        if path.is_symlink():
            raise RuntimeError('foreign synthetic manager log')
        if path.is_file():
            with path.open('rb') as source:
                source.seek(max(0, path.stat().st_size - 131072))
                raw = source.read(131072)
            logs.append({'name': name, 'sample_sha256': hashlib.sha256(raw).hexdigest(),
                         'sample_bytes': len(raw), 'sqlite_messages': sqlite_messages(raw)})
    class_logs = []
    result['osd_class_logs'] = class_logs
    for name in ('osd.log', 'osd.0.native.log'):
        path = runtime.root / name
        if path.is_symlink():
            raise RuntimeError('foreign synthetic OSD log')
        if path.is_file():
            with path.open('rb') as source:
                source.seek(max(0, path.stat().st_size - 131072))
                raw = source.read(131072)
            class_logs.append({'name': name, 'sample_sha256': hashlib.sha256(raw).hexdigest(),
                               'sample_bytes': len(raw), 'class_messages': class_messages(raw)})
    journal = runtime.command(['journalctl', '-k', '-b', '--no-pager', '--output=json',
                               '--grep=avc:.*denied', '--lines=64'], check=False)
    denials = []
    result.update(kernel_avc_query_exit=journal.returncode, kernel_avc_denials=denials)
    for line in journal.stdout.splitlines():
        text = json.loads(line).get('MESSAGE', '')
        if not isinstance(text, str) or 'avc:' not in text or 'denied' not in text:
            continue
        fields = {}
        for key in ('pid', 'comm', 'scontext', 'tcontext', 'tclass', 'permissive'):
            found = re.search(r'\b' + key + r'=("[A-Za-z0-9_.:+-]+"|[A-Za-z0-9_.:+-]+)', text)
            if found:
                fields[key] = found.group(1).strip('"')
        permissions = re.search(r'denied\s+\{([a-z_ ]+)\}', text)
        if permissions:
            fields['permissions'] = permissions.group(1).split()
        denials.append(fields)
    config = []
    result['osd_class_config'] = config
    socket_path = runtime.root / 'osd.0.asok'
    if socket_path.is_symlink():
        raise RuntimeError('foreign synthetic OSD admin socket')
    for name in ('osd_class_dir', 'osd_class_load_list', 'osd_class_default_list'):
        row = {'name': name}
        config.append(row)
        response = runtime.command(['ceph', '--admin-daemon', str(socket_path),
                                    'config', 'get', name], check=False)
        row['exit_code'] = response.returncode
        if response.returncode == 0:
            value = json.loads(response.stdout)
            pattern = r'[A-Za-z0-9_./-]{1,512}' if name == 'osd_class_dir' else r'[a-z0-9_ *]{1,1024}'
            if (not isinstance(value, dict) or set(value) != {name} or
                    not isinstance(value[name], str) or not re.fullmatch(pattern, value[name])):
                raise RuntimeError('native OSD class configuration shape changed')
            row['value'] = value[name]
    pools = json.loads(runtime.ceph('osd', 'pool', 'ls', 'detail', '--format=json'))
    policies = []
    result['pool_policies'] = policies
    for pool in pools:
        if pool.get('pool_name') not in ('qualification', '.mgr'):
            raise RuntimeError('foreign native diagnostic pool')
        policy = {'name': pool['pool_name']}
        for key in ('pool_id', 'size', 'min_size', 'pg_num'):
            value = pool[key]
            if type(value) is not int:
                raise RuntimeError('native diagnostic pool shape changed')
            policy[key] = value
        policies.append(policy)
    return result


def manager_diagnostic(runtime):
    """Retain public module health and bounded native SQLite/AVC diagnostics."""
    value = json.loads(runtime.ceph('health', 'detail', '--format=json'))
    finding = value.get('checks', {}).get('MGR_MODULE_ERROR', {})
    def message(row):
        text = row.get('message', '')
        if not isinstance(text, str):
            raise RuntimeError('manager diagnostic message shape changed')
        return sanitized(text.encode())
    result = {'health_status': value['status'], 'checks': sorted(value.get('checks', {})),
            'manager_module_error': {'severity': finding.get('severity'),
                'summary': message(finding.get('summary', {})),
                'details': [message(row) for row in finding.get('detail', [])]}}
    result['native'] = {}
    try:
        manager_native_diagnostic(runtime, result['native'])
    except Exception as error:
        result['native_diagnostic_error'] = type(error).__name__
    return result


def main():
    runtime = Runtime()
    def cancel(_number, _frame):
        raise InterruptedError('owned Ceph kernel fixture cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = {'modern_rados': runtime.run(), 'kernel_rbd': runtime.kernel_io()}
        print(json.dumps(result), flush=True)
    except Exception as error:
        failure = {'accepted': False, 'stage': runtime.stage, 'error': sanitized(str(error).encode())}
        try:
            failure['manager_diagnostic'] = manager_diagnostic(runtime)
        except Exception as diagnostic_error:
            failure['diagnostic_error'] = type(diagnostic_error).__name__
        print(json.dumps(failure), flush=True)
        raise
    finally:
        for name in list(reversed(runtime.children)):
            runtime.stop(name)


if __name__ == '__main__':
    main()
