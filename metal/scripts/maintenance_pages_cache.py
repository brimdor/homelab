#!/usr/bin/env python3
"""Restore Pages Canary's original image to its scheduled node during Issue 103."""

import argparse
import json
from pathlib import Path
import subprocess

from maintenance_coordination import JOURNAL, LOCK, require
from maintenance_growlithe_images import (
    CAPACITY, PROTECTED_NIBBLE_SOURCE, bindings,
)
from maintenance_nibble_artifact import RECEIVE_PROGRAM, REGISTER_PROGRAM, stream
from maintenance_production_node import remote


OWNER = 'homelab-maintenance-103-1c844363-2bac-4e15-90f5-6139f5624d5c'
VALUES = {
    'IMAGE': '10.0.20.11:32309/pages:2026-07-13-v1-canary',
    'ALIAS': '10.0.20.11:32309/pages@sha256:b2bc2a7eaaad23fb8b6a079a6dca521dd92555f4bd540c1b1d099400f4ac0eb3',
    'DIGEST': 'sha256:b2bc2a7eaaad23fb8b6a079a6dca521dd92555f4bd540c1b1d099400f4ac0eb3',
    'CONFIG': 'sha256:65850e052c7d484c0e58a506792a084acf490cd4a1966daf87736001ff17de95',
    'BLOB_COUNT': 25,
    'SOURCE_HOST': 'totodile',
    'SOURCE_MACHINE': '0f1915a59a124d999d8d68b53f406af1',
    'SOURCE_ROOT': '489f1af8-5d55-4356-8d48-418fcb2069a2',
    'SOURCE_ARCHIVE': '/var/lib/homelab-recovery/maintenance-103/pages-canary-image-b2bc2a7e-local-export/image.tar',
    'SOURCE_ARCHIVE_SHA256': '7e0aa7e078e51b51c1841a3d856c96dc202b176857c439ea5f97d47303ee0050',
    'SOURCE_ARCHIVE_BYTES': 54111232,
    'TARGET_HOST': 'growlithe',
    'TARGET_MACHINE': 'a26cbcc990c044dea41fbf4f957f453d',
    'TARGET_ROOT': '710e2dca-691e-4123-a867-4994b9c6e612',
    # Keep Growlithe's previously protected recovery-store inventory unchanged.
    'RECOVERY': '/var/lib/homelab-image-recovery/maintenance-103/pages-canary-b2bc2a7e',
    'ARTIFACT': 'maintenance103-pages-canary-b2bc2a7e-growlithe.tar',
}


def check_state(get):
    ds = get('get', 'daemonset', 'kured', '-n', 'kured')
    annotations = ds['metadata'].get('annotations', {})
    lock = json.loads(annotations[LOCK])
    active = json.loads(annotations[JOURNAL])
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            lock['nodeID'] == OWNER and active['owner'] == OWNER and
            active['node'] == 'totodile', 'exact active maintenance owner required')
    for name, uid, cordoned in (
        ('totodile', '83e0e536-e94a-45a1-8dfb-1cedac1e9bd7', True),
        ('growlithe', '50f95b8f-4117-4c1e-84bc-266c5b23bffb', False),
    ):
        node = get('get', 'node', name)
        require(node['metadata']['uid'] == uid and
                bool(node['spec'].get('unschedulable')) == cordoned and
                any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in node['status']['conditions']), 'exact ready node state required')
    deployment = get('get', 'deployment', 'pages-canary', '-n', 'pages-canary')
    containers = deployment['spec']['template']['spec']['containers']
    require(deployment['metadata']['uid'] == '0ff8ede9-76f9-4b25-b303-3bedf46e4793' and
            sum(c['name'] == 'pages-canary' and c['image'] == VALUES['IMAGE'] and
                c.get('imagePullPolicy') == 'IfNotPresent' for c in containers) == 1,
            'declared Pages Canary image changed')
    pod = get('get', 'pod', 'pages-canary-5b5b56cd7f-bx7n6', '-n', 'pages-canary')
    require(pod['metadata']['uid'] == 'e5ac29b5-40f3-488b-b5e3-942b58c8b659' and
            pod['spec']['nodeName'] == 'growlithe' and not pod['metadata'].get('deletionTimestamp'),
            'scheduled recovery Pod identity changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--register-digest', action='store_true')
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    require(subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master',
            'master required')
    path = 'metal/scripts/maintenance_pages_cache.py'
    require(Path(path).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + path]),
            'published recovery source required')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() ==
            subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0],
            'canonical publication differs')

    def get(*argv):
        return json.loads(subprocess.check_output([args.kubectl, *argv, '-o', 'json']))

    check_state(get)
    ceph = json.loads(subprocess.check_output([args.kubectl, 'exec', '-n', 'rook-ceph',
        'deploy/rook-ceph-tools', '--', 'ceph', 'health', '-f', 'json']))
    require(ceph['status'] == 'HEALTH_OK', 'Ceph not HEALTH_OK')
    prefix = bindings(VALUES)
    if args.register_digest:
        result = remote(args, prefix + CAPACITY + REGISTER_PROGRAM, '10.0.20.18')
    else:
        result = stream(args, '10.0.20.17', prefix + PROTECTED_NIBBLE_SOURCE,
                        prefix + CAPACITY + RECEIVE_PROGRAM, '10.0.20.18')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
