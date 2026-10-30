#!/usr/bin/env python3
"""Observe one published interrupted release; never dispatch a release or restart."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import subprocess
import sys

import maintenance_coordination as coordination
from maintenance_node_drain import hashed
from maintenance_safe_release import KINDS


PROFILE = Path('metal/maintenance/k3s-growlithe-release-recovery.json')
REQUEST = 'weave.works/kured-reboot-in-progress'


def recover(worker, profile, verify_safe, verify_runtime):
    """Exact historical request cleanup after a proven committed global removal."""
    require = coordination.require
    expected = {name: value['queued_reboot'] for name, value in profile['nodes'].items()}
    digest = hashed(profile)

    def verified():
        require(verify_runtime() is True, 'release recovery runtime changed')
        state = worker.read()
        require(state['kinds'] in (list(KINDS[:4]), list(KINDS)), 'global release intent is not proven')
        require(state['header']['owners']['global'] == profile['owner'] and
                state['header']['owners']['host']['identity'] == profile['identity'],
                'original release identity differs')
        require(all(hashed(json.loads((worker.path / name).read_bytes())) == value
                    for name, value in profile['release_records'].items()), 'original release record differs')
        require(not worker.host_held(state['header']), 'host ownership returned')
        created = datetime.fromisoformat(profile['owner']['created'].replace('Z', '+00:00'))
        audited = datetime.fromisoformat(profile['audit_time'])
        require(created.utcoffset() is not None and audited.utcoffset() is not None and
                all(created <= datetime.fromisoformat(value.replace('Z', '+00:00')) <= audited
                    for value in expected.values()), 'request was not queued behind the original owner')
        ds = worker.ownership.observed(released_requests=expected)
        nodes = worker.ownership.api.call('get', 'nodes', '-o', 'json')['items']
        require({n['metadata']['name']: {'uid': n['metadata']['uid'], 'boot': n['status']['nodeInfo']['bootID']}
                 for n in nodes} == {name: {k: value[k] for k in ('uid', 'boot')}
                                     for name, value in profile['nodes'].items()}, 'original node boot or UID differs')
        require(not {coordination.LOCK, coordination.JOURNAL}.intersection(
            ds['metadata'].get('annotations', {})), 'global ownership returned')
        return state, nodes

    state, nodes = verified()
    require(verify_safe(state['header'], digest) is True, 'current release recovery safety refused')
    pointer = '/metadata/annotations/' + REQUEST.replace('/', '~1')
    for name in sorted(expected):
        state, nodes = verified()
        node = next(n for n in nodes if n['metadata']['name'] == name)
        metadata = node['metadata']
        pending = metadata.get('annotations', {}).get(REQUEST)
        if pending is None:
            continue
        require(pending == expected[name], 'queued request changed before cleanup')
        worker.ownership.api.call('patch', 'node', name, '--type=json', '--patch', coordination.encoded([
            {'op': 'test', 'path': '/metadata/uid', 'value': metadata['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': metadata['resourceVersion']},
            {'op': 'test', 'path': pointer, 'value': pending},
            {'op': 'remove', 'path': pointer},
        ]), '-o', 'json')
        after = worker.ownership.api.call('get', 'node', name, '-o', 'json')
        require(after['metadata']['uid'] == metadata['uid'] and
                REQUEST not in after['metadata'].get('annotations', {}), 'request cleanup uncertain; observe only')
    verified()
    worker.ownership.observed()
    return worker.observe(digest, verify_safe)


NATIVE = r'''
import json,sys,types,pathlib,socket,subprocess,os
for name,source in BUNDLE.items():
 module=types.ModuleType(name);sys.modules[name]=module;exec(compile(source,name+'.py','exec'),module.__dict__)
coord=sys.modules['maintenance_coordination'];actors=sys.modules['maintenance_actor_hold']
hops=sys.modules['maintenance_hop_journal'];release=sys.modules['maintenance_safe_release']
bridge=sys.modules['maintenance_k3s_production'];recovery=sys.modules['maintenance_k3s_release_recovery']
def native(*argv):return actors.Systemd.call(*argv).decode().strip()
def identity():
 value={'machine':pathlib.Path('/etc/machine-id').read_text().strip(),'root_uuid':native('findmnt','-n','-o','UUID','/')}
 assert os.geteuid()==0 and socket.gethostname()==PROFILE['node']and value==PROFILE['identity']
 return value
identity()
def rpc(kind,**payload):
 print(json.dumps({'rpc':kind,**payload}),flush=True)
 reply=json.loads(sys.stdin.readline());assert reply.get('ok'),reply.get('error','readback refused')
 return reply['result']
class API:
 def call(self,*argv):return rpc('api',argv=list(argv))
 def snapshot(self):return(self.call('get','daemonset','kured','-n','kured','-o','json'),self.call('get','pods','-n','kured','-o','json')['items'],self.call('get','nodes','-o','json')['items'])
api=API();controller=coord.Ownership(api,DS_UID,{n:v['uid']for n,v in PROFILE['nodes'].items()})
hold=actors.Hold(actors.Systemd(),identity,lambda _:False)
journal=hops.Journal(controller,hold,PROFILE['owner']['owner']);worker=release.Release(journal)
before=sys.modules['maintenance_node_drain'].private_json(hold.state/('k3s-before-'+journal.token+'.json'))
after=bridge.runtime(native,bridge.TARGET);bridge.unchanged_runtime(before,after)
assert after['pid']==PROFILE['pid']and after['boot']==PROFILE['boot']
health=rpc('applications')
def safe(header,digest):
 return(header['owners']['global']==PROFILE['owner']and digest==recovery.hashed(PROFILE)and bridge.runtime(native,bridge.TARGET)==after and rpc('applications')==health)
result=recovery.recover(worker,PROFILE,safe,lambda:identity()==PROFILE['identity']and bridge.runtime(native,bridge.TARGET)==after)
print(json.dumps({'result':result}),flush=True)
'''


def main():
    import maintenance_production_node as production
    import maintenance_k3s_production as bridge
    from maintenance_api_reader import Reader
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kubectl', 'identity', 'known-hosts'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    require = coordination.require
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab') and
            subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'master' and
            subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip() ==
            'git@git.eaglepass.io:ops/homelab.git', 'canonical deployment checkout required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] ==
            revision, 'publish recovery before execution')
    raw = PROFILE.read_bytes()
    require(raw == subprocess.check_output(['git', 'show', revision + ':' + str(PROFILE)]), 'unpublished release profile')
    profile = json.loads(raw)
    require(profile['version'] == 1 and profile['node'] == 'growlithe' and
            profile['owner']['owner'] == 'homelab-maintenance-103-97a88314-4ad1-4fad-86e3-47e0adcbe84c' and
            set(profile['release_records']) == {str(i).zfill(8) + '.json' for i in range(4)}, 'unreviewed recovery profile')
    production.select_node(profile['node'])
    require(profile['identity'] == production.IDENTITY, 'recovery host identity differs')
    names = (*production.MODULES, 'maintenance_k3s_contract', 'maintenance_k3s_binary',
             'maintenance_k3s_production', 'maintenance_k3s_release_recovery')
    bundle = {}
    for name in names:
        path = Path('metal/scripts') / (name + '.py')
        published = subprocess.check_output(['git', 'show', revision + ':' + str(path)])
        require(path.read_bytes() == published, 'unpublished native recovery dependency')
        bundle[name] = published.decode()
    program = 'BUNDLE=' + repr(bundle) + '\nPROFILE=' + repr(profile) + '\nDS_UID=' + repr(production.DS_UID) + '\n' + NATIVE
    bootstrap = 'import json,sys;exec(compile(json.loads(sys.stdin.readline())["program"],"release-recovery","exec"))'
    api = Reader(args.kubectl)
    child = None
    try:
        child = subprocess.Popen(production.ssh(args) + ['python3 -u -c ' + shlex.quote(bootstrap)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child.stdin.write(json.dumps({'program': program}) + '\n');child.stdin.flush()
        result = None
        for line in child.stdout:
            request = json.loads(line)
            if 'result' in request:
                result = request['result'];continue
            try:
                if request['rpc'] == 'applications':
                    value = bridge.observe(args, api, profile['owner'], 'applications')
                else:
                    require(request['rpc'] == 'api', 'unreviewed recovery request')
                    argv = request['argv']
                    allowed = (['get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'],
                               ['get', 'pods', '-n', 'kured', '-o', 'json'], ['get', 'nodes', '-o', 'json'])
                    if argv not in allowed:
                        require(len(argv) >= 5 and argv[1] == 'node' and argv[2] in profile['nodes'], 'unreviewed recovery API target')
                        if argv[0] == 'get':
                            require(argv[3:] == ['-o', 'json'], 'unreviewed node read')
                        else:
                            require(argv[0] == 'patch' and len(argv) == 8 and argv[3:5] == ['--type=json', '--patch'] and
                                    argv[6:] == ['-o', 'json'], 'unreviewed recovery mutation')
                            node = api.call('get', 'node', argv[2], '-o', 'json')['metadata']
                            pointer = '/metadata/annotations/' + REQUEST.replace('/', '~1')
                            require(node['uid'] == profile['nodes'][argv[2]]['uid'] and json.loads(argv[5]) == [
                                {'op': 'test', 'path': '/metadata/uid', 'value': node['uid']},
                                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['resourceVersion']},
                                {'op': 'test', 'path': pointer, 'value': profile['nodes'][argv[2]]['queued_reboot']},
                                {'op': 'remove', 'path': pointer}], 'queued-request patch differs')
                    value = api.call(*argv)
                reply = {'ok': True, 'result': value}
            except Exception as error:
                reply = {'ok': False, 'error': str(error)}
            child.stdin.write(json.dumps(reply) + '\n');child.stdin.flush()
        child.wait()
        require(child.returncode == 0 and result is not None,
                'release observation incomplete; retain original journal: ' + child.stderr.read()[-2000:])
        print(json.dumps(result))
    finally:
        if child is not None and child.poll() is None:
            child.terminate();child.wait()
        api.close()


if __name__ == '__main__':
    main()
