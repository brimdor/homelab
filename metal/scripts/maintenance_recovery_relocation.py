"""Relocate three historical Issue 103 recovery points without losing their bytes.

The workstation relays SSH pipes only. NAS, live data, current K3s recovery points,
and unrelated backups are outside this exact migration.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import subprocess


ROOT = Path('/var/lib/homelab-recovery/maintenance-103')
HOSTS = {
    'pikachu': ('10.0.20.14', '0a7daf8b33244d9d85f46223c3582da9', '76e53a95-725a-4430-9d7b-a8db413f3997'),
    'growlithe': ('10.0.20.18', 'a26cbcc990c044dea41fbf4f957f453d', '710e2dca-691e-4123-a867-4994b9c6e612'),
}
POINTS = {
    'radarr-complete-files-20261020-1718': 'a6aa9e3fed4b15c27e1e5b71c53a0c2cc3a12b75e4816cca322ac21cb7ddf72e',
    'prometheus-monitoring-20261020-quiesced': 'b9d2bedfa37e07b9eb3d5736337294e465c53b5cb44a9af5521a7f5d4e4e1a58',
    'prometheus-monitoring-20261020-retained-current': '570984782b09c0668ebfe520484c0db46bb854f2ea4643d60d2b9735e50dfdae',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def safe(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink in recovery path')


def destination(name):
    require(name in POINTS, 'unreviewed receiver recovery name')
    return ROOT / (name + '-relocated-20261101')


def native(node):
    _, machine, root_uuid = HOSTS[node]
    require(os.geteuid() == 0 and socket.gethostname() == node and
            Path('/etc/machine-id').read_text().strip() == machine and
            subprocess.check_output(['findmnt', '-n', '-o', 'UUID', '/'], text=True).strip() == root_uuid,
            'recovery host identity differs')
    safe(ROOT)
    require(ROOT.is_dir() and ROOT.stat().st_uid == 0 and
            stat.S_IMODE(ROOT.stat().st_mode) == 0o700 and
            subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(ROOT)], text=True).strip() == 'ext4',
            'private local ext4 recovery root required')


def record(path):
    safe(path)
    before = path.lstat()
    kind = 'directory' if stat.S_ISDIR(before.st_mode) else 'file'
    require(stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            'recovery tree contains a link or special file')
    require(before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == (0o700 if kind == 'directory' else 0o600),
            'recovery tree is not root-private')
    value = {'kind': kind, 'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid,
             'gid': before.st_gid, 'mtime_ns': before.st_mtime_ns,
             'xattrs': {n: hashlib.sha256(os.getxattr(path, n, follow_symlinks=False)).hexdigest()
                        for n in sorted(os.listxattr(path, follow_symlinks=False))}}
    if kind == 'file':
        digest = hashlib.sha256()
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
            require(os.fstat(source.fileno()) == before, 'recovery file changed before open')
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        value.update(bytes=before.st_size, sha256=digest.hexdigest())
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), 'recovery entry changed while reading')
    return value


def inventory(point):
    safe(point)
    require(point.is_dir(), 'recovery point missing')
    entries = {'': record(point)}
    for parent, directories, files in os.walk(point, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            relative = str(path.relative_to(point))
            require(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', relative) and
                    path.lstat().st_dev == point.stat().st_dev, 'unsafe or cross-device recovery entry')
            entries[relative] = record(path)
    return entries


def unused(point):
    prefix = str(point)
    mounts = subprocess.check_output(['findmnt', '-r', '-n', '-o', 'TARGET'], text=True).splitlines()
    require(not any(p == prefix or p.startswith(prefix + '/') for p in mounts), 'recovery point is mounted')
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            paths = [proc / 'cwd', proc / 'root', *list((proc / 'fd').iterdir())]
            for path in paths:
                try:
                    target = os.readlink(path)
                    require(not (target == prefix or target.startswith(prefix + '/')), 'recovery point has a live consumer')
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    pass
            maps = (proc / 'maps').read_text()
            require(not any(line.split()[-1].startswith(prefix + '/') for line in maps.splitlines() if line.split()),
                    'recovery point has a mapped consumer')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass


def inspect_point(node, name):
    native(node)
    require(name in POINTS, 'unreviewed historical recovery point')
    point = ROOT / name if node == 'pikachu' else destination(name)
    unused(point)
    tree = inventory(point)
    require(tree['verified.json']['sha256'] == POINTS[name], 'original recovery manifest differs')
    manifest = json.loads((point / 'verified.json').read_bytes())
    actual = {n.removeprefix('data/'): {'bytes': v['bytes'], 'sha256': v['sha256']}
              for n, v in tree.items() if n.startswith('data/') and v['kind'] == 'file'}
    if name.startswith('radarr-'):
        original = {str(index): {'bytes': value['bytes'], 'sha256': value['sha256']}
                    for index, (_, value) in enumerate(sorted(manifest['tree'].items())) if value['kind'] == 'file'}
        restored = json.loads((point / 'restore.json').read_bytes())
        require(restored['accepted'] is True and restored['manifest_sha256'] == POINTS[name],
                'original Radarr restore acceptance differs')
    else:
        original = manifest['files']
    require(actual == original, 'recovery payload differs from its original verified manifest')
    return {'name': name, 'tree_sha256': hashlib.sha256(canonical(tree)).hexdigest(),
            'manifest_sha256': POINTS[name], 'file_bytes': sum(v.get('bytes', 0) for v in tree.values()),
            'entries': len(tree), 'allocated_bytes': int(subprocess.check_output(['du', '-s', '-x', '-B1', str(point)], text=True).split()[0])}


def write_json(path, value):
    with path.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(canonical(value)); output.flush(); os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def send(expected):
    require(inspect_point('pikachu', expected['name']) == expected, 'source recovery point changed')
    result = subprocess.run(['tar', '--format=pax', '--numeric-owner', '--acls', '--xattrs',
                             '--xattrs-include=*', '--selinux', '-C', str(ROOT / expected['name']), '-cf', '-', '.'])
    require(result.returncode == 0 and inspect_point('pikachu', expected['name']) == expected,
            'source changed or transfer failed; preserve source')


def receive(expected):
    native('growlithe')
    require(expected['name'] in POINTS and expected['manifest_sha256'] == POINTS[expected['name']], 'unreviewed receiver point')
    point = destination(expected['name'])
    safe(point)
    require(not point.exists(), 'receiver point already exists; inspect rather than replay')
    space = os.statvfs(ROOT)
    require(space.f_bavail * space.f_frsize - expected['allocated_bytes'] > space.f_blocks * space.f_frsize // 5,
            'receiver would cross verified kubelet image-GC low threshold')
    point.mkdir(mode=0o700)
    result = subprocess.run(['tar', '--numeric-owner', '--same-owner', '--same-permissions', '--acls',
                             '--xattrs', '--xattrs-include=*', '--selinux', '-C', str(point), '-xf', '-'])
    require(result.returncode == 0, 'transfer incomplete; preserve source and partial receiver')
    tree = inventory(point)
    require(hashlib.sha256(canonical(tree)).hexdigest() == expected['tree_sha256'], 'receiver bytes or metadata differ')
    for path in [p for p in point.rglob('*') if p.is_file()]:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    for path in sorted([point, *[p for p in point.rglob('*') if p.is_dir()]], key=lambda p: len(p.parts), reverse=True):
        fd = os.open(path, os.O_DIRECTORY); os.fsync(fd); os.close(fd)
    return {'accepted': True, 'receiver': 'growlithe', 'point': str(point), 'expected': expected}


def retire_source(expected, receipt):
    native('pikachu')
    require(receipt == {'accepted': True, 'receiver': 'growlithe', 'point': str(destination(expected['name'])), 'expected': expected},
            'independent complete receiver readback required')
    require(inspect_point('pikachu', expected['name']) == expected, 'source changed before relocation commit')
    point = ROOT / expected['name']
    tree = inventory(point)
    require(hashlib.sha256(canonical(tree)).hexdigest() == expected['tree_sha256'], 'source inventory differs')
    marker = ROOT / ('relocation-' + expected['name'] + '.json')
    write_json(marker, {**receipt, 'source': 'pikachu', 'source_path': str(point),
                        'disposition': 'verified protected relocation; original bytes retained on receiver'})
    # The durable mapping exists before the first unlink. Failures preserve the receiver and mapping.
    unused(point)
    for name, entry in tree.items():
        if entry['kind'] == 'file':
            path = point / name
            require(record(path) == entry, 'source file changed before unlink')
            path.unlink()
    for name, entry in sorted(tree.items(), key=lambda item: len(Path(item[0]).parts), reverse=True):
        if name and entry['kind'] == 'directory':
            (point / name).rmdir()
    write_json(point / 'relocated.json', json.loads(marker.read_bytes()))
    require({p.name for p in point.iterdir()} == {'relocated.json'}, 'source relocation incomplete')
    return {'accepted': True, 'source_marker': str(marker), 'retained_receiver': receipt['point'],
            'tree_sha256': expected['tree_sha256']}


def remote(args, node, source, expression, *, stdin=None, stream=False):
    import maintenance_production_node as production
    program = source + '\n' + (expression if stream else 'print(json.dumps(' + expression + '))') + '\n'
    return subprocess.Popen(production.ssh(args, HOSTS[node][0]) + ['python3 -B -c ' + shlex.quote(program)],
                            stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def copy(args, source, expected):
    sender = receiver = None
    try:
        sender = remote(args, 'pikachu', source, 'send(' + repr(expected) + ')', stream=True)
        receiver = remote(args, 'growlithe', source, 'receive(' + repr(expected) + ')', stdin=sender.stdout)
        sender.stdout.close()
        output, _ = receiver.communicate(); sender.wait()
        require(sender.returncode == receiver.returncode == 0,
                'relocation copy failed; preserve source and partial receiver; inspect before continuation')
        receipt = json.loads(output)
        expected_receipt = {'accepted': True, 'receiver': 'growlithe', 'point': str(destination(expected['name'])), 'expected': expected}
        require(receipt == expected_receipt, 'copy receipt differs')
        readback = remote(args, 'growlithe', source, "inspect_point('growlithe', " + repr(expected['name']) + ')')
        try:
            output, _ = readback.communicate()
            require(readback.returncode == 0, 'independent receiver readback failed; retain source')
            value = json.loads(output)
            require({k: v for k, v in value.items() if k != 'allocated_bytes'} ==
                    {k: v for k, v in expected.items() if k != 'allocated_bytes'},
                    'independent receiver readback differs; retain source')
        finally:
            if readback.poll() is None:
                readback.terminate(); readback.wait()
        return receipt
    finally:
        for process in (receiver, sender):
            if process is not None and process.poll() is None:
                process.terminate(); process.wait()
