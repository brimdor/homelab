#!/usr/bin/env python3
"""Qualify three blank virtual disks only in an existing owned disposable VM."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import stat
import subprocess

import yaml


DISK_BYTES = 8 * 1024**3
TOOLS = {'colima': '/opt/homebrew/bin/colima', 'lima': '/opt/homebrew/bin/limactl',
         'docker': '/opt/homebrew/bin/docker'}


class DiskIdentityError(RuntimeError):
    def __init__(self, observation):
        super().__init__('owned blank disk file identity differs')
        self.observation = observation


class GuestDiskIdentityError(RuntimeError):
    def __init__(self, devices, names):
        super().__init__('owned guest disk serial is missing or ambiguous')
        self.observation = {'expected_serials': ['lima-' + name for name in names],
                            'whole_device_count': len(devices), 'devices': []}
        for row in devices[:32]:
            values = {key: row.get(key) for key in ('path', 'serial', 'size', 'type', 'maj:min', 'ro')}
            for key in ('path', 'serial', 'type', 'maj:min'):
                value = values[key]
                if value is not None and (not isinstance(value, str) or
                                          not re.fullmatch(r'[a-zA-Z0-9/_.:-]{0,128}', value)):
                    values[key] = 'unclassified'
            for key in ('size', 'ro'):
                if type(values[key]) not in (int, bool, type(None)):
                    values[key] = 'unclassified'
            values.update(has_filesystem=bool(row.get('fstype')), has_children=bool(row.get('children')),
                          has_parent=bool(row.get('pkname')), mounted=any(row.get('mountpoints') or []))
            self.observation['devices'].append(values)


def backing_identity(path):
    metadata = path.lstat()
    observation = {'regular_file': stat.S_ISREG(metadata.st_mode),
                   'owned_by_current_user': metadata.st_uid == os.getuid(),
                   'bytes': metadata.st_size, 'expected_bytes': DISK_BYTES,
                   'symlink': path.is_symlink(),
                   'ancestor_symlink': any(p.is_symlink() for p in path.parents)}
    if (not observation['regular_file'] or not observation['owned_by_current_user'] or
            metadata.st_size != DISK_BYTES or observation['symlink'] or observation['ancestor_symlink']):
        raise DiskIdentityError(observation)
    return {'device': metadata.st_dev, 'inode': metadata.st_ino, 'bytes': metadata.st_size}


def file_identity(path):
    identity = backing_identity(path)
    with path.open('rb') as source:
        first = source.read(512)
        source.seek(-512, 2)
        last = source.read(512)
    if first != bytes(512) or last != bytes(512):
        raise RuntimeError('owned blank disk has nonzero boundary sectors')
    return identity


def require_config(value, vm_type='vz', profile='substrate'):
    profiles = {'substrate': (2, '2048MiB'), 'storage': (8, '12288MiB')}
    if profile not in profiles or (profile == 'storage' and vm_type != 'qemu'):
        raise RuntimeError('unreviewed disk fixture profile')
    cpus, memory = profiles[profile]
    if (vm_type not in ('vz', 'qemu') or value.get('vmType') != vm_type or
            value.get('mounts') or value.get('blockDevices') or
            value.get('cpus') != cpus or value.get('memory') != memory or
            value.get('ssh', {}).get('forwardAgent') is not False):
        raise RuntimeError('owned disk fixture VM contract differs')


def added_config(before, after, names, vm_type='vz'):
    require_config(before, vm_type)
    expected = before | {'additionalDisks': [*(before.get('additionalDisks') or []),
                                           *({'name': name, 'format': False, 'mount': False}
                                             for name in names)]}
    if after != expected:
        raise RuntimeError('VM configuration changed beyond exact raw disk attachment')


def require_imported_disk(value, name):
    if not isinstance(value, dict):
        raise RuntimeError('native imported disk metadata is missing')
    native = {key.lower(): item for key, item in value.items()}
    if native.get('name') != name or native.get('format') != 'raw' or native.get('size') != DISK_BYTES:
        raise RuntimeError('native imported disk format or identity differs')


def qemu_arguments(identities, root):
    names = list(identities)
    if (len(names) != 3 or not re.fullmatch(r'rook-[a-f0-9]{8}-0', names[0]) or
            names != [names[0][:-1] + str(number) for number in range(3)]):
        raise RuntimeError('explicit QEMU disk names differ')
    arguments = ['/opt/homebrew/bin/qemu-system-aarch64']
    for name, identity in identities.items():
        path = root / 'l/_disks' / name / 'datadisk'
        if (identity['path'] != str(path) or any(character in str(path) for character in ',\r\n') or
                file_identity(path) != {key: identity[key] for key in ('device', 'inode', 'bytes')}):
            raise RuntimeError('explicit QEMU backing file identity differs')
        arguments.extend(['-drive', f'file={path},if=none,format=raw,id={name}',
                          '-device', f'virtio-blk-pci,drive={name},id={name},serial=lima-{name}'])
    return shlex.join(arguments)


def require_qemu_backends(rows, identities):
    paths = []
    for name, identity in identities.items():
        matches = [row for row in rows if row.get('device') == name]
        if len(matches) != 1:
            raise RuntimeError('explicit QEMU native backend is missing or ambiguous')
        row = matches[0]
        inserted = row.get('inserted', {})
        image = inserted.get('image', {})
        if (row.get('qdev') != '/machine/peripheral/' + name + '/virtio-backend' or
                inserted.get('file') != identity['path'] or inserted.get('drv') != 'raw' or
                inserted.get('ro') is not False or image.get('filename') != identity['path'] or
                image.get('format') != 'raw' or image.get('virtual-size') != DISK_BYTES):
            raise RuntimeError('explicit QEMU native backend identity differs')
        paths.append(row['qdev'])
    return paths


def qemu_observation(root, identities):
    path = root / 'l/colima-q/qmp.sock'
    metadata = path.lstat()
    if (not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid() or
            any(p.is_symlink() for p in (path, *path.parents))):
        raise RuntimeError('owned QEMU monitor socket identity differs')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(30)
        connection.connect(str(path))
        with connection.makefile('rb') as stream:
            def read():
                raw = stream.readline(1024 * 1024 + 1)
                if not raw.endswith(b'\n') or len(raw) > 1024 * 1024:
                    raise RuntimeError('owned QEMU monitor response is incomplete or oversized')
                return json.loads(raw)

            greeting = read()
            if greeting.get('QMP', {}).get('version', {}).get('qemu') != {
                    'major': 11, 'minor': 1, 'micro': 2}:
                raise RuntimeError('owned QEMU monitor version differs')

            def request(operation, arguments=None):
                if operation not in ('qmp_capabilities', 'query-block', 'qom-get'):
                    raise RuntimeError('unreviewed QEMU monitor command')
                connection.sendall(json.dumps({'execute': operation, 'arguments': arguments or {},
                                               'id': operation}).encode() + b'\n')
                for _number in range(64):
                    value = read()
                    if 'event' in value:
                        continue
                    if value.get('id') != operation or 'return' not in value or 'error' in value:
                        raise RuntimeError('owned QEMU monitor refused ' + operation)
                    return value['return']
                raise RuntimeError('owned QEMU monitor response not observed')

            request('qmp_capabilities')
            rows = request('query-block')
            paths = require_qemu_backends(rows, identities)
            for name, qdev in zip(identities, paths):
                if request('qom-get', {'path': qdev, 'property': 'serial'}) != 'lima-' + name:
                    raise RuntimeError('explicit QEMU device serial differs')
    return {'exact_backends_and_serials_verified': True, 'monitor_connections_closed': True,
            'qemu_version': '11.1.2', 'backend_count': len(paths)}


def guest_disks(value, names):
    devices = value['blockdevices']
    found = []
    for name in names:
        matches = [row for row in devices if row.get('serial') == 'lima-' + name]
        if len(matches) != 1:
            raise GuestDiskIdentityError(devices, names)
        row = matches[0]
        if (not re.fullmatch(r'/dev/vd[a-z]+', row['path']) or row.get('type') != 'disk' or
                row.get('size') != DISK_BYTES or row.get('ro') not in (False, 0) or
                row.get('fstype') or row.get('pkname') or row.get('children') or
                any(row.get('mountpoints') or []) or
                not re.fullmatch(r'[0-9]+:[0-9]+', row.get('maj:min', ''))):
            raise RuntimeError('owned guest disk is not a blank unmounted whole device')
        found.append({key: row[key] for key in ('path', 'serial', 'size', 'maj:min')})
    if len({row['path'] for row in found}) != 3 or len({row['maj:min'] for row in found}) != 3:
        raise RuntimeError('owned guest disk identities overlap')
    return found


class Fixture:
    def __init__(self, root, run_id, vm_type='vz', profile='substrate'):
        metadata = root.lstat()
        if (not root.is_absolute() or not re.fullmatch(r'v-[a-z0-9_]{8}', root.name) or
                not re.fullmatch(r'rook-[a-f0-9]{8}', run_id) or not root.is_dir() or
                stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid() or
                any(p.is_symlink() for p in (root, *root.parents)) or vm_type not in ('vz', 'qemu') or
                profile not in ('substrate', 'storage') or (profile == 'storage' and vm_type != 'qemu')):
            raise RuntimeError('owned VM root or run identity differs')
        for name in ('h', 'l', 'd'):
            path = root / name
            metadata = path.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700 or
                    metadata.st_uid != os.getuid()):
                raise RuntimeError('owned VM environment directory differs')
        self.root = root
        self.vm_type = vm_type
        self.profile = profile
        self.names = [run_id + '-' + str(number) for number in range(3)]
        self.env = os.environ.copy()
        self.env.pop('DOCKER_CONTEXT', None)
        self.env.pop('QEMU_SYSTEM_AARCH64', None)
        self.env.update(COLIMA_HOME=str(root / 'h'), LIMA_HOME=str(root / 'l'),
                        DOCKER_CONFIG=str(root / 'd'), DOCKER_HOST='unix://' + str(root / 'h/q/docker.sock'))
        self.stage = 'preflight'
        self.commands = []
        self.children = []

    def command(self, arguments):
        child = subprocess.Popen(arguments, env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        self.children.append(child)
        try:
            output, error = child.communicate()
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            child.stdout.close()
            child.stderr.close()
        self.commands.append({'stage': self.stage, 'exit': child.returncode,
                              'stdout_bytes': len(output), 'stderr_bytes': len(error),
                              'stderr_sha256': hashlib.sha256(error).hexdigest()})
        if child.returncode:
            raise RuntimeError('owned disk fixture command failed at ' + self.stage)
        return output

    def colima(self, *arguments):
        return self.command([TOOLS['colima'], '-p', 'q', *arguments])

    def run(self, consumer=None):
        """Caller must finally delete the entire exact owned VM and root."""
        if (self.profile == 'storage') != callable(consumer):
            raise RuntimeError('storage profile requires its explicit native consumer')
        versions = {'colima': self.command([TOOLS['colima'], 'version']).decode(),
                    'lima': self.command([TOOLS['lima'], '--version']).decode()}
        if (not versions['colima'].startswith('colima version 0.10.3\n') or
                versions['lima'].strip() != 'limactl version 2.2.1'):
            raise RuntimeError('reviewed VM tooling version changed')
        if self.vm_type == 'qemu':
            for tool, prefix in [('/opt/homebrew/bin/qemu-system-aarch64', b'QEMU emulator version 11.1.2\n'),
                                 ('/opt/homebrew/bin/qemu-img', b'qemu-img version 11.1.2\n')]:
                if not self.command([tool, '--version']).startswith(prefix):
                    raise RuntimeError('reviewed QEMU tooling version changed')
        config_path = self.root / 'l/colima-q/lima.yaml'
        socket_path = self.root / 'h/q/docker.sock'
        if (any(path.is_symlink() for path in (config_path, config_path.parent, socket_path.parent)) or
                not socket_path.resolve().is_relative_to(self.root) or
                not stat.S_ISSOCK(socket_path.stat().st_mode) or socket_path.stat().st_uid != os.getuid()):
            raise RuntimeError('owned VM configuration or Docker socket escapes root')
        info = json.loads(self.command([TOOLS['docker'], '--host', self.env['DOCKER_HOST'],
                                       'info', '--format', '{{json .}}']))
        if info['Name'] != 'colima-q' or info['OSType'] != 'linux' or info['Architecture'] != 'aarch64':
            raise RuntimeError('owned Docker daemon identity differs')
        if self.command([TOOLS['docker'], '--host', self.env['DOCKER_HOST'], 'ps', '-aq']).strip():
            raise RuntimeError('owned disk fixture requires an empty Docker daemon')
        before = yaml.safe_load(config_path.read_text())
        require_config(before, self.vm_type, self.profile)
        self.stage = 'stop-owned-vm-before-attachment'
        self.colima('stop')
        identities = {}
        self.stage = 'create-owned-raw-files'
        source = self.root / 'blank-source.raw'
        with source.open('xb') as output:
            output.truncate(DISK_BYTES)
        source_identity = file_identity(source)
        for name in self.names:
            # Lima 2.2.1 accepts --format=raw but creates qcow2; import preserves a real raw source.
            self.command([TOOLS['lima'], 'disk', 'import', name, str(source)])
            paths = list((self.root / 'l').glob('_disk*/' + name + '/datadisk'))
            if len(paths) != 1:
                raise RuntimeError('owned raw disk path is missing or ambiguous')
            identities[name] = {'path': str(paths[0]), **file_identity(paths[0])}
            native = json.loads(self.command([TOOLS['lima'], 'disk', 'list', name, '--json']))
            require_imported_disk(native, name)
        if file_identity(source) != source_identity:
            raise RuntimeError('owned raw source identity changed during import')
        source.unlink()
        self.stage = 'attach-only-owned-raw-files'
        if self.vm_type == 'qemu':
            # Lima's additionalDisks producer omits serials; explicitly assign them for this fixture.
            self.env['QEMU_SYSTEM_AARCH64'] = qemu_arguments(identities, self.root)
        else:
            additions = [{'name': name, 'format': False, 'mount': False} for name in self.names]
            expression = '.additionalDisks += ' + json.dumps(additions)
            self.command([TOOLS['lima'], 'edit', 'colima-q', '--set', expression])
            added_config(before, yaml.safe_load(config_path.read_text()), self.names, self.vm_type)
        self.stage = 'start-owned-vm-with-raw-files'
        self.command([TOOLS['lima'], 'start', 'colima-q'])
        monitor = None
        if self.vm_type == 'qemu':
            if yaml.safe_load(config_path.read_text()) != before:
                raise RuntimeError('explicit QEMU startup changed the VM configuration')
            self.stage = 'read-only-native-qemu-backend-identity'
            monitor = qemu_observation(self.root, identities)
        else:
            added_config(before, yaml.safe_load(config_path.read_text()), self.names, self.vm_type)
        self.stage = 'read-only-guest-disk-inventory'
        raw = self.colima('ssh', '--', 'lsblk', '--json', '--bytes', '--output',
                          'PATH,TYPE,SIZE,SERIAL,FSTYPE,MOUNTPOINTS,PKNAME,MAJ:MIN,RO')
        devices = guest_disks(json.loads(raw), self.names)
        for name, identity in identities.items():
            if file_identity(Path(identity['path'])) != {key: identity[key] for key in ('device', 'inode', 'bytes')}:
                raise RuntimeError('owned backing file changed during attachment')
        self.stage = 'owned-guest-host-prerequisites'
        native = json.loads(self.colima('ssh', '--', 'sh', '-ec',
                                       'printf "{\\"cpus\\":%s,\\"udev\\":%s}\\n" '
                                       '"$(getconf _NPROCESSORS_ONLN)" '
                                       '"$(pgrep -xc \'systemd-udevd|udevd\')"'))
        if native['cpus'] != (8 if self.profile == 'storage' else 2) or native['udev'] != 1:
            raise RuntimeError('owned guest CPU or udev prerequisite differs')
        storage = None
        if consumer is not None:
            self.stage = 'owned-native-storage-consumer'
            storage = consumer(self, json.loads(raw), identities)
            for identity in identities.values():
                if backing_identity(Path(identity['path'])) != {
                        key: identity[key] for key in ('device', 'inode', 'bytes')}:
                    raise RuntimeError('native storage changed its declared backing file identity')
        self.stage = 'stop-owned-vm-after-observation'
        self.colima('stop')
        self.stage = 'detach-only-owned-raw-files'
        if self.vm_type == 'qemu':
            self.env.pop('QEMU_SYSTEM_AARCH64')
        else:
            expression = ('.additionalDisks = ' + json.dumps(before['additionalDisks'])
                          if 'additionalDisks' in before else 'del(.additionalDisks)')
            self.command([TOOLS['lima'], 'edit', 'colima-q', '--set', expression])
        if yaml.safe_load(config_path.read_text()) != before:
            raise RuntimeError('VM configuration did not return to its exact pre-attachment state')
        self.stage = 'delete-owned-raw-files'
        for name, identity in identities.items():
            self.command([TOOLS['lima'], 'disk', 'delete', name])
            if Path(identity['path']).exists():
                raise RuntimeError('owned raw disk remains')
        return {'accepted': True, 'guest_disks': devices, 'blank_backing_identities': identities,
                'qemu_native_identity': monitor,
                'storage': storage,
                'owned_raw_files_removed': True, 'vm_left_stopped_for_parent_cleanup': True,
                'raw_host_devices_attached': False, 'rook_or_csi_executed': consumer is not None,
                'children_reaped': all(child.poll() is not None for child in self.children),
                'commands': self.commands}
