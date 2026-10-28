"""Read-only, exact serial OSD host gates for Issue 103 in-place host maintenance."""

import datetime
import json
import re

from maintenance_coordination import JOURNAL, require


NODE = 'cyndaquil'
NODE_UID = '6a26f4ed-68e6-4681-baf9-47660549c4fb'
CLUSTER_UID = '901ad331-70b6-40cf-8654-2c6ed97a06b2'
FSID = '13c20377-d801-43f9-aebd-59f62df5dad1'
DEPLOYMENT_UID = '204dce1a-c8d5-49ed-9b40-76ed940e6cfe'
STATE_UID = '5bb7a0f0-5cd6-4c83-b004-2d11c1def154'
PROFILES = {
    'cyndaquil': {'node_uid': NODE_UID, 'osd': 1, 'deployment_uid': DEPLOYMENT_UID,
                   'address': '10.0.20.16'},
    'arcanine': {'node_uid': '88aa2572-09df-40b9-8a00-960e9682917c',
                 'osds': {2: 'f8842303-fd7d-423e-84da-43cda22c7c9b',
                          8: '2c6eb278-3ab2-4f6c-b694-64eeb4324648'}, 'address': '10.0.20.19'},
    'growlithe': {'node_uid': '50f95b8f-4117-4c1e-84bc-266c5b23bffb', 'osd': 6,
                  'deployment_uid': '2c29b0f2-06c1-4f67-8bc5-6dccee9c7970', 'address': '10.0.20.18'},
    'sprigatito': {'node_uid': '5d80125d-4228-47dd-b19c-ca86f7d4316c', 'osd': 7,
                  'deployment_uid': '42a28e8a-1390-4c03-9999-5156912beaca', 'address': '10.0.20.20'},
}


def profile_for(node):
    require(node in PROFILES, 'unreviewed OSD host profile')
    return PROFILES[node]


def targets_for(node):
    profile = profile_for(node)
    return profile['osds'] if 'osds' in profile else {profile['osd']: profile['deployment_uid']}


def wait_for_protection(api, node, owner, ref):
    """After one committed eviction, await Rook's own flag; never set it ourselves."""
    profile = profile_for(node)
    targets = targets_for(node)
    match = re.fullmatch(r'rook-ceph-osd-([0-9]+)-[a-z0-9]+', ref.get('controller', {}).get('name', ''))
    target = int(match[1]) if match else None
    require(owner.get('node') == node and owner.get('node_uid') == profile['node_uid'] and
            ref.get('namespace') == 'rook-ceph' and ref.get('keep') is False and
            ref.get('uid') and ref['controller']['kind'] == 'ReplicaSet' and
            target in targets, 'unreviewed queued OSD eviction')
    ds = api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json')
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1' and
            json.loads(ds['metadata']['annotations'][JOURNAL]) == owner,
            'OSD protection wait owner changed')
    current_node = api.call('get', 'node', node, '-o', 'json')
    require(current_node['metadata']['uid'] == profile['node_uid'] and
            current_node['spec'].get('unschedulable') is True, 'OSD protection wait lost cordon')
    replica = api.call('get', 'replicaset', ref['controller']['name'], '-n', 'rook-ceph', '-o', 'json')
    parents = replica['metadata'].get('ownerReferences', [])
    require(replica['metadata']['uid'] == ref['controller']['uid'] and
            not replica['metadata'].get('deletionTimestamp') and len(parents) == 1 and
            parents[0].get('kind') == 'Deployment' and parents[0].get('controller') is True and
            parents[0].get('uid') == targets[target], 'queued OSD controller changed')
    state = api.call('get', 'configmap', 'rook-ceph-pdbstatemap', '-n', 'rook-ceph', '-o', 'json')
    require(state['metadata']['uid'] == STATE_UID and
            state['data'].get('draining-failure-domain', '') in ('', node),
            'foreign Rook protection owner')
    # Eviction acceptance precedes Rook's asynchronous noout/ConfigMap update.
    state = api.call('wait', 'configmap/rook-ceph-pdbstatemap', '-n', 'rook-ceph',
                     '--for=jsonpath={.data.set-no-out}=true', '--timeout=60s', '-o', 'json')
    require(state['metadata']['uid'] == STATE_UID and
            state['data'].get('draining-failure-domain') == node and
            state['data'].get('set-no-out') == 'true', 'Rook protection wait did not match this host')
    accepted = observe(api, node=node)
    current = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                       'ceph', 'osd', 'dump', '--format', 'json')
    require(accepted['owner'] == owner['owner'] and current['fsid'] == FSID and
            current['crush_node_flags'] == {node: ['noout']}, 'actual owned noout protection is absent')
    return {'owner': owner['owner'], 'osd': target, 'evicted_pod_uid': ref['uid'],
            'rook_state_uid': STATE_UID, 'actual_noout_verified': True, 'mutation_performed': False}

