#!/usr/bin/env python3
"""Qualify Cilium's native Fedora datapath without production or NAS access."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import signal

import yaml

import fedora_target_qualification as fedora
from fedora_kernel_qualification import Qualification as Kernel, VERSION
from fedora_nfs_csi_qualification import archive_identity, POLICY
from fedora_nvidia_package_qualification import verify_repository_disk, verify_signature_output
from maintenance_combined_qualification import K3S, AIRGAP, SELINUX_KEY


CHART = '505abff8385811df1a949776fc42e9f10697989a332acc86d6e8933efcb855ed'
ASSETS = '/var/tmp/qualification-cilium-assets'
IMAGE_FILE = Path(__file__).resolve().parents[1] / 'maintenance/cilium-native-images.json'
VALUES = {'operator': {'replicas': 1}, 'kubeProxyReplacement': True,
          'k8sServiceHost': '127.0.0.1', 'k8sServicePort': 6443,
          'ipam': {'operator': {'clusterPoolIPv4PodCIDRList': ['10.42.0.0/16']}},
          'hubble': {'relay': {'enabled': True}, 'tls': {'auto': {'method': 'helm'}}},
          'l2announcements': {'enabled': True}}


def image_records():
    records = json.loads(IMAGE_FILE.read_bytes())
    if (len(records) != 5 or len({r['image'] for r in records}) != 5 or
            sum(r['image'].startswith('quay.io/cilium/') for r in records) != 4 or
            records[-1]['image'] != 'docker.io/library/python:3.13-alpine' or
            any(set(r) != {'image', 'index_digest', 'digest'} or
                not all(re.fullmatch('sha256:[0-9a-f]{64}', r[k]) for k in ('digest', 'index_digest'))
                for r in records)):
        raise RuntimeError('native Cilium image inventory differs')
    return records


def reviewed_chart(objects, records):
    pins = {r['image'] + '@' + r['index_digest']: r['image'].rsplit(':', 1)[0] + '@' + r['digest']
            for r in records[:-1]}
    workloads = [o for o in objects if o['kind'] in ('DaemonSet', 'Deployment')]
    if (len(objects) != 30 or {(o['kind'], o['metadata']['name']) for o in workloads} != {
            ('DaemonSet', 'cilium'), ('DaemonSet', 'cilium-envoy'),
            ('Deployment', 'cilium-operator'), ('Deployment', 'hubble-relay')} or
            any(o['kind'] not in ('Namespace', 'ServiceAccount', 'Secret', 'ConfigMap', 'ClusterRole',
                                 'ClusterRoleBinding', 'Role', 'RoleBinding', 'Service',
                                 'DaemonSet', 'Deployment') for o in objects) or
            any(o['kind'] == 'Namespace' and o['metadata']['name'] != 'cilium-secrets' for o in objects)):
        raise RuntimeError('reviewed Cilium chart resource contract differs')
    found = set()
    for obj in workloads:
        spec = obj['spec']['template']['spec']
        for container in spec.get('containers', []) + spec.get('initContainers', []):
            image = container['image']
            if image not in pins:
                raise RuntimeError('unreviewed native Cilium image')
            found.add(image)
            container['image'] = pins[image]
            container['imagePullPolicy'] = 'Never'
    if found != set(pins):
        raise RuntimeError('reviewed Cilium images missing')
    return objects


class Qualification(Kernel):
    def __init__(self, args):
        fedora.require_root(args.work_dir)
        if (not args.assets_dir.is_absolute() or not args.assets_dir.is_relative_to(args.work_dir) or
                any(p.is_symlink() for p in (args.assets_dir, *args.assets_dir.parents))):
            raise RuntimeError('native Cilium assets outside the owned fixture')
        self.records = image_records()
        self.assets = {'k3s': K3S, 'airgap.tar.zst': AIRGAP, 'policy.rpm': POLICY,
                       'rancher-public.key': SELINUX_KEY, 'cilium-chart.tgz': CHART}
        for number, record in enumerate(self.records):
            path = args.assets_dir / ('image-' + str(number) + '.tar')
            if not path.is_file() or path.is_symlink():
                raise RuntimeError('native Cilium OCI asset is not a regular owned file')
            self.assets[path.name] = archive_identity(path, record)
        for name, digest in self.assets.items():
            fedora.require_media(args.work_dir, args.assets_dir / name, digest)
        super().__init__(args)

    def runtime(self, phase):
        result = json.loads(self.command(self.ssh + [
            'sudo python3 -B ' + ASSETS + '/cilium_native_runtime.py ' + phase]))
        (self.root / ('cilium-' + phase + '.json')).write_text(json.dumps(result, indent=2))
        if result.get('accepted') is not True:
            raise RuntimeError('native Cilium runtime refused; inspect retained result')
        return result

    def run(self):
        kernel = super().run()
        (self.root / 'kernel-result.json').write_text(json.dumps(kernel, indent=2))
        values = self.root / 'cilium-values.yaml'
        values.write_text(yaml.safe_dump(VALUES))
        rendered = self.command([self.args.helm, 'template', 'cilium',
                                 str(self.args.assets_dir / 'cilium-chart.tgz'), '--namespace', 'kube-system',
                                 '--kube-version', '1.33.6', '--include-crds', '-f', str(values)])
        objects = reviewed_chart([o for o in yaml.safe_load_all(rendered) if o], self.records)
        storage = self.guest('import os\n' + inspect.getsource(verify_repository_disk) +
                             '\nassets_path=' + repr(ASSETS) + '\n' + '''
assets=pathlib.Path(assets_path)
assert not any(p.is_symlink() for p in (assets,*assets.parents))
assets.mkdir(mode=0o700)
assert assets.stat().st_uid==0 and assets.stat().st_mode&0o777==0o700
mount=json.loads(native('findmnt','--json','--target',str(assets),'--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
root=json.loads(native('findmnt','--json','--target','/','--output=TARGET,SOURCE,FSTYPE,MAJ:MIN'))['filesystems']
verify_repository_disk(mount,root)
space=os.statvfs(assets);assert space.f_bavail>0
print(json.dumps({'mount':mount,'root_mount':root,'available_bytes':space.f_bavail*space.f_frsize}))
''')
        (self.root / 'cilium-storage.json').write_text(json.dumps(storage, indent=2))
        for name, digest in self.assets.items():
            self.upload(self.args.assets_dir / name, ASSETS + '/' + name, digest)
        payload = self.root / 'cilium-input.json'
        payload.write_text(json.dumps({'records': self.records, 'objects': objects, 'assets': self.assets}))
        self.upload(payload, ASSETS + '/input.json', hashlib.sha256(payload.read_bytes()).hexdigest())
        installed = self.guest(inspect.getsource(verify_signature_output) + '\nassets_path=' + repr(ASSETS) + '\n' + '''
assets=pathlib.Path(assets_path)
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo','/mnt/qualification-repo')
native('rpmkeys','--import',str(assets/'rancher-public.key'))
signature=native('rpmkeys','--checksig','--verbose',str(assets/'policy.rpm'))
verify_signature_output(signature)
assert 'e257814a' in signature.lower()
assert native('rpm','-qp','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',str(assets/'policy.rpm'))=='1.6-1.el9.noarch'
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=localpkg_gpgcheck=True','--setopt=install_weak_deps=False','--assumeyes','install',
       'container-selinux',str(assets/'policy.rpm'))
assert not native('rpm','-V','container-selinux','k3s-selinux')
assert any(line.split()[:2]==['200','k3s']for line in native('semodule','--list=full').splitlines())
print(json.dumps({'signed_policy_and_dependencies':True,'policy':'1.6-1.el9.noarch','enforcing':True}))
''')
        for name in ('cilium_native_runtime.py', 'nfs_csi_native_runtime.py'):
            source = Path(__file__).with_name(name)
            self.upload(source, ASSETS + '/' + name, hashlib.sha256(source.read_bytes()).hexdigest())
        before = self.runtime('initial')
        before_boot = self.identity()
        after_boot = self.reboot(VERSION, before_boot)
        after = self.runtime('after-reboot')
        if any(before[k] != after[k] for k in ('node_uid', 'cluster_uid', 'packages', 'booleans_sha256', 'images', 'native_cni')):
            raise RuntimeError('native Cilium identities or policy changed across reboot')
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'before': before, 'after': after,
                'before_boot': before_boot, 'after_boot': after_boot,
                'production_nas_gpu_ceph_csi_and_multihost_unqualified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir', 'assets-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    parser.add_argument('--helm', default='helm')
    qualification = Qualification(parser.parse_args())

    def cancel(_number, _frame):
        raise RuntimeError('owned native Cilium qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'cilium-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
