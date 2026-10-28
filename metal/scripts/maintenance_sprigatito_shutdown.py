#!/usr/bin/env python3
"""Drain and request graceful shutdown only after protected OSD7 evacuation."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

import emby_volume_recovery as emby
import maintenance_sprigatito_evacuation as evacuation
import maintenance_sprigatito_recovery as recovery
from maintenance_coordination import JOURNAL, Kubectl, Ownership, require
import maintenance_production_node as production


ETCD_MANIFEST = 'a74d5b8665e4595d45e0ffad83ff93fc1c1b3ab55c449b3f0125f0d0d4ad5970'
CONTROLLERS = {
    'rook-ceph-crashcollector-sprigatito': 'c1645408-b4aa-4c63-a27e-460fff95a433',
    'rook-ceph-exporter-sprigatito': '14740ebf-c39d-4bc8-a91f-8a94b25285e8',
    'rook-ceph-osd-7': '1f50fe47-e553-44b4-99d0-42da81638909',
}


def proof(args, name, value=None):
    require(re.fullmatch(r'(?:shutdown|eviction|etcd-restore)[a-z0-9-]*\.json', name), 'unreviewed shutdown record')
    source = Path(emby.__file__).read_text().split('\ndef observe(')[0]
    program = source + '\nhost("bulbasaur")\np=POINT/' + repr(name) + '\n'
    if value is not None:
        program += 'write_json(p,' + repr(value) + ')\nd=os.open(POINT,os.O_DIRECTORY);os.fsync(d);os.close(d)\n'
    program += 'print(json.dumps(json.loads(p.read_bytes())if p.exists()else None))'
    result = production.remote(args, program, '10.0.20.13')
    require(value is None or result == value, 'shutdown record readback differs')
    return result


def inventory(api):
    """Keep healthy DaemonSets and proven completed Pods; evict three host daemons."""
    spec = importlib.util.spec_from_file_location('core_health', 'scripts/homelab-health.py')
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    daemonsets = api.call('get', 'daemonsets', '-A', '-o', 'json')['items']
    by_uid = {d['metadata']['uid']: d for d in daemonsets}
    pods = api.call('get', 'pods', '-A', '--field-selector', 'spec.nodeName=sprigatito', '-o', 'json')['items']
    targets, kept = [], []
    for pod in pods:
        meta, spec, status = pod['metadata'], pod['spec'], pod['status']
        require(not meta.get('deletionTimestamp'), 'target Pod is still terminating')
        refs = [o for o in meta.get('ownerReferences', []) if o.get('controller')]
        require(len(refs) == 1 and refs[0].get('uid'), 'unowned target Pod')
        owner = refs[0]
        row = {'namespace': meta['namespace'], 'name': meta['name'], 'node_in_active_inventory': True,
               'containers': health.container_evidence(spec, status, 'containers'),
               'init_containers': health.container_evidence(spec, status, 'initContainers')}
        successful = lambda c: c['state'] == 'terminated' and c['exit_code'] == 0
        if owner['kind'] == 'Job':
            job = api.call('get', 'job', owner['name'], '-n', meta['namespace'], '-o', 'json')
            evidence = health.job_evidence(job)
            require(job['metadata']['uid'] == owner['uid'] and not job['metadata'].get('deletionTimestamp') and
                    (evidence['complete'] or evidence['active'] > 0 and not evidence['terminal_failed']) and
                    status['phase'] == 'Succeeded' and spec['restartPolicy'] in ('Never', 'OnFailure') and
                    all(successful(c) for c in row['containers']) and
                    all(c['state'] == 'terminated' if c['sidecar_init'] else successful(c) for c in row['init_containers']),
                    'completed Job Pod lacks full completion proof')
        elif owner['kind'] == 'ClusterPolicy':
            require(health.cuda_completion_proven(pod, row, daemonsets), 'CUDA completion is not proven')
        else:
            require(status['phase'] == 'Running' and all(c['state'] == 'running' and c['ready'] for c in row['containers']) and
                    all(c['state'] == 'running' and c['ready'] if c['sidecar_init'] else successful(c)
                        for c in row['init_containers']), 'active target Pod is unhealthy')
            if owner['kind'] == 'DaemonSet':
                parent = by_uid.get(owner['uid'])
                require(parent is not None and parent['metadata']['name'] == owner['name'] and
                        parent['metadata']['namespace'] == meta['namespace'] and not parent['metadata'].get('deletionTimestamp'),
                        'DaemonSet identity changed')
            else:
                require(owner['kind'] == 'ReplicaSet' and meta['namespace'] == 'rook-ceph', 'new application consumer on target')
                matches = [n for n, uid in CONTROLLERS.items() if uid == owner['uid'] and owner['name'].startswith(n + '-')]
                require(len(matches) == 1, 'unreviewed host daemon')
                parent = api.call('get', 'replicaset', owner['name'], '-n', 'rook-ceph', '-o', 'json')
                require(parent['metadata']['uid'] == owner['uid'] and not parent['metadata'].get('deletionTimestamp'), 'host daemon controller changed')
                require(not any('persistentVolumeClaim' in v or 'nfs' in v for v in spec.get('volumes', [])), 'new data consumer on host daemon')
                targets.append({'namespace': meta['namespace'], 'name': meta['name'], 'uid': meta['uid'],
                                'resource_version': meta['resourceVersion'], 'controller': matches[0]})
                continue
        kept.append({'namespace': meta['namespace'], 'name': meta['name'], 'uid': meta['uid'], 'kind': owner['kind']})
    targets.sort(key=lambda p: (p['controller'] == 'rook-ceph-osd-7', p['name']))
    return {'targets': targets, 'kept': kept}


def prerequisites(args, api, *, stopped):
    value = evacuation.collect(api)
    result = evacuation.validate(value, stopped=stopped)
    require(result['clean'] and result['pgs_depending_on_osd7'] == 0, 'full evacuation is not complete')
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    ownership = Ownership(api, evacuation.DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes})
    owner = json.loads(value['kured']['metadata']['annotations'][JOURNAL])
    require(owner['node'] == recovery.NODE and owner['node_uid'] == recovery.UID and ownership.resume(owner['owner']) == owner,
            'shutdown ownership differs')
    emby.observe(args)
    evacuation.receipts(args)
    receipt = proof(args, 'etcd-restore-accepted.json')
    require(receipt and receipt['accepted'] and receipt['manifest_sha256'] == ETCD_MANIFEST and
            receipt['protected_point_unchanged'] and receipt['protected_point_labels_unchanged'] and
            all(receipt['cleanup'].values()) and receipt['restored_nodes'] == 9,
            'current control-plane restore acceptance is missing')
    return {'owner': owner, 'storage': result, 'inventory': inventory(api)}


def actor_hold(args, api, owner, *, acquire=False):
    """Reuse persistent updater guards with a fresh global-owner RPC for each check."""
    source = Path('metal/scripts/maintenance_actor_hold.py').read_text()
    program = '''import json,pathlib,socket,subprocess,sys,types
m=types.ModuleType('actors');exec(''' + repr(source) + ''',m.__dict__)
owner=''' + repr(owner) + '''
def identity():
 assert socket.gethostname()=='sprigatito'
 value={'machine':pathlib.Path('/etc/machine-id').read_text().strip(),'root_uuid':subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()}
 assert value==''' + repr(recovery.IDENTITY) + '''
 return value
def verify(token):
 print(json.dumps({'rpc':'verify_owner','token':token}),flush=True)
 assert json.loads(sys.stdin.readline())=={'verified':True},'current global ownership refused'
 return True
hold=m.Hold(m.Systemd(),identity,verify)
''' + ('''assert not hold.marker.exists(),'existing native owner must be observed'
result=hold.acquire(owner['owner'],identity(),owner['revision'])
''' if acquire else "result=hold.resume(owner['owner'])\n") + '''print(json.dumps({'result':result}),flush=True)
'''
    bootstrap = 'import json,sys;exec(compile(json.loads(sys.stdin.readline())["program"],"protected-actor-hold","exec"))'
    child = subprocess.Popen(production.ssh(args, recovery.ADDRESS) + ['python3 -u -c ' + shlex.quote(bootstrap)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        child.stdin.write(json.dumps({'program': program}) + '\n');child.stdin.flush()
        result = None
        for line in child.stdout:
            request = json.loads(line)
            if 'result' in request:
                result = request['result'];continue
            require(request == {'rpc': 'verify_owner', 'token': owner['owner']}, 'unreviewed hold RPC')
            nodes = api.call('get', 'nodes', '-o', 'json')['items']
            controller = Ownership(api, evacuation.DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes})
            require(controller.resume(owner['owner']) == owner, 'native hold global owner changed')
            child.stdin.write('{"verified":true}\n');child.stdin.flush()
        child.wait()
        require(child.returncode == 0 and result is not None, 'native hold failed; retain owner: ' + child.stderr.read()[-1500:])
        return result
    finally:
        if child.poll() is None:
            child.terminate();child.wait()


def shutdown_native(owner, dispatch=False):
    return '''import json,os,pathlib,re,socket,subprocess
P=pathlib.Path
assert os.geteuid()==0 and socket.gethostname()=='sprigatito'
assert P('/etc/machine-id').read_text().strip()==''' + repr(recovery.IDENTITY['machine']) + '''
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==''' + repr(recovery.IDENTITY['root_uuid']) + '''
disks=json.loads(subprocess.check_output(['lsblk','-b','-J','-o','NAME,SIZE,SERIAL,PARTUUID'],text=True))
disk=next(d for d in disks['blockdevices']if d['name']=='sda')
assert disk['serial']=='DI0403Y002080'and disk['size']==512110190592
assert {p['name']:p['partuuid']for p in disk['children']}=={'sda1':'7a137097-0224-47c7-94fd-07554b4b2ae6','sda2':'3318f778-614d-4a51-8598-854df4d1ae06','sda3':'75944ab8-2af9-4622-af67-c41d61977f4f'}
osd=P(''' + repr('/' + recovery.OSD_DIRECTORY) + ''')
assert os.readlink(osd/'block')=='/dev/sda3'and(osd/'fsid').read_text().strip()==''' + repr(evacuation.OSDS[7]) + '''
for path in P('/proc').glob('[0-9]*/comm'):
 try: name=path.read_text().strip()
 except FileNotFoundError: continue
 assert not re.fullmatch(r'(?:rpm|dnf.*|fwupd.*|qemu.*|libvirtd|virtqemud)',name),'active package, firmware or VM process'
assert not subprocess.check_output(['docker','ps','-q'],text=True).strip(),'native Docker writer remains'
boot=P('/proc/sys/kernel/random/boot_id').read_text().strip()
unit=''' + repr(owner['owner'] + '-protected-poweroff') + '''
''' + ('''subprocess.run(['systemd-run','--unit='+unit,'--on-active=10s','--property=Restart=no','/usr/bin/systemctl','poweroff'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
assert subprocess.check_output(['systemctl','is-active',unit+'.timer'],text=True).strip()=='active'
''' if dispatch else '') + '''print(json.dumps({'node':'sprigatito','machine':''' + repr(recovery.IDENTITY['machine']) + ''','boot':boot,'disk_serial':disk['serial'],'unit':unit,'poweroff_scheduled':''' + repr(dispatch) + '''}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['observe', 'hold', 'evict', 'shutdown'])
    for name in ('identity', 'known-hosts', 'kubectl'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    revision = emby.command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
    require(emby.command('git', 'branch', '--show-current').stdout.strip() == b'master' and
            emby.command('git', 'remote', 'get-url', 'origin').stdout.strip() == b'git@git.eaglepass.io:ops/homelab.git' and
            emby.command('git', 'ls-remote', 'origin', 'refs/heads/master').stdout.decode().split()[0] == revision,
            'publish shutdown candidate to canonical master')
    for name in ('maintenance_sprigatito_shutdown', 'maintenance_sprigatito_evacuation', 'emby_volume_recovery',
                 'maintenance_sprigatito_recovery', 'maintenance_coordination', 'maintenance_actor_hold', 'maintenance_osd_host', 'maintenance_production_node'):
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == emby.command('git', 'show', revision + ':' + str(path)).stdout, 'unpublished shutdown dependency')
    health = Path('scripts/homelab-health.py')
    require(health.read_bytes() == emby.command('git', 'show', revision + ':' + str(health)).stdout, 'unpublished completion classifier')
    api = Kubectl(args.kubectl)
    value = prerequisites(args, api, stopped=True)
    if args.operation == 'hold':
        result = actor_hold(args, api, value['owner'], acquire=True)
        proof(args, 'shutdown-actor-hold.json', result)
        value = {'native_actor_hold': result, 'owner_retained': True}
    elif args.operation == 'evict':
        actor_hold(args, api, value['owner'])
        require(value['inventory']['targets'], 'no host daemon remains to evict; observe')
        target = value['inventory']['targets'][0]
        name = 'eviction-' + target['uid'] + '-intent.json'
        require(proof(args, name) is None, 'existing eviction intent; observe, never repeat')
        proof(args, name, {'target': target, 'prerequisites': value, 'revision': revision})
        request = {'apiVersion': 'policy/v1', 'kind': 'Eviction',
                   'metadata': {'namespace': target['namespace'], 'name': target['name']},
                   'deleteOptions': {'preconditions': {'uid': target['uid'], 'resourceVersion': target['resource_version']}}}
        response = api.call('create', '--raw=/api/v1/namespaces/rook-ceph/pods/' + target['name'] + '/eviction',
                            '-f', '-', data=emby.canonical(request))
        require(response.get('kind') == 'Status' and response.get('status') == 'Success', 'eviction result uncertain; observe')
        value = {'eviction_requested': target, 'owner_retained': True}
    elif args.operation == 'shutdown':
        actor_hold(args, api, value['owner'])
        require(not value['inventory']['targets'], 'active host daemon remains')
        require(proof(args, 'shutdown-intent.json') is None, 'existing shutdown intent; observe, never repeat')
        native = production.remote(args, shutdown_native(value['owner']), recovery.ADDRESS)
        proof(args, 'shutdown-intent.json', {'prerequisites': value, 'native': native, 'revision': revision,
              'created': datetime.now(timezone.utc).isoformat(), 'physical_power_off_not_yet_proven': True})
        require(prerequisites(args, api, stopped=True) == value, 'shutdown prerequisites changed')
        value = production.remote(args, shutdown_native(value['owner'], dispatch=True), recovery.ADDRESS)
        proof(args, 'shutdown-dispatched.json', value)
    print(json.dumps(value, sort_keys=True))


if __name__ == '__main__':
    main()
