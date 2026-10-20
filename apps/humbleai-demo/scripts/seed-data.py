#!/usr/bin/env python3
"""Seed only an empty retained demo volume from its exact protected final point."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import quote


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
        raise RuntimeError('recovery input is not a regular file')


def seed(database, manifest, target, expected):
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise RuntimeError('exact final manifest hash required')
    regular(database); regular(manifest)
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('protected manifest hash differs')
    proof = json.loads(raw)
    source = proof['source']; key = proof['encryption_key']; capture = proof['capture']
    if (proof['format'] != 1 or proof['cluster_uid'] != '7ff226e0-565a-4610-8a3e-97e7e87355a3' or
            source['namespace'] != 'humbleai-demo' or source['container'] != 'main' or
            source['pod_uid'] != 'fae3621d-e4da-41a8-8087-e1768c066053' or
            source['node'] != 'growlithe' or source['data_storage'] != 'container-layer' or
            source['database'] != '/app/server/data/humbleai.db' or
            source['image'] != 'registry.eaglepass.io/humbleai@sha256:fcf08c14538753af9539a66d2c3551e07445c664970a392da4928b80cb9fe542' or
            key['uid'] != '8d3d65c0-e6da-4dc8-9ad6-1b0ddc20e595' or
            key['secret'] != 'secrets' or key['field'] != 'openai-encryption-key' or
            key['environment'] != 'OPENAI_ENCRYPTION_KEY' or key['bytes'] <= 0 or
            not re.fullmatch(r'[a-f0-9]{64}', key['sha256']) or
            capture['snapshot']['schema_sha256'] != '34ea8a6d7cbe469a4b5d67dc3bf1a03223e823b64814379950df02b6085c68a2'):
        raise RuntimeError('reviewed source, schema or key identity differs')
    if (type(capture['bytes']) is not int or capture['bytes'] <= 0 or
            database.stat().st_size != capture['bytes'] or digest(database) != capture['sha256']):
        raise RuntimeError('protected database hash or size differs')
    if target.is_symlink() or not target.is_dir():
        raise RuntimeError('target is not the retained volume directory')
    entries = list(target.iterdir())
    if any(p.name != 'lost+found' or p.is_symlink() or not p.is_dir() or any(p.iterdir()) for p in entries):
        raise RuntimeError('retained volume is not empty; never overwrite data')
    partial = target / '.humbleai-final-seed.partial'
    destination = target / 'humbleai.db'
    owned_partial = None
    try:
        with partial.open('xb') as output:
            owned_partial = os.fstat(output.fileno()).st_ino
            os.fchmod(output.fileno(), 0o600)
            with database.open('rb') as original:
                while block := original.read(1048576):
                    output.write(block)
            output.flush(); os.fsync(output.fileno())
        if partial.stat().st_size != capture['bytes'] or digest(partial) != capture['sha256']:
            raise RuntimeError('seed readback differs from protected source')
        uri = 'file:' + quote(str(partial), safe='/') + '?mode=ro&immutable=1'
        db = sqlite3.connect(uri, uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('seed integrity or foreign keys failed')
        finally:
            db.close()
        os.link(partial, destination)  # Atomic no-overwrite publication, even if another writer appeared.
        partial.unlink()
        directory = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if digest(destination) != capture['sha256'] or digest(database) != capture['sha256'] or manifest.read_bytes() != raw:
            raise RuntimeError('seed or protected original changed after publication')
        return {'accepted': True, 'manifest_sha256': expected, 'database_sha256': capture['sha256'],
                'bytes': capture['bytes'], 'snapshot': capture['snapshot'], 'source_pod_uid': source['pod_uid']}
    finally:
        if owned_partial is not None and partial.exists() and partial.lstat().st_ino == owned_partial:
            partial.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if not os.path.ismount('/data'):
        raise RuntimeError('retained volume is not mounted')
    print(json.dumps(seed(Path('/original/database.sqlite'), Path('/original/verified.json'),
                          Path('/data'), args.manifest_sha256)))
