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

    def kernel_io(self):
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


def manager_diagnostic(runtime):
    """Retain only public module health, never auth metadata or arbitrary daemon logs."""
    value = json.loads(runtime.ceph('health', 'detail', '--format=json'))
    finding = value.get('checks', {}).get('MGR_MODULE_ERROR', {})
    def message(row):
        text = row.get('message', '')
        if not isinstance(text, str):
            raise RuntimeError('manager diagnostic message shape changed')
        return sanitized(text.encode())
    return {'health_status': value['status'], 'checks': sorted(value.get('checks', {})),
            'manager_module_error': {'severity': finding.get('severity'),
                'summary': message(finding.get('summary', {})),
                'details': [message(row) for row in finding.get('detail', [])]}}


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
