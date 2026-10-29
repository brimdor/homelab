#!/usr/bin/env python3
"""Issue 103 serial K3s bridge using the existing ownership and drain journals."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

import maintenance_actor_hold as actors
import maintenance_hop_journal as hops
import maintenance_k3s_contract as contract
from maintenance_node_drain import ZOT, hashed, private_json


# The first production stage cannot cross the unresolved upstream etcd 3.6 gate.
SOURCE, TARGET = contract.VERSIONS[:2]
SERVERS = ('charmander', 'squirtle', 'bulbasaur')
AUTH_WARNINGS = {'AUTH_INSECURE_CLIENT_KEY_TYPE', 'AUTH_INSECURE_KEYS_ALLOWED',
                 'AUTH_INSECURE_KEYS_CREATABLE', 'AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE'}


def backup_node(args):
    """Stream only K3s executable/configuration to an existing trusted off-node receiver."""
    import maintenance_production_node as production
    point = '/var/lib/homelab-recovery/maintenance-103/k3s-config-' + args.node + '-' + uuid.uuid4().hex
    header = {'node': args.node, 'node_uid': production.UID, 'identity': production.IDENTITY, 'version': SOURCE}
    sender_program = r'''
import hashlib,json,os,pathlib,socket,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()==HEADER['node']
assert pathlib.Path('/etc/machine-id').read_text().strip()==HEADER['identity']['machine']
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()==HEADER['identity']['root_uuid']
paths=[pathlib.Path(p)for p in('/usr/local/bin/k3s','/etc/rancher/k3s/config.yaml',
 '/etc/systemd/system/k3s.service','/etc/systemd/system/k3s.service.env')]
paths+=[p for directory in('/etc/rancher/k3s/config.yaml.d','/etc/systemd/system/k3s.service.d')
 for p in sorted(pathlib.Path(directory).glob('*'))]
paths=[p for p in paths if p.exists()]
assert paths and paths[0]==pathlib.Path('/usr/local/bin/k3s')
records={}
for path in paths:
 assert not any(p.is_symlink()for p in(path,*path.parents))
 info=path.stat();assert path.is_file()and info.st_uid==0 and not info.st_mode&0o022
 records[str(path)]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':info.st_size}
assert records['/usr/local/bin/k3s']['sha256']==EXPECTED_SHA
sys.stdout.buffer.write(json.dumps({'header':HEADER,'files':records},sort_keys=True).encode()+b'\n');sys.stdout.buffer.flush()
result=subprocess.run(['tar','--numeric-owner','--acls','--xattrs','--selinux','-C','/','-cf','-',
 *[str(p).lstrip('/')for p in paths]])
assert result.returncode==0
assert all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==v['sha256']for p,v in records.items())
'''
    receiver_program = '''
import hashlib,json,os,pathlib,socket,stat,subprocess,sys,tarfile
assert os.geteuid()==0 and socket.gethostname()=='pikachu'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0a7daf8b33244d9d85f46223c3582da9'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='76e53a95-725a-4430-9d7b-a8db413f3997'
point=pathlib.Path(POINT)
assert not any(p.is_symlink()for p in(point,*point.parents))and not point.exists()
assert point.parent.is_dir()and point.parent.stat().st_uid==0 and stat.S_IMODE(point.parent.stat().st_mode)==0o700
assert subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(point.parent)],text=True).strip()=='ext4'
point.mkdir(mode=0o700)
value=json.loads(sys.stdin.buffer.readline(65537));assert value['header']==HEADER and len(value['files'])<50
digest=hashlib.sha256();total=0
with(point/'config.tar').open('xb')as output:
 os.fchmod(output.fileno(),0o600)
 for chunk in iter(lambda:sys.stdin.buffer.read(1048576),b''):
  total+=len(chunk);assert total<256*1024*1024;digest.update(chunk);output.write(chunk)
 output.flush();os.fsync(output.fileno())
with tarfile.open(point/'config.tar')as archive:
 members=archive.getmembers();assert len(members)==len(value['files'])
 assert {m.name for m in members}=={p.lstrip('/')for p in value['files']}
 for member in members:
  expected=value['files']['/'+member.name]
  assert member.isfile()and member.uid==0 and member.size==expected['size']
  assert hashlib.sha256(archive.extractfile(member).read()).hexdigest()==expected['sha256']
value.update(point=POINT,receiver='pikachu',archive_sha256=digest.hexdigest(),bytes=total,accepted=True)
raw=json.dumps(value,sort_keys=True).encode()
with(point/'verified.json').open('xb')as output:
 os.fchmod(output.fileno(),0o600);output.write(raw);output.flush();os.fsync(output.fileno())
for path in(point,point.parent):
 fd=os.open(path,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(raw.decode())
'''
    sender = receiver = None
    try:
        sender_program = 'HEADER=' + repr(header) + '\nEXPECTED_SHA=' + repr(contract.SHA256[SOURCE]) + '\n' + sender_program
        receiver_program = 'POINT=' + repr(point) + '\nHEADER=' + repr(header) + '\n' + receiver_program
        sender = subprocess.Popen(production.ssh(args) + ['python3 -B -c ' + shlex.quote(sender_program)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        receiver = subprocess.Popen(production.ssh(args, '10.0.20.14') +
            ['python3 -B -c ' + shlex.quote(receiver_program)], stdin=sender.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sender.stdout.close(); output, _ = receiver.communicate(); sender.wait()
        actors.require(sender.returncode == receiver.returncode == 0,
                       'protected K3s configuration transfer incomplete; preserve partial point')
        value = json.loads(output)
        actors.require(value['accepted'] is True and value['header'] == header, 'configuration receipt differs')
        return value
    finally:
        for process in (sender, receiver):
            if process is not None and process.poll() is None:
                process.terminate(); process.wait()


def verify_recovery(args, nodes, fresh=False):
    """Re-read original protected data; a local success receipt alone cannot authorize activation."""
    import etcd_recovery
    import maintenance_production_node as production
    copied = json.loads(Path(args.recovery_copy).read_bytes())
    restored = json.loads(Path(args.recovery_receipt).read_bytes())
    config = json.loads(Path(args.node_recovery).read_bytes())
    actors.require(copied.get('accepted') is True and copied.get('phase') == 'protected-copy' and
                   restored.get('accepted') is True and restored.get('phase') == 'full-restore' and
                   copied['manifest_sha256'] == restored['manifest_sha256'] and restored['version'] == SOURCE and
                   all(restored.get(k) is True for k in ('protected_point_unchanged',
                       'protected_point_labels_unchanged', 'protected_secret_readback_matches')) and
                   all(restored['cleanup'].values()) and copied['metadata']['version'] == SOURCE and
                   copied['metadata']['nodes'] == {n['metadata']['name']: n['metadata']['uid'] for n in nodes},
                   'matching protected source restore evidence differs')
    actors.require(config.get('accepted') is True and config['header'] == {
        'node': args.node, 'node_uid': production.UID, 'identity': production.IDENTITY, 'version': SOURCE} and
        config['receiver'] == 'pikachu' and config['files']['/usr/local/bin/k3s']['sha256'] == contract.SHA256[SOURCE],
        'off-node K3s executable/configuration recovery differs')
    source = Path(etcd_recovery.__file__).read_text().rsplit('\nif __name__ == "__main__":', 1)[0]
    program = source + '\n' + '''
require_host('pikachu', VERSION)
point=Path(COPIED['point']);manifest=verify_point(point,COPIED['manifest_sha256'])
assert manifest['metadata']==COPIED['metadata']
if FRESH:assert 0<=time.time()-manifest['metadata']['snapshot_mtime_ns']/1e9<3600
private_root();root=Path(CONFIG['point'])
assert root.parent==ROOT and not any(p.is_symlink()for p in(root,*root.parents))
assert stat.S_IMODE(root.stat().st_mode)==0o700
assert json.loads((root/'verified.json').read_bytes())==CONFIG
assert source_record('config.tar',root/'config.tar')[0]['sha256']==CONFIG['archive_sha256']
print(json.dumps({'protected_points_unchanged':True}))
'''
    production.remote(args, 'COPIED=' + repr(copied) + '\nCONFIG=' + repr(config) +
        '\nFRESH=' + repr(fresh) + '\n' + program, '10.0.20.14')
    return {'etcd': copied, 'restored': restored, 'configuration': config}


def runtime(native, version):
    """Observe the packed binary and the actual unpacked running executable separately."""
    import tomllib
    from maintenance_k3s_binary import record
    actors.require(native('rpm', '-E', '%fedora') == '44' and native('getenforce') == 'Enforcing' and
                   Path('/sys/fs/selinux/enforce').read_text().strip() == '1', 'host security differs')
    actors.require('SELINUX=enforcing' in Path('/etc/selinux/config').read_text().splitlines() and
                   not {'selinux=0', 'enforcing=0'}.intersection(Path('/proc/cmdline').read_text().split()),
                   'persistent SELinux enforcement differs')
    binary = record(Path('/usr/local/bin/k3s'))
    actors.require(binary['sha256'] == contract.SHA256[version] and binary['mode'] == 0o755,
                   'installed K3s artifact differs')
    pid = int(native('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value'))
    actors.require(pid > 1 and native('systemctl', 'is-active', 'k3s') == 'active' and
                   native('systemctl', 'show', 'k3s', '-p', 'KillMode', '--value') == 'process' and
                   native('systemctl', 'show', 'k3s', '-p', 'Delegate', '--value') == 'yes',
                   'K3s service cannot preserve running containers')
    executable = '/proc/' + str(pid) + '/exe'
    # The multicall executable reports argv[0]'s basename when invoked through /proc.
    actors.require(native(executable, '--version').splitlines()[0].split()[:3] ==
                   ['exe', 'version', version], 'running K3s executable version differs')
    config = tomllib.loads(Path('/var/lib/rancher/k3s/agent/etc/containerd/config.toml').read_text())
    images = config.get('plugins', {}).get('io.containerd.cri.v1.images', {})
    actors.require(config.get('version') == 3 and images.get('snapshotter') == 'stargz' and
                   images.get('disable_snapshot_annotations') is False, 'CRI stargz configuration differs')
    rows = [line.split() for line in native('/usr/local/bin/k3s', 'ctr', 'plugins', 'list').splitlines()
            if line.split()[:2] == ['io.containerd.snapshotter.v1', 'stargz']]
    actors.require(rows == [['io.containerd.snapshotter.v1', 'stargz', 'linux/amd64', 'ok']],
                   'native AMD64 stargz plugin is not healthy')
    identifiers = native('/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'list', '-q').splitlines()
    actors.require(identifiers, 'running native workload evidence absent')
    for identifier in identifiers:
        actors.require(len(identifier) == 64 and all(c in '0123456789abcdef' for c in identifier),
                       'native container identifier differs')
        item = json.loads(native('/usr/local/bin/k3s', 'ctr', '-n', 'k8s.io', 'containers', 'info', identifier))
        actors.require(item['ID'] == identifier and item['Snapshotter'] == 'stargz' and item['SnapshotKey'],
                       'running workload does not use stargz')
    files = [Path('/etc/rancher/k3s/config.yaml'), Path('/etc/systemd/system/k3s.service.env')]
    files += sorted(Path('/etc/rancher/k3s/config.yaml.d').glob('*.yaml'))
    files += [Path('/etc/systemd/system/k3s.service')]
    files += sorted(Path('/etc/systemd/system/k3s.service.d').glob('*'))
    configs = {}
    for path in files:
        actors.safe(path)
        if path.exists():
            actors.require(path.is_file() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022,
                           'unsafe K3s configuration')
            configs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    unit = native('systemctl', 'cat', 'k3s')
    actors.require(not native('systemctl', '--failed', '--no-legend', '--plain'), 'failed host units remain')
    return {'version': version, 'binary_sha256': binary['sha256'], 'pid': pid,
            'runtime_sha256': hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
            'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'configs': configs, 'unit_sha256': hashlib.sha256(unit.encode()).hexdigest(),
            'stargz': True, 'selinux': 'Enforcing'}


def unchanged_runtime(before, after):
    actors.require(all(before[key] == after[key] for key in ('boot', 'configs', 'unit_sha256', 'selinux', 'stargz')),
                   'K3s activation changed protected host state')
    actors.require(before['pid'] != after['pid'], 'K3s service restart not observed')


def behavior(args, api, pods):
    """Read existing data paths only; no synthetic Pods, application writes or NAS writes."""
    import datetime
    import re
    agents = [p for p in pods if p['metadata'].get('labels', {}).get('k8s-app') == 'cilium']
    actors.require(len(agents) == 1, 'target Cilium membership differs')
    health = api.call('exec', '-n', 'kube-system', agents[0]['metadata']['name'], '-c', 'cilium-agent',
                      '--', 'cilium-health', 'status', '--verbose', '-o', 'json')
    actors.require({n['name'] for n in health['nodes']} == set(contract.ORDER), 'native mesh membership differs')
    interval = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?', health['probeInterval'])
    actors.require(interval is not None and any(interval.groups()), 'native mesh probe interval invalid')
    seconds = sum(float(v or 0) * scale for v, scale in zip(interval.groups(), (3600, 60, 1)))
    actors.require(0 < seconds <= 600, 'native mesh interval exceeds reviewed bound')
    now = datetime.datetime.now(datetime.timezone.utc)
    for node in health['nodes']:
        for address in (node['host']['primary-address'], node['health-endpoint']['primary-address']):
            for protocol in ('http', 'icmp'):
                result = address[protocol]
                age = (now - datetime.datetime.fromisoformat(result['lastProbed'].replace('Z', '+00:00'))).total_seconds()
                actors.require(not result.get('status') and type(result.get('latency')) is int and result['latency'] > 0
                               and 0 <= age <= 2 * seconds + 30, 'native mesh protocol failed or stale')
    command = [args.kubectl, 'exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'sh', '-c',
               'getent ahostsv4 kubernetes.default.svc.cluster.local && '
               'curl -fsS --connect-timeout 10 --max-time 20 http://gitea-http.gitea:3000/api/healthz']
    result = subprocess.run(command, capture_output=True)
    actors.require(result.returncode == 0 and b'"pass"' in result.stdout, 'cluster DNS/internal Gitea behavior failed')
    result = subprocess.run(['curl', '-fsS', '--connect-timeout', '10', '--max-time', '20', '--resolve',
        'git.eaglepass.io:443:10.0.20.226', 'https://git.eaglepass.io/api/v1/version'], capture_output=True)
    actors.require(result.returncode == 0 and json.loads(result.stdout).get('version'), 'Gitea TLS/L2 behavior failed')
    return {'mesh_nodes': sorted(contract.ORDER), 'http_icmp_host_endpoint': True,
            'cluster_dns_internal_gitea': True, 'gitea_tls_l2': True}


def native_operation(context):
    """Run one explicit action; pending actions are observed, never replayed."""
    from maintenance_k3s_binary import Binary
    from maintenance_node_drain import Drain
    from maintenance_node_scheduling import Scheduling
    from maintenance_safe_release import Release, KINDS
    api, controller, hold, owner, native, identity, rpc = (context[key] for key in
        ('api', 'controller', 'hold', 'owner', 'native', 'identity', 'rpc'))
    operation, root = context['operation'], hold.state
    actors.require(owner.get('component') == 'k3s' and (owner['source'], owner['target']) == (SOURCE, TARGET)
                   and owner['node'] in SERVERS, 'unreviewed production bridge stage')
    journal = hops.Journal(controller, hold, owner['owner'])
    before_path = root / ('k3s-before-' + owner['owner'] + '.json')
    def evidence(kind='prerequisites'):
        return rpc(kind)
    def verifier(value):
        return lambda step, digest: digest == hashed(value) and evidence() == value
    if operation == 'initialize':
        if hold.marker.exists():
            hold.resume(owner['owner'])
        else:
            hold.acquire(owner['owner'], context['expected_identity'], owner['revision'])
        before = runtime(native, SOURCE)
        if not before_path.exists():
            actors.exclusive_file(before_path, hops.canonical(before), 0o600)
        actors.require(private_json(before_path) == before, 'initial K3s runtime changed')
        saved = context['recovery_manifest']['configuration']['files']
        actors.require(all(saved.get(path, {}).get('sha256') == digest for path, digest in before['configs'].items()),
                       'off-node configuration backup does not match current host')
        recovery_path = root / ('k3s-recovery-' + owner['owner'] + '.json')
        if not recovery_path.exists():
            actors.exclusive_file(recovery_path, hops.canonical(context['recovery_manifest']), 0o600)
        actors.require(private_json(recovery_path) == context['recovery_manifest'], 'recovery binding differs')
        if not journal.path.exists():
            journal.initialize()
        result = {'owner': owner, 'journal': journal.inspect(), 'before': before}
    elif operation == 'release':
        release = Release(journal)
        value = evidence('applications'); digest = hashed(value)
        def safe(header, observed):
            unchanged_runtime(private_json(before_path), runtime(native, TARGET))
            return (observed == digest and identity() == header['owners']['host']['identity'] and
                    evidence('applications') == value)
        if not release.path.exists():
            release.prepare(digest, safe)
        result = release.observe(digest, safe)
        if result['state']['kinds'] == ['header']:
            result = release.release_host(digest, safe)
        if result['state']['kinds'] == list(KINDS[:3]):
            result = release.release_global(digest, safe)
    else:
        state = journal.inspect()
        if operation == 'inspect':
            result = {'owner': owner, 'journal': state}
        elif operation in ('cordon', 'restore-scheduling'):
            step = operation.replace('-', '_'); worker = Scheduling(journal, api)
            value = evidence(); digest = hashed(value)
            path = root / (step + '-' + owner['owner'] + '.json')
            original = private_json(root / ('cordon-' + owner['owner'] + '.json')) if step != 'cordon' else None
            if not path.exists():
                actors.exclusive_file(path, hops.canonical(worker.plan(step, original)), 0o600)
            plan = private_json(path)
            if not state['pending']:
                worker.dispatch(plan, hashed(plan), digest, verifier(value))
            result = worker.observe(plan, digest, verifier(value))
        elif operation == 'drain':
            worker = Drain(journal, api); value = evidence(); digest = hashed(value)
            path = root / ('drain-' + owner['owner'] + '.json')
            if not path.exists():
                actors.exclusive_file(path, hops.canonical(worker.inventory()), 0o600)
            plan = private_json(path)
            if not state['pending']:
                worker.start(plan, hashed(plan), digest, verifier(value))
            elif not worker.path.exists():
                worker.attach(plan)
            result = worker.advance(digest, verifier(value))
            if result.get('complete'):
                accepted = dict(result)
                journal.accept(result['parent_intent']['sha256'], hashed(accepted),
                    lambda step, observed: step == 'drain' and observed == hashed(accepted) and
                    evidence() == value and worker.advance(digest, verifier(value)) == accepted)
        elif operation in ('prepare-binary', 'activate-binary', 'observe-binary'):
            worker = Binary(journal, native)
            if operation == 'observe-binary':
                def verify_runtime(current_owner, pid):
                    after = runtime(native, TARGET); unchanged_runtime(private_json(before_path), after)
                    actors.require(current_owner == owner and after['pid'] == pid, 'runtime owner or PID differs')
                    evidence('infrastructure')
                    return dict(after, accepted=True)
                result = worker.observe(verify_runtime)
            else:
                value = evidence(); digest = hashed(value)
                def source_verified(step, observed):
                    return verifier(value)(step, observed) and runtime(native, SOURCE) == private_json(before_path)
                result = (worker.prepare(digest, source_verified) if operation == 'prepare-binary'
                          else worker.activate(digest, source_verified))
        elif operation in ('verify-infrastructure', 'accept-applications'):
            step = operation.replace('-', '_'); kind = 'applications' if step == 'accept_applications' else 'infrastructure'
            after = runtime(native, TARGET); unchanged_runtime(private_json(before_path), after)
            value = {'runtime': after, 'health': evidence(kind)}; digest = hashed(value)
            def verify(step_name, observed):
                return (step_name == step and observed == digest and runtime(native, TARGET) == after and
                        evidence(kind) == value['health'])
            if not state['pending']:
                state = journal.begin(step, digest, digest, verify)
            result = {'receipt': value, 'journal': journal.accept(state['pending']['sha256'], digest, verify)}
        else:
            raise RuntimeError('unreviewed K3s operation')
    print(json.dumps({'result': result}), flush=True)


def registry(args, api, ref=None):
    import maintenance_production_node as production
    production.protected_registry(api)
    pods = api.call('get', 'pods', '-n', 'zot', '-o', 'json')['items']; pod = pods[0]
    if ref is not None:
        actors.require(ref == {'namespace': 'zot', 'name': pod['metadata']['name'], 'uid': ZOT['pod_uid'],
                               'spec_sha256': hashed(pod['spec'])}, 'registry drain reference differs')
    program = '''
import json,pathlib,subprocess
cid=EXPECTED['container_id'].removeprefix('containerd://')
item=json.loads(subprocess.check_output(['/usr/local/bin/k3s','crictl','inspect',cid]))
assert item['status']['id']==cid and item['status']['state']=='CONTAINER_RUNNING'
assert item['status']['labels']['io.kubernetes.pod.uid']==EXPECTED['pod_uid']
pid=item['info']['pid'];value=pathlib.Path('/proc/'+str(pid)+'/stat').read_text()
result={'pid':pid,'start_ticks':value[value.rfind(')')+2:].split()[19],
 'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'label':pathlib.Path('/proc/'+str(pid)+'/attr/current').read_text().strip().rstrip('\\x00')}
assert all(result[key]==EXPECTED[key]for key in result)
print(json.dumps(result))
'''
    production.remote(args, 'EXPECTED=' + repr(ZOT) + '\n' + program, '10.0.20.11')
    return dict(ZOT, spec_sha256=hashed(pod['spec']))


def observe(args, api, owner, kind):
    """Known key-migration warnings stay visible; all data-plane gates remain strict."""
    import maintenance_production_node as production
    from maintenance_control_plane import observe as quorum
    nodes = api.call('get', 'nodes', '-o', 'json')['items']
    current = {node['metadata']['name']: node for node in nodes}
    actors.require(set(current) == set(contract.ORDER) and len(nodes) == 9, 'active inventory differs')
    for node in nodes:
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        actors.require(not node['metadata'].get('deletionTimestamp') and conditions.get('Ready') == 'True' and
                       all(conditions.get(k) == 'False' for k in ('DiskPressure', 'MemoryPressure', 'PIDPressure')),
                       'node health differs')
    actors.require(current[production.NODE]['metadata']['uid'] == production.UID, 'target Node UID differs')
    versions = {name: node['status']['nodeInfo']['kubeletVersion'] for name, node in current.items()}
    contract.next_node(nodes, SOURCE, TARGET)
    target_version = versions[owner['node']]
    actors.require(target_version in (SOURCE, TARGET), 'target runtime differs')
    cp = quorum(args, {name: versions[name] for name in SERVERS})
    health = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'health', '-f', 'json')
    warnings = set(health.get('checks', {}))
    actors.require(health['status'] in ('HEALTH_OK', 'HEALTH_WARN') and warnings <= AUTH_WARNINGS,
                   'new Ceph health finding')
    cluster = api.call('get', 'cephcluster', 'rook-ceph', '-n', 'rook-ceph', '-o', 'json')
    csi = cluster['status']['cephx']['csi']
    actors.require(cluster['metadata']['uid'] == '901ad331-70b6-40cf-8654-2c6ed97a06b2' and
                   cluster['status']['phase'] == 'Ready' and
                   csi['keyGeneration'] == 1 and csi['keyType'] == 'aes256k' and csi['priorKeyCount'] == 1,
                   'staged CSI key migration identity differs')
    pg = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'pg', 'stat', '-f', 'json')['pg_summary']
    actors.require(pg['num_pgs'] == 177 and sum(s['num'] for s in pg['num_pg_by_state']) == 177 and
                   all({'active', 'clean'} <= set(s['name'].split('+')) <=
                   {'active', 'clean', 'scrubbing', 'deep'} for s in pg['num_pg_by_state']), 'PGs are not clean')
    osds = api.call('exec', '-n', 'rook-ceph', 'deploy/rook-ceph-tools', '--', 'ceph', 'osd', 'dump', '-f', 'json')
    actors.require({o['osd'] for o in osds['osds']} == {1, 2, 6, 7, 8} and
                   all(o['up'] == o['in'] == 1 for o in osds['osds']), 'OSD membership or availability differs')
    held = []
    for item in api.call('get', 'deployments,statefulsets', '-A', '-o', 'json')['items']:
        status, meta = item.get('status', {}), item['metadata']; desired = item['spec'].get('replicas', 1)
        if (status.get('observedGeneration') == meta['generation'] and
                status.get('readyReplicas', 0) == status.get('updatedReplicas', 0) == desired):
            continue
        actors.require(kind != 'applications' and current[owner['node']]['spec'].get('unschedulable') is True and
                       production.pending_on_maintained_node(api, item, owner['node']),
                       'controller recovery incomplete: ' + meta['namespace'] + '/' + meta['name'])
        held.append(meta['uid'])
    registry(args, api)
    if kind in ('infrastructure', 'applications'):
        actors.require(target_version == TARGET, 'target API has not observed new kubelet')
        pods = api.call('get', 'pods', '-A', '--field-selector', 'spec.nodeName=' + owner['node'], '-o', 'json')['items']
        for pod in pods:
            if pod.get('status', {}).get('phase') == 'Succeeded':
                production.completed_job_pod(api, pod)
                continue
            actors.require(not pod['metadata'].get('deletionTimestamp') and
                           pod.get('status', {}).get('phase') == 'Running' and
                           any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status'].get('conditions', [])) and
                           len(pod['status'].get('containerStatuses', [])) == len(pod['spec']['containers']) and
                           all(c.get('ready') for c in pod['status'].get('containerStatuses', [])), 'target Pod unready')
        agents = [p for p in pods if p['metadata'].get('labels', {}).get('k8s-app') == 'cilium']
        actors.require(len(agents) == 1, 'target Cilium membership differs')
        status = api.call('exec', '-n', 'kube-system', agents[0]['metadata']['name'], '-c', 'cilium-agent',
                          '--', 'cilium-dbg', 'status', '--output', 'json')
        actors.require(status['cilium']['state'] == status['kubernetes']['state'] == 'Ok', 'target Cilium unhealthy')
        registration = api.call('get', 'csinode', owner['node'], '-o', 'json')
        actors.require(not registration['metadata'].get('deletionTimestamp') and
                       any(o.get('kind') == 'Node' and o.get('uid') == production.UID
                           for o in registration['metadata'].get('ownerReferences', [])) and
                       {d['name'] for d in registration['spec']['drivers'] if d['nodeID'] == owner['node']} ==
                       {'rook-ceph.rbd.csi.ceph.com', 'rook-ceph.cephfs.csi.ceph.com'}, 'CSI registration differs')
        behavior(args, api, pods)
    if kind == 'applications':
        actors.require(not current[owner['node']]['spec'].get('unschedulable'), 'target remains cordoned')
        applications = api.call('get', 'applications', '-n', 'argocd', '-o', 'json')['items']
        actors.require(applications and all(a['status']['sync']['status'] == 'Synced' and
            (a['status']['health']['status'] == 'Healthy' or
             a['metadata']['name'] == 'rook-ceph' and bool(warnings)) for a in applications), 'Argo recovery incomplete')
    return {'nodes': {name: n['metadata']['uid'] for name, n in current.items()}, 'versions': versions,
            'ceph': health['status'], 'auth_migration_findings': sorted(warnings), 'clean_pgs': 177,
            'held_target_controllers': sorted(held),
            'etcd_members': sorted(m['ID'] for m in cp['members']['members']), 'zot_preserved': True}


def main():
    import maintenance_production_node as production
    from maintenance_api_reader import Reader
    from maintenance_coordination import JOURNAL, Ownership
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'initialize', 'inspect', 'cordon', 'drain', 'prepare-binary',
        'activate-binary', 'observe-binary', 'verify-infrastructure', 'restore-scheduling', 'accept-applications', 'release'))
    parser.add_argument('--node', choices=SERVERS, required=True)
    for name in ('kubectl', 'identity', 'known-hosts'):
        parser.add_argument('--' + name, required=True)
    for name in ('recovery-receipt', 'recovery-copy', 'node-recovery'):
        parser.add_argument('--' + name)
    args = parser.parse_args(); production.select_node(args.node)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    actors.require(subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/master'], text=True).split()[0] ==
                   revision, 'publish reviewed controller before execution')
    names = (*production.MODULES, 'maintenance_k3s_contract', 'maintenance_k3s_binary', 'maintenance_k3s_production')
    bundle = {}
    for name in (*names, 'maintenance_production_node', 'maintenance_control_plane', 'maintenance_api_reader', 'etcd_recovery'):
        path = 'metal/scripts/' + name + '.py'; published = subprocess.check_output(['git', 'show', revision + ':' + path])
        actors.require(Path(path).read_bytes() == published, 'unpublished production dependency: ' + path)
        if name in names:
            bundle[name] = published.decode()
    if args.operation == 'backup':
        print(json.dumps(backup_node(args))); return
    actors.require(all((args.recovery_receipt, args.recovery_copy, args.node_recovery)), 'recovery receipts required')
    api = Reader(args.kubectl)
    try:
        ds, _, nodes = api.snapshot()
        recovery = verify_recovery(args, nodes, fresh=args.operation in ('initialize', 'activate-binary'))
        controller = Ownership(api, production.DS_UID, {n['metadata']['name']: n['metadata']['uid'] for n in nodes})
        raw = ds['metadata'].get('annotations', {}).get(JOURNAL)
        if raw:
            owner = controller.resume(json.loads(raw)['owner'])
            actors.require(owner.get('component') == 'k3s' and owner['node'] == args.node and
                           owner['node_uid'] == production.UID and (owner['source'], owner['target']) == (SOURCE, TARGET),
                           'another transition owns maintenance')
        else:
            actors.require(args.operation == 'initialize' and contract.next_node(nodes, SOURCE, TARGET) == args.node,
                           'finish preceding node before acquiring next')
            prospective = {'node': args.node}
            observe(args, api, prospective, 'prerequisites')
            program = '''
import json,sys,types,pathlib,socket,subprocess
for name,source in BUNDLE.items():
 module=types.ModuleType(name);sys.modules[name]=module;exec(compile(source,name+'.py','exec'),module.__dict__)
def native(*argv):return subprocess.check_output(argv,text=True).strip()
assert socket.gethostname()==NODE and pathlib.Path('/etc/machine-id').read_text().strip()==IDENTITY['machine']
assert native('findmnt','-n','-o','UUID','/')==IDENTITY['root_uuid']
assert MAC in{p.read_text().strip()for p in pathlib.Path('/sys/class/net').glob('*/address')}
result=sys.modules['maintenance_k3s_production'].runtime(native,SOURCE)
assert all(CONFIG['files'].get(path,{}).get('sha256')==digest for path,digest in result['configs'].items())
print(json.dumps(result))
'''
            production.remote(args, 'BUNDLE=' + repr(bundle) + '\nNODE=' + repr(args.node) +
                '\nIDENTITY=' + repr(production.IDENTITY) + '\nMAC=' + repr(production.MAC) +
                '\nSOURCE=' + repr(SOURCE) + '\nCONFIG=' + repr(recovery['configuration']) + '\n' + program)
            owner = controller.acquire(args.node, SOURCE, TARGET, revision, component='k3s')
        def observer(request):
            return registry(args, api, request['ref']) if request['rpc'] == 'protected_registry' else observe(
                args, api, owner, request['rpc'])
        print(json.dumps(production.run_worker(args, api, owner, {}, recovery, bundle,
                                              component_observer=observer)))
    finally:
        api.close()


if __name__ == '__main__':
    main()
