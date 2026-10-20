"""Persistent automatic-service exclusion for the future maintenance controller.

No mutation CLI. The controller must verify the shared Kured owner and host identity.
"""

from contextlib import contextmanager
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


SERVICES = ('dnf-automatic.service', 'dnf-automatic-download.service',
            'dnf-automatic-install.service', 'dnf-automatic-notifyonly.service',
            'dnf5-automatic.service')
STATE = Path('/var/lib/homelab-maintenance')
UNITS = Path('/etc/systemd/system')
GUARD = '90-homelab-maintenance-103.conf'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def safe(path):
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
            'unsafe actor ownership path')


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def exclusive_file(path, data, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.maintenance-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)
        fsync_directory(path.parent)


class Systemd:
    @staticmethod
    def call(*args):
        p = subprocess.run(args, capture_output=True)
        require(p.returncode == 0, 'native actor query failed; retain ownership: ' +
                repr(args) + ' exit ' + str(p.returncode) + ': ' +
                p.stderr.decode(errors='replace')[-1024:])
        return p.stdout

    @contextmanager
    def reference(self, service):
        # A private client reference prevents inactive-unit GC between query clients.
        library = ctypes.CDLL('libsystemd.so.0')
        pointer = ctypes.c_void_p
        library.sd_bus_open_system.argtypes = [ctypes.POINTER(pointer)]
        library.sd_bus_open_system.restype = ctypes.c_int
        library.sd_bus_call_method.argtypes = [pointer, ctypes.c_char_p, ctypes.c_char_p,
                                              ctypes.c_char_p, ctypes.c_char_p, pointer,
                                              ctypes.POINTER(pointer), ctypes.c_char_p]
        library.sd_bus_call_method.restype = ctypes.c_int
        library.sd_bus_message_unref.argtypes = [pointer]
        library.sd_bus_message_unref.restype = pointer
        library.sd_bus_flush_close_unref.argtypes = [pointer]
        library.sd_bus_flush_close_unref.restype = pointer
        bus, reply = pointer(), pointer()
        try:
            result = library.sd_bus_open_system(ctypes.byref(bus))
            require(result >= 0, 'native system bus open failed: ' + str(result))
            result = library.sd_bus_call_method(bus, b'org.freedesktop.systemd1',
                     b'/org/freedesktop/systemd1', b'org.freedesktop.systemd1.Manager',
                     b'RefUnit', None, ctypes.byref(reply), b's', ctypes.c_char_p(service.encode()))
            require(result >= 0, 'native unit reference failed; retain ownership: ' +
                    service + ' errno ' + str(result))
            yield
        finally:
            if reply.value:
                library.sd_bus_message_unref(reply)
            if bus.value:
                library.sd_bus_flush_close_unref(bus)

    def reload(self):
        self.call('systemctl', 'daemon-reload')

    def idle(self, marker):
        for service in SERVICES:
            raw = self.call('systemctl', 'show', service, '-p', 'LoadState', '-p', 'ActiveState',
                            '-p', 'MainPID', '-p', 'ControlPID', '-p', 'Job').decode()
            values = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
            if values.get('LoadState') == 'not-found':
                continue
            require(values.get('LoadState') in ('loaded', 'masked') and
                    values.get('ActiveState') == 'inactive' and
                    values.get('MainPID', '0') == '0' and values.get('ControlPID', '0') == '0' and
                    values.get('Job') in ('', '0'), 'automatic service active or has a pending job')
            if values['LoadState'] == 'masked':
                continue
            with self.reference(service):
                require(raw == self.call('systemctl', 'show', service, '-p', 'LoadState', '-p', 'ActiveState',
                        '-p', 'MainPID', '-p', 'ControlPID', '-p', 'Job').decode(),
                        'automatic service changed while referencing; retain ownership')
                self.condition(service, marker)
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                arguments = (path / 'cmdline').read_bytes().split(b'\0')[:2]
            except FileNotFoundError:
                continue
            require(not any(os.path.basename(a) in (b'dnf', b'dnf5', b'rpm', b'rpmdb', b'packagekitd', b'pkcon')
                            for a in arguments), 'native package actor active; never terminate it')

    def condition(self, service, marker):
        unit = json.loads(self.call('busctl', '--json=short', 'call', 'org.freedesktop.systemd1',
                          '/org/freedesktop/systemd1', 'org.freedesktop.systemd1.Manager',
                          'GetUnit', 's', service))['data'][0]
        require(isinstance(unit, str) and unit.startswith('/org/freedesktop/systemd1/unit/'),
                'unreviewed systemd unit identity')
        conditions = json.loads(self.call('busctl', '--json=short', 'get-property',
                                'org.freedesktop.systemd1', unit,
                                'org.freedesktop.systemd1.Unit', 'Conditions'))['data']
        require(any(len(c) == 5 and c[0] == 'ConditionPathExists' and c[1] is False and
                    c[2] is True and c[3] == str(marker) for c in conditions),
                'effective systemd hold condition absent')


