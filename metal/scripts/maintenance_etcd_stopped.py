"""Read-only proof for the parent's owned etcd 3.5 SOURCE stop interval."""

import hashlib
import os
from pathlib import Path
import stat

from maintenance_actor_hold import require, safe
from maintenance_k3s_binary import record
from maintenance_k3s_contract import SHA256


SOURCE = 'v1.33.10+k3s1'
PROPERTIES = ('ActiveState', 'SubState', 'MainPID', 'ControlPID', 'Job', 'KillMode', 'Delegate')


def observe(native, before, identity, confirm_owned, root=Path('/')):
    """No ownership relaxation or service action; the parent supplies exact owner checks."""
    root = Path(root)
    require(callable(confirm_owned) and confirm_owned() is True, 'exact stopped-source owner required')
    require(before['version'] == SOURCE and before['binary_sha256'] == SHA256[SOURCE] and
            before['pid'] > 1 and before['selinux'] == 'Enforcing', 'stopped-source baseline differs')

    def path(name):
        result = root / name.lstrip('/')
        safe(result)
        return result

    def service():
        raw = native('systemctl', 'show', 'k3s', *[v for name in PROPERTIES for v in ('-p', name)])
        rows = raw.splitlines()
        require(len(rows) == len(PROPERTIES) and all('=' in row for row in rows), 'incomplete stopped unit proof')
        value = dict(row.split('=', 1) for row in rows)
        require(set(value) == set(PROPERTIES) and value['ActiveState'] == 'inactive' and
                value['SubState'] == 'dead' and value['MainPID'] == value['ControlPID'] == '0' and
                value['Job'] in ('', '0') and value['KillMode'] == 'process' and value['Delegate'] == 'yes',
                'SOURCE unit is not stopped and idle')
        return value

    first = service()
    require(path('/etc/machine-id').read_text().strip() == identity['machine'] and
            native('findmnt', '-n', '-o', 'UUID', '/') == identity['root_uuid'] and
            path('/proc/sys/kernel/random/boot_id').read_text().strip() == before['boot'],
            'stopped-source host identity changed')
    require(native('getenforce') == 'Enforcing' and path('/sys/fs/selinux/enforce').read_text().strip() == '1',
            'stopped-source SELinux enforcement changed')
    require(record(path('/usr/local/bin/k3s'))['sha256'] == SHA256[SOURCE], 'stopped SOURCE executable changed')
    configs = before['configs']
    require({'/etc/rancher/k3s/config.yaml', '/etc/systemd/system/k3s.service'} <= set(configs),
            'required stopped-source configuration missing')
    actual = [path(name) for name in ('/etc/rancher/k3s/config.yaml', '/etc/systemd/system/k3s.service',
                                     '/etc/systemd/system/k3s.service.env') if path(name).exists()]
    actual += sorted(path('/etc/rancher/k3s/config.yaml.d').glob('*.yaml'))
    actual += sorted(path('/etc/systemd/system/k3s.service.d').glob('*'))
    require({'/' + str(p.relative_to(root)) for p in actual} == set(configs),
            'stopped-source configuration membership changed')
    for name, digest in configs.items():
        require(name in ('/etc/rancher/k3s/config.yaml', '/etc/systemd/system/k3s.service',
                         '/etc/systemd/system/k3s.service.env') or
                name.startswith(('/etc/rancher/k3s/config.yaml.d/', '/etc/systemd/system/k3s.service.d/')),
                'unreviewed stopped-source configuration path')
        target = path(name);info = target.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o022 and
                hashlib.sha256(target.read_bytes()).hexdigest() == digest, 'stopped-source configuration changed')
    require(hashlib.sha256(native('systemctl', 'cat', 'k3s').encode()).hexdigest() == before['unit_sha256'],
            'stopped-source effective unit changed')
    for row in native('ss', '-H', '-lnt').splitlines():
        fields = row.split()
        require(len(fields) >= 5 and not fields[3].endswith(':2379'), 'etcd TCP listener remains')
    for process in path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        name = os.path.basename(args[0])
        require(name != b'etcd' and not (name == b'k3s' and len(args) > 1 and args[1] == b'server'),
                'independent etcd or K3s server process remains')
    require(service() == first and confirm_owned() is True, 'stopped-source service or ownership changed')
    return {'source': SOURCE, 'original_identity': identity, 'original_boot': before['boot'],
            'source_binary_sha256': SHA256[SOURCE], 'configuration_unchanged': True,
            'unit': first, 'SELinux': 'Enforcing', 'no_etcd_listener_or_process': True, 'accepted': True}
