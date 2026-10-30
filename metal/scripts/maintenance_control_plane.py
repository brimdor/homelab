"""Squirtle's exact etcd observation client and off-node recovery binding."""

import hashlib
import json
from pathlib import Path


CLIENT = '/var/lib/homelab-recovery/maintenance-103/tools/etcd-v3.5.21/etcdctl'
ARCHIVE_URL = 'https://github.com/etcd-io/etcd/releases/download/v3.5.21/etcd-v3.5.21-linux-amd64.tar.gz'
ARCHIVE_SHA256 = 'adddda4b06718e68671ffabff2f8cee48488ba61ad82900e639d108f2148501c'
BINARY_SHA256 = 'a3599fe339c6c1c9f67263565055ba7b84ac9198c9aea7abf9175a476ae2ca22'
IDENTITY = '90c7f1d7caea486d9dc9bdbb4ec5ae21'
IDENTITIES = {'charmander': '58d682ccab5a4269acedc3cdf53e46dc', 'squirtle': IDENTITY,
              'bulbasaur': 'f61201c3e2ba4b8cbd31e09f77da2ad0'}

INSTALL = r'''
import hashlib,io,json,os,pathlib,socket,stat,subprocess,tarfile,urllib.request
assert os.geteuid()==0 and socket.gethostname()==HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==IDENTITY
path=pathlib.Path(CLIENT)
assert not any(p.is_symlink()for p in(path,*path.parents))
assert subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(path.parents[2])],text=True).strip()=='ext4'
with urllib.request.urlopen(ARCHIVE_URL,timeout=60)as response:archive=response.read(32*1024*1024+1)
assert hashlib.sha256(archive).hexdigest()==ARCHIVE_SHA256,'official etcd archive changed'
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz')as package:
 member=package.getmember('etcd-v3.5.21-linux-amd64/etcdctl')
 assert member.isfile()and 0<member.size<32*1024*1024
 content=package.extractfile(member).read()
assert hashlib.sha256(content).hexdigest()==BINARY_SHA256,'official etcd client checksum differs'
for parent in reversed(path.parents):
 if not parent.exists():parent.mkdir(mode=0o700)
 assert parent.is_dir()and parent.stat().st_uid==0 and not parent.stat().st_mode&0o022
if not path.exists():
 with path.open('xb')as target:
  os.fchmod(target.fileno(),0o500);target.write(content);target.flush();os.fsync(target.fileno())
assert path.read_bytes()==content and stat.S_IMODE(path.stat().st_mode)==0o500
fd=os.open(path.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps({'installed':str(path),'archive_sha256':ARCHIVE_SHA256,'binary_sha256':hashlib.sha256(content).hexdigest(),
 'version':subprocess.check_output([str(path),'version'],text=True).splitlines()}))
'''

OBSERVE = r'''
import hashlib,json,os,pathlib,socket,subprocess,urllib.request
assert os.geteuid()==0 and socket.gethostname()==HOST
assert pathlib.Path('/etc/machine-id').read_text().strip()==IDENTITY
assert hashlib.sha256(pathlib.Path(CLIENT).read_bytes()).hexdigest()==BINARY_SHA256,'etcd client changed'
tls='/var/lib/rancher/k3s/server/tls/etcd/'
argv=[CLIENT,'--endpoints='+','.join(ACTIVE_ENDPOINTS),
 '--cacert='+tls+'server-ca.crt','--cert='+tls+'client.crt','--key='+tls+'client.key',
 '--dial-timeout=5s','--command-timeout=15s','--write-out=json']
def query(*args):
 result=subprocess.run(argv+list(args),capture_output=True)
 assert result.returncode==0,'etcd observation failed: '+str(args)
 return json.loads(result.stdout)
members=query('member','list');status=query('endpoint','status');health=query('endpoint','health');alarms=query('alarm','list')
expected={'https://10.0.20.11:2379','https://10.0.20.12:2379','https://10.0.20.13:2379'}
assert len(members['members'])==3 and not any(m.get('isLearner')for m in members['members'])
assert {u for m in members['members']for u in m['clientURLs']}==expected
assert {m['peerURLs'][0]for m in members['members']}=={u.replace(':2379',':2380')for u in expected}
assert len(status)==len(health)==len(ACTIVE_ENDPOINTS) and {v['Endpoint']for v in status}==set(ACTIVE_ENDPOINTS)
assert {v['endpoint']for v in health}==set(ACTIVE_ENDPOINTS)
assert all(v['health']is True for v in health)and not alarms.get('alarms')
assert len({v['Status']['header']['cluster_id']for v in status})==1
assert status[0]['Status']['header']['cluster_id']==10496245635645811339
assert {m['clientURLs'][0]:m['ID']for m in members['members']}=={
 'https://10.0.20.11:2379':11787375536453005064,
 'https://10.0.20.12:2379':16426130908996892198,
 'https://10.0.20.13:2379':480346530818056711}
ids={m['clientURLs'][0]:m['ID']for m in members['members']}
assert len({v['Status']['leader']for v in status})==1 and status[0]['Status']['leader']in{ids[u]for u in ACTIVE_ENDPOINTS}
assert all(v['Status']['header']['member_id']==ids[v['Endpoint']]for v in status)
assert all(v['Status']['version']==EXPECTED_VERSIONS[v['Endpoint']]and not v['Status'].get('errors')for v in status)
print(json.dumps({'members':members,'status':status,'health':health,'alarms':alarms}))
'''


