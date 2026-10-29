#!/usr/bin/env python3
"""Prepare only Emby's existing local transcode tree before its protected return."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess


ROOT = Path('/var/lib/emby-transcode')
LABEL = 'system_u:object_r:container_file_t:s0'
PATTERN = str(ROOT) + '(/.*)?'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def inventory(root):
    require(root == ROOT and not any(p.is_symlink() for p in (root, *root.parents)),
            'unexpected transcode root or ancestry')
    device = Path('/').stat().st_dev
    result = {}
    for path in (root, *root.rglob('*')):
        info = path.lstat()
        require(info.st_dev == device and not path.is_symlink() and
                (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                'unsafe or foreign transcode member')
        result[str(path.relative_to(root))] = [info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)]
    require('.' in result and 'transcoding-temp' in result, 'original transcode directories missing')
    return result


def desired_policy(lines):
    matches = [line for line in lines if line.split() and line.split()[0] == PATTERN]
    require(not matches or len(matches) == 1 and matches[0].split()[-1] == LABEL,
            'conflicting local transcode SELinux policy')
    return bool(matches)


def native(context):
    import maintenance_actor_hold as actors

    def call(*args):
        return actors.Systemd.call(*args).decode().strip()

    require(os.geteuid() == 0 and socket.gethostname() == 'sprigatito' and
            Path('/etc/machine-id').read_text().strip() == 'e5796c3018b6448eae0c69405926317e' and
            call('findmnt', '-n', '-o', 'UUID', '/') == 'c27f6613-788e-4d00-802c-5b84a730a631' and
            call('rpm', '-E', '%fedora') == '44' and call('getenforce') == 'Enforcing' and
            Path('/proc/sys/kernel/random/boot_id').read_text().strip() == context['boot'],
            'transcode preparation host identity differs')
    hold = actors.Hold(actors.Systemd(), lambda: None, lambda owner: False)
    with hold.serialized():
        require(not hold.marker.exists(), 'finish native node maintenance first')
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            target = line.split()[4]
            require(target != str(ROOT) and not target.startswith(str(ROOT) + '/'),
                    'mounted filesystem within transcode tree')
        before = inventory(ROOT)
        require(before['.'][3:] == [0, 0, 0o1777] and
                before['transcoding-temp'][3:] in ([0, 0, 0o755], [99, 100, 0o755]),
                'unexpected transcode directory ownership or permissions')
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                require(str(ROOT).encode() not in (process / 'cmdline').read_bytes() and
                        str(ROOT).encode() not in (process / 'maps').read_bytes(),
                        'transcode tree has an active mapped or command reference')
                for link in [process / 'cwd', process / 'root', *(process / 'fd').iterdir()]:
                    try:
                        target = os.readlink(link)
                    except FileNotFoundError:
                        continue
                    require(target != str(ROOT) and not target.startswith(str(ROOT) + '/'),
                            'transcode tree has an active process reference')
            except FileNotFoundError:
                continue
        exists = desired_policy(call('semanage', 'fcontext', '-l', '-C').splitlines())
        point = hold.state / 'emby-transcode-103'
        actors.safe(point)
        point.mkdir(mode=0o700, exist_ok=True)
        require(point.stat().st_uid == 0 and stat.S_IMODE(point.stat().st_mode) == 0o700,
                'unsafe transcode receipt directory')
        accepted = point / 'accepted.json'
        actors.safe(accepted)
        if accepted.exists():
            require(accepted.stat().st_uid == 0 and accepted.stat().st_nlink == 1 and
                    stat.S_IMODE(accepted.stat().st_mode) == 0o600 and
                    json.loads(accepted.read_bytes())['accepted'] is True and exists and
                    all(os.getxattr(ROOT / name, 'security.selinux').decode().rstrip('\0') == LABEL
                    for name in before) and before['transcoding-temp'][3:] == [99, 100, 0o755],
                    'accepted transcode preparation differs')
            return {'accepted': True, 'observed_existing': True, 'files': len(before), 'label': LABEL}
        intent = point / 'intent.json'
        require(not intent.exists(), 'interrupted preparation; inspect before resuming')
        actors.exclusive_file(intent, json.dumps({'context': context, 'before': before,
            'before_labels': {name: os.getxattr(ROOT / name, 'security.selinux').decode().rstrip('\0')
                              for name in before},
            'policy_existed': exists, 'desired_label': LABEL}, sort_keys=True).encode(), 0o600)
        if not exists:
            call('semanage', 'fcontext', '-a', '-t', 'container_file_t', '-r', 's0', PATTERN)
        call('restorecon', '-R', '-F', '-x', str(ROOT))
        os.chown(ROOT / 'transcoding-temp', 99, 100)
        after = inventory(ROOT)
        expected = {name: list(value) for name, value in before.items()}
        expected['transcoding-temp'][3:5] = [99, 100]
        require(after == expected and all(
            os.getxattr(ROOT / name, 'security.selinux').decode().rstrip('\0') == LABEL and
            call('matchpathcon', '-n', str(ROOT / name)) == LABEL for name in after),
            'transcode content metadata or effective policy differs')
        result = {'accepted': True, 'files': len(after), 'label': LABEL,
                  'temp_uid': 99, 'temp_gid': 100, 'content_metadata_preserved': True,
                  'nas_modified': False, 'before_sha256': hashlib.sha256(
                      json.dumps(before, sort_keys=True).encode()).hexdigest()}
        actors.exclusive_file(accepted, json.dumps(result, sort_keys=True).encode(), 0o600)
        return result


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
            'git@git.eaglepass.io:ops/homelab.git' and subprocess.check_output([
                'git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] == revision,
            'publish transcode preparation to canonical master first')
    bundle = {}
    for name in ('maintenance_actor_hold', 'maintenance_production_node', 'maintenance_emby_hostpath'):
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == subprocess.check_output(['git', 'show', revision + ':' + str(path)]),
                'unpublished transcode preparation dependency')
        if name == 'maintenance_actor_hold':
            bundle[name] = path.read_text()
    api = production.Kubectl(args.kubectl)
    node = api.call('get', 'node', 'sprigatito', '-o', 'json')
    ds = api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')
    require(node['metadata']['uid'] == '5d80125d-4228-47dd-b19c-ca86f7d4316c' and
            not node['spec'].get('unschedulable') and any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in node['status']['conditions']) and
            ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            production.JOURNAL not in ds['metadata'].get('annotations', {}),
            'finish global node maintenance first')
    app = api.call('get', 'application', 'emby', '-n', 'argocd', '-o', 'json')
    deployment = api.call('get', 'deployment', 'emby-main', '-n', 'emby', '-o', 'json')
    crons = api.call('get', 'cronjobs', '-n', 'emby', '-o', 'json')['items']
    require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == revision and
            deployment['spec']['replicas'] == 0 and deployment['status'].get('replicas', 0) == 0 and
            len(crons) == 2 and all(c['spec'].get('suspend') and not c['status'].get('active') for c in crons),
            'Emby writer and ordinary Jobs must remain stopped')
    pods = api.call('get', 'pods', '-A', '-o', 'json')['items']
    require(not any(p['spec'].get('nodeName') == 'sprigatito' and any(
        v.get('hostPath', {}).get('path', '').rstrip('/') == str(ROOT) or
        v.get('hostPath', {}).get('path', '').startswith(str(ROOT) + '/')
        for v in p['spec'].get('volumes', [])) for p in pods), 'transcode hostPath still has a Pod consumer')
    source = Path(__file__).read_text().split('\ndef main(')[0]
    program = 'import sys,types\nbundle=' + repr(bundle) + '\n'
    program += 'for name,code in bundle.items():\n m=types.ModuleType(name);sys.modules[name]=m;exec(compile(code,name,"exec"),m.__dict__)\n'
    program += source + '\nprint(json.dumps(native(' + repr({'boot': node['status']['nodeInfo']['bootID']}) + ')))'
    print(json.dumps(production.remote(args, program, '10.0.20.20'), sort_keys=True))


if __name__ == '__main__':
    main()