OSDS = {1: '1c69c51e-b0da-42ee-bd34-581361740a02',
        2: 'a527115d-9f22-48cc-a718-4f30bdb64399',
        6: 'e7ccd0a2-4d7a-41bb-aac9-5464abe2ba85',
        7: 'ce0a1b10-f169-401b-801c-df3cc7748051',
        8: '38cfd0d6-ace5-4bc2-972a-0315835b3b92'}
POOLS = {1: ('standard-rwo', 2, 1, 1), 2: ('standard-rwx-metadata', 2, 1, 2),
         3: ('standard-rwx-data0', 2, 1, 3), 4: ('.mgr', 3, 2, 0)}
BASE_FLAGS = {'pglog_hardlimit', 'purged_snapdirs', 'recovery_deletes', 'sortbitwise'}
WARNING_CHECKS = {'OSD_DOWN', 'OSD_HOST_DOWN', 'PG_DEGRADED', 'OSD_FLAGS'}
CLEAN_STATES = {'active', 'clean', 'scrubbing', 'deep'}
OWNED_STATES = CLEAN_STATES | {'undersized', 'degraded', 'recovering', 'recovery_wait'}


def validate(value, now=None, node=NODE):
    """Reject any degradation outside the exact owned, cordoned failure domain."""
    profile = profile_for(node)
    node_name, node_uid = node, profile['node_uid']
    targets = targets_for(node)
    deployments = value['deployments'] if len(targets) > 1 else {next(iter(targets)): value['deployment']}
    require(set(deployments) == set(targets), 'exact OSD deployment set differs')
    node, cluster = value['node'], value['cluster']
    require(node['metadata']['name'] == node_name and node['metadata']['uid'] == node_uid and
            not node['metadata'].get('deletionTimestamp'), 'OSD node identity differs')
    require(cluster['metadata']['uid'] == CLUSTER_UID and
            cluster['spec']['removeOSDsIfOutAndSafeToRemove'] is False and
            cluster['spec']['disruptionManagement'] == {
                'managePodBudgets': True, 'osdMaintenanceTimeout': 90}, 'OSD protection differs')
    for target, deployment_uid in targets.items():
        deployment = deployments[target]
        require(deployment['metadata']['uid'] == deployment_uid and
                deployment['spec']['replicas'] == 1 and
                deployment['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname'] == node_name and
                not deployment['metadata'].get('deletionTimestamp'), 'exact OSD deployment differs')
    ds = value['kured']
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1', 'Kured identity differs')
    raw = ds['metadata'].get('annotations', {}).get(JOURNAL)
    owner = json.loads(raw) if raw else None
    owned = bool(owner and owner.get('node') == node_name)
    if owned:
        require(owner.get('node_uid') == node_uid and re.fullmatch(
            r'homelab-maintenance-103-[0-9a-f-]{36}', owner.get('owner', '')) and
            (owner.get('source'), owner.get('target')) in ((39, 41), (41, 43), (43, 44)),
            'OSD maintenance owner differs')
    cordoned = node['spec'].get('unschedulable') is True
    maintenance = owned and cordoned
    osdmap, quorum, health, pgs = value['map'], value['quorum'], value['health'], value['pgs']
    require(osdmap['fsid'] == FSID and quorum['monmap']['fsid'] == FSID and
            len(quorum['quorum_names']) == 3 and len(set(quorum['quorum_names'])) == 3 and
            set(quorum['quorum_names']) == {m['name'] for m in quorum['monmap']['mons']},
            'OSD cluster or monitor quorum differs')
    osds = {o['osd']: o for o in osdmap['osds']}
    require(len(osdmap['osds']) == len(OSDS) and set(osds) == set(OSDS) and
            all(o['uuid'] == OSDS[i] and o['in'] == 1 and o['weight'] == 1
                for i, o in osds.items()), 'OSD identity, membership or weight differs')
    down = {i for i, o in osds.items() if o['up'] != 1}
    require(not down or maintenance and down <= set(targets), 'unowned or unrelated down OSD')
    require(set(osdmap['flags_set']) == BASE_FLAGS and not osdmap['device_class_flags'] and
            all(not (set(o.get('state', [])) & {'noout', 'noup', 'nodown', 'noin'})
                for o in osds.values()), 'unowned global, class or individual OSD flags')
    flags = osdmap['crush_node_flags']
    require(not flags or maintenance and flags == {node_name: ['noout']}, 'foreign CRUSH maintenance flags')
    state = value['pdb_state']
    require(state['metadata']['uid'] == STATE_UID, 'Rook managed PDB state identity differs')
    data = state['data']
    require(not maintenance or data.get('draining-failure-domain', '') in ('', node_name),
            'another failure domain owns Rook disruption protection')
    if flags or down:
        require(maintenance and flags == {node_name: ['noout']} and
                data.get('draining-failure-domain') == node_name and data.get('set-no-out') == 'true',
                'owned OSD noout protection is absent')
        stamp = datetime.datetime.fromisoformat(data[node_name + '-noout-last-set-at'].replace('Z', '+00:00'))
        require(stamp.tzinfo is not None, 'Rook noout timestamp lacks timezone')
        now = now or datetime.datetime.now(datetime.timezone.utc)
        require(0 <= (now - stamp).total_seconds() < 90 * 60, 'Rook noout protection expired or timestamp is future')
    elif not maintenance:
        require(not data.get('draining-failure-domain') and not data.get('set-no-out'),
                'another failure domain owns Rook disruption protection')
    checks = health.get('checks', {})
    require(not health.get('mutes'), 'muted Ceph findings prevent maintenance acceptance')
    if maintenance:
        require(health['status'] in ('HEALTH_OK', 'HEALTH_WARN') and set(checks) <= WARNING_CHECKS and
                all(c.get('severity') == 'HEALTH_WARN' for c in checks.values()),
                'unexpected Ceph health finding during owned OSD maintenance')
        require(not (set(checks) & {'OSD_DOWN', 'OSD_HOST_DOWN'}) or down and down <= set(targets),
                'OSD health warning does not match observed down target')
        require('OSD_FLAGS' not in checks or flags == {node_name: ['noout']}, 'OSD flag warning is not owned')
    else:
        require(health['status'] == 'HEALTH_OK' and not checks and not down and not flags,
                'OSD host requires fully recovered HEALTH_OK')
    pools = {str(p['pool']): p for p in osdmap['pools']}
    require(set(pools) == {str(i) for i in POOLS} and all(p['type'] == 1 and
            (p['pool_name'], p['size'], p['min_size'], p['crush_rule']) == POOLS[int(i)]
            for i, p in pools.items()), 'review changed pool replication before maintenance')
    require(pgs and len(pgs) == value['num_pgs'] and
            len({p['pgid'] for p in pgs}) == len(pgs), 'PG evidence incomplete or duplicated')
    restored = value.get('restored_mapping', {})
    if down:
        require(set(restored) == {p['pgid'] for p in pgs}, 'restored PG mapping evidence incomplete')
    for pg in pgs:
        states = set(pg['state'].split('+'))
        expected = restored[pg['pgid']] if down else pg['up']
        affected = bool(set(targets) & set(expected))
        allowed = OWNED_STATES if maintenance and affected else CLEAN_STATES
        require('active' in states and states <= allowed and
                (maintenance and affected or 'clean' in states), 'inactive or unrelated unhealthy PG')
        pool = pools.get(pg['pgid'].split('.', 1)[0])
        require(pool is not None, 'PG pool is not reviewed')
        require(len(expected) == pool['size'] and len(set(expected)) == pool['size'] and
                set(expected) <= set(OSDS) and
                len(set(expected) - set(targets)) >= pool['min_size'] and
                set(pg['up']) == set(expected) - down and
                len(set(pg['up'])) == len(pg['up']) and
                pg['acting'] and len(set(pg['acting'])) == len(pg['acting']) and
                set(pg['acting']) <= set(expected) and
                sum(osds[i]['up'] == 1 for i in pg['acting']) >= pool['min_size'],
                'PG lacks a reviewed active surviving replica')
        if 'clean' in states:
            require(set(pg['up']) == set(pg['acting']) and len(pg['up']) == pool['size'],
                    'clean PG mapping differs')
    if not down:
        stop = value['ok_to_stop']
        require(stop['ok_to_stop'] is True and stop['osds'] == sorted(targets) and
                stop['num_not_ok_pgs'] == 0, 'exact OSD is not safe to stop')
    for deployment in deployments.values():
        unready = not (deployment.get('status', {}).get('observedGeneration') == deployment['metadata']['generation'] and
                       deployment.get('status', {}).get('readyReplicas') == 1 and
                       deployment.get('status', {}).get('updatedReplicas') == 1)
        require(not unready or maintenance, 'OSD deployment has not recovered')
    # Recheck actual state each time; keep the owner interval stable across a cordon.
    result = {'scope': 'OWNED_OSD_HOST_INTERVAL' if owned else 'HEALTH_OK',
              'cluster_uid': CLUSTER_UID, 'fsid': FSID, 'owner': owner['owner'] if owned else None}
    if len(targets) == 1:
        target, deployment_uid = next(iter(targets.items()))
        result.update(osd=target, osd_uuid=OSDS[target], managed_deployment_uid=deployment_uid)
    else:
        result.update(osds={str(i): OSDS[i] for i in targets},
                      managed_deployment_uids=sorted(targets.values()))
    return result