def expected_versions(versions=None):
    names = ('charmander', 'squirtle', 'bulbasaur')
    if versions is None:
        return dict.fromkeys(('https://10.0.20.' + str(n) + ':2379' for n in (11, 12, 13)), '3.5.21')
    import maintenance_k3s_contract as contract
    if set(versions) != set(names) or any(v not in contract.ETCD for v in versions.values()):
        raise RuntimeError('unreviewed control-plane K3s versions')
    order = [contract.VERSIONS.index(versions[name]) for name in names]
    if order != sorted(order, reverse=True) or max(order) - min(order) > 1:
        raise RuntimeError('control-plane serial version order differs')
    return {'https://10.0.20.' + str(n) + ':2379': contract.ETCD[versions[name]]
            for n, name in zip((11, 12, 13), names)}


def program(source, versions=None, active_endpoints=None, *, host='squirtle'):
    if host not in IDENTITIES:
        raise RuntimeError('unreviewed native etcd observation host')
    expected = expected_versions(versions)
    active = tuple(sorted(expected)) if active_endpoints is None else tuple(active_endpoints)
    if len(active) not in (2, 3) or len(set(active)) != len(active) or not set(active) <= set(expected):
        raise RuntimeError('unreviewed etcd observation endpoints')
    return ('CLIENT=' + repr(CLIENT) + '\nIDENTITY=' + repr(IDENTITIES[host]) + '\nHOST=' + repr(host) +
            '\nARCHIVE_URL=' + repr(ARCHIVE_URL) + '\nARCHIVE_SHA256=' + repr(ARCHIVE_SHA256) +
            '\nBINARY_SHA256=' + repr(BINARY_SHA256) +
            '\nEXPECTED_VERSIONS=' + repr(expected) + '\nACTIVE_ENDPOINTS=' + repr(active) + '\n' + source)


def native_result(source, host, versions=None, active_endpoints=None):
    """Run the identical pinned-client assertions on an original server, never a service action."""
    from contextlib import redirect_stdout
    import io
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(program(source, versions, active_endpoints, host=host), 'native-etcd-client', 'exec'), {})
    return json.loads(output.getvalue())


def native_install(host):
    return native_result(INSTALL, host)


def stopped_endpoints(versions, node, confirm_stopped):
    names = ('charmander', 'squirtle', 'bulbasaur')
    expected_versions(versions)
    if (node not in names or versions[node] != 'v1.33.10+k3s1' or
            any(v not in ('v1.33.10+k3s1', 'v1.33.13+k3s2') for v in versions.values())):
        raise RuntimeError('unreviewed stopped-server transition')
    if not callable(confirm_stopped) or confirm_stopped() is not True:
        raise RuntimeError('exact owned stopped-source proof required')
    return tuple('https://10.0.20.' + str(n) + ':2379'
                 for n, name in zip((11, 12, 13), names) if name != node)


def native_observe(host, versions, *, confirm_stopped=None):
    active = None if confirm_stopped is None else stopped_endpoints(versions, host, confirm_stopped)
    result = native_result(OBSERVE, host, versions, active)
    if confirm_stopped is not None and confirm_stopped() is not True:
        raise RuntimeError('owned stopped-source proof changed during observation')
    return result


def observe(args, versions=None):
    from maintenance_production_node import remote
    return remote(args, program(OBSERVE, versions), '10.0.20.12')


def observe_stopped(args, versions, node, confirm_stopped):
    """The parent must prove its exact owned stop on both sides of this read."""
    from maintenance_production_node import remote
    active = stopped_endpoints(versions, node, confirm_stopped)
    result = remote(args, program(OBSERVE, versions, active), '10.0.20.12')
    if confirm_stopped() is not True:
        raise RuntimeError('owned stopped-source proof changed during observation')
    return result


def recovery(args, release, capture=False, node='squirtle', security_followup=False):
    """A consistent K3s snapshot, token and encryption config remain on Pikachu."""
    import etcd_recovery
    from maintenance_production_node import remote
    assert release in (39, 41, 43, 44)
    assert node in ('squirtle', 'charmander', 'bulbasaur')
    run_id = node + '-fedora' + str(release) + ('-20261028-a' if node == 'bulbasaur' else '-20261026-a')
    if security_followup:
        assert node == 'squirtle' and release == 44, 'unreviewed control-plane security recovery'
        run_id = 'squirtle-fedora44-seccomp-20261028-a'
    point = str(etcd_recovery.ROOT / run_id)
    read = ('from pathlib import Path\nimport json\npoint=Path(' + repr(point) + ')\n' +
            "print(json.dumps(json.loads((point/'verified.json').read_bytes())if(point/'verified.json').exists()else None))")
    manifest = remote(args, read, '10.0.20.14')
    if manifest is None:
        assert capture, 'capture a consistent off-master etcd recovery point first'
        observe(args)
        receipt = etcd_recovery.copy_point(run_id, Path(etcd_recovery.__file__).read_text())
        assert receipt['accepted'] is True
        manifest = {key: receipt[key] for key in ('format', 'metadata', 'files')}
    digest = hashlib.sha256(etcd_recovery.canonical(manifest)).hexdigest()
    source = Path(etcd_recovery.__file__).read_text().rsplit('\nif __name__ == "__main__":', 1)[0]
    verified = remote(args, source + '\nrequire_host("pikachu")\nprint(json.dumps(verify_point(Path(' +
                      repr(point) + '),' + repr(digest) + ')))', '10.0.20.14')
    assert verified == manifest
    return {'point': point, 'manifest_sha256': digest,
            'snapshot': next(v for v in manifest['files'] if v['name'] == 'snapshot'),
            'snapshot_mtime_ns': manifest['metadata']['snapshot_mtime_ns']}
