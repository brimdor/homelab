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
import stat
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
