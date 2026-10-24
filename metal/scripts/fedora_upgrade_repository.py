#!/usr/bin/env python3
"""Serve only hash-bound public Fedora packages to an isolated upgrade fixture."""

import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET

from fedora_ceph_repository import NS, safe_path


ARCHIVE = 'https://ftp-stud.hs-esslingen.de/pub/Mirrors/archive.fedoraproject.org/fedora/linux/'
CURRENT = 'https://dl.fedoraproject.org/pub/fedora/linux/'
BASES = {str(release) + '-' + kind: origin + path for release, origin in (
    (39, ARCHIVE), (41, ARCHIVE), (43, CURRENT), (44, CURRENT)) for kind, path in (
    ('base', 'releases/' + str(release) + '/Everything/x86_64/os/'),
    ('updates', 'updates/' + str(release) + '/Everything/x86_64/'))}


def fetch(base, relative, destination, expected=None):
    if base not in BASES.values():
        raise RuntimeError('foreign Fedora upgrade repository')
    safe_path(relative, 'repodata' if relative.startswith('repodata/') else 'Packages')
    if destination.exists() or any(path.is_symlink() for path in (destination, *destination.parents)):
        raise RuntimeError('upgrade repository output already exists or is redirected')
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(base + relative, timeout=90) as response, destination.open('xb') as output:
            if response.status != 200 or response.url != base + relative:
                raise RuntimeError('Fedora upgrade response changed origin or path')
            while block := response.read(4 * 1024 * 1024):
                output.write(block)
                digest.update(block)
        if expected is not None and digest.hexdigest() != expected:
            raise RuntimeError('Fedora upgrade artifact checksum differs')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def mirror(root, name):
    if name not in BASES:
        raise RuntimeError('foreign Fedora upgrade release')
    base = BASES[name]
    directory = root / name
    directory.mkdir(mode=0o700)
    repomd = directory / 'repodata/repomd.xml'
    files = {'repodata/repomd.xml': fetch(base, 'repodata/repomd.xml', repomd)}
    primary = None
    for record in ET.parse(repomd).getroot().findall('r:data', NS):
        relative = safe_path(record.find('r:location', NS).attrib['href'], 'repodata')
        checksum = record.find('r:checksum', NS)
        if checksum.attrib['type'] != 'sha256' or not re.fullmatch('[0-9a-f]{64}', checksum.text or ''):
            raise RuntimeError('unsupported upgrade metadata checksum')
        if relative not in files:
            files[relative] = fetch(base, relative, directory / relative, checksum.text)
        elif files[relative] != checksum.text:
            raise RuntimeError('ambiguous upgrade metadata identity')
        if record.attrib['type'] == 'primary':
            if primary is not None:
                raise RuntimeError('duplicate upgrade primary metadata')
            primary = directory / relative
    if primary is None:
        raise RuntimeError('upgrade primary metadata absent')
    raw = directory / 'primary.xml'
    try:
        if primary.suffix == '.gz':
            with gzip.open(primary, 'rb') as source, raw.open('xb') as output:
                shutil.copyfileobj(source, output)
        elif primary.suffix == '.zst':
            with raw.open('xb') as output:
                subprocess.run(['zstd', '-dc', str(primary)], stdout=output, check=True)
        else:
            raise RuntimeError('unsupported upgrade metadata compression')
        packages = {}
        for _event, package in ET.iterparse(raw, events=('end',)):
            if package.tag != '{' + NS['p'] + '}package':
                continue
            if package.find('p:arch', NS).text in ('x86_64', 'noarch'):
                relative = safe_path(package.find('p:location', NS).attrib['href'], 'Packages')
                checksum = package.find('p:checksum', NS)
                if (relative in packages or checksum.attrib['type'] != 'sha256' or
                        not re.fullmatch('[0-9a-f]{64}', checksum.text or '')):
                    raise RuntimeError('ambiguous upgrade package identity')
                packages[relative] = checksum.text
            package.clear()
    finally:
        raw.unlink(missing_ok=True)
    return {'base': base, 'files': files, 'packages': packages}


def requested_path(raw, repositories):
    if not isinstance(raw, str) or '?' in raw or '#' in raw or '%' in raw or not raw.startswith('/'):
        raise RuntimeError('foreign upgrade request')
    name, separator, relative = raw[1:].partition('/')
    if not separator or name not in repositories or name not in BASES:
        raise RuntimeError('foreign upgrade repository request')
    safe_path(relative, 'repodata' if relative.startswith('repodata/') else 'Packages')
    record = repositories[name]
    expected = record['files'].get(relative) or record['packages'].get(relative)
    if record['base'] != BASES[name] or expected is None:
        raise RuntimeError('unverified upgrade file request')
    return name, relative, expected


class RepositoryServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, root):
        self.root = Path(root)
        if any(path.is_symlink() for path in (self.root, *self.root.parents)):
            raise RuntimeError('upgrade repository root is redirected')
        self.root.mkdir(mode=0o700)
        self.repositories = {}
        self.requests = []
        self.errors = []
        self.lock = threading.Lock()
        super().__init__(('127.0.0.1', 0), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        self.deliver(False)

    def do_HEAD(self):
        self.deliver(True)

    def deliver(self, head):
        try:
            name, relative, expected = requested_path(self.path, self.server.repositories)
        except RuntimeError:
            self.send_error(404)
            return
        try:
            with self.server.lock:
                path = self.server.root / name / relative
                if not path.exists():
                    fetch(BASES[name], relative, path, expected)
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError('upgrade cache identity changed')
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    while block := source.read(4 * 1024 * 1024):
                        digest.update(block)
                if digest.hexdigest() != expected:
                    raise RuntimeError('upgrade cache checksum differs')
                self.server.requests.append({'repository': name, 'path': relative, 'sha256': expected})
            self.send_response(200)
            self.send_header('Content-Length', str(path.stat().st_size))
            self.send_header('Connection', 'close')
            self.end_headers()
            if not head:
                with path.open('rb') as source:
                    shutil.copyfileobj(source, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            return
        except BaseException as error:
            self.server.errors.append({'repository': name, 'path': relative,
                                       'error': type(error).__name__ + ': ' + str(error)})
            self.close_connection = True
