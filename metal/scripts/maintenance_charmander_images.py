"""Retain Charmander's exact running images using verified native OCI archives."""

from maintenance_coordination import require
from maintenance_nibble_artifact import RECEIVE_PROGRAM, REGISTER_PROGRAM, SOURCE_PROGRAM, stream
from maintenance_production_node import remote


PROFILES = {
    'strata-backup': ('10.0.20.11:32309/strata',
                      '71f04326edf6e1defeabf2dc211abcf6bc6c7e14b0838c9e0704ab12253b08f0',
                      '2a3b8160a9028d97db97420f62e237b50eed90206fc4790ffa42c3944e6e9b19', 13),
    'postgres': ('docker.io/brimdor/postgres',
                 'cf396ec97def9e03769e1736e7f1224b989bb664ead28e49dc28815e5c25988e',
                 '0096220d344ab0607551bb0b8259859179205f41f69dfdbbbc9db409fba0fad4', 17),
    'jovo-backend': ('10.0.20.11:32309/broville/jovo_backend',
                     '318caf0dff23a37af6be2bc1caa396899d73cee1ea9b5e18a2d63418cd3cf031',
                     '96e57675e8bcc55e4dbae18ea37acde19cc214c75c9d3998c62082884d90be76', 14),
    'jovo-frontend': ('10.0.20.11:32309/broville/jovo_frontend',
                      '5d55e87f270624c5ec87595a731ff607d3f07589fec1fe4ebc5fa67afef69457',
                      '3aff8e678a73207f1b59efe14850c42f3cbf549b3044f12f534fbc114180d959', 11),
    'strata': ('10.0.20.11:32309/strata',
               '52991cff84cf9c743d376b7509b9d40151bc3f6e89dafe269169bc62e1001774',
               '9244110b098115a0d5d353f26344a46654b5a8623e1dcdfb246ff9a0e413279e', 13),
}
TARGETS = {
    'totodile': ('10.0.20.17', '0f1915a59a124d999d8d68b53f406af1', '489f1af8-5d55-4356-8d48-418fcb2069a2'),
    'pikachu': ('10.0.20.14', '0a7daf8b33244d9d85f46223c3582da9', '76e53a95-725a-4430-9d7b-a8db413f3997'),
    'squirtle': ('10.0.20.12', '90c7f1d7caea486d9dc9bdbb4ec5ae21', 'eea5afa0-dbb6-43f5-abe6-f1be801fb03a'),
    'growlithe': ('10.0.20.18', 'a26cbcc990c044dea41fbf4f957f453d', '710e2dca-691e-4123-a867-4994b9c6e612'),
}


def bindings(key, target):
    require(key in PROFILES and target in TARGETS, 'unreviewed retained image or receiver')
    repository, digest, config, count = PROFILES[key]
    _, machine, root = TARGETS[target]
    image = repository + '@sha256:' + digest
    values = {'IMAGE': image, 'ALIAS': image, 'DIGEST': 'sha256:' + digest,
              'CONFIG': 'sha256:' + config, 'BLOB_COUNT': count,
              'SOURCE_HOST': 'charmander', 'SOURCE_MACHINE': '58d682ccab5a4269acedc3cdf53e46dc',
              'SOURCE_ROOT': '4a64a6d6-e982-4694-aa03-ad5f317b3ab2',
              'TARGET_HOST': target, 'TARGET_MACHINE': machine, 'TARGET_ROOT': root,
              'RECOVERY': '/var/lib/homelab-recovery/maintenance-103/charmander-image-' + key + '-' + digest[:8],
              'ARTIFACT': 'maintenance103-charmander-' + key + '-' + digest[:8] + '.tar'}
    return ''.join(k + '=' + repr(v) + '\n' for k, v in values.items())


def preserve(args, key, target='totodile'):
    values = bindings(key, target)
    return stream(args, '10.0.20.11', values + SOURCE_PROGRAM,
                  values + RECEIVE_PROGRAM, TARGETS[target][0])


def register(args, key, target='totodile'):
    return remote(args, bindings(key, target) + REGISTER_PROGRAM, TARGETS[target][0])


LAYER = 'sha256:76cbedd71a05bf6e8513645fbf8bf436d911348bb3f027280fb28a7476ed12d0'
LAYER_SIZE = 3981862
LAYER_SOURCE = r'''
import os,pathlib,socket,subprocess
assert os.geteuid()==0 and socket.gethostname()=='totodile'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='0f1915a59a124d999d8d68b53f406af1'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='489f1af8-5d55-4356-8d48-418fcb2069a2'
os.execv('/usr/local/bin/k3s',['k3s','ctr','-n','k8s.io','content','get',LAYER])
'''
LAYER_RECEIVER = r'''
import hashlib,json,os,pathlib,socket,subprocess,sys
assert os.geteuid()==0 and socket.gethostname()=='charmander'
assert pathlib.Path('/etc/machine-id').read_text().strip()=='58d682ccab5a4269acedc3cdf53e46dc'
assert subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip()=='4a64a6d6-e982-4694-aa03-ad5f317b3ab2'
root=pathlib.Path('/var/lib/homelab-recovery/maintenance-103/charmander-jovo-frontend-layer-'+LAYER[7:15])
assert not any(p.is_symlink()for p in(root,*root.parents))
assert subprocess.check_output(['findmnt','-n','-o','UUID','-T',str(root.parent)],text=True).strip()=='4a64a6d6-e982-4694-aa03-ad5f317b3ab2'
assert root.parent.is_dir()and root.parent.stat().st_uid==0 and not root.parent.stat().st_mode&0o022
assert not root.exists(),'existing layer recovery intent; observe only'
root.mkdir(mode=0o700);path=root/'blob';h=hashlib.sha256();size=0
with path.open('xb')as target:
 os.fchmod(target.fileno(),0o600)
 while True:
  chunk=sys.stdin.buffer.read(1024*1024)
  if not chunk:break
  target.write(chunk);h.update(chunk);size+=len(chunk)
 target.flush();os.fsync(target.fileno())
assert size==LAYER_SIZE and 'sha256:'+h.hexdigest()==LAYER
prefix=['/usr/local/bin/k3s','ctr','-n','k8s.io','content']
with path.open('rb')as source:
 subprocess.run(prefix+['ingest','--expected-size',str(LAYER_SIZE),'--expected-digest',LAYER,'maintenance103-jovo-frontend-original-layer'],stdin=source,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
process=subprocess.Popen(prefix+['get',LAYER],stdout=subprocess.PIPE,stderr=subprocess.PIPE);check=hashlib.sha256();observed=0
for chunk in iter(lambda:process.stdout.read(1024*1024),b''):check.update(chunk);observed+=len(chunk)
process.wait();assert process.returncode==0 and observed==LAYER_SIZE and 'sha256:'+check.hexdigest()==LAYER
record={'digest':LAYER,'bytes':size,'native_readback_verified':True,'source':'totodile','target':'charmander'}
with(root/'verified.json').open('x')as target:
 os.fchmod(target.fileno(),0o600);json.dump(record,target);target.flush();os.fsync(target.fileno())
for parent in(root,root.parent):
 fd=os.open(parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps(record))
'''


def recover_frontend_layer(args):
    values = 'LAYER=' + repr(LAYER) + '\nLAYER_SIZE=' + repr(LAYER_SIZE) + '\n'
    return stream(args, '10.0.20.17', values + LAYER_SOURCE,
                  values + LAYER_RECEIVER, '10.0.20.11')