def observe(api, node=NODE):
    """No mutations: gather complete native Ceph and controller evidence."""
    if node == 'sprigatito':
        from maintenance_sprigatito_evacuation import collect, validate as evacuation_validate
        value = collect(api)
        target = next(o for o in value['map']['osds'] if o['osd'] == 7)
        if target['in'] == 0:
            raw = value['kured']['metadata'].get('annotations', {}).get(JOURNAL)
            owner = json.loads(raw) if raw else None
            profile = profile_for(node)
            require(not owner or owner['node'] == node and owner['node_uid'] == profile['node_uid'] and
                    (owner['source'], owner['target']) in ((39, 41), (41, 43), (43, 44)),
                    'foreign software evacuation owner')
            cordoned = value['node']['spec'].get('unschedulable') is True
            require(target['up'] == 1 or owner and cordoned, 'unowned stopped evacuated OSD')
            require(owner or not value['map']['crush_node_flags'] and value['health']['status'] == 'HEALTH_OK',
                    'unowned evacuation protection or finding')
            evacuation_validate(value, stopped=True, require_cordon=cordoned)
            return {'scope': 'EVACUATED_OSD7_FULL_REPLICAS', 'cluster_uid': CLUSTER_UID, 'fsid': FSID,
                    'owner': owner['owner'] if owner else None, 'osd': 7, 'osd_uuid': OSDS[7],
                    'managed_deployment_uid': profile['deployment_uid']}
    targets = targets_for(node)
    def ceph(*args):
        return api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                        'ceph', *args, '--format', 'json')
    status = ceph('status')
    value = {'node': api.call('get', 'node', node, '-o', 'json'),
             'cluster': api.call('get', 'cephcluster', 'rook-ceph', '-n', 'rook-ceph', '-o', 'json'),
             'kured': api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'),
             'pdb_state': api.call('get', 'configmap', 'rook-ceph-pdbstatemap', '-n', 'rook-ceph', '-o', 'json'),
             'map': ceph('osd', 'dump'), 'quorum': ceph('quorum_status'),
             'health': ceph('health', 'detail'), 'pgs': ceph('pg', 'dump', 'pgs_brief')['pg_stats'],
             'num_pgs': status['pgmap']['num_pgs']}
    deployments = {i: api.call('get', 'deployment', 'rook-ceph-osd-' + str(i), '-n', 'rook-ceph', '-o', 'json') for i in targets}
    if len(targets) == 1:
        value['deployment'] = next(iter(deployments.values()))
    else:
        value['deployments'] = deployments
    if all(o['up'] == 1 for o in value['map']['osds']):
        value['ok_to_stop'] = ceph('osd', 'ok-to-stop', *map(str, sorted(targets)))
    if any(o['up'] != 1 for o in value['map']['osds']):
        recovered = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                             'python3', '-c', OFFLINE_MAPPING, *map(str, sorted(targets)))
        require(recovered['map'] == value['map'] and recovered['temporary_removed'],
                'OSD map changed during offline attribution or native cleanup failed')
        value['restored_mapping'] = parse_mapping(recovered['mapping'])
    return validate(value, node=node)


