"""Prepare native K3s only on the fixed three-endpoint synthetic Fedora fleet."""

import os
from pathlib import Path
import signal
import subprocess

import maintenance_actor_hold as actors
from maintenance_combined_qualification import (AIRGAP, K3S, SELINUX_KEY,
                                                Qualification as Combined, archive_identity)
from maintenance_fedora_endpoint import endpoint
from fedora_target_qualification import require_media
from fedora_nfs_csi_qualification import archive_identity as workload_archive_identity


ASSETS = '/var/tmp/qualification-native-assets'
SERVER = '192.0.2.12'
# K3s 1.33.6's installer selects the vendor EL8 policy for Fedora releases above 36.
SELINUX_RPM = 'a1e24b0d82b1a6806cd420e2c0398a1796b055efe368fa4aebc8bb173850934f'
WORKLOAD = {'image': 'docker.io/library/python:3.13-alpine',
            'digest': 'sha256:ba27df8b6499cc3756cff167690f3fcb5321faa1703b3a914df5f4fdadb32f05'}


def configuration(index):
    value = endpoint(index, 1)
    config = {'node-name': value['hostname'], 'node-ip': value['address'],
              'flannel-iface': 'cluster0', 'prefer-bundled-bin': True,
              'selinux': True}
    if index == 1:
        config.update({'cluster-init': True, 'write-kubeconfig-mode': '600',
                       'tls-san': [SERVER], 'disable-network-policy': True,
                       'disable': ['traefik', 'servicelb', 'local-storage', 'metrics-server', 'coredns']})
    else:
        config.update({'server': 'https://' + SERVER + ':6443',
                       'token-file': '/etc/rancher/k3s/qualification-token'})
    return config


