#!/usr/bin/env python3
"""Observe reviewed Builder processes without rebinding recovery authority."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import signal

import builder_readiness_trace as trace
import builder_recovery as original


# These reviewed identities authorize observation only, never recovery or writer control.
CURRENT = copy.deepcopy(original.SOURCES)
CURRENT['builder'].update(
    pid=4663, start_ticks='76487', pod_uid='f565fc06-9a28-4c32-baa4-60ee78319ed0',
    container_id='9febb66dae60c4085ee1a7e348002280895b134fe83d8f7e619c52a3c9cfabe4')
CURRENT['builder']['stores']['recovery']['device'] = 64256
CURRENT['builder-canary'].update(
    pid=9407, start_ticks='178551', pod_uid='ee480580-6ff9-45fd-8fcc-242faab13339',
    container_id='5023f41ec5471ba3284ccdc8c35e49dcf5d6d09d439670699d8b931985c6e7ad')
CURRENT['builder-canary']['stores']['data']['device'] = 64432
CURRENT['builder-canary']['stores']['recovery']['device'] = 64320

# October 28 replacement: observation only; original recovery profiles stay frozen.
OCTOBER28_CANARY = copy.deepcopy(original.SOURCES['builder-canary'])
OCTOBER28_CANARY.update(
    node='pikachu', pid=148089, start_ticks='1069913',
    pod_uid='7ebe7de7-c9ee-42f6-8abc-0812901fcde7',
    container_id='2cf269f8c21f7a1e14527f42777bbd9f8dbf13e33ed92a331b5353e7a042aa3a')
OCTOBER28_CANARY['stores']['data']['device'] = 64128
OCTOBER28_CANARY['stores']['recovery']['device'] = 64112


def validate_runtime(runtime, namespace, expected):
    status = runtime['status']
    labels = status['labels']
    spec = runtime['info']['runtimeSpec']
    if (status['id'] != expected['container_id'] or status['state'] != 'CONTAINER_RUNNING' or
            status['imageRef'].split('@')[-1] != 'sha256:' + expected['digest'] or
            labels.get('io.kubernetes.pod.uid') != expected['pod_uid'] or
            labels.get('io.kubernetes.pod.namespace') != namespace or
            labels.get('io.kubernetes.container.name') != 'main' or
            runtime['info']['pid'] != expected['pid'] or
            spec['process']['user'] != {'uid': 1000, 'gid': 1000, 'additionalGids': [1000]}):
        raise RuntimeError('reviewed current Builder observation runtime changed')
    return spec


def validate_release(release, bundle_hash, expected):
    if (release.get('sourceRevision') != expected['source_revision'] or
            release.get('gitTree') != expected['git_tree'] or release.get('sourceClean') is not True or
            bundle_hash != expected['bundle_sha256']):
        raise RuntimeError('exact current clean Builder release changed')


def source_identity(namespace, expected=None):
    expected = CURRENT[namespace] if expected is None else expected
    original.common.require_host(expected['node'])
    cid = expected['container_id']
    runtime = json.loads(original.common.command(['/usr/local/bin/k3s', 'crictl', 'inspect', cid]).stdout)
    spec = validate_runtime(runtime, namespace, expected)
    pid = expected['pid']
    process = original.process.process_identity(pid)
    if (process['start_ticks'] != expected['start_ticks'] or process['exe'] != '/usr/local/bin/node' or
            expected['pod_uid'].replace('-', '_') not in process['cgroup']):
        raise RuntimeError('current Builder process identity changed')
    tasks = original.common.command(['/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'ps', cid]).stdout.decode().splitlines()[1:]
    if [int(line.split()[0]) for line in tasks if line.strip()] != [pid]:
        raise RuntimeError('unreviewed additional Builder process')
    root = Path('/proc') / str(pid) / 'root'
    validate_release(json.loads((root / 'app/dist/release.json').read_text()),
                     hashlib.sha256((root / 'app/dist/server/index.js').read_bytes()).hexdigest(), expected)
    for name, store in expected['stores'].items():
        path = (Path('/var/lib/kubelet/pods') / expected['pod_uid'] /
                'volumes/kubernetes.io~csi' / ('pvc-' + store['pvc_uid']) / 'mount')
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise RuntimeError('unsafe current CSI ancestry')
        mounts = [m for m in spec['mounts'] if m['destination'] == '/' + name]
        a, b = path.stat(), (root / name).stat()
        if (len(mounts) != 1 or mounts[0]['source'] != str(path) or
                (a.st_dev, a.st_ino) != (store['device'], store['inode']) or
                (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)):
            raise RuntimeError('current two-store CSI source changed')
    return {'namespace': namespace, 'profile': expected, 'process': process,
            'image': 'registry.eaglepass.io/pointsite-builder@sha256:' + expected['digest']}


def observe(namespace, seconds, expected=None):
    return trace.observe(seconds, identity_provider=lambda: trace.descriptor_identity(source_identity(namespace, expected)),
                         include_intervals=True)


if __name__ == '__main__':
    def cancel(_number, _frame):
        raise InterruptedError('owned current Builder observation cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', choices=sorted(CURRENT), required=True)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--october28-canary', action='store_true',
                        help='Observe only the exact reviewed October 28 Canary process')
    args = parser.parse_args()
    if args.october28_canary and args.namespace != 'builder-canary':
        parser.error('--october28-canary requires --namespace builder-canary')
    observe(args.namespace, args.seconds, OCTOBER28_CANARY if args.october28_canary else None)