# Ceph's --mark-up changes only the copied map in memory; never use --save.
OFFLINE_MAPPING = r'''
import tempfile,subprocess,pathlib,json,hashlib,sys
targets=sys.argv[1:];assert targets in (['1'],['6'],['2','8'])
with tempfile.TemporaryDirectory(prefix='maintenance103-readonly-osdmap-') as directory:
 path=pathlib.Path(directory)/'map'
 subprocess.run(['ceph','osd','getmap','-o',str(path)],check=True,capture_output=True)
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 def call(*args):
  return subprocess.check_output(['osdmaptool',str(path),*args],text=True,stderr=subprocess.PIPE)
 original=json.loads(call('--dump','json'))
 assert original['fsid']=='13c20377-d801-43f9-aebd-59f62df5dad1'
 osds=original['osds']
 assert {o['osd']for o in osds}=={1,2,6,7,8}and len(osds)==5
 assert all(o['in']==1 and o['weight']==1 for o in osds)
 assert {o['osd']for o in osds if o['up']!=1}<=set(map(int,targets))
 # Ceph 20.2.1 retains only the last --mark-up argument. With every other OSD
 # already up/in at weight one, --mark-up-in restores only this copied host.
 arguments=['--mark-up',targets[0]]if len(targets)==1 else ['--mark-up-in']
 result={'map':original,'mapping':call(*arguments,'--test-map-pgs-dump-all')}
 assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
assert not pathlib.Path(directory).exists()
result['temporary_removed']=True
print(json.dumps(result))
'''