def transfer_private(source, target, kind):
    """Pipe fixture credentials between pinned SSH sessions, never through command logs."""
    actors.require(kind in ('join-token', 'admin-config') and source is not target,
                   'foreign native credential transfer')
    actors.require(source.endpoint == endpoint(1, source.endpoint['port']) and
                   any(target.endpoint == endpoint(index, target.endpoint['port']) for index in (0, 2)),
                   'private transfer requires exact fixture server and agent')
    source_path = ('/var/lib/rancher/k3s/server/node-token' if kind == 'join-token'
                   else '/etc/rancher/k3s/k3s.yaml')
    destination = ('/etc/rancher/k3s/qualification-token' if kind == 'join-token'
                   else '/etc/rancher/k3s/qualification-admin.yaml')
    # Only fixed fixture paths are passed to the shell; credential bytes stay in the pipe.
    writer = ('sudo python3 -c "import os,pathlib,sys; p=pathlib.Path(\'' + destination +
              '\'); raw=sys.stdin.buffer.read(65537); assert 0<len(raw)<=65536; '
              + ("assert raw.count(b'https://127.0.0.1:6443')==1; raw=raw.replace(b'https://127.0.0.1:6443',b'https://" + SERVER + ":6443'); "
                 if kind == 'admin-config' else "assert raw.count(b'::server:')==1; ") +
              'fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); '
              'f=os.fdopen(fd,\'wb\'); f.write(raw); f.flush(); os.fsync(f.fileno()); f.close()"')
    children = []
    try:
        reader = subprocess.Popen(source.ssh + ['sudo cat ' + source_path], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        children.append(reader)
        sink = subprocess.Popen(target.ssh + [writer], stdin=reader.stdout, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        children.append(sink)
        reader.stdout.close()
        sink_exit, reader_exit = sink.wait(), reader.wait()
        actors.require(sink_exit == 0 and reader_exit == 0, 'native private transfer failed; never replay')
    finally:
        for child in reversed(children):
            if child.poll() is None:
                try:os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:pass
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:pass
                    child.wait()
        if children and children[0].stdout is not None:children[0].stdout.close()


class Cluster:
    def __init__(self, nodes, args):
        actors.require(len(nodes) == 3 and all(node.endpoint == endpoint(index, node.endpoint['port'])
                       for index, node in enumerate(nodes)), 'exact ordered native fleet required')
        self.nodes, self.args = nodes, args
        self.assets = {'k3s': K3S, 'airgap.tar.zst': AIRGAP,
                       'policy.rpm': SELINUX_RPM, 'rancher-public.key': SELINUX_KEY}
        directory = args.assets_dir
        actors.safe(directory)
        actors.require(directory.is_relative_to(args.work_dir) and directory.is_dir(),
                       'native assets outside owned fixture')
        for name, digest in self.assets.items():require_media(args.work_dir, directory / name, digest)
        self.assets['kured.tar'] = archive_identity(directory / 'kured.tar')
        require_media(args.work_dir, directory / 'kured.tar', self.assets['kured.tar'])
        self.assets['workload.tar'] = workload_archive_identity(directory / 'workload.tar', WORKLOAD)
        require_media(args.work_dir, directory / 'workload.tar', self.assets['workload.tar'])
        self.prepared, self.started = set(), set()

    def prepare(self, index):
        configuration(index)
        actors.require(index not in self.prepared, 'native K3s preparation already started; never replay')
        self.prepared.add(index)
        node = self.nodes[index]
        node.repositories(39)
        configured = node.configure()
        node.guest("assets_path=" + repr(ASSETS) + "\n" + """
assets=pathlib.Path(assets_path);assert not assets.exists();assets.mkdir(mode=0o700)
print(json.dumps({'private_asset_directory_created':True}))
""")
        for name, digest in self.assets.items():
            Combined.upload(node, self.args.assets_dir / name, ASSETS + '/' + name, digest)
        result = node.guest("assets_path=" + repr(ASSETS) + "\n" + """
assets=pathlib.Path(assets_path)
native('rpmkeys','--import',str(assets/'rancher-public.key'))
signature=native('rpmkeys','--checksig','--verbose',str(assets/'policy.rpm'))
assert 'e257814a'in signature.lower() and 'NOKEY'not in signature and 'NOT OK'not in signature and 'BAD'not in signature
assert native('rpm','-qp','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',str(assets/'policy.rpm'))=='1.6-1.el8.noarch'
native('/usr/bin/dnf','-y','install','container-selinux',str(assets/'policy.rpm'))
assert not native('rpm','-V','container-selinux','k3s-selinux')
assert any(line.split()[:2]==['200','k3s']for line in native('semodule','--list=full').splitlines())
binary=pathlib.Path('/usr/local/bin/k3s');assert not binary.exists()
(assets/'k3s').rename(binary);binary.chmod(0o755)
native('chcon','-u','system_u','-r','object_r','-t','container_runtime_exec_t',str(binary))
assert os.getxattr(binary,'security.selinux').decode().split(':')[:3]==['system_u','object_r','container_runtime_exec_t']
assert 'v1.33.6+k3s1'in native(str(binary),'--version')
images=pathlib.Path('/var/lib/rancher/k3s/agent/images');assert not images.exists();images.mkdir(parents=True)
for name in('airgap.tar.zst','kured.tar','workload.tar'):(assets/name).rename(images/name)
config=pathlib.Path('/etc/rancher/k3s');config.mkdir(parents=True,mode=0o700,exist_ok=True)
assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
print(json.dumps({'signed_vendor_policy':'1.6-1.el8.noarch','enforcing':True,
 'k3s':'v1.33.6+k3s1','native_rpm_verification_clean':True,'owned_images_preloaded':True}))
""")
        return {'configured': configured, 'installed': result}

    def start(self, index):
        actors.require(index in self.prepared and index not in self.started,
                       'native K3s endpoint not prepared or dispatch already started; never replay')
        self.started.add(index)
        config = configuration(index)
        return self.nodes[index].guest('config=' + repr(config) + '\nrole=' + repr('server' if index == 1 else 'agent') + '\n' + """
root=pathlib.Path('/etc/rancher/k3s');path=root/'config.yaml';assert not path.exists()
# JSON is valid YAML and avoids an extra guest dependency.
path.write_text(json.dumps(config));path.chmod(0o600)
if role=='agent':assert (root/'qualification-token').is_file()
assert json.loads(native('ip','-j','route','show','default'))==[]
route=pathlib.Path('/etc/systemd/system/qualification-airgap-route.service');assert not route.exists()
route.write_text('[Unit]\\nBefore=qualification-k3s.service\\n[Service]\\nType=oneshot\\nRemainAfterExit=yes\\n'
 'ExecStart=/usr/sbin/ip link add dummy0 type dummy\\nExecStart=/usr/sbin/ip link set dummy0 up\\n'
 'ExecStart=/usr/sbin/ip addr add 203.0.113.254/31 dev dummy0\\n'
 'ExecStart=/usr/sbin/ip route add default via 203.0.113.255 dev dummy0 metric 1000\\n')
unit=pathlib.Path('/etc/systemd/system/qualification-k3s.service');assert not unit.exists()
unit.write_text('[Unit]\\nAfter=network-online.target qualification-airgap-route.service\\nWants=network-online.target\\n'
 'Requires=qualification-airgap-route.service\\n[Service]\\nType=notify\\nKillMode=process\\nDelegate=yes\\n'
 'LimitNOFILE=1048576\\nTasksMax=infinity\\nTimeoutStartSec=0\\nExecStart=/usr/local/bin/k3s '+role+'\\n'
 '[Install]\\nWantedBy=multi-user.target\\n')
native('systemctl','daemon-reload');native('systemctl','enable','--now','qualification-k3s.service')
routes=json.loads(native('ip','-j','route','show','default'))
assert len(routes)==1 and routes[0]['dev']=='dummy0'and routes[0]['gateway']=='203.0.113.255'
pid=int(native('systemctl','show','qualification-k3s.service','--property=MainPID','--value'))
assert pid>1 and pathlib.Path('/proc/'+str(pid)+'/attr/current').read_text().split(':')[2]=='container_runtime_t'
assert pathlib.Path('/sys/fs/selinux/enforce').read_text().strip()=='1'
print(json.dumps({'native_service_started':True,'role':role,'pid':pid,'enforcing':True,'inert_dummy_default_only':True}))
""")

    def import_images(self, index):
        actors.require(index in self.started, 'native container runtime not started')
        return self.nodes[index].guest("workload=" + repr(WORKLOAD) + "\n" + """
images=pathlib.Path('/var/lib/rancher/k3s/agent/images')
for name,base,digest in [('kured.tar','ghcr.io/kubereboot/kured',
 'sha256:76567a71427b074bfc51df6797c8c30ba44c9678ace7cd61a186ddb662ce97b1'),
 ('workload.tar','docker.io/library/python',workload['digest'])]:
 native('/usr/local/bin/k3s','ctr','images','import','--local','--digests','--all-platforms','--no-unpack',
  '--base-name',base,str(images/name))
 ref=base+'@'+digest
 assert ref in json.loads(native('/usr/local/bin/k3s','crictl','inspecti',ref))['status']['repoDigests']
print(json.dumps({'verified_digest_imports':True,'enforcing':True}))
""")

    def wrapper(self, index):
        actors.require(index in (0, 1) and index in self.started, 'foreign native API endpoint')
        return self.nodes[index].guest('config_path=' + repr('/etc/rancher/k3s/k3s.yaml' if index == 1
                                                           else '/etc/rancher/k3s/qualification-admin.yaml') + '\n' + """
assert pathlib.Path(config_path).is_file()
wrapper=pathlib.Path('/usr/local/bin/qualification-kubectl');assert not wrapper.exists()
wrapper.write_text('#!/bin/sh\\nset -eu\\nexport KUBECONFIG='+config_path+
 '\\nexec /usr/local/bin/k3s kubectl --request-timeout=30s "$@"\\n');wrapper.chmod(0o755)
print(json.dumps({'fixed_private_API_wrapper_created':True}))
""")
