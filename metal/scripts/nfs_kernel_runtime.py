#!/usr/bin/env python3
"""Exercise only owned loopback NFS in a disconnected enforcing Fedora VM."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys


ROOT = Path('/var/lib/qualification-nfs103')
EXPORT = ROOT / 'export'
MOUNTS = (Path('/mnt/qualification-nfs-a'), Path('/mnt/qualification-nfs-b'))
CONFIG = Path('/etc/exports.d/qualification-nfs103.exports')
VERSION = '7.2.11-200.fc44.x86_64'
OPTIONS = 'hard,nosharecache,local_lock=none,proto=tcp'
CLIENTS = (('qualification-nfs-a', 'q103ha', 'q103ca', '198.18.103.1', '198.18.103.2'),
           ('qualification-nfs-b', 'q103hb', 'q103cb', '198.18.103.5', '198.18.103.6'))
EXPORT_OPTIONS = '(rw,sync,root_squash,no_subtree_check,fsid=0,anonuid=65534,anongid=65534)'


def export_configuration():
    return str(EXPORT) + ' ' + ' '.join(address + EXPORT_OPTIONS for address in
                                       ('127.0.0.1', *(client[4] for client in CLIENTS))) + '\n'


def network_client(client, *args):
    return command('nsenter', '--net=/run/netns/' + client[0], *args)


def prepare_clients():
    records = []
    for name, host, peer, server, address in CLIENTS:
        if Path('/run/netns', name).exists() or Path('/sys/class/net', host).exists():
            raise RuntimeError('preexisting synthetic NFS network client')
        command('ip', 'netns', 'add', name)
        command('ip', 'link', 'add', host, 'type', 'veth', 'peer', 'name', peer)
        command('ip', 'link', 'set', peer, 'netns', name)
        command('ip', 'address', 'add', server + '/30', 'dev', host)
        command('ip', 'link', 'set', host, 'up')
        client = (name, host, peer, server, address)
        network_client(client, 'ip', 'link', 'set', 'lo', 'up')
        network_client(client, 'ip', 'address', 'add', address + '/30', 'dev', peer)
        network_client(client, 'ip', 'link', 'set', peer, 'up')
        identifier = 'qualification-nfs103-' + name[-1]
        observed = json.loads(network_client(client, sys.executable, '-B', '-c',
            "import json,pathlib,sys; p=pathlib.Path('/sys/fs/nfs/net/nfs_client/identifier');"
            "assert not p.read_text().strip();p.write_text(sys.argv[1]);"
            "print(json.dumps({'identifier':p.read_text().strip(),'namespace':pathlib.Path('/proc/self/ns/net').readlink().as_posix()}))",
            identifier))
        routes = json.loads(network_client(client, 'ip', '-j', 'route'))
        links = json.loads(network_client(client, 'ip', '-j', 'link'))
        if (observed['identifier'] != identifier or len(routes) != 1 or
                routes[0].get('dev') != peer or routes[0].get('prefsrc') != address or
                routes[0].get('dst') != ('198.18.103.0/30' if name.endswith('a') else '198.18.103.4/30') or
                {row['ifname'] for row in links} != {'lo', peer}):
            raise RuntimeError('synthetic NFS network client identity or routes differ')
        records.append({**observed, 'server': server, 'address': address, 'routes': routes})
    if len({row['namespace'] for row in records}) != 2:
        raise RuntimeError('synthetic NFS clients share a network namespace')
    return records


def cleanup_clients():
    if mounted():
        raise RuntimeError('refuse network cleanup while NFS mounts remain')
    for client in reversed(CLIENTS):
        name, host, peer, server, address = client
        if command('ip', 'netns', 'pids', name):
            raise RuntimeError('synthetic NFS network client has active processes')
        rows = json.loads(command('ip', '-j', 'address', 'show', 'dev', host))
        if (len(rows) != 1 or rows[0]['ifname'] != host or
                {row['local'] for row in rows[0]['addr_info'] if row['family'] == 'inet'} != {server}):
            raise RuntimeError('owned NFS veth identity changed')
        command('ip', 'link', 'delete', host)
        command('ip', 'netns', 'delete', name)
        if Path('/run/netns', name).exists() or Path('/sys/class/net', host).exists():
            raise RuntimeError('owned NFS network client remains')


def command(*args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError('native NFS command failed ' + json.dumps({
            'command': list(args), 'exit': result.returncode,
            'stderr': result.stderr.decode(errors='replace')[-4096:]}))
    return result.stdout.decode().strip()


def metadata(path):
    value = path.stat()
    return {'uid': value.st_uid, 'gid': value.st_gid, 'mode': stat.S_IMODE(value.st_mode)}


def corpus(version):
    return {f'{version}:{writer}:{number:03d}:' + hashlib.sha256(
        f'Issue103:{version}:{writer}:{number}'.encode()).hexdigest()
        for writer in ('a', 'b') for number in range(100)}


def verify_corpus(data, version):
    lines = data.decode().splitlines()
    if len(lines) != 200 or set(lines) != corpus(version) or not data.endswith(b'\n'):
        raise RuntimeError('complete NFS corpus mismatch')
    return hashlib.sha256(data).hexdigest()


def require_mount(row, version):
    target = row.get('target')
    if target not in tuple(map(str, MOUNTS)):
        raise RuntimeError('foreign NFS mount target')
    source = CLIENTS[tuple(map(str, MOUNTS)).index(target)][3] + ':/' if version == '4.1' else '127.0.0.1:' + str(EXPORT)
    options = set(row.get('options', '').split(','))
    if (row.get('source') != source or row.get('fstype') not in {'nfs', 'nfs4'} or
            not {'vers=' + version, 'hard', 'nosharecache', 'local_lock=none', 'proto=tcp'} <= options or
            not row.get('maj:min') or 'soft' in options or 'nolock' in options):
        raise RuntimeError('foreign NFS mount or unsafe protocol/cache/lock options')
    return row['maj:min']


def identity():
    if (os.geteuid() != 0 or socket.gethostname() != 'qualification-fedora44' or
            command('uname', '-r') != VERSION or
            'VERSION_ID=44' not in Path('/etc/os-release').read_text() or
            Path('/sys/fs/selinux/enforce').read_text().strip() != '1'):
        raise RuntimeError('native NFS requires the exact enforcing Fedora fixture')
    for address in ('10.0.20.50', '10.0.40.3', '1.1.1.1'):
        try:
            with socket.create_connection((address, 443), timeout=2):
                pass
        except OSError:
            pass
        else:
            raise RuntimeError('native NFS fixture has an external route')
    for path in (ROOT, CONFIG, *MOUNTS):
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise RuntimeError('owned NFS path has a symlink')


def run_user(source, *args):
    result = subprocess.run([sys.executable, '-B', '-c', source, *map(str, args)],
                            user=1000, group=1000, extra_groups=[], capture_output=True)
    if result.returncode:
        raise RuntimeError('synthetic UID1000 operation failed ' + result.stderr.decode(errors='replace')[-4096:])
    return result.stdout


def snapshot():
    return {str(path.relative_to(EXPORT)): metadata(path)
            for version in ('3', '4.1') for path in
            (EXPORT / version, EXPORT / version / 'marker', EXPORT / ('backup-' + version),
             EXPORT / ('denied-' + version))}


def prepare():
    if ROOT.exists() or CONFIG.exists() or any(path.exists() for path in MOUNTS):
        raise RuntimeError('preexisting owned NFS fixture path')
    if command('exportfs', '-s'):
        raise RuntimeError('preexisting NFS export in fresh VM')
    ROOT.mkdir(mode=0o755)
    EXPORT.mkdir(mode=0o755)
    for path in MOUNTS:
        path.mkdir(mode=0o755)
    for version in ('3', '4.1'):
        data = EXPORT / version
        data.mkdir(mode=0o2770)
        os.chown(data, 1000, 1000)
        data.chmod(0o2770)
        marker = data / 'marker'
        marker.write_bytes(b'preserved synthetic ownership\n')
        os.chown(marker, 1000, 1000)
        marker.chmod(0o600)
        backup = EXPORT / ('backup-' + version)
        backup.mkdir(mode=0o2770)
        os.chown(backup, 65534, 65534)
        backup.chmod(0o2770)
        (EXPORT / ('denied-' + version)).mkdir(mode=0o755)
    before = snapshot()
    (ROOT / 'metadata.json').write_text(json.dumps(before))
    CONFIG.parent.mkdir(exist_ok=True)
    CONFIG.write_text(export_configuration())
    command('systemctl', 'enable', '--now', 'rpcbind.service', 'nfs-server.service')
    command('exportfs', '-ra')
    return {'prepared': True, 'export': command('exportfs', '-s'), 'metadata': before,
            'selinux_booleans': command('getsebool', 'nfs_export_all_ro', 'nfs_export_all_rw'),
            'export_context': command('ls', '-Zd', str(EXPORT)),
            'nfs_utils': command('rpm', '-q', 'nfs-utils')}


def mounted():
    rows = json.loads(command('findmnt', '-J', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN'))['filesystems']
    result = {}
    def visit(row):
        if row['target'] in map(str, MOUNTS):
            if row['target'] in result:
                raise RuntimeError('duplicate owned NFS mount')
            result[row['target']] = row
        for child in row.get('children', []):
            visit(child)
    for row in rows:
        visit(row)
    return result


def unmount_owned(version):
    for path in reversed(MOUNTS):
        rows = mounted()
        if str(path) in rows:
            require_mount(rows[str(path)], version)
            command('umount', str(path))
    if mounted():
        raise RuntimeError('owned NFS mount remains')


def lock_and_write(version):
    paths = [path / version / 'corpus' for path in MOUNTS]
    holder = subprocess.Popen([sys.executable, '-B', '-c',
        "import fcntl,sys;f=open(sys.argv[1],'a');fcntl.flock(f,fcntl.LOCK_EX);print('LOCKED',flush=True);sys.stdin.buffer.read(1)",
        str(paths[0])], user=1000, group=1000, extra_groups=[], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if holder.stdout.readline() != b'LOCKED\n':
            raise RuntimeError('native UID1000 lock holder did not acknowledge')
        run_user("import fcntl,sys\nf=open(sys.argv[1],'a')\ntry:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:pass\nelse:raise RuntimeError('remote lock was not excluded')", paths[1])
    finally:
        _, error = holder.communicate(input=b'x')
        if holder.returncode:
            raise RuntimeError('native lock holder failed ' + error.decode(errors='replace')[-4096:])
    source = """import fcntl,hashlib,os,sys