def parse_mapping(text):
    """Use the upmap-adjusted placement, not raw CRUSH or temporary acting sets."""
    result = {}
    pattern = r'([0-9]+\.[0-9a-f]+) raw \(\[.*?\], p-?\d+\) up \(\[([0-9,]*)\], p-?\d+\) acting \(\[.*?\], p-?\d+\)'
    for line in text.splitlines():
        if not re.match(r'^[0-9]+\.[0-9a-f]+\s', line):
            continue
        match = re.fullmatch(pattern, line)
        require(match is not None and match[1] not in result, 'invalid or duplicate offline PG mapping')
        result[match[1]] = [int(i) for i in match[2].split(',')] if match[2] else []
    require(result, 'offline PG mapping absent')
    return result


NATIVE_IDENTITY = r'''
import json,os,pathlib,stat,subprocess,socket
assert os.geteuid()==0 and socket.gethostname()=='cyndaquil'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='51140709f60f45c1bcd0edfa23dba2ef'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='fc02c8c4-35c6-4efe-a88a-b03d7673c0c8'
assert pathlib.Path('/sys/class/net/enp0s31f6/address').read_text().strip()=='6c:4b:90:5f:8e:43'
disk=json.loads(subprocess.check_output(['lsblk','--json','--bytes','-o','NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,SERIAL','/dev/sda']))['blockdevices']
assert len(disk)==1 and disk[0]['name']=='sda' and disk[0]['type']=='disk'
assert disk[0]['serial']=='S1ZKNXAGB03370' and disk[0]['size']==512110190592
parts=disk[0]['children']
expected=[('sda1',536870912,'vfat','8CAE-C52C','c32010c6-b680-4d44-9c1e-4e21384488b0'),
 ('sda2',68719476736,'ext4','fc02c8c4-35c6-4efe-a88a-b03d7673c0c8','3286e8ce-0da8-4e56-bb7c-42a957e8ca2c'),
 ('sda3',442852442112,'ceph_bluestore',None,'65459bd3-62d0-457c-8d50-d8629b78e787')]
assert [(p['name'],p['size'],p['fstype'],p['uuid'],p['partuuid'])for p in parts]==expected
assert all(p['type']=='part' and not p.get('children')for p in parts)
root=pathlib.Path('/var/lib/rook/rook-ceph/13c20377-d801-43f9-aebd-59f62df5dad1_1c69c51e-b0da-42ee-bd34-581361740a02')
assert root.is_dir()and not any(p.is_symlink()for p in(root,*root.parents))
assert (root/'block').is_symlink()and os.readlink(root/'block')=='/dev/sda3'
for name,wanted in [('ceph_fsid','13c20377-d801-43f9-aebd-59f62df5dad1'),('fsid','1c69c51e-b0da-42ee-bd34-581361740a02'),('whoami','1'),('type','bluestore')]:
 path=root/name
 assert path.is_file()and not path.is_symlink()and path.read_text().strip()==wanted
keyring=root/'keyring';info=keyring.lstat()
assert stat.S_ISREG(info.st_mode)and info.st_uid==0 and not info.st_mode&0o022 and 0<info.st_size<4096
print(json.dumps({'node':'cyndaquil','machine':'51140709f60f45c1bcd0edfa23dba2ef','root_uuid':'fc02c8c4-35c6-4efe-a88a-b03d7673c0c8',
 'disk_serial':'S1ZKNXAGB03370','osd_partition':'65459bd3-62d0-457c-8d50-d8629b78e787','osd_uuid':'1c69c51e-b0da-42ee-bd34-581361740a02',
 'partition_table_and_osd_identity_verified':True,'keyring_content_not_returned':True}))
'''


