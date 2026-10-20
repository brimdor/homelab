#!/usr/bin/env python3
"""Connect actual Kured API ownership, native host holds and a durable pending hop."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tarfile

import fedora_target_qualification as fedora


K3S = '86945269160fdd1bbd06283ea5b3bafd6c0ec0d1df3ac68ad3686656632081a5'
AIRGAP = '1a852774a4cf27b24b1c60fc8fdc88e1f31841955dad99dfedd492a4ccfb6c08'
KURED = '76567a71427b074bfc51df6797c8c30ba44c9678ace7cd61a186ddb662ce97b1'
MODULES = ('maintenance_coordination', 'maintenance_actor_hold', 'maintenance_hop_journal')


def archive_identity(path):
    with tarfile.open(path) as source:
        members = source.getmembers()
        if not members or any(not (
                member.isdir() and member.name.removeprefix('./').rstrip('/') in ('', '.', 'blobs', 'blobs/sha256') or
                member.isfile() and re.fullmatch(r'(?:\./)?(?:index\.json|oci-layout|blobs/sha256/[a-f0-9]{64})', member.name))
                for member in members):
            raise RuntimeError('unexpected Kured OCI archive member')
        if len({member.name.removeprefix('./') for member in members}) != len(members):
            raise RuntimeError('duplicate Kured OCI archive member')
        files = {member.name.removeprefix('./'): member for member in members if member.isfile()}
        if 'index.json' not in files or 'oci-layout' not in files or files['index.json'].size > 65536:
            raise RuntimeError('Kured OCI archive metadata missing or excessive')
        for name, member in files.items():
            if name.startswith('blobs/sha256/'):
                checksum = hashlib.sha256()
                with source.extractfile(member) as blob:
                    for block in iter(lambda: blob.read(1048576), b''):
                        checksum.update(block)
                if checksum.hexdigest() != name.rsplit('/', 1)[1]:
                    raise RuntimeError('Kured OCI blob checksum differs')
        if 'blobs/sha256/' + KURED not in files:
            raise RuntimeError('Kured root blob missing')
        value = json.load(source.extractfile(files['index.json']))
        manifests = value.get('manifests', [])
        if len(manifests) != 1 or manifests[0].get('digest') != 'sha256:' + KURED:
            raise RuntimeError('Kured root digest differs')
        if manifests[0].get('annotations', {}).get('org.opencontainers.image.ref.name') != 'ghcr.io/kubereboot/kured:1.21.0':
            raise RuntimeError('Kured import name differs')
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Qualification(fedora.Qualification):
    def __init__(self, args):
        if not re.fullmatch('[0-9a-f]{40}', args.revision):
            raise RuntimeError('missing exact published revision')
        for name, checksum in (('k3s_binary', K3S), ('airgap_images', AIRGAP)):
            fedora.require_media(args.work_dir, getattr(args, name), checksum)
        if (not args.kured_archive.is_absolute() or not args.kured_archive.is_relative_to(args.work_dir) or
                any(p.is_symlink() for p in (args.kured_archive, *args.kured_archive.parents)) or
                not args.kured_archive.is_file()):
            raise RuntimeError('Kured archive outside fixture')
        self.kured_checksum = archive_identity(args.kured_archive)
        fedora.require_media(args.work_dir, args.kured_archive, self.kured_checksum)
        super().__init__(args)

    def guest(self, body, expected=0):
        bundle = {name: Path(__file__).with_name(name + '.py').read_text() for name in MODULES}
        header = 'bundle=' + repr(bundle) + '\nrevision=' + repr(self.args.revision) + '\n' + '''import types,sys,json,pathlib,subprocess,hashlib,time,os,shutil
assert subprocess.check_output(['hostname']).strip()==b'qualification-fedora44'
assert 'VERSION_ID=44' in pathlib.Path('/etc/os-release').read_text()
for name,source in bundle.items():
 module=types.ModuleType(name);module.__file__='/ram/'+name+'.py';sys.modules[name]=module
 exec(compile(source,module.__file__,'exec'),module.__dict__)
global_owner=sys.modules['maintenance_coordination'];actors=sys.modules['maintenance_actor_hold'];hops=sys.modules['maintenance_hop_journal']
def identity():
 return {'machine':pathlib.Path('/etc/machine-id').read_text().strip(),
         'root_uuid':subprocess.check_output(['findmnt','-n','-o','UUID','/']).decode().strip()}
def native(*args):return subprocess.check_output(args,stderr=subprocess.PIPE)
def hashed(value):return hashlib.sha256(hops.canonical(value)).hexdigest()
api=global_owner.Kubectl('/usr/local/bin/qualification-kubectl')
def context():return json.loads((actors.STATE/'combined-context.json').read_bytes())
def controller(value):return global_owner.Ownership(api,value['daemonset_uid'],value['node_uids'])
def connected(value):
 ownership=controller(value);journal=value['global'];token=journal['owner']
 hold=actors.Hold(actors.Systemd(),identity,lambda t:ownership.resume(t)==journal)
 return ownership,hold,hops.Journal(ownership,hold,token)
def ready():
 end=time.monotonic()+900
 while True:
  result=subprocess.run(['/usr/local/bin/qualification-kubectl','get','daemonset','kured','-n','kured','-o','json'],capture_output=True)
  if result.returncode==0:
   ds=json.loads(result.stdout);status=ds.get('status',{})
   if status.get('numberReady')==status.get('desiredNumberScheduled')==1 and status.get('observedGeneration')==ds['metadata']['generation']:return
  elif any(word in result.stderr.lower() for word in (b'unauthorized',b'forbidden',b'x509',b'certificate')):
   raise RuntimeError('synthetic API security refusal; do not bypass')
  if time.monotonic()>end:raise RuntimeError('synthetic Kured did not become ready')
  time.sleep(2)
'''
        return json.loads(self.command(self.ssh + ['sudo python3 -B -'], data=(header + body).encode(), expected=expected))

    def upload(self, path, destination, checksum):
        command = 'sudo sh -c ' + shlex.quote('umask 077;set -eu;test ! -e ' + destination + ';cat > ' + destination)
        with path.open('rb') as source:
            child = subprocess.Popen(self.ssh + [command], stdin=source, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, start_new_session=True)
            try:
                _out, error = child.communicate()
                if child.returncode:
                    raise RuntimeError('owned fixture asset upload failed: ' + str(child.returncode))
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                child.stderr.close()
        raw = self.command(self.ssh + ['sudo sha256sum ' + destination]).decode().split()
        if raw != [checksum, destination]:
            raise RuntimeError('guest transferred asset checksum differs')

    def run(self):
        primitive = super().run()
        before = self.identity()
        self.command(self.ssh + ['sudo mkdir -m 0700 /run/qualification-assets'])
        for path, destination, checksum in (
            (self.args.k3s_binary, '/run/qualification-assets/k3s', K3S),
            (self.args.airgap_images, '/run/qualification-assets/airgap.tar.zst', AIRGAP),
            (self.args.kured_archive, '/run/qualification-assets/kured.tar', self.kured_checksum),
        ):
            self.upload(path, destination, checksum)
        setup = self.guest('''
state=pathlib.Path('/sys/fs/selinux/enforce');enforcement=state.read_text().strip()if state.exists()else None
assert not pathlib.Path('/usr/local/bin/k3s').exists() and not pathlib.Path('/var/lib/rancher/k3s').exists()
assets=pathlib.Path('/run/qualification-assets')
shutil.move(str(assets/'k3s'),'/usr/local/bin/k3s');pathlib.Path('/usr/local/bin/k3s').chmod(0o755)
assert b'v1.33.6+k3s1' in native('/usr/local/bin/k3s','--version')
images=pathlib.Path('/var/lib/rancher/k3s/agent/images');images.mkdir(parents=True)
shutil.move(str(assets/'airgap.tar.zst'),str(images/'airgap.tar.zst'));shutil.move(str(assets/'kured.tar'),str(images/'kured.tar'))
wrapper=pathlib.Path('/usr/local/bin/qualification-kubectl');assert not wrapper.exists()
wrapper.write_text('#!/bin/sh\\nset -eu\\nexport KUBECONFIG=/etc/rancher/k3s/k3s.yaml\\nexec /usr/local/bin/k3s kubectl "$@"\\n');wrapper.chmod(0o755)
unit=pathlib.Path('/etc/systemd/system/qualification-k3s.service');assert not unit.exists()
unit.write_text('[Unit]\\nAfter=network-online.target\\nWants=network-online.target\\n[Service]\\nType=notify\\nKillMode=process\\nDelegate=yes\\nLimitNOFILE=1048576\\nTasksMax=infinity\\nTimeoutStartSec=0\\nExecStart=/usr/local/bin/k3s server --cluster-init --write-kubeconfig-mode=600 --disable=traefik,servicelb,local-storage,metrics-server,coredns --disable-network-policy --prefer-bundled-bin\\n[Install]\\nWantedBy=multi-user.target\\n')
native('systemctl','daemon-reload');native('systemctl','enable','--now','qualification-k3s.service')
assert enforcement==(state.read_text().strip()if state.exists()else None)
# No host channel or sentinel exists in this restricted, unprivileged Kured fixture.
for name in actors.SERVICES[:-1]:
 p=actors.UNITS/name;assert not p.exists()
 p.write_text('[Unit]\\nDescription=Synthetic DNF4 payload\\n[Service]\\nType=oneshot\\nExecStart=/usr/bin/touch /var/lib/homelab-maintenance/combined-executed\\n')
native('systemctl','daemon-reload')
end=time.monotonic()+900
while True:
 node=api.call('get','nodes','-o','json')['items']
 if len(node)==1 and any(c['type']=='Ready'and c['status']=='True'for c in node[0].get('status',{}).get('conditions',[])):break
 if time.monotonic()>end:raise RuntimeError('synthetic node did not become Ready')
 time.sleep(2)
assert node[0]['metadata']['name']=='qualification-fedora44'
name=node[0]['metadata']['name']
objects=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':'kured','labels':{'pod-security.kubernetes.io/enforce':'restricted'}}},
 {'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'kured','namespace':'kured'}},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole','metadata':{'name':'qualification-kured'},'rules':[{'apiGroups':[''],'resources':['nodes'],'verbs':['get','list','watch']}]},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRoleBinding','metadata':{'name':'qualification-kured'},'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'qualification-kured'},'subjects':[{'kind':'ServiceAccount','name':'kured','namespace':'kured'}]},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':'kured','namespace':'kured'},'rules':[{'apiGroups':['apps'],'resources':['daemonsets'],'resourceNames':['kured'],'verbs':['get','update','patch']}]},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':'kured','namespace':'kured'},'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'kured'},'subjects':[{'kind':'ServiceAccount','name':'kured','namespace':'kured'}]},
 {'apiVersion':'apps/v1','kind':'DaemonSet','metadata':{'name':'kured','namespace':'kured'},'spec':{'selector':{'matchLabels':{'app':'kured'}},'template':{'metadata':{'labels':{'app':'kured'}},'spec':{'serviceAccountName':'kured','securityContext':{'runAsNonRoot':True,'runAsUser':65532,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'kured','image':global_owner.IMAGE,'imagePullPolicy':'Never','command':['/usr/bin/kured'],'args':global_owner.ARGS,'env':global_owner.ENV,'ports':[{'containerPort':8080}],'readinessProbe':{'httpGet':{'path':'/metrics','port':8080}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}}}]}}}}]
p=subprocess.run(['/usr/local/bin/qualification-kubectl','apply','-f','-'],input=json.dumps({'apiVersion':'v1','kind':'List','items':objects}).encode(),capture_output=True);assert p.returncode==0
ready()
ds,pods,nodes=api.snapshot();assert len(nodes)==1
value={'daemonset_uid':ds['metadata']['uid'],'node_uids':{n['metadata']['name']:n['metadata']['uid']for n in nodes}}
ownership=controller(value);journal=ownership.acquire(name,39,41,revision);token=journal['owner'];value['global']=journal
hold=actors.Hold(actors.Systemd(),identity,lambda t:ownership.resume(t)==journal)
held=hold.acquire(token,identity(),revision);hop=hops.Journal(ownership,hold,token);hop.initialize()
node=api.call('get','node',name,'-o','json');assert not node['spec'].get('unschedulable',False)
inputs=hashed({'node':name,'uid':node['metadata']['uid'],'unschedulable':True});evidence=hashed({'identity':identity(),'node':node,'owner':journal})
intent=hop.begin('cordon',inputs,evidence,lambda step,h:step=='cordon'and h==evidence and not api.call('get','node',name,'-o','json')['spec'].get('unschedulable',False))
reviewed=node;node=api.call('get','node',name,'-o','json');assert node['metadata']['uid']==reviewed['metadata']['uid'] and node['spec']==reviewed['spec']
operations=[{'op':'test','path':'/metadata/uid','value':node['metadata']['uid']},{'op':'test','path':'/metadata/resourceVersion','value':node['metadata']['resourceVersion']},{'op':'add','path':'/spec/unschedulable','value':True}]
cordoned=api.call('patch','node',name,'--type=json','--patch',global_owner.encoded(operations),'-o','json')
receipt=hashed({'node_uid':cordoned['metadata']['uid'],'spec':cordoned['spec']})
hop.accept(intent['pending']['sha256'],receipt,lambda step,h:step=='cordon'and h==receipt and api.call('get','node',name,'-o','json')['spec']['unschedulable']is True)
pending=hop.begin('drain',hashed({'node_uid':node['metadata']['uid'],'operation':'drain-not-executed'}),receipt,lambda step,h:step=='drain'and h==receipt and api.call('get','node',name,'-o','json')['spec']['unschedulable']is True)
value.update(pending=pending,host_marker=hold.marker.read_text(),runtime_annotations={k:api.snapshot()[0]['metadata']['annotations'][k]for k in(global_owner.LOCK,global_owner.JOURNAL)},enforcement=enforcement)
actors.exclusive_file(actors.STATE/'combined-context.json',json.dumps(value,sort_keys=True).encode(),0o600)
print(json.dumps({'actual_global_owner_and_native_hold':True,'cordon_intent_action_and_acceptance':True,'pending_drain_not_executed':True,'records':pending['records'],'head_sha256':pending['head_sha256'],'selinux_enforcement':enforcement}),flush=True)
os._exit(73)
''', expected=73)
        reboot = self.root / 'combined-reboot.yml'
        reboot.write_text('- hosts: fixture\n  gather_facts: false\n  become: true\n  tasks:\n'
                          '    - ansible.builtin.reboot:\n        reboot_timeout: 1200\n'
                          '        connect_timeout: 10\n        post_reboot_delay: 0\n')
        env = {**os.environ, 'ANSIBLE_CONFIG': str(Path('metal/maintenance/ansible.cfg').resolve()),
               'ANSIBLE_COLLECTIONS_PATH': str(self.args.collection_dir), 'ANSIBLE_HOST_KEY_CHECKING': 'True',
               'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp'),
               'ANSIBLE_SSH_ARGS': '-o ControlMaster=no -o ControlPersist=no'}
        self.command([str(self.args.ansible_playbook), '-i', str(self.root / 'inventory.yml'), str(reboot),
                      '--limit', 'fixture'], env=env)
        after = self.identity()
        if before['boot'] == after['boot'] or any(before[k] != after[k] for k in ('machine', 'root_uuid', 'architecture', 'kernel')):
            raise RuntimeError('combined fixture reboot/identity differs')
        resumed = self.guest('''
ready();value=context();ownership,hold,hop=connected(value);token=value['global']['owner']
assert hold.marker.read_text()==value['host_marker'];hold.resume(token)
assert hop.inspect()==value['pending']
for step in('drain','prepare_source'):
 try:hop.begin(step,'b'*64,'c'*64,lambda *_:True)
 except RuntimeError as error:assert 'pending or out-of-order' in str(error)
 else:raise RuntimeError('pending intent replay accepted')
try:hop.accept(value['pending']['pending']['sha256'],'d'*64,lambda *_:False)
except RuntimeError as error:assert 'observed hop result refused' in str(error)
else:raise RuntimeError('refused pending result accepted')
assert hop.inspect()==value['pending'] and hold.marker.read_text()==value['host_marker']
for name in actors.SERVICES:native('systemctl','start',name)
assert not(actors.STATE/'combined-executed').exists();hold.systemd.idle(hold.marker)
ds,pods,nodes=api.snapshot();assert len(nodes)==1 and nodes[0]['spec']['unschedulable']is True
assert{k:ds['metadata']['annotations'][k]for k in(global_owner.LOCK,global_owner.JOURNAL)}==value['runtime_annotations']
state=pathlib.Path('/sys/fs/selinux/enforce');assert value['enforcement']==(state.read_text().strip()if state.exists()else None)
print(json.dumps({'fresh_real_owner_host_hold_journal_resume':True,'pending_intent_exact':True,'replay_and_refused_completion_rejected':True,'all_native_service_starts_excluded':True,'no_automatic_release_or_uncordon':True,'same_node_and_daemonset_uids':True,'selinux_state_unchanged':True,'records':hop.inspect()['records']}))
''')
        return {'combined_qualification': True, 'primitive': primitive, 'before': before, 'after': after,
                'setup': setup, 'resumed': resumed, 'real_api_systemd_and_hop_journal': True,
                'dnf4_service_payloads_synthetic': True, 'production_changes': False,
                'os_release_drain_availability_gpu_csi_and_safe_release_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'k3s-binary', 'airgap-images', 'kured-archive'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned combined qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'combined-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
