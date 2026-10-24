#!/usr/bin/env python3
"""Mirror verified official Fedora44 metadata for a disconnected Ceph fixture."""

import gzip
import hashlib
import http.client
import time
import urllib.error
from pathlib import PurePosixPath
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET


BASES = {
    'ceph-base': 'https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/',
    'ceph-updates': 'https://dl.fedoraproject.org/pub/fedora/linux/updates/44/Everything/x86_64/',
}
NS = {'r': 'http://linux.duke.edu/metadata/repo', 'p': 'http://linux.duke.edu/metadata/common'}


def safe_path(value, prefix):
    if not isinstance(value, str):
        raise RuntimeError('foreign or unsafe Fedora repository path')
    path = PurePosixPath(value)
    if (not re.fullmatch(r'[A-Za-z0-9._/+~^:-]+', value) or
            path.is_absolute() or '..' in path.parts or str(path) != value or
            len(path.parts) < 2 or path.parts[0] != prefix):
        raise RuntimeError('foreign or unsafe Fedora repository path')
    return value


def retryable_fetch_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (500, 502, 503, 504)
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, (TimeoutError, ConnectionResetError, ConnectionAbortedError,
                               http.client.IncompleteRead))


def fetch_verified(base, relative, destination, expected=None, attempts=None):
    safe_path(relative, 'repodata' if relative.startswith('repodata/') else 'Packages')
    if destination.exists() or any(path.is_symlink() for path in (destination, *destination.parents)):
        raise RuntimeError('Fedora repository output already exists or is redirected')
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 4):
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(base + relative, timeout=90) as response, destination.open('xb') as output:
                if response.status != 200 or response.url != base + relative:
                    raise RuntimeError('official Fedora HTTPS response changed origin or path')
                while block := response.read(4 * 1024 * 1024):
                    output.write(block)
                    digest.update(block)
            if expected is not None and digest.hexdigest() != expected:
                raise RuntimeError('official Fedora artifact checksum differs')
            return digest.hexdigest()
        except BaseException as error:
            destination.unlink(missing_ok=True)
            retry = attempt < 3 and retryable_fetch_error(error)
            if attempts is not None:
                reason = error.reason if isinstance(error, urllib.error.URLError) else error
                attempts.append({'base': base, 'path': relative, 'attempt': attempt,
                                 'error_type': type(error).__name__, 'reason_type': type(reason).__name__,
                                 'http_status': error.code if isinstance(error, urllib.error.HTTPError) else None,
                                 'retrying': retry})
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            if not retry:
                raise
            time.sleep(2)


def fetch(base, relative, destination, expected=None, attempts=None):
    if base not in BASES.values():
        raise RuntimeError('foreign Fedora repository origin')
    return fetch_verified(base, relative, destination, expected, attempts)


def mirror(root, repository, attempts=None):
    attempts = [] if attempts is None else attempts
    first_attempt = len(attempts)
    base = BASES[repository]
    directory = root / repository
    directory.mkdir(mode=0o700)
    repomd = directory / 'repodata/repomd.xml'
    repomd_hash = fetch(base, 'repodata/repomd.xml', repomd, attempts=attempts)
    files = {'repodata/repomd.xml': repomd_hash}
    primary = None
    for record in ET.parse(repomd).getroot().findall('r:data', NS):
        relative = safe_path(record.find('r:location', NS).attrib['href'], 'repodata')
        checksum = record.find('r:checksum', NS)
        if checksum.attrib['type'] != 'sha256' or not re.fullmatch(r'[0-9a-f]{64}', checksum.text or ''):
            raise RuntimeError('unsupported Fedora metadata checksum')
        files[relative] = fetch(base, relative, directory / relative, checksum.text, attempts)
        if record.attrib['type'] == 'primary':
            if primary is not None:
                raise RuntimeError('duplicate Fedora primary metadata')
            primary = directory / relative
    if primary is None:
        raise RuntimeError('Fedora primary metadata missing')
    raw = root / (repository + '-primary.xml')
    if primary.suffix == '.zst':
        with raw.open('xb') as output:
            subprocess.run(['zstd', '-dc', str(primary)], stdout=output, check=True)
    elif primary.suffix == '.gz':
        with gzip.open(primary, 'rb') as source, raw.open('xb') as output:
            import shutil
            shutil.copyfileobj(source, output)
    else:
        raise RuntimeError('unsupported Fedora primary metadata compression')
    packages = {}
    try:
        for _event, package in ET.iterparse(raw, events=('end',)):
            if package.tag != '{' + NS['p'] + '}package':
                continue
            architecture = package.find('p:arch', NS).text
            if architecture in ('x86_64', 'noarch'):
                relative = safe_path(package.find('p:location', NS).attrib['href'], 'Packages')
                checksum = package.find('p:checksum', NS)
                if (checksum.attrib['type'] != 'sha256' or
                        not re.fullmatch(r'[0-9a-f]{64}', checksum.text or '') or relative in packages):
                    raise RuntimeError('ambiguous or unsupported Fedora package identity')
                packages[relative] = checksum.text
            package.clear()
    finally:
        raw.unlink()
    return {'base': base, 'files': files, 'packages': packages, 'transport_attempts': attempts[first_attempt:]}


def selection(url, repositories, guest_root):
    for repository, value in repositories.items():
        prefix = 'file://' + guest_root + '/' + repository + '/'
        if url.startswith(prefix):
            relative = safe_path(url[len(prefix):], 'Packages')
            if relative not in value['packages']:
                break
            return repository, relative, value['packages'][relative]
    raise RuntimeError('native solver selected an unverified package URL')
