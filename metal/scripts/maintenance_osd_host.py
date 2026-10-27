"""Read-only, exact Cyndaquil OSD gates for Issue 103 in-place host maintenance."""

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


def validate(value, now=None):
    """Reject any degradation outside the exact owned, cordoned failure domain."""
    node, cluster, deployment = value['node'], value['cluster'], value['deployment']
    require(node['metadata']['name'] == NODE and node['metadata']['uid'] == NODE_UID and
            not node['metadata'].get('deletionTimestamp'), 'OSD node identity differs')
    require(cluster['metadata']['uid'] == CLUSTER_UID and
            cluster['spec']['removeOSDsIfOutAndSafeToRemove'] is False and
            cluster['spec']['disruptionManagement'] == {
                'managePodBudgets': True, 'osdMaintenanceTimeout': 90}, 'OSD protection differs')
    require(deployment['metadata']['uid'] == DEPLOYMENT_UID and
            deployment['spec']['replicas'] == 1 and
            deployment['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname'] == NODE and
            not deployment['metadata'].get('deletionTimestamp'), 'exact OSD deployment differs')
    ds = value['kured']
    require(ds['metadata']['uid'] == '4abc4fee-c3be-440e-8945-34bb3fb15ce1', 'Kured identity differs')
    raw = ds['metadata'].get('annotations', {}).get(JOURNAL)
    owner = json.loads(raw) if raw else None
    owned = bool(owner and owner.get('node') == NODE)
    if owned:
        require(owner.get('node_uid') == NODE_UID and re.fullmatch(
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
    require(not down or maintenance and down == {1}, 'unowned or unrelated down OSD')
    require(set(osdmap['flags_set']) == BASE_FLAGS and not osdmap['device_class_flags'] and
            all(not (set(o.get('state', [])) & {'noout', 'noup', 'nodown', 'noin'})
                for o in osds.values()), 'unowned global, class or individual OSD flags')
    flags = osdmap['crush_node_flags']
    require(not flags or maintenance and flags == {NODE: ['noout']}, 'foreign CRUSH maintenance flags')
    state = value['pdb_state']
    require(state['metadata']['uid'] == STATE_UID, 'Rook managed PDB state identity differs')
    data = state['data']
    require(not maintenance or data.get('draining-failure-domain', '') in ('', NODE),
            'another failure domain owns Rook disruption protection')
    if flags or down:
        require(maintenance and flags == {NODE: ['noout']} and
                data.get('draining-failure-domain') == NODE and data.get('set-no-out') == 'true',
                'owned OSD noout protection is absent')
        stamp = datetime.datetime.fromisoformat(data[NODE + '-noout-last-set-at'].replace('Z', '+00:00'))
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
        require(not (set(checks) & {'OSD_DOWN', 'OSD_HOST_DOWN'}) or down == {1},
                'OSD health warning does not match observed down target')
        require('OSD_FLAGS' not in checks or flags == {NODE: ['noout']}, 'OSD flag warning is not owned')
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
        affected = 1 in expected
        allowed = OWNED_STATES if maintenance and affected else CLEAN_STATES
        require('active' in states and states <= allowed and
                (maintenance and affected or 'clean' in states), 'inactive or unrelated unhealthy PG')
        pool = pools.get(pg['pgid'].split('.', 1)[0])
        require(pool is not None, 'PG pool is not reviewed')
        require(len(expected) == pool['size'] and len(set(expected)) == pool['size'] and
                set(expected) <= set(OSDS) and
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
        require(stop['ok_to_stop'] is True and stop['osds'] == [1] and
                stop['num_not_ok_pgs'] == 0, 'exact OSD is not safe to stop')
    unready = not (deployment.get('status', {}).get('observedGeneration') == deployment['metadata']['generation'] and
                   deployment.get('status', {}).get('readyReplicas') == 1 and
                   deployment.get('status', {}).get('updatedReplicas') == 1)
    require(not unready or maintenance, 'OSD deployment has not recovered')
    # Recheck actual state each time; keep the owner interval stable across a cordon.
    return {'scope': 'OWNED_OSD_HOST_INTERVAL' if owned else 'HEALTH_OK',
            'cluster_uid': CLUSTER_UID, 'fsid': FSID, 'osd': 1, 'osd_uuid': OSDS[1],
            'owner': owner['owner'] if owned else None,
            'managed_deployment_uid': DEPLOYMENT_UID}


def observe(api):
    """No mutations: gather complete native Ceph and controller evidence."""
    def ceph(*args):
        return api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                        'ceph', *args, '--format', 'json')
    status = ceph('status')
    value = {'node': api.call('get', 'node', NODE, '-o', 'json'),
             'cluster': api.call('get', 'cephcluster', 'rook-ceph', '-n', 'rook-ceph', '-o', 'json'),
             'deployment': api.call('get', 'deployment', 'rook-ceph-osd-1', '-n', 'rook-ceph', '-o', 'json'),
             'kured': api.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'),
             'pdb_state': api.call('get', 'configmap', 'rook-ceph-pdbstatemap', '-n', 'rook-ceph', '-o', 'json'),
             'map': ceph('osd', 'dump'), 'quorum': ceph('quorum_status'),
             'health': ceph('health', 'detail'), 'pgs': ceph('pg', 'dump', 'pgs_brief')['pg_stats'],
             'num_pgs': status['pgmap']['num_pgs']}
    if all(o['up'] == 1 for o in value['map']['osds']):
        value['ok_to_stop'] = ceph('osd', 'ok-to-stop', '1')
    if any(o['up'] != 1 for o in value['map']['osds']):
        recovered = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--',
                             'python3', '-c', OFFLINE_MAPPING)
        require(recovered['map'] == value['map'] and recovered['temporary_removed'],
                'OSD map changed during offline attribution or native cleanup failed')
        value['restored_mapping'] = parse_mapping(recovered['mapping'])
    return validate(value)


# Ceph's --mark-up changes only the copied map in memory; never use --save.
OFFLINE_MAPPING = r'''
import tempfile,subprocess,pathlib,json,hashlib
with tempfile.TemporaryDirectory(prefix='maintenance103-readonly-osdmap-') as directory:
 path=pathlib.Path(directory)/'map'
 subprocess.run(['ceph','osd','getmap','-o',str(path)],check=True,capture_output=True)
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 def call(*args):
  return subprocess.check_output(['osdmaptool',str(path),*args],text=True,stderr=subprocess.PIPE)
 result={'map':json.loads(call('--dump','json')),
         'mapping':call('--mark-up','1','--test-map-pgs-dump-all')}
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


def native_identity(args):
    from maintenance_production_node import remote
    return remote(args, NATIVE_IDENTITY, '10.0.20.16')
