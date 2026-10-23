#!/usr/bin/env python3
"""Observe the active synthetic transition using Ceph's exact service-key scope."""

import hashlib
import json
import os
from pathlib import Path
import signal

import ceph_legacy_transition as legacy


SERVICES = {'mon.*', 'mds.*', 'osd.*', 'mgr.*'}
WARNING = 'AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE'
ERRORS = {'AUTH_INSECURE_SERVICE_KEY_TYPE', 'AUTH_INSECURE_SERVICE_TICKETS'}


def service_keys_ready(types, checks):
    rotating = types['rotating']
    if (set(rotating) != SERVICES | {'auth.*'} or
            any(not isinstance(kinds, list) or len(kinds) != 3 or
                any(kind not in {'aes', 'aes256k'} for kind in kinds) for kinds in rotating.values())):
        raise RuntimeError('native rotating family inventory differs')
    if (any(types['entities'].get(entity) != 'aes256k' for entity in legacy.CORE) or
            types['entities'].get('client.ordinary') != 'aes' or set(checks) & ERRORS or
            set(checks) - legacy.AUTH_FINDINGS - {'POOL_NO_REDUNDANCY'}):
        raise RuntimeError('core/client authentication or native health differs')
    ready = all(kind == 'aes256k' for entity in SERVICES for kind in rotating[entity])
    if ready == (WARNING in checks):
        raise RuntimeError('native service-key metadata contradicts warning state')
    return ready


def transition_arguments(run_id):
    return [b'python3', b'-B', b'/work/ceph_legacy_transition.py', b'--internal-runtime',
            b'transition', b'--run-id', run_id.encode()]


def select_runtime(processes, run_id):
    matches = [(pid, start) for pid, start, arguments in processes
               if arguments == transition_arguments(run_id) and pid > 1 and start.isdigit()]
    if len(matches) != 1:
        raise RuntimeError('cannot identify one exact owned transition runtime')
    return matches[0]


def process_identity(path):
    # Field22 follows the closing comm parenthesis; comm may contain spaces.
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    return fields[19], (path / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')


def request_graceful_stop(run_id):
    processes = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            start, arguments = process_identity(path)
        except FileNotFoundError:
            continue
        processes.append((int(path.name), start, arguments))
    pid, start = select_runtime(processes, run_id)
    descriptor = os.pidfd_open(pid)
    try:
        if process_identity(Path('/proc') / str(pid)) != (start, transition_arguments(run_id)):
            raise RuntimeError('owned transition process identity changed')
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    finally:
        os.close(descriptor)
    return {'pid': pid, 'start_ticks': start, 'pidfd_sigterm_requested': True}


def observe(run_id, *, stop_when_ready=False):
    runtime = legacy.Runtime(Path('/work'), run_id)
    baseline = json.loads((runtime.root / 'baseline.json').read_bytes())
    if runtime.identity() != baseline['identity']:
        raise RuntimeError('original synthetic identity or ordinary client changed')
    status = runtime.status()
    checks = sorted(status['health'].get('checks', {}))
    if (not status.get('mgrmap', {}).get('available') or
            status.get('osdmap', {}).get('num_up_osds') != 1 or
            status.get('osdmap', {}).get('num_in_osds') != 1 or
            not status.get('pgmap', {}).get('pgs_by_state') or
            any(row['state_name'] != 'active+clean' for row in status['pgmap']['pgs_by_state'])):
        raise RuntimeError('native transition daemons or PGs not steady')
    monmap = json.loads(runtime.ceph('mon', 'dump', '--format=json'))
    if monmap['auth_service_cipher']['name'] != 'aes256k':
        raise RuntimeError('native service cipher differs')
    types = legacy.key_types(json.loads(runtime.ceph('auth', 'dump-keys', '--format=json')))
    ready = service_keys_ready(types, checks)
    target = runtime.root / 'companion-readback'
    if target.exists() or target.is_symlink():
        raise RuntimeError('companion readback already exists')
    try:
        runtime.client('ordinary', 'get', 'fixture', str(target))
        data = target.read_bytes()
        if (len(data) != baseline['payload_bytes'] or
                hashlib.sha256(data).hexdigest() != baseline['payload_sha256'] or
                runtime.identity() != baseline['identity']):
            raise RuntimeError('complete native object or retained identity differs')
    finally:
        target.unlink(missing_ok=True)
    result = {'accepted': ready, 'checks': checks, 'key_types': types,
              'same_identity_and_complete_io': True, 'payload_bytes': baseline['payload_bytes'],
              'payload_sha256': baseline['payload_sha256'], 'identity': baseline['identity'],
              'auth_family_excluded_by_native_warning_contract': True,
              'production_or_nas_changes': False}
    if ready and stop_when_ready:
        result['original_runtime_stop'] = request_graceful_stop(run_id)
    return result
