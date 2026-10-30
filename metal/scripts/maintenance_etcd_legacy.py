"""Check an isolated copy of a protected, complete etcd member tree.

The parent transaction must prove a stopped source, consistent off-node transfer,
SOURCE restart and original voter recovery. This module never stops a service.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

import maintenance_actor_hold as actors


VERSION = '3.5.35'
ARCHIVE_URL = ('https://github.com/etcd-io/etcd/releases/download/v3.5.35/'
               'etcd-v3.5.35-linux-amd64.tar.gz')
ARCHIVE_SHA256 = 'ca9f94cdc80be66923ef571d82b128819d0f5f3aa9f01522bafd991618ee29d1'
BINARY_SHA256 = '187249c118c209ad485e7d343aee50751c637329a6051e94e2b2ea3bd5076ac5'
BINARY_BYTES = 17268898
SUCCESS = b'No custom content found in both v2store and WAL records.\n'


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def attributes(path):
    return {key: base64.b64encode(os.getxattr(path, key, follow_symlinks=False)).decode()
            for key in os.listxattr(path, follow_symlinks=False)}


def file_record(path):
    """Read a single owned regular file without following a substituted symlink."""
    actors.safe(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        actors.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                       before.st_nlink == 1 and not before.st_mode & 0o022,
                       'unsafe etcd member file')
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1048576), b''):
            digest.update(chunk)
        xattrs = attributes(path)
        actors.require(identity(os.fstat(source.fileno())) == identity(before),
                       'etcd member file changed while reading')
    return {'kind': 'file', 'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid,
            'gid': before.st_gid, 'size': before.st_size, 'sha256': digest.hexdigest(),
            'identity': identity(before), 'xattrs': xattrs}


def directory_record(path):
    actors.safe(path)
    info = path.stat()
    actors.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
                   not info.st_mode & 0o022, 'unsafe etcd member directory')
    return {'kind': 'directory', 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid, 'identity': identity(info),
            'xattrs': attributes(path)}


def member_manifest(root):
    """Include the entire member tree; missing WAL must never yield a clean check."""
    root = Path(root)
    root_record = directory_record(root)
    member = root / 'member'
    entries = {}
    # Check every directory before descending; do not let rglob traverse unsafe entries.
    def visit(path):
        entries[str(path.relative_to(root))] = directory_record(path)
        for child in sorted(path.iterdir()):
            actors.safe(child)
            info = child.lstat()
            if stat.S_ISDIR(info.st_mode):
                visit(child)
            else:
                actors.require(stat.S_ISREG(info.st_mode), 'special etcd member entry')
                entries[str(child.relative_to(root))] = file_record(child)
        actors.require(directory_record(path) == entries[str(path.relative_to(root))],
                       'etcd member directory changed during traversal')
    visit(member)
    db = entries.get('member/snap/db', {})
    actors.require(db.get('kind') == 'file' and db['size'] > 0,
                   'complete nonempty etcd snap/db required')
    wal = [value for name, value in entries.items()
           if re.fullmatch(r'member/wal/[0-9a-f]{16}-[0-9a-f]{16}\.wal', name)]
    actors.require(wal and all(value['kind'] == 'file' and value['size'] > 0 for value in wal),
                   'complete nonempty etcd WAL required')
    actors.require(directory_record(root) == root_record, 'etcd data root changed during traversal')
    return {'version': 1, 'root': root_record, 'entries': entries}


def contents(manifest):
    """A disposable copy gets its native label; original labels remain in its manifest."""
    return {name: {key: value for key, value in entry.items() if key not in ('identity', 'xattrs')}
            for name, entry in manifest['entries'].items()}


def manifest_sha256(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def copy_member(source, destination, expected):
    """Exclusive copy; preserve partial points for the caller's exact cleanup policy."""
    source, destination = Path(source), Path(destination)
    actors.require(source.is_absolute() and destination.is_absolute() and source != destination and
                   source not in destination.parents and destination not in source.parents,
                   'isolated copy must be outside protected source')
    actors.require(member_manifest(source) == expected, 'protected etcd point changed before copy')
    actors.safe(destination)
    destination.mkdir(mode=0o700)
    for name, entry in expected['entries'].items():
        origin, target = source / name, destination / name
        if entry['kind'] == 'directory':
            target.mkdir(mode=0o700)
            continue
        actors.safe(origin);actors.safe(target)
        source_fd = os.open(origin, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, 'rb') as input_file:
            actors.require(identity(os.fstat(input_file.fileno())) == entry['identity'],
                           'protected etcd source identity changed')
            target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(target_fd, 'wb') as output:
                shutil.copyfileobj(input_file, output, length=1048576)
                output.flush()
                if os.fstat(output.fileno()).st_gid != entry['gid']:
                    os.fchown(output.fileno(), entry['uid'], entry['gid'])
                os.fchmod(output.fileno(), entry['mode']);os.fsync(output.fileno())
            actors.require(identity(os.fstat(input_file.fileno())) == entry['identity'],
                           'protected etcd source changed during copy')
    for name, entry in reversed(list(expected['entries'].items())):
        if entry['kind'] == 'directory':
            path = destination / name
            if path.stat().st_gid != entry['gid']:
                os.chown(path, entry['uid'], entry['gid'])
            path.chmod(entry['mode']);actors.fsync_directory(path)
    actors.fsync_directory(destination)
    actors.require(contents(member_manifest(destination)) == contents(expected),
                   'isolated etcd copy bytes or metadata differ')
    actors.require(member_manifest(source) == expected, 'protected etcd point changed after copy')