GROWLITHE_NATIVE_IDENTITY = NATIVE_IDENTITY
for before, after in (
    ('cyndaquil', 'growlithe'),
    ('51140709f60f45c1bcd0edfa23dba2ef', 'a26cbcc990c044dea41fbf4f957f453d'),
    ('fc02c8c4-35c6-4efe-a88a-b03d7673c0c8', '710e2dca-691e-4123-a867-4994b9c6e612'),
    ('6c:4b:90:5f:8e:43', '6c:4b:90:5b:6e:6d'),
    ('S1ZKNXAGB03370', '3C320074050513551212'),
    ('8CAE-C52C', 'D52C-5831'),
    ('c32010c6-b680-4d44-9c1e-4e21384488b0', '5e4ff3cd-c90e-4eac-adfa-58e8f40b8597'),
    ('3286e8ce-0da8-4e56-bb7c-42a957e8ca2c', '5150bd4d-4287-4f71-8ba4-c5315fa3c44a'),
    ('65459bd3-62d0-457c-8d50-d8629b78e787', 'af9a1561-010c-4a61-b73b-e54c75f5c44b'),
    ('1c69c51e-b0da-42ee-bd34-581361740a02', 'e7ccd0a2-4d7a-41bb-aac9-5464abe2ba85'),
    ("('whoami','1')", "('whoami','6')"),
    ("=='/dev/sda3'", "=='/dev/nvme0n1p1'"),
    ("'osd_partition':'af9a1561-010c-4a61-b73b-e54c75f5c44b'", "'osd_partition':'7f1094b0-d185-448d-9a09-6a35e46309e5'"),
):
    assert before in GROWLITHE_NATIVE_IDENTITY
    GROWLITHE_NATIVE_IDENTITY = GROWLITHE_NATIVE_IDENTITY.replace(before, after)
GROWLITHE_NATIVE_IDENTITY = GROWLITHE_NATIVE_IDENTITY.replace("root=pathlib.Path('/var/lib/rook/rook-ceph/", "nvme=json.loads(subprocess.check_output(['lsblk','--json','--bytes','-o','NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,SERIAL','/dev/nvme0n1']))['blockdevices']\nassert nvme==[{'name': 'nvme0n1', 'type': 'disk', 'size': 500107862016, 'fstype': None, 'uuid': None, 'partuuid': None, 'serial': 'S58SNM0R508184P', 'children': [{'name': 'nvme0n1p1', 'type': 'part', 'size': 500106788864, 'fstype': 'ceph_bluestore', 'uuid': None, 'partuuid': '7f1094b0-d185-448d-9a09-6a35e46309e5', 'serial': None}]}]\n" + "root=pathlib.Path('/var/lib/rook/rook-ceph/", 1)


