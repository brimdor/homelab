#!/usr/bin/env python3
"""Remove only the verified Fedora 43 vendor cache after final Sprigatito release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys


OWNER = 'homelab-maintenance-103-53ab87f8-7c92-4724-877e-bfe8b73ddbe7'
CACHE = 'nvidia-vendor-local-fedora43-595.112.07'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def remove_verified_cache(cache, expected, inventory):
    """Refuse unknown content; unlink only files in the accepted private manifest."""
    require(cache.name == CACHE and not cache.is_symlink() and
            cache.stat().st_uid == os.geteuid() and stat.S_IMODE(cache.stat().st_mode) == 0o700,
            'vendor cache identity or permissions differ')
    observed = inventory(cache)
    require(observed == expected, 'vendor cache content differs')
    members = list(cache.rglob('*'))
    require(all(not p.is_symlink() and
                (p.is_dir() or p.is_file() and p.stat().st_nlink == 1) for p in members),
            'unsafe vendor cache member')
    allocated = sum(p.stat().st_blocks * 512 for p in [cache, *members])
    for path in sorted(members, key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    cache.rmdir()
    require(not cache.exists(), 'vendor cache cleanup incomplete')
    return allocated


def native(context):
    import maintenance_actor_hold as actors
    import maintenance_hop_journal as hops
    import maintenance_nvidia as gpu
    import maintenance_safe_release as release
    from maintenance_node_drain import private_json

    def call(*args):
        return actors.Systemd.call(*args).decode().strip()

    def identity():
        value = {'machine': Path('/etc/machine-id').read_text().strip(),
                 'root_uuid': call('findmnt', '-n', '-o', 'UUID', '/')}
        require(os.geteuid() == 0 and socket.gethostname() == 'sprigatito' and value == {
            'machine': 'e5796c3018b6448eae0c69405926317e',
            'root_uuid': 'c27f6613-788e-4d00-802c-5b84a730a631'}, 'cleanup host identity differs')
        return value

    identity()
    require(call('rpm', '-E', '%fedora') == '44' and call('getenforce') == 'Enforcing' and
            Path('/proc/sys/kernel/random/boot_id').read_text().strip() == context['boot'],
            'cleanup requires the accepted Fedora 44 boot')
    hold = actors.Hold(actors.Systemd(), identity, lambda token: False)
    with hold.serialized():
        require(not hold.marker.exists(), 'native maintenance still owned')
        hold.systemd.idle(hold.marker)
        state = release.Release(hops.Journal(None, hold, OWNER)).read()
        require(state['kinds'] == list(release.KINDS) and
                state['header']['owners']['global']['node'] == 'sprigatito' and
                state['header']['owners']['global']['source'] == 43 and
                state['header']['owners']['global']['target'] == 44, 'final release is incomplete')
        require(gpu.regular_digest(gpu.PERMANENT_REPOSITORY, 0o644) == gpu.PERMANENT_SHA256,
                'permanent Fedora 44 repository differs')
        cache = hold.state / CACHE
        actors.safe(cache)
        intent_path = hold.state / 'sprigatito-nvidia43-cache-cleanup.json'
        accepted_path = hold.state / 'sprigatito-nvidia43-cache-cleanup-accepted.json'
        if accepted_path.exists():
            accepted = private_json(accepted_path)
            require(not cache.exists() and accepted['release_head_sha256'] == state['head_sha256'] and
                    accepted['accepted'] is True, 'cleanup readback differs')
            return accepted
        require(cache.exists(), 'cache absent without an accepted cleanup receipt')
        require(not intent_path.exists(), 'cleanup interrupted; inspect exact remaining files before resuming')
        proof = private_json(cache / 'verified.json')
        require(proof == {'capsule_sha256': gpu.LOCAL43['sha256'], 'files': gpu.local_files(cache)},
                'original vendor cache manifest differs')
        cache_bytes = str(cache).encode()
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                require(cache_bytes not in (process / 'cmdline').read_bytes() and
                        cache_bytes not in (process / 'maps').read_bytes(), 'vendor cache has an active consumer')
                for link in [process / 'cwd', process / 'root', *(process / 'fd').iterdir()]:
                    try:
                        target = os.readlink(link)
                    except FileNotFoundError:
                        continue
                    require(not (target == str(cache) or target.startswith(str(cache) + '/')),
                            'vendor cache has an open reference')
            except FileNotFoundError:
                continue
        actors.exclusive_file(intent_path, hops.canonical({
            'owner': OWNER, 'release_head_sha256': state['head_sha256'],
            'cache_manifest_sha256': hashlib.sha256((cache / 'verified.json').read_bytes()).hexdigest(),
            'cache': CACHE, 'files': proof['files'], 'boot': context['boot']}), 0o600)
        reclaimed = remove_verified_cache(cache, proof['files'], gpu.local_files)
        actors.fsync_directory(hold.state)
        accepted = {'accepted': True, 'owner': OWNER, 'cache_absent': True,
                    'release_head_sha256': state['head_sha256'], 'allocated_bytes_removed': reclaimed,
                    'protected_recovery_modified': False, 'nas_modified': False}
        actors.exclusive_file(accepted_path, hops.canonical(accepted), 0o600)
        return accepted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('identity', 'known-hosts', 'kubectl'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    import maintenance_production_node as production
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master' and
            subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip() ==
            'git@git.eaglepass.io:ops/homelab.git' and
            subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] == revision,
            'publish cleanup to canonical master first')
    bundle = {}
    for name in production.MODULES:
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == subprocess.check_output(['git', 'show', revision + ':' + str(path)]),
                'unpublished cleanup dependency')
        bundle[name] = path.read_text()
    require(Path(__file__).read_bytes() == subprocess.check_output([
        'git', 'show', revision + ':metal/scripts/maintenance_sprigatito_cache_cleanup.py']), 'unpublished cleanup')
    api = production.Kubectl(args.kubectl)
    node = api.call('get', 'node', 'sprigatito', '-o', 'json')
    ds = api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')
    require(node['metadata']['uid'] == '5d80125d-4228-47dd-b19c-ca86f7d4316c' and
            not node['spec'].get('unschedulable') and any(c['type'] == 'Ready' and c['status'] == 'True'
            for c in node['status']['conditions']) and
            ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            production.JOURNAL not in ds['metadata'].get('annotations', {}), 'cleanup node or global ownership differs')
    health = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                      'ceph', 'health', 'detail', '--format', 'json')
    pgs = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                   'ceph', 'pg', 'dump', 'pgs', '--format', 'json')
    require(health['status'] == 'HEALTH_OK' and not health.get('checks') and
            pgs['pg_ready'] and len(pgs['pg_stats']) == 177 and all(
                set(p['state'].split('+')) <= {'active', 'clean', 'scrubbing', 'deep'} and
                {'active', 'clean'} <= set(p['state'].split('+')) for p in pgs['pg_stats']),
            'cleanup requires completed clean replication')
    source = Path(__file__).read_text().split('\ndef main(')[0]
    program = 'import sys,types\nbundle=' + repr(bundle) + '\n'
    program += 'for name,code in bundle.items():\n m=types.ModuleType(name);sys.modules[name]=m;exec(compile(code,name,"exec"),m.__dict__)\n'
    program += source + '\nprint(json.dumps(native(' + repr({'boot': node['status']['nodeInfo']['bootID']}) + ')))'
    result = production.remote(args, program, '10.0.20.20')
    require(api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')['spec'] == ds['spec'],
            'Kured schedule changed during cleanup')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