def check_copy(protected, expected, tool, scratch_parent, native, run=subprocess.run):
    """Run the pinned native checker once; retain hashes, never raw datastore logs."""
    protected, tool, scratch_parent = map(Path, (protected, tool, scratch_parent))
    actors.require(scratch_parent.is_absolute() and protected.is_absolute() and tool.is_absolute(),
                   'absolute etcd check paths required')
    actors.require(scratch_parent != protected and protected not in scratch_parent.parents,
                   'scratch must be outside protected recovery point')
    for path in (protected, scratch_parent):
        info = directory_record(path)
        actors.require(info['mode'] == 0o700 and
                       native('findmnt', '-n', '-o', 'FSTYPE', '-T', str(path)) == 'ext4',
                       'private ext4 recovery and scratch required for native etcd check')
    original_tool = file_record(tool)
    actors.require(original_tool['sha256'] == BINARY_SHA256 and
                   original_tool['size'] == BINARY_BYTES and original_tool['mode'] & 0o100,
                   'official etcdutl checksum, length or executable mode differs')
    actors.require(member_manifest(protected) == expected, 'protected etcd check binding differs')
    scratch = Path(tempfile.mkdtemp(prefix='etcd-legacy-', dir=scratch_parent))
    scratch.chmod(0o700)
    try:
        isolated = scratch / 'data'
        copy_member(protected, isolated, expected)
        result = run([str(tool), 'check', 'v2store', '--data-dir=' + str(isolated)], capture_output=True)
        actors.require(member_manifest(protected) == expected, 'checker changed protected etcd point')
        actors.require(file_record(tool) == original_tool, 'etcd checker changed during execution')
        receipt = {'accepted': result.returncode == 0 and result.stdout == SUCCESS,
                   'version': VERSION, 'tool_sha256': BINARY_SHA256,
                   'protected_manifest_sha256': manifest_sha256(expected),
                   'checker_exit': result.returncode,
                   'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
                   'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(),
                   'protected_point_unchanged': True, 'one_checker_dispatch': True}
    finally:
        # Only this invocation's exclusive disposable copy; original points are never deleted.
        shutil.rmtree(scratch)
        actors.require(not scratch.exists(), 'owned etcd checker scratch cleanup incomplete')
        actors.fsync_directory(scratch_parent)
    receipt['cleanup'] = {'scratch_absent': True}
    return receipt