ARCANINE_NATIVE_IDENTITY = r'''
import json,os,pathlib,socket,stat,subprocess
assert os.geteuid()==0 and socket.gethostname()=='arcanine'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='d877c676fcc2434f9a169f8dc0594676'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='d5ffa207-0e76-47a7-a941-1829732d3bc6'
assert '4c:cc:6a:3d:e5:3f'in{p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
columns='NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,SERIAL'
disk=json.loads(subprocess.check_output(['lsblk','--json','--bytes','-o',columns,'/dev/sda']))['blockdevices']
assert len(disk)==1 and disk[0]['type']=='disk'and disk[0]['name']=='sda'
assert disk[0]['serial']=='160511B2554D'and disk[0]['size']==1024209543168
parts=disk[0]['children']
assert [(p['name'],p['size'],p['fstype'],p['uuid'],p['partuuid'])for p in parts]==[
 ('sda1',536870912,'vfat','D3B6-7854','26c0de68-23b8-4a74-abbe-fc1054cc60a3'),
 ('sda2',68719476736,'ext4','d5ffa207-0e76-47a7-a941-1829732d3bc6','71e8bd51-73b4-4d35-838d-0f7085e869d5'),
 ('sda3',954951794688,'ceph_bluestore',None,'1a61507d-ed61-4f12-8927-4eb3716555b5')]
assert all(p['type']=='part'and not p.get('children')for p in parts)
second=json.loads(subprocess.check_output(['lsblk','--json','--bytes','-o',columns,'/dev/sdb']))['blockdevices']
assert second==[{'name':'sdb','type':'disk','size':512110190592,'fstype':'ceph_bluestore','uuid':None,
 'partuuid':None,'serial':'S1ZKNXAGA08806'}]
fsid='13c20377-d801-43f9-aebd-59f62df5dad1'
identities={2:('a527115d-9f22-48cc-a718-4f30bdb64399','/dev/sda3'),8:('38cfd0d6-ace5-4bc2-972a-0315835b3b92','/dev/sdb')}
for target,(uid,block)in identities.items():
 root=pathlib.Path('/var/lib/rook/rook-ceph')/(fsid+'_'+uid)
 assert root.is_dir()and not any(p.is_symlink()for p in(root,*root.parents))
 assert(root/'block').is_symlink()and os.readlink(root/'block')==block
 for name,wanted in [('ceph_fsid',fsid),('fsid',uid),('whoami',str(target)),('type','bluestore')]:
  path=root/name
  assert path.is_file()and not path.is_symlink()and path.read_text().strip()==wanted
 info=(root/'keyring').lstat()
 assert stat.S_ISREG(info.st_mode)and info.st_uid==0 and not info.st_mode&0o022 and 0<info.st_size<4096
print(json.dumps({'node':'arcanine','machine':'d877c676fcc2434f9a169f8dc0594676',
 'root_uuid':'d5ffa207-0e76-47a7-a941-1829732d3bc6','disk_serials':['160511B2554D','S1ZKNXAGA08806'],
 'osds':{str(i):uid for i,(uid,block)in identities.items()},
 'partition_table_and_osd_identity_verified':True,'keyring_content_not_returned':True}))
'''


def native_identity(args, node=NODE):
    from maintenance_production_node import remote
    profile = profile_for(node)
    program = {'cyndaquil': NATIVE_IDENTITY, 'growlithe': GROWLITHE_NATIVE_IDENTITY,
               'arcanine': ARCANINE_NATIVE_IDENTITY, 'sprigatito': SPRIGATITO_NATIVE_IDENTITY}[node]
    return remote(args, program, profile['address'])


SPRIGATITO_NATIVE_IDENTITY = NATIVE_IDENTITY
for before, after in (
    ('cyndaquil', 'sprigatito'),
    ('enp0s31f6', 'eno1'),
    ('51140709f60f45c1bcd0edfa23dba2ef', 'e5796c3018b6448eae0c69405926317e'),
    ('fc02c8c4-35c6-4efe-a88a-b03d7673c0c8', 'c27f6613-788e-4d00-802c-5b84a730a631'),
    ('6c:4b:90:5f:8e:43', '4c:cc:6a:34:dc:6d'),
    ('S1ZKNXAGB03370', 'DI0403Y002080'),
    ('8CAE-C52C', '6972-C181'),
    ('c32010c6-b680-4d44-9c1e-4e21384488b0', '7a137097-0224-47c7-94fd-07554b4b2ae6'),
    ('3286e8ce-0da8-4e56-bb7c-42a957e8ca2c', '3318f778-614d-4a51-8598-854df4d1ae06'),
    ('65459bd3-62d0-457c-8d50-d8629b78e787', '75944ab8-2af9-4622-af67-c41d61977f4f'),
    ('1c69c51e-b0da-42ee-bd34-581361740a02', 'ce0a1b10-f169-401b-801c-df3cc7748051'),
    ("('whoami','1')", "('whoami','7')"),
):
    assert before in SPRIGATITO_NATIVE_IDENTITY
    SPRIGATITO_NATIVE_IDENTITY = SPRIGATITO_NATIVE_IDENTITY.replace(before, after)
