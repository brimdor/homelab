#!/usr/bin/env python3
"""Exact OSD7 evacuation. Preserve the daemon, device, pool policy and all NAS data."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import emby_volume_recovery as emby
from maintenance_coordination import JOURNAL, Kubectl, Ownership, require
from maintenance_osd_host import BASE_FLAGS, CLUSTER_UID, FSID, OSDS, POOLS, STATE_UID
import maintenance_production_node as production
import maintenance_sprigatito_recovery as recovery


DS_UID = '4abc4fee-c3be-440e-8945-34bb3fb15ce1'
DEPLOYMENT_UID = '42a28e8a-1390-4c03-9999-5156912beaca'
HOSTS = {1: 'cyndaquil', 2: 'arcanine', 6: 'growlithe', 7: 'sprigatito', 8: 'arcanine'}


def collect(api):
    def ceph(*args):
        return api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', *args, '--format', 'json')
    return {'node': api.call('get', 'node', recovery.NODE, '-o', 'json'),
            'cluster': api.call('get', 'cephcluster', 'rook-ceph', '-n', 'rook-ceph', '-o', 'json'),
            'deployment': api.call('get', 'deployment', 'rook-ceph-osd-7', '-n', 'rook-ceph', '-o', 'json'),
            'kured': api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'),
            'pdb_state': api.call('get', 'configmap', 'rook-ceph-pdbstatemap', '-n', 'rook-ceph', '-o', 'json'),
            'map': ceph('osd', 'dump'), 'quorum': ceph('quorum_status'), 'health': ceph('health', 'detail'),
            'pgs': ceph('pg', 'dump', 'pgs'), 'df': ceph('osd', 'df', 'tree'),
            'metadata': ceph('osd', 'metadata', '7')}


def validate(value, *, baseline=False):
    node, cluster, deployment = value['node'], value['cluster'], value['deployment']
    require(value['kured']['metadata']['uid'] == DS_UID and value['pdb_state']['metadata']['uid'] == STATE_UID and
            not value['pdb_state']['data'].get('draining-failure-domain') and
            not value['pdb_state']['data'].get('set-no-out'), 'foreign Rook or Kured disruption ownership')
    require(node['metadata']['uid'] == recovery.UID and not node['metadata'].get('deletionTimestamp') and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']), 'Sprigatito identity/readiness changed')
    require(cluster['metadata']['uid'] == CLUSTER_UID and
            cluster['spec']['removeOSDsIfOutAndSafeToRemove'] is False and
            cluster['spec']['disruptionManagement'] == {'managePodBudgets': True, 'osdMaintenanceTimeout': 90},
            'Rook retention or disruption contract changed')
    require(deployment['metadata']['uid'] == DEPLOYMENT_UID and deployment['spec']['replicas'] == 1 and
            deployment['spec']['template']['spec']['nodeSelector'] == {'kubernetes.io/hostname': recovery.NODE} and
            not deployment['metadata'].get('deletionTimestamp'), 'OSD7 controller changed')
    metadata = value['metadata']
    require(metadata['id'] == 7 and metadata['hostname'] == recovery.NODE and
            metadata['device_ids'] == 'sda=KingFast_DI0403Y002080' and
            metadata['bluestore_bdev_partition_path'] == '/dev/sda3', 'OSD7 native identity changed')
    mapping, quorum = value['map'], value['quorum']
    require(mapping['fsid'] == FSID and quorum['monmap']['fsid'] == FSID and
            len(quorum['quorum_names']) == 3 and set(quorum['quorum_names']) == {m['name'] for m in quorum['monmap']['mons']},
            'full monitor quorum unavailable')
    osds = {o['osd']: o for o in mapping['osds']}
    require(set(osds) == set(OSDS) and all(o['uuid'] == OSDS[i] and o['up'] == 1 and
            (o['in'], o['weight']) == ((1, 1) if baseline or i != 7 else (0, 0))
            for i, o in osds.items()), 'unexpected OSD identity, availability or membership')
    require(set(mapping['flags_set']) == BASE_FLAGS and not mapping['crush_node_flags'] and
            not mapping['device_class_flags'] and not any(set(o.get('state', [])) & {'noout', 'noup', 'nodown', 'noin'} for o in osds.values()),
            'foreign storage flags prevent evacuation')
    pools = {p['pool']: p for p in mapping['pools']}
    require(set(pools) == set(POOLS) and all(p['type'] == 1 and
            (p['pool_name'], p['size'], p['min_size'], p['crush_rule']) == POOLS[i]
            for i, p in pools.items()), 'pool replication contract changed')
    pgs = value['pgs']['pg_stats']
    expected = {f'{i}.{number:x}' for i, p in pools.items() for number in range(p['pg_num'])}
    require(value['pgs']['pg_ready'] and {p['pgid'] for p in pgs} == expected and len(pgs) == len(expected), 'incomplete PG evidence')
    clean = True
    dependent = 0
    for pg in pgs:
        states = set(pg['state'].split('+'))
        require(not states & {'incomplete', 'stale', 'down', 'inconsistent', 'recovery_toofull', 'backfill_toofull'} and
                not pg['stat_sum']['num_objects_unfound'] and not pg['stat_sum']['num_scrub_errors'], 'unsafe PG finding during evacuation')
        clean = clean and states <= {'active', 'clean', 'scrubbing', 'deep'} and {'active', 'clean'} <= states
        dependent += int(7 in pg['up'] or 7 in pg['acting'])
        if baseline or clean:
            size = pools[int(pg['pgid'].split('.')[0])]['size']
            require(len(pg['up']) == len(pg['acting']) == size and len(set(pg['acting'])) == size and
                    len({HOSTS[i] for i in pg['acting']}) == size, 'configured replicas/failure domains absent')
    health = value['health']
    require(not health.get('mutes') and health['status'] in ('HEALTH_OK', 'HEALTH_WARN') and
            set(health.get('checks', {})) <= {'PG_DEGRADED', 'PG_AVAILABILITY', 'OBJECT_MISPLACED'}, 'unexpected Ceph health finding')
    if baseline:
        require(clean and health['status'] == 'HEALTH_OK' and not health.get('checks'), 'evacuation needs an initially clean cluster')
    else:
        require(node['spec'].get('unschedulable') is True, 'evacuation lost its cordon')
    for osd in value['df']['nodes']:
        if osd['id'] in OSDS and osd['id'] != 7:
            require(osd['utilization'] / 100 < value['map']['nearfull_ratio'], 'destination approached near-full')
    return {'epoch': mapping['epoch'], 'pg_count': len(pgs), 'clean': bool(clean),
            'pgs_depending_on_osd7': dependent, 'health': health['status'],
            'complete': bool(not baseline and clean and dependent == 0 and health['status'] == 'HEALTH_OK' and not health.get('checks'))}


def model(api, value):
    program = '''import json,pathlib,subprocess,tempfile
with tempfile.TemporaryDirectory(prefix='maintenance103-osd7-model-',dir='/tmp')as temporary:
 path=str(pathlib.Path(temporary)/'osdmap');cleanup=str(pathlib.Path(temporary)/'cleanup')
 assert subprocess.run(['ceph','osd','getmap','-o',path],capture_output=True).returncode==0
 description=subprocess.run(['osdmaptool',path,'--dump','json'],capture_output=True);assert description.returncode==0
 # Match OSDMonitor.encode_pending, which cleans invalid upmaps before committing.
 mapping=subprocess.run(['osdmaptool',path,'--mark-out','7','--upmap-cleanup',cleanup,'--test-map-pgs-dump-all'],capture_output=True);assert mapping.returncode==0
 print(json.dumps({'map':json.loads(description.stdout),'mapping':mapping.stdout.decode(),'cleanup':pathlib.Path(cleanup).read_text()}))
'''
    result = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'python3', '-c', program)
    require(result['map']['epoch'] == value['map']['epoch'] and result['map']['fsid'] == FSID, 'capacity model map became stale')
    destinations = {}
    for line in result['mapping'].splitlines():
        match = re.fullmatch(r'([0-9]+\.[0-9a-f]+) raw .* up \(\[([0-9,]*)\], p[0-9]+\) acting .*', line)
        if match:
            require(match[1] not in destinations, 'duplicate modeled PG')
            destinations[match[1]] = [int(i) for i in match[2].split(',')]
    require(set(destinations) == {p['pgid'] for p in value['pgs']['pg_stats']}, 'capacity model omitted PGs')
    incoming = {i: 0 for i in OSDS if i != 7}
    for pg in value['pgs']['pg_stats']:
        targets = destinations[pg['pgid']]
        size = POOLS[int(pg['pgid'].split('.')[0])][1]
        require(7 not in targets and len(targets) == len(set(targets)) == size and
                len({HOSTS[i] for i in targets}) == size, 'modeled placement lacks complete independent replicas')
        for target in set(targets) - set(pg['acting']):
            incoming[target] += pg['stat_sum']['num_bytes'] * 5 // 4 + 64 * 1024**2
    projected = {}
    for osd in value['df']['nodes']:
        if osd['id'] in incoming:
            ratio = (osd['kb_used'] * 1024 + incoming[osd['id']]) / (osd['kb'] * 1024)
            require(ratio < value['map']['nearfull_ratio'], 'modeled peak exceeds safe destination capacity')
            projected[str(osd['id'])] = {'incoming_bytes_upper_estimate': incoming[osd['id']], 'peak_ratio_upper_estimate': ratio}
    return {'epoch': value['map']['epoch'], 'destinations': projected, 'pg_count': len(destinations),
            'monitor_cleanup_commands': result['cleanup'].splitlines(),
            'mapping_sha256': hashlib.sha256(emby.canonical(destinations)).hexdigest()}


def receipts(args):
    source = Path(emby.__file__).read_text().split('\ndef observe(')[0]
    application = production.remote(args, source + '\nvalue=verified();result=json.loads((POINT/"restore-accepted.json").read_bytes())\n'
        'require(result["accepted"] and result["manifest_sha256"]==summary(value)["manifest_sha256"],"Emby restore proof changed")\n'
        'print(json.dumps(result))', '10.0.20.13')
    config = production.remote(args, '''import hashlib,json,pathlib,socket,subprocess
assert socket.gethostname()=='charmander'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='58d682ccab5a4269acedc3cdf53e46dc'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='4a64a6d6-e982-4694-aa03-ad5f317b3ab2'
point=pathlib.Path(''' + repr(recovery.POINT) + ''')
assert not any(p.is_symlink()for p in(point,*point.parents))
value=json.loads((point/'verified.json').read_bytes());proof=json.loads((point/'restore-accepted.json').read_bytes())
digest=hashlib.sha256()
with(point/'node-config.tar').open('rb')as f:
 for chunk in iter(lambda:f.read(1048576),b''):digest.update(chunk)
assert value['sha256']==proof['archive_sha256']==digest.hexdigest()=='fc3c7ccd53d5b716689981fd00d6dc2397c4387212204cc9b41b03c481d5b42c'
assert value['node_uid']==proof['node_uid']==''' + repr(recovery.UID) + ''' and proof['reconstruction_removed']
print(json.dumps({'configuration_sha256':digest.hexdigest(),'reconstruction_verified':True}))
''', '10.0.20.11')
    return {'application': application, 'configuration': config}


def record(args, name, value):
    require(name in ('evacuation-intent.json', 'evacuation-out-observed.json', 'evacuation-complete.json'), 'unreviewed evacuation record')
    source = Path(emby.__file__).read_text().split('\ndef observe(')[0]
    return production.remote(args, source + '\nhost("bulbasaur")\nvalue=' + repr(value) + '\n'
        'write_json(POINT/' + repr(name) + ',value)\n'
        'descriptor=os.open(POINT,os.O_DIRECTORY);os.fsync(descriptor);os.close(descriptor)\n'
        'require(json.loads((POINT/' + repr(name) + ').read_bytes())==value,"evacuation record readback differs")\n'
        'print(json.dumps(value))', '10.0.20.13')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['baseline', 'start', 'observe'])
    for name in ('identity', 'known-hosts', 'kubectl'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    require(Path.cwd() == Path('/Users/chris/Documents/Github/homelab'), 'canonical checkout required')
    revision = emby.command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
    require(emby.command('git', 'branch', '--show-current').stdout.decode().strip() == 'master' and
            emby.command('git', 'remote', 'get-url', 'origin').stdout.decode().strip() == 'git@git.eaglepass.io:ops/homelab.git' and
            emby.command('git', 'ls-remote', 'origin', 'refs/heads/master').stdout.decode().split()[0] == revision,
            'publish exact evacuation candidate to canonical master')
    for name in ('maintenance_sprigatito_evacuation', 'emby_volume_recovery', 'maintenance_coordination',
                 'maintenance_sprigatito_recovery', 'maintenance_osd_host', 'maintenance_production_node'):
        path = Path('metal/scripts') / (name + '.py')
        require(path.read_bytes() == emby.command('git', 'show', revision + ':' + str(path)).stdout, 'unpublished evacuation dependency')
    api = Kubectl(args.kubectl)
    value = collect(api)
    if args.operation == 'baseline':
        result = {'baseline': validate(value, baseline=True), 'capacity': model(api, value)}
    elif args.operation == 'start':
        baseline = validate(value, baseline=True)
        require(JOURNAL not in value['kured']['metadata'].get('annotations', {}), 'existing owner must be resumed')
        proof = receipts(args)
        context = emby.observe(args)
        capacity = model(api, value)
        nodes = api.call('get', 'nodes', '-o', 'json')['items']
        ownership = Ownership(api, DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes})
        owner = ownership.acquire(recovery.NODE, 39, 41, revision)
        node = api.call('get', 'node', recovery.NODE, '-o', 'json')
        require(node['metadata']['uid'] == recovery.UID and not node['spec'].get('unschedulable'), 'unexpected preexisting node cordon')
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': recovery.UID},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
                 {'op': 'add', 'path': '/spec/unschedulable', 'value': True}]
        api.call('patch', 'node', recovery.NODE, '--type=json', '-p', json.dumps(patch), '-o', 'json')
        latest = collect(api)
        validate(latest, baseline=True)
        require(latest['map']['epoch'] == baseline['epoch'] and emby.observe(args) == context, 'pre-out state changed; observe before continuing')
        intent = {'owner': owner, 'revision': revision, 'baseline': baseline, 'capacity': capacity,
                  'recovery': proof, 'created': datetime.now(timezone.utc).isoformat(), 'action': 'ceph osd out 7',
                  'osd_uuid': OSDS[7], 'no_purge_or_device_write': True}
        record(args, 'evacuation-intent.json', intent)
        # One durable intent, one request. An uncertain result is observed, never replayed.
        request = subprocess.run([args.kubectl, 'exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                                  'ceph', 'osd', 'out', '7'], capture_output=True)
        current = collect(api)
        result = {'owner': owner, 'request_returncode': request.returncode, **validate(current)}
        record(args, 'evacuation-out-observed.json', result)
    else:
        result = validate(value)
        owner = json.loads(value['kured']['metadata']['annotations'][JOURNAL])
        require(owner['node_uid'] == recovery.UID and owner['node'] == recovery.NODE and
                owner['source'] == 39 and owner['target'] == 41, 'evacuation maintenance ownership changed')
        result['owner'] = owner
        if result['complete']:
            source = Path(emby.__file__).read_text().split('\ndef observe(')[0]
            existing = production.remote(args, source + '\nhost("bulbasaur")\np=POINT/"evacuation-complete.json"\nprint(json.dumps(json.loads(p.read_bytes())if p.exists()else None))', '10.0.20.13')
            if existing is None:
                record(args, 'evacuation-complete.json', result)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
