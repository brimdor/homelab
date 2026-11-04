#!/usr/bin/env python3
"""Cold Zot capture and disconnected native restore qualification for Issue 103."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import urllib.request


ROOT = Path('/recovery')
POINT = ROOT / 'zot-2.1.17-cold-20261103-a'
SOURCE = Path('/source')
CLIENT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def tree(root):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
                'recovery refuses symlinks and special files')
        require(info.st_dev == root.stat().st_dev, 'recovery crosses a device')
        record = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid,
                  'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns,
                  'kind': 'directory' if path.is_dir() else 'file',
                  'xattrs': {key: os.getxattr(path, key).hex() for key in os.listxattr(path)
                             if key != 'security.selinux'}}
        if path.is_file():
            record.update(bytes=info.st_size, sha256=digest(path))
        result[str(path.relative_to(root))] = record
    return result


def clone(source, destination):
    require(not destination.exists(), 'preserve existing recovery material')
    shutil.copytree(source, destination, symlinks=False)
    for path in [destination, *destination.rglob('*')]:
        original = source / path.relative_to(destination)
        info = original.stat()
        os.chown(path, info.st_uid, info.st_gid)


def write(path, value):
    with path.open('x') as target:
        os.fchmod(target.fileno(), 0o600)
        json.dump(value, target, sort_keys=True)
        target.flush()
        os.fsync(target.fileno())
    fd = os.open(path.parent, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)


def capture():
    require(os.geteuid() == 0 and os.statvfs(SOURCE).f_flag & os.ST_RDONLY,
            'capture requires an enforced read-only source')
    require(not POINT.exists(), 'existing point requires inspection, never overwrite')
    records = tree(SOURCE)
    size = sum(r.get('bytes', 0) for r in records.values())
    require(shutil.disk_usage(ROOT).free > size * 3 + len(records) * 16384,
            'recovery volume cannot hold backup and both isolated restores')
    POINT.mkdir(mode=0o700)
    baseline = POINT / 'baseline'
    clone(SOURCE, baseline)
    require(tree(baseline) == records and tree(SOURCE) == records,
            'cold source or captured bytes changed')
    write(POINT / 'manifest.json', records)
    write(POINT / 'capture.json', {'accepted': True, 'bytes': size, 'entries': len(records),
          'manifest_sha256': digest(POINT / 'manifest.json'), 'source_read_only': True})
    for version in ('old', 'new'):
        restored = POINT / ('restore-' + version)
        clone(baseline, restored)
        require(tree(restored) == records, 'isolated full reconstruction differs')
    print(json.dumps({'captured': True, 'bytes': size, 'entries': len(records)}), flush=True)


def request(port, path, method='GET'):
    with CLIENT.open(urllib.request.Request('http://127.0.0.1:' + str(port) + path,
                     method=method, headers={'Accept': 'application/vnd.oci.image.manifest.v1+json, '
                     'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, '
                     'application/vnd.docker.distribution.manifest.list.v2+json'}), timeout=30) as response:
        require(response.status == 200, 'restored registry read failed')
        return response.read(), response.headers


def qualify(port):
    end = time.monotonic() + 600
    while True:
        try:
            request(port, '/readyz')
            break
        except OSError:
            require(time.monotonic() < end, 'native Zot did not become ready')
            time.sleep(1)
    count = blobs = tags = 0
    baseline = POINT / 'baseline'
    for index in sorted(baseline.rglob('index.json')):
        if 'blobs' in index.relative_to(baseline).parts:
            continue
        data = json.loads(index.read_bytes())
        require(data.get('schemaVersion') == 2 and isinstance(data.get('manifests'), list),
                'unexpected registry repository index')
        repo = str(index.parent.relative_to(baseline))
        pending = list(data['manifests'])
        seen = set()
        while pending:
            descriptor = pending.pop()
            key = descriptor['digest']
            require(key.startswith('sha256:') and len(key) == 71, 'unsupported content digest')
            if key in seen:
                continue
            seen.add(key)
            raw, _ = request(port, '/v2/' + repo + '/manifests/' + key)
            require('sha256:' + hashlib.sha256(raw).hexdigest() == key,
                    'native restored manifest digest differs')
            manifest = json.loads(raw)
            pending.extend(manifest.get('manifests', []))
            for blob in ([manifest['config']] if 'config' in manifest else []) + manifest.get('layers', []):
                _, headers = request(port, '/v2/' + repo + '/blobs/' + blob['digest'], 'HEAD')
                require(int(headers['Content-Length']) == blob['size'], 'restored blob size differs')
                blobs += 1
            tag = descriptor.get('annotations', {}).get('org.opencontainers.image.ref.name')
            if tag:
                tagged, _ = request(port, '/v2/' + repo + '/manifests/' + tag)
                require(hashlib.sha256(tagged).digest() == hashlib.sha256(raw).digest(),
                        'restored tag resolves to a different manifest')
                tags += 1
            count += 1
    require(count > 0 and blobs > 0 and tags > 0, 'native restore covered no registry content')
    return {'manifest_reads': count, 'blob_heads': blobs, 'tag_reads': tags}


def acceptance():
    require(json.loads((POINT / 'capture.json').read_text())['accepted'], 'capture not accepted')
    results = {version: qualify(port) for version, port in [('old', 5001), ('new', 5002)]}
    require(results['old'] == results['new'], 'native versions expose different captured content')
    require(tree(POINT / 'baseline') == json.loads((POINT / 'manifest.json').read_text()),
            'protected baseline changed during qualification')
    write(POINT / 'restore-accepted.json', {'accepted': True, 'versions': results,
          'manifest_sha256': digest(POINT / 'manifest.json'), 'gc_disabled': True,
          'isolated_loopback_only': True})
    print(json.dumps({'accepted': True, 'versions': results, 'gc_disabled': True}), flush=True)


if __name__ == '__main__':
    require(len(sys.argv) == 2 and sys.argv[1] in ('capture', 'acceptance'), 'invalid operation')
    {'capture': capture, 'acceptance': acceptance}[sys.argv[1]]()
