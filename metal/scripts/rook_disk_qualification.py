#!/usr/bin/env python3
"""Qualify three blank virtual disks only in an existing owned disposable VM."""

import hashlib
import json
import os
from pathlib import Path
import re
import signal
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


def file_identity(path):
    metadata = path.lstat()
    observation = {'regular_file': stat.S_ISREG(metadata.st_mode),
                   'owned_by_current_user': metadata.st_uid == os.getuid(),
                   'bytes': metadata.st_size, 'expected_bytes': DISK_BYTES,
                   'symlink': path.is_symlink(),
                   'ancestor_symlink': any(p.is_symlink() for p in path.parents)}
    if (not observation['regular_file'] or not observation['owned_by_current_user'] or
            metadata.st_size != DISK_BYTES or observation['symlink'] or observation['ancestor_symlink']):
        raise DiskIdentityError(observation)
    with path.open('rb') as source:
        first = source.read(512)
        source.seek(-512, 2)
        last = source.read(512)
    if first != bytes(512) or last != bytes(512):
        raise RuntimeError('owned blank disk has nonzero boundary sectors')
    return {'device': metadata.st_dev, 'inode': metadata.st_ino, 'bytes': metadata.st_size}


def require_config(value):
    if (value.get('vmType') != 'vz' or value.get('mounts') or value.get('blockDevices') or
            value.get('cpus') != 2 or value.get('memory') != '2048MiB' or
            value.get('ssh', {}).get('forwardAgent') is not False):
        raise RuntimeError('owned disk fixture VM contract differs')


def added_config(before, after, names):
    require_config(before)
    expected = before | {'additionalDisks': [*(before.get('additionalDisks') or []),
                                           *({'name': name, 'format': False, 'mount': False}
                                             for name in names)]}
    if after != expected:
        raise RuntimeError('VM configuration changed beyond exact raw disk attachment')


def guest_disks(value, names):
    devices = value['blockdevices']
    found = []
    for name in names:
        matches = [row for row in devices if row.get('serial') == 'lima-' + name]
        if len(matches) != 1:
            raise RuntimeError('owned guest disk serial is missing or ambiguous')
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
    def __init__(self, root, run_id):
        metadata = root.lstat()
        if (not root.is_absolute() or not re.fullmatch(r'v-[a-z0-9_]{8}', root.name) or
                not re.fullmatch(r'rook-[a-f0-9]{8}', run_id) or not root.is_dir() or
                stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid() or
                any(p.is_symlink() for p in (root, *root.parents))):
            raise RuntimeError('owned VM root or run identity differs')
        for name in ('h', 'l', 'd'):
            path = root / name
            metadata = path.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700 or
                    metadata.st_uid != os.getuid()):
                raise RuntimeError('owned VM environment directory differs')
        self.root = root
        self.names = [run_id + '-' + str(number) for number in range(3)]
        self.env = os.environ.copy()
        self.env.pop('DOCKER_CONTEXT', None)
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

    def run(self):
        """Caller must finally delete the entire exact owned VM and root."""
        versions = {'colima': self.command([TOOLS['colima'], 'version']).decode(),
                    'lima': self.command([TOOLS['lima'], '--version']).decode()}
        if (not versions['colima'].startswith('colima version 0.10.3\n') or
                versions['lima'].strip() != 'limactl version 2.2.1'):
            raise RuntimeError('reviewed VM tooling version changed')
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
        require_config(before)
        self.stage = 'stop-owned-vm-before-attachment'
        self.colima('stop')
        identities = {}
        self.stage = 'create-owned-raw-files'
        for name in self.names:
            self.command([TOOLS['lima'], 'disk', 'create', name, '--size=8GiB', '--format=raw'])
            paths = list((self.root / 'l').glob('_disk*/' + name + '/datadisk'))
            if len(paths) != 1:
                raise RuntimeError('owned raw disk path is missing or ambiguous')
            identities[name] = {'path': str(paths[0]), **file_identity(paths[0])}
        self.stage = 'attach-only-owned-raw-files'
        additions = [{'name': name, 'format': False, 'mount': False} for name in self.names]
        expression = '.additionalDisks += ' + json.dumps(additions)
        self.command([TOOLS['lima'], 'edit', 'colima-q', '--set', expression])
        after = yaml.safe_load(config_path.read_text())
        added_config(before, after, self.names)
        self.stage = 'start-owned-vm-with-raw-files'
        self.command([TOOLS['lima'], 'start', 'colima-q'])
        added_config(before, yaml.safe_load(config_path.read_text()), self.names)
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
        if native['cpus'] != 2 or native['udev'] != 1:
            raise RuntimeError('owned guest CPU or udev prerequisite differs')
        self.stage = 'stop-owned-vm-after-observation'
        self.colima('stop')
        self.stage = 'delete-owned-raw-files'
        for name, identity in identities.items():
            self.command([TOOLS['lima'], 'disk', 'delete', name])
            if Path(identity['path']).exists():
                raise RuntimeError('owned raw disk remains')
        return {'accepted': True, 'guest_disks': devices, 'blank_backing_identities': identities,
                'owned_raw_files_removed': True, 'vm_left_stopped_for_parent_cleanup': True,
                'raw_host_devices_attached': False, 'rook_or_csi_executed': False,
                'children_reaped': all(child.poll() is not None for child in self.children),
                'commands': self.commands}
