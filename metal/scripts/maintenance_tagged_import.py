"""Copy a verified digest-only OCI import with its existing declared tag.

The caller owns host, recovery-receipt, staging-entry and deployment checks.
This converter never changes the source or invokes a runtime or registry.
"""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tarfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink)


def safe_path(value):
    path = Path(value)
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
            'absolute nonsymlink archive path required')
    return path


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def checked_file(path, expected_hash):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                not before.st_mode & 0o022, 'unsafe import file')
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == expected_hash and
                identity(os.fstat(stream.fileno())) == identity(before) and
                identity(path.stat()) == identity(before), 'import file changed or hash differs')
    return before


def stage(source, candidate, staged, intent, original_sha256, candidate_sha256):
    """Atomically replace one import link; recover only proven unsubmitted work.

    Caller must serialize this operation and bind host, published input profile,
    converter receipt and absence of concurrent node maintenance beforehand.
    """
    source, candidate, staged, intent = map(safe_path, (source, candidate, staged, intent))
    require(len({source, candidate, staged, intent}) == 4 and intent.parent == candidate.parent,
            'distinct import and intent paths required')
    original = checked_file(source, original_sha256)
    converted = checked_file(candidate, candidate_sha256)
    require((original.st_dev, original.st_ino) != (converted.st_dev, converted.st_ino),
            'candidate aliases protected source')
    temporary = safe_path(staged.parent / ('.' + staged.name + '.tagged-import-pending'))
    binding = {'version': 1, 'source': str(source), 'candidate': str(candidate), 'staged': str(staged),
               'original_sha256': original_sha256, 'candidate_sha256': candidate_sha256,
               'candidate_inode': [converted.st_dev, converted.st_ino]}
    if intent.exists():
        info = intent.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                info.st_mode & 0o777 == 0o600 and info.st_nlink == 1, 'unsafe staging intent')
        raw = intent.read_bytes(); recorded = json.loads(raw)
        require(raw == json.dumps(recorded, sort_keys=True, separators=(',', ':')).encode() and
                {k: recorded.get(k) for k in binding} == binding and
                set(recorded) == set(binding) | {'original_identity'}, 'staging intent differs')
        expected_identity = recorded['original_identity']
    else:
        require(staged.samefile(source) and original.st_nlink == 2 and converted.st_nlink == 1 and
                not temporary.exists(), 'original staging link or candidate ownership differs')
        expected_identity = list(identity(original))
        recorded = {**binding, 'original_identity': expected_identity}
        with os.fdopen(os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(json.dumps(recorded, sort_keys=True, separators=(',', ':')).encode())
            stream.flush(); os.fsync(stream.fileno())
        sync_directory(intent.parent)
    require(list(identity(original))[:4] == expected_identity[:4], 'protected original identity differs')
    if staged.samefile(candidate):
        require(original.st_nlink == 1 and converted.st_nlink == 2 and not temporary.exists(),
                'accepted import link ownership differs')
        checked_file(staged, candidate_sha256)
        return {**binding, 'already_staged': True, 'mutation_performed': False}
    require(staged.samefile(source) and list(identity(original)) == expected_identity and
            original.st_nlink == 2, 'uncertain staging outcome; original dispatch cannot be proven absent')
    if temporary.exists():
        require(temporary.samefile(candidate) and converted.st_nlink == 2,
                'foreign pending import link')
    else:
        require(converted.st_nlink == 1, 'candidate has an unknown link')
        os.link(candidate, temporary)
        sync_directory(staged.parent)
    require(list(identity(checked_file(source, original_sha256))) == expected_identity and
            staged.samefile(source) and temporary.samefile(candidate), 'staging inputs changed before replacement')
    checked_file(temporary, candidate_sha256)
    os.replace(temporary, staged)
    sync_directory(staged.parent)
    after = checked_file(source, original_sha256)
    require(list(identity(after))[:4] == expected_identity[:4] and after.st_nlink == 1 and
            staged.samefile(candidate) and candidate.stat().st_nlink == 2 and not temporary.exists(),
            'atomic import replacement differs')
    checked_file(staged, candidate_sha256)
    return {**binding, 'already_staged': False, 'mutation_performed': True}


def convert(source, destination, profile, original_sha256):
    """Exclusive separate copy; only index reference metadata may change."""
    source, destination = safe_path(source), safe_path(destination)
    require(re.fullmatch('[a-f0-9]{64}', original_sha256) is not None,
            'original archive hash required')
    digest, config = profile['digest'], profile['config']
    require(all(re.fullmatch('sha256:[a-f0-9]{64}', v) for v in (digest, config)),
            'immutable manifest and configuration required')
    tagged = profile['declared'].split('@', 1)[0]
    require('@' in profile['declared'] and profile['declared'].split('@', 1)[1] == digest and
            ':' in tagged.rsplit('/', 1)[-1] and
            re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tagged.rsplit(':', 1)[1]) and
            tagged.rsplit(':', 1)[0] + '@' + digest == profile['image'],
            'existing declared tag and immutable image differ')
    require(not destination.exists(), 'destination already exists; observe instead')
    created = None
    try:
        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as origin:
            before = os.fstat(origin.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                    not before.st_mode & 0o022, 'unsafe source archive')
            require(hashlib.file_digest(origin, 'sha256').hexdigest() == original_sha256,
                    'original archive hash differs')
            origin.seek(0)
            with tarfile.open(fileobj=origin, mode='r:') as archive:
                members = archive.getmembers()
                names = {m.name for m in members}
                require(len(names) == len(members) and all(m.isfile() and not m.pax_headers
                        and (m.name in ('oci-layout', 'index.json') or
                             re.fullmatch('blobs/sha256/[a-f0-9]{64}', m.name)) for m in members),
                        'unexpected, duplicate or unsafe archive member')
                def metadata(name):
                    member = archive.getmember(name)
                    require(0 < member.size <= 1048576, 'OCI metadata exceeds bound')
                    return json.load(archive.extractfile(member))
                require(metadata('oci-layout') == {'imageLayoutVersion': '1.0.0'},
                        'OCI layout differs')
                index = metadata('index.json')
                require(index.get('schemaVersion') == 2 and len(index.get('manifests', [])) == 1,
                        'one OCI manifest required')
                descriptor = index['manifests'][0]
                require(descriptor.get('digest') == digest and
                        descriptor.get('platform') == {'architecture': 'amd64', 'os': 'linux'} and
                        descriptor.get('annotations') == {'org.opencontainers.image.ref.name': profile['image']},
                        'original import descriptor differs')
                manifest_name = 'blobs/sha256/' + digest[7:]
                manifest = metadata(manifest_name)
                require(manifest.get('schemaVersion') == 2 and manifest['config']['digest'] == config and
                        descriptor['size'] == archive.getmember(manifest_name).size and
                        descriptor['mediaType'] == manifest['mediaType'], 'manifest identity differs')
                descriptors = [{'digest': digest, 'size': descriptor['size']},
                               manifest['config'], *manifest['layers']]
                expected = {}
                for value in descriptors:
                    require(re.fullmatch('sha256:[a-f0-9]{64}', value['digest']) and
                            type(value['size']) is int and value['size'] >= 0 and
                            expected.get(value['digest'], value['size']) == value['size'],
                            'invalid or conflicting blob descriptor')
                    expected[value['digest']] = value['size']
                require(len(expected) == profile['blobs'] and names == {'oci-layout', 'index.json'} |
                        {'blobs/sha256/' + key[7:] for key in expected}, 'blob graph differs')
                for key, size in expected.items():
                    member = archive.getmember('blobs/sha256/' + key[7:])
                    with archive.extractfile(member) as stream:
                        require(member.size == size and hashlib.file_digest(stream, 'sha256').hexdigest() == key[7:],
                                'original blob content differs')
                descriptor['annotations']['org.opencontainers.image.ref.name'] = tagged
                encoded = json.dumps(index, separators=(',', ':')).encode()
                descriptor_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor_fd, 'wb') as output:
                    created = os.fstat(output.fileno())
                    require((created.st_dev, created.st_ino) != (before.st_dev, before.st_ino),
                            'destination aliases protected source')
                    with tarfile.open(fileobj=output, mode='w|', format=tarfile.USTAR_FORMAT) as target:
                        for member in members:
                            entry = copy.copy(member)
                            if member.name == 'index.json':
                                entry.size = len(encoded)
                                target.addfile(entry, io.BytesIO(encoded))
                            else:
                                with archive.extractfile(member) as stream:
                                    target.addfile(entry, stream)
                    output.flush(); os.fsync(output.fileno())
                require(identity(os.fstat(origin.fileno())) == identity(before) and
                        identity(source.stat()) == identity(before), 'source changed during conversion')
                with destination.open('rb') as output:
                    result_hash = hashlib.file_digest(output, 'sha256').hexdigest()
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {'original_sha256': original_sha256, 'archive_sha256': result_hash,
                'manifest': digest, 'config': config, 'tagged_reference': tagged,
                'verified_blobs': len(expected), 'original_unchanged': True}
    except BaseException:
        if created is not None and destination.exists():
            current = destination.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                destination.unlink()
        raise