path,version,writer=sys.argv[1:]
with open(path,'a') as output:
 for number in range(100):
  line=f'{version}:{writer}:{number:03d}:'+hashlib.sha256(f'Issue103:{version}:{writer}:{number}'.encode()).hexdigest()+'\\n'
  fcntl.flock(output,fcntl.LOCK_EX)
  try:output.write(line);output.flush();os.fsync(output.fileno())
  finally:fcntl.flock(output,fcntl.LOCK_UN)
"""
    children = []
    try:
        for path, writer in zip(paths, ('a', 'b')):
            children.append(subprocess.Popen([sys.executable, '-B', '-c', source, str(path), version, writer],
                            user=1000, group=1000, extra_groups=[], stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for child in children:
            _, error = child.communicate()
            if child.returncode:
                raise RuntimeError('native writer failed ' + error.decode(errors='replace')[-4096:])
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate()


def exercise(verify_only=False):
    if snapshot() != json.loads((ROOT / 'metadata.json').read_text()):
        raise RuntimeError('prepared NFS metadata changed')
    clients = prepare_clients()
    try:
        return exercise_protocols(verify_only, clients)
    finally:
        cleanup_clients()


def exercise_protocols(verify_only, clients):
    records = []
    for version in ('4.1', '3'):
        source = '127.0.0.1:' + ('/' if version == '4.1' else str(EXPORT))
        try:
            for client, path in zip(CLIENTS, MOUNTS):
                if version == '4.1':
                    network_client(client, 'mount', '-t', 'nfs', '-o', 'vers=' + version + ',' + OPTIONS,
                                   client[3] + ':/', str(path))
                else:
                    command('mount', '-t', 'nfs', '-o', 'vers=' + version + ',' + OPTIONS, source, str(path))
            rows = mounted()
            if set(rows) != set(map(str, MOUNTS)):
                raise RuntimeError('owned NFS alias inventory differs')
            devices = [require_mount(rows[str(path)], version) for path in MOUNTS]
            if len(set(devices)) != 2:
                raise RuntimeError('nosharecache aliases share a superblock')
            if not verify_only:
                backup = MOUNTS[0] / ('backup-' + version) / 'root-marker'
                with backup.open('xb') as output:
                    output.write(b'squashed synthetic root\n')
                    output.flush()
                    os.fsync(output.fileno())
                run_user("import pathlib,sys\ntry:pathlib.Path(sys.argv[1]).write_bytes(b'denied')\nexcept PermissionError:pass\nelse:raise RuntimeError('incompatible ownership unexpectedly writable')",
                         MOUNTS[1] / ('denied-' + version) / 'forbidden')
                lock_and_write(version)
            data = [run_user("import pathlib,sys\nsys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
                             path / version / 'corpus') for path in MOUNTS]
            if data[0] != data[1]:
                raise RuntimeError('NFS aliases disagree on complete corpus')
            digest = verify_corpus(data[0], version)
            for path in MOUNTS:
                owner = json.loads(run_user("import json,pathlib,sys\ns=pathlib.Path(sys.argv[1]).stat()\nprint(json.dumps([s.st_uid,s.st_gid]))",
                                            path / version / 'corpus'))
                if owner != [1000, 1000]:
                    raise RuntimeError('UID1000 corpus ownership differs')
                root_marker = path / ('backup-' + version) / 'root-marker'
                if (metadata(root_marker)['uid'] != 65534 or metadata(root_marker)['gid'] != 65534 or
                        root_marker.read_bytes() != b'squashed synthetic root\n' or
                        (path / ('denied-' + version) / 'forbidden').exists()):
                    raise RuntimeError('root squash or protected metadata/content differs')
                run_user("import pathlib,sys\nassert pathlib.Path(sys.argv[1]).read_bytes()==b'preserved synthetic ownership\\n'",
                         path / version / 'marker')
            records.append({'version': version, 'mounts': rows, 'distinct_superblocks': devices,
                            'full_records': 200, 'corpus_sha256': digest, 'root_squash_uid_gid': [65534, 65534],
                            'after_reboot': verify_only, 'lock_exclusion': not verify_only})
        finally:
            unmount_owned(version)
    if snapshot() != json.loads((ROOT / 'metadata.json').read_text()):
        raise RuntimeError('prepared NFS metadata changed')
    return {'accepted': True, 'protocols': records, 'network_clients': clients, 'mounts_absent': not mounted(),
            'selinux_enforcing': Path('/sys/fs/selinux/enforce').read_text().strip() == '1'}


def cleanup():
    if mounted():
        raise RuntimeError('refuse export cleanup while owned mounts remain')
    expected = export_configuration()
    if CONFIG.read_text() != expected:
        raise RuntimeError('owned export configuration changed')
    for address in ('127.0.0.1', *(client[4] for client in CLIENTS)):
        command('exportfs', '-u', address + ':' + str(EXPORT))
    CONFIG.unlink()
    command('systemctl', 'disable', '--now', 'nfs-server.service', 'rpcbind.service', 'rpcbind.socket')
    if command('exportfs', '-s'):
        raise RuntimeError('owned export remains')
    shutil.rmtree(ROOT)
    for path in MOUNTS:
        path.rmdir()
    return {'exports_absent': True, 'mounts_absent': True, 'owned_data_absent': not ROOT.exists(),
            'configuration_absent': not CONFIG.exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'exercise', 'verify', 'cleanup'))
    args = parser.parse_args()
    identity()
    result = {'prepare': prepare, 'exercise': exercise,
              'verify': lambda: exercise(verify_only=True), 'cleanup': cleanup}[args.phase]()
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