class Hold:
    def __init__(self, systemd, identity, verify_global_owner, state=STATE, units=UNITS):
        self.systemd, self.identity, self.verify_global_owner = systemd, identity, verify_global_owner
        self.state, self.units = Path(state), Path(units)
        safe(self.state)
        safe(self.units)
        unit_info = self.units.stat()
        require(stat.S_ISDIR(unit_info.st_mode) and unit_info.st_uid == os.geteuid() and
                not unit_info.st_mode & 0o022, 'unsafe systemd unit directory')
        self.state.mkdir(mode=0o700, exist_ok=True)
        info = self.state.stat()
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'actor journal directory is not private and owned')
        self.marker = self.state / 'owner.json'
        self.content = ('# Repository-owned maintenance103 automatic-updater exclusion\n'
                        '[Unit]\nConditionPathExists=!' + str(self.marker) + '\n').encode()

    @contextmanager
    def serialized(self):
        descriptor = os.open(self.state / 'controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                    stat.S_IMODE(info.st_mode) == 0o600, 'unsafe actor controller lock')
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def observed(self, token):
        safe(self.marker)
        info = self.marker.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                stat.S_IMODE(info.st_mode) == 0o600, 'unsafe actor journal')
        value = json.loads(self.marker.read_bytes())
        require(set(value) == {'version', 'owner', 'identity', 'revision'} and
                type(value['version']) is int and value['version'] == 1 and
                value['owner'] == token and value['identity'] == self.identity() and
                re.fullmatch('[0-9a-f]{40}', value['revision']) and
                self.verify_global_owner(token) is True, 'actor owner or host identity changed')
        return value

    def guards(self, install):
        for service in SERVICES:
            directory = self.units / (service + '.d')
            safe(directory)
            if install and not directory.exists():
                directory.mkdir(mode=0o755)
                fsync_directory(directory.parent)
            directory_info = directory.stat()
            require(stat.S_ISDIR(directory_info.st_mode) and directory_info.st_uid == os.geteuid() and
                    not directory_info.st_mode & 0o022, 'unsafe maintenance drop-in directory')
            path = directory / GUARD
            safe(path)
            if install and not path.exists():
                exclusive_file(path, self.content, 0o644)
            info = path.stat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                    not info.st_mode & 0o022 and path.read_bytes() == self.content,
                    'foreign or changed maintenance guard; retain ownership')

    def acquire(self, token, expected_identity, revision):
        require(isinstance(token, str) and re.fullmatch(r'homelab-maintenance-103-[0-9a-f-]{36}', token) and
                isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision), 'invalid actor owner or revision')
        require(isinstance(expected_identity, dict) and set(expected_identity) == {'machine', 'root_uuid'} and
                all(isinstance(v, str) and v for v in expected_identity.values()) and
                expected_identity == self.identity() and self.verify_global_owner(token) is True,
                'global owner or expected host identity refused')
        with self.serialized():
            value = {'version': 1, 'owner': token, 'identity': expected_identity, 'revision': revision}
            exclusive_file(self.marker, json.dumps(value, sort_keys=True).encode(), 0o600)
            return self._resume(token)

    def _resume(self, token):
        value = self.observed(token)
        self.guards(install=True)
        self.systemd.reload()
        self.systemd.idle(self.marker)
        require(self.observed(token) == value, 'actor ownership changed while holding')
        return value

    def resume(self, token):
        with self.serialized():
            return self._resume(token)

    def release(self, token, verify_release):
        with self.serialized():
            value = self.observed(token)
            self.guards(install=False)
            self.systemd.idle(self.marker)
            require(verify_release(json.loads(json.dumps(value))) is True, 'actor release gates failed')
            require(self.observed(token) == value, 'actor owner changed during release verification')
            self.systemd.idle(self.marker)
            self.marker.unlink()
            fsync_directory(self.state)
            require(not self.marker.exists(), 'actor release uncertain')
            return value