def native_host(inputs):
    """Only the already-qualified Pikachu runtime and local ext4 paths."""
    require(os.geteuid() == 0 and socket.gethostname() == inputs['node'] == 'pikachu',
            'tagged import host differs')
    require(Path('/etc/machine-id').read_text().strip() == inputs['identity']['machine'] ==
            '0a7daf8b33244d9d85f46223c3582da9' and
            subprocess.check_output(['findmnt', '-n', '-o', 'UUID', '/'], text=True).strip() ==
            inputs['identity']['root_uuid'] == '76e53a95-725a-4430-9d7b-a8db413f3997',
            'tagged import root identity differs')
    require(not Path('/var/lib/homelab-maintenance/owner.json').exists(),
            'finish native node maintenance before image import repair')
    executable = Path('/usr/local/bin/k3s')
    require(inputs['runtime_sha256'] == '1572f0f23bd5a844bd405b71875877aacacc7ab79e279d3d73735654c37c7735',
            'unreviewed native import runtime hash')
    checked_file(executable, inputs['runtime_sha256'])
    require(inputs['runtime_version'] == 'v1.33.13+k3s2' and
            subprocess.check_output([str(executable), '--version'], text=True).splitlines()[0].split()[2] ==
            inputs['runtime_version'], 'tagged import runtime differs')
    pid = int(subprocess.check_output(['systemctl', 'show', 'k3s', '-p', 'MainPID', '--value'], text=True))
    require(pid > 1 and subprocess.check_output(['systemctl', 'is-active', 'k3s'], text=True).strip() == 'active',
            'tagged import runtime is not active')
    return {'pid': pid, 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def write_private(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        stream.flush(); os.fsync(stream.fileno())
    sync_directory(path.parent)


def read_private(path):
    safe_path(path); info = path.stat()
    require(info.st_uid == os.geteuid() and info.st_mode & 0o777 == 0o600 and info.st_nlink == 1 and
            stat.S_ISREG(info.st_mode), 'unsafe private import record')
    raw = path.read_bytes(); value = json.loads(raw)
    require(raw == json.dumps(value, sort_keys=True, separators=(',', ':')).encode(),
            'noncanonical private import record')
    return value


def native_aliases(profile):
    tagged = profile['declared'].split('@', 1)[0]
    result = {}
    for reference in (profile['image'], tagged):
        rows = subprocess.check_output(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'images', 'list',
                                        'name==' + reference], text=True).splitlines()[1:]
        require(len(rows) <= 1 and (rows or reference == tagged), 'canonical image alias disappeared')
        if rows:
            fields = rows[0].split()
            require(len(fields) >= 6 and fields[0] == reference and fields[2] == profile['digest'],
                    'native tag or canonical alias names another image')
            result[reference] = {'digest': fields[2], 'CRI_pinned': 'io.cri-containerd.pinned=pinned' in fields[-1],
                                 'K3s_pinned': 'io.cattle.k3s.pinned=pinned' in fields[-1]}
    return result


def repair(operation, key, inputs, profile):
    """Prepare, stage once, or observe one published native import."""
    require(operation in ('prepare', 'stage', 'observe') and key in inputs['images'] and
            re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', key), 'unreviewed tagged import operation')
    runtime = native_host(inputs)
    native_aliases(profile)
    expected = inputs['images'][key]
    original = safe_path(expected['original']); staged = safe_path(expected['staged'])
    base = safe_path(Path('/var/lib/homelab-recovery/maintenance-103'))
    require(original == base / ('squirtle-image-' + key + '-' + profile['digest'][7:15]) / 'image.tar' and
            staged == Path('/var/lib/rancher/k3s/agent/images') /
            ('maintenance103-squirtle-' + key + '-' + profile['digest'][7:15] + '.tar'),
            'published tagged import paths differ')
    require(subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(base)], text=True).strip() == 'ext4' and
            subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(staged.parent)], text=True).strip() == 'ext4',
            'local ext4 import storage required')
    checked_file(original.parent / 'verified.json', expected['verified_receipt_sha256'])
    before = checked_file(original, expected['archive_sha256'])
    require((before.st_dev, before.st_ino, before.st_size) ==
            tuple(expected[k] for k in ('device', 'inode', 'bytes')), 'published original archive identity differs')
    point = safe_path(base / ('tagged-import-' + key + '-' + profile['digest'][7:15]))
    if not point.exists():
        require(operation == 'prepare', 'prepare tagged import before staging')
        point.mkdir(mode=0o700); sync_directory(base)
    require(point.is_dir() and point.stat().st_uid == os.geteuid() and point.stat().st_mode & 0o777 == 0o700,
            'unsafe tagged import recovery directory')
    import fcntl
    with os.fdopen(os.open(point / 'controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate, record = point / 'image.tar', point / 'prepared.json'
        if operation == 'prepare' and not record.exists():
            require(staged.samefile(original) and before.st_nlink == expected['links'] == 2 and
                    not candidate.exists(), 'original staged input changed; inspect prior preparation')
            converted = convert(original, candidate, profile, expected['archive_sha256'])
            prepared = {'version': 1, 'key': key, 'expected': expected, 'profile': profile,
                        'converted': converted, 'runtime': runtime}
            write_private(record, prepared)
        prepared = read_private(record)
        require(prepared['version'] == 1 and prepared['key'] == key and prepared['expected'] == expected and
                prepared['profile'] == profile and prepared['runtime'] == runtime and
                prepared['converted']['original_sha256'] == expected['archive_sha256'],
                'prepared tagged import binding differs')
        checked_file(candidate, prepared['converted']['archive_sha256'])
        if operation == 'prepare':
            return {'prepared': True, 'key': key, 'point': str(point), 'converted': prepared['converted']}
        watch_path = point / 'import-watch.json'
        if not watch_path.exists():
            require(operation == 'stage' and not (point / 'stage-intent.json').exists() and
                    staged.samefile(original), 'import observation must precede staging')
            rows = subprocess.check_output(['journalctl', '-u', 'k3s', '-n', '1', '-o', 'json',
                                            '--no-pager'], text=True).splitlines()
            require(len(rows) == 1, 'exact native import journal cursor required')
            last = json.loads(rows[0])
            require(last['_BOOT_ID'] == runtime['boot'].replace('-', '') and last.get('__CURSOR'),
                    'native import journal belongs to another boot')
            write_private(watch_path, {'runtime': runtime, 'cursor': last['__CURSOR']})
        watch = read_private(watch_path)
        require(watch['runtime'] == runtime and watch.get('cursor'), 'native import observation binding differs')
        if operation == 'observe':
            intent = read_private(point / 'stage-intent.json')
            require(intent['source'] == str(original) and intent['candidate'] == str(candidate) and
                    intent['staged'] == str(staged) and intent['original_sha256'] == expected['archive_sha256'] and
                    intent['candidate_sha256'] == prepared['converted']['archive_sha256'] and
                    list(identity(before))[:4] == intent['original_identity'][:4] and
                    before.st_nlink == 1 and staged.samefile(candidate) and candidate.stat().st_nlink == 2,
                    'native import staged mapping differs')
            checked_file(staged, prepared['converted']['archive_sha256'])
            rows = subprocess.check_output(['journalctl', '-u', 'k3s', '--after-cursor', watch['cursor'],
                                            '-o', 'json', '--no-pager'], text=True).splitlines()
            success = [row for row in map(json.loads, rows) if
                       row.get('_BOOT_ID') == runtime['boot'].replace('-', '') and
                       'Imported 1 images from ' + str(staged) + ' in ' in row.get('MESSAGE', '')]
            require(success, 'supported native importer success not observed after staging cursor')
            aliases = native_aliases(profile)
            require(len(aliases) == 2 and all(v['CRI_pinned'] and v['K3s_pinned'] for v in aliases.values()),
                    'native imported references are not both pinned')
            require(native_host(inputs) == runtime, 'native runtime changed during import observation')
            return {'accepted': True, 'key': key, 'runtime': runtime, 'aliases': aliases,
                    'archive_sha256': prepared['converted']['archive_sha256'],
                    'import_journal_cursor': success[-1]['__CURSOR'], 'original_unchanged': True}
        require(native_host(inputs) == runtime, 'native runtime changed before staging')
        native_aliases(profile)
        result = stage(original, candidate, staged, point / 'stage-intent.json',
                       expected['archive_sha256'], prepared['converted']['archive_sha256'])
        require(native_host(inputs) == runtime, 'native runtime changed during staging')
        return {'staged': True, 'key': key, 'point': str(point), 'converted': prepared['converted'],
                'runtime': runtime, 'result': result, 'native_import_acceptance_pending': True}
