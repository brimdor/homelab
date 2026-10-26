"""Squirtle's exact etcd observation client and off-node recovery binding."""

import hashlib
import json
from pathlib import Path


CLIENT = '/var/lib/homelab-recovery/maintenance-103/tools/etcd-v3.5.21/etcdctl'
ARCHIVE_URL = 'https://github.com/etcd-io/etcd/releases/download/v3.5.21/etcd-v3.5.21-linux-amd64.tar.gz'
ARCHIVE_SHA256 = 'adddda4b06718e68671ffabff2f8cee48488ba61ad82900e639d108f2148501c'
IDENTITY = '90c7f1d7caea486d9dc9bdbb4ec5ae21'

INSTALL = r'''
import hashlib,io,json,os,pathlib,socket,stat,subprocess,tarfile,urllib.request
assert os.geteuid()==0 and socket.gethostname()=='squirtle'
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
import json,os,pathlib,socket,subprocess,urllib.request
assert os.geteuid()==0 and socket.gethostname()=='squirtle'
assert pathlib.Path('/etc/machine-id').read_text().strip()==IDENTITY
tls='/var/lib/rancher/k3s/server/tls/etcd/'
argv=[CLIENT,'--endpoints=https://10.0.20.11:2379,https://10.0.20.12:2379,https://10.0.20.13:2379',
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
assert len(status)==len(health)==3 and {v['Endpoint']for v in status}==expected
assert all(v['health']is True for v in health)and not alarms.get('alarms')
assert len({v['Status']['header']['cluster_id']for v in status})==1
assert len({v['Status']['leader']for v in status})==1 and status[0]['Status']['leader']in{m['ID']for m in members['members']}
assert {v['Status']['header']['member_id']for v in status}=={m['ID']for m in members['members']}
assert all(v['Status']['version']=='3.5.21'and not v['Status'].get('errors')for v in status)
print(json.dumps({'members':members,'status':status,'health':health,'alarms':alarms}))
'''


def program(source):
    return ('CLIENT=' + repr(CLIENT) + '\nIDENTITY=' + repr(IDENTITY) +
            '\nARCHIVE_URL=' + repr(ARCHIVE_URL) + '\nARCHIVE_SHA256=' + repr(ARCHIVE_SHA256) + '\n' + source)


def observe(args):
    from maintenance_production_node import remote
    return remote(args, program(OBSERVE), '10.0.20.12')


def recovery(args, release, capture=False):
    """A consistent K3s snapshot, token and encryption config remain on Pikachu."""
    import etcd_recovery
    from maintenance_production_node import remote
    assert release in (39, 41, 43, 44)
    run_id = 'squirtle-fedora' + str(release) + '-20261026-a'
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
    source = Path(etcd_recovery.__file__).read_text().split('if __name__ == "__main__":')[0]
    verified = remote(args, source + '\nrequire_host("pikachu")\nprint(json.dumps(verify_point(Path(' +
                      repr(point) + '),' + repr(digest) + ')))', '10.0.20.14')
    assert verified == manifest
    return {'point': point, 'manifest_sha256': digest,
            'snapshot': next(v for v in manifest['files'] if v['name'] == 'snapshot'),
            'snapshot_mtime_ns': manifest['metadata']['snapshot_mtime_ns']}
