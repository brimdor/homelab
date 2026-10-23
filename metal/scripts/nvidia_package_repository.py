#!/usr/bin/env python3
"""Verify the official Fedora44 NVIDIA package inputs for an offline fixture."""

import gzip
import hashlib
from pathlib import PurePosixPath
import re
import urllib.request
import xml.etree.ElementTree as ET

from fedora_ceph_repository import NS


BASE = 'https://developer.download.nvidia.com/compute/cuda/repos/fedora44/x86_64/'
KEY = '73CD9B30.pub'
KEY_SHA256 = '9221458f62030a18d5a28eecf44496016ff9c11548492ac2ce428f75c7513cab'
KEY_FINGERPRINT = '129994480ec63d2789bc98e490dfed2f73cd9b30'


def safe_path(value, metadata=False):
    path = PurePosixPath(value)
    shape = len(path.parts) == 2 and path.parts[0] == 'repodata' if metadata else (
        len(path.parts) == 1 and (value.endswith('.rpm') or value == KEY))
    if (not shape or path.is_absolute() or '..' in path.parts or str(path) != value or
            not re.fullmatch(r'[A-Za-z0-9._+~-]+(?:/[A-Za-z0-9._+~-]+)?', value)):
        raise RuntimeError('unsafe NVIDIA repository path')
    return value


def fetch(relative, destination, expected=None):
    safe_path(relative, relative.startswith('repodata/'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with urllib.request.urlopen(BASE + relative, timeout=90) as response, destination.open('xb') as output:
        if response.status != 200 or response.geturl() != BASE + relative:
            raise RuntimeError('NVIDIA HTTPS origin or path differs')
        while block := response.read(4 * 1024 * 1024):
            output.write(block)
            digest.update(block)
    if expected is not None and digest.hexdigest() != expected:
        raise RuntimeError('NVIDIA artifact hash differs')
    return digest.hexdigest()


def mirror(root):
    directory = root / 'nvidia-vendor'
    directory.mkdir(mode=0o700)
    fetch(KEY, root / KEY, KEY_SHA256)
    repomd = directory / 'repodata/repomd.xml'
    files = {'repodata/repomd.xml': fetch('repodata/repomd.xml', repomd)}
    primary = None
    for record in ET.parse(repomd).getroot().findall('r:data', NS):
        relative = safe_path(record.find('r:location', NS).attrib['href'], True)
        checksum = record.find('r:checksum', NS)
        if (relative in files or checksum.attrib['type'] != 'sha256' or
                not re.fullmatch('[0-9a-f]{64}', checksum.text or '')):
            raise RuntimeError('ambiguous or unsupported NVIDIA metadata')
        files[relative] = fetch(relative, directory / relative, checksum.text)
        if record.attrib['type'] == 'primary':
            if primary is not None or not relative.endswith('.gz'):
                raise RuntimeError('ambiguous or unsupported NVIDIA primary metadata')
            primary = directory / relative
    if primary is None:
        raise RuntimeError('NVIDIA primary metadata missing')
    packages = {}
    with gzip.open(primary, 'rb') as source:
        for _event, package in ET.iterparse(source, events=('end',)):
            if package.tag != '{' + NS['p'] + '}package':
                continue
            if package.find('p:arch', NS).text in ('x86_64', 'noarch'):
                relative = safe_path(package.find('p:location', NS).attrib['href'])
                checksum = package.find('p:checksum', NS)
                if (relative in packages or checksum.attrib['type'] != 'sha256' or
                        not re.fullmatch('[0-9a-f]{64}', checksum.text or '')):
                    raise RuntimeError('ambiguous or unsupported NVIDIA package')
                packages[relative] = checksum.text
            package.clear()
    return {'base': BASE, 'files': files, 'packages': packages}


def selection(url, value, guest_root):
    prefix = 'file://' + guest_root + '/nvidia-vendor/'
    if not url.startswith(prefix):
        raise RuntimeError('foreign NVIDIA solver URL')
    relative = safe_path(url[len(prefix):])
    if relative not in value['packages']:
        raise RuntimeError('unverified NVIDIA solver package')
    return relative, value['packages'][relative]
