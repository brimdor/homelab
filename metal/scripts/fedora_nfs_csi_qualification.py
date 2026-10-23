#!/usr/bin/env python3
"""Qualify native Fedora NFS CSI with explicit containerd SELinux support."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import tarfile

import yaml

import fedora_target_qualification as fedora
from fedora_kernel_qualification import Qualification as Kernel
from maintenance_combined_qualification import K3S, AIRGAP, SELINUX_KEY


POLICY = '23d0095a766b89317d2bdbe8773825987db7221e48743417930a994ca1096793'
CHART = 'aace8754451ecbd87e090ec29e6cbffcf88dbd9980cecb165da8b9d0880f7fac'
NAMESPACE = 'nfs-csi-native'
IMAGE_FILE = Path(__file__).resolve().parents[1] / 'maintenance/nfs-csi-native-images.json'


def image_records():
    records = json.loads(IMAGE_FILE.read_bytes())
    if (len(records) != 6 or len({r['image'] for r in records}) != 6 or
            sum(r['image'].startswith('registry.k8s.io/sig-storage/') for r in records) != 5 or
            records[-1]['image'] != 'docker.io/library/python:3.13-alpine' or
            any(set(r) != {'image', 'index_digest', 'digest'} or
                not all(re.fullmatch('sha256:[0-9a-f]{64}', r[k]) for k in ('digest', 'index_digest'))
                for r in records)):
        raise RuntimeError('native CSI image inventory differs')
    return records


def archive_identity(path, record):
    """Require a single exact AMD64 manifest and its complete reachable blobs."""
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        files = {}
        names = set()
        for member in members:
            name = member.name.removeprefix('./')
            if name in names:
                raise RuntimeError('duplicate OCI member')
            names.add(name)
            if member.isdir() and name.rstrip('/') in ('', '.', 'blobs', 'blobs/sha256'):
                continue
            if not member.isfile() or not re.fullmatch(r'index\.json|oci-layout|blobs/sha256/[a-f0-9]{64}', name):
                raise RuntimeError('unsafe OCI member')
            files[name] = member
            if name.startswith('blobs/'):
                digest = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(1048576), b''):
                        digest.update(block)
                if digest.hexdigest() != name.rsplit('/', 1)[1]:
                    raise RuntimeError('OCI blob checksum differs')

        def read(name):
            if name not in files or files[name].size > 65536:
                raise RuntimeError('missing or excessive OCI metadata')
            return json.load(archive.extractfile(files[name]))

        if read('oci-layout') != {'imageLayoutVersion': '1.0.0'}:
            raise RuntimeError('OCI layout version differs')
        index = read('index.json')
        manifests = index.get('manifests', [])
        if (index.get('schemaVersion') != 2 or len(manifests) != 1 or
                manifests[0].get('digest') != record['digest'] or
                manifests[0].get('annotations', {}).get('org.opencontainers.image.ref.name') != record['image']):
            raise RuntimeError('OCI import identity differs')
        root_name = 'blobs/sha256/' + record['digest'].split(':')[1]
        manifest = read(root_name)
        descriptors = [manifest['config'], *manifest['layers']]
        expected = {'oci-layout', 'index.json', root_name}
        for descriptor in descriptors:
            if not re.fullmatch('sha256:[a-f0-9]{64}', descriptor['digest']):
                raise RuntimeError('OCI descriptor digest differs')
            name = 'blobs/sha256/' + descriptor['digest'].split(':')[1]
            if name not in files or files[name].size != descriptor['size']:
                raise RuntimeError('OCI descriptor length differs')
            expected.add(name)
        config = read('blobs/sha256/' + manifest['config']['digest'].split(':')[1])
        if config.get('architecture') != 'amd64' or config.get('os') != 'linux' or set(files) != expected:
            raise RuntimeError('OCI platform or reachable blob set differs')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def reviewed_chart(objects, records):
    pins = {r['image']: r['image'].rsplit(':', 1)[0] + '@' + r['digest'] for r in records[:-1]}
    workloads = [o for o in objects if o['kind'] in ('Deployment', 'DaemonSet')]
    if (len(objects) != 9 or len(workloads) != 2 or
            any(o['kind'] in ('PersistentVolume', 'PersistentVolumeClaim', 'StorageClass',
                              'CustomResourceDefinition', 'VolumeSnapshotClass') for o in objects) or
            {c['image'] for o in workloads for c in o['spec']['template']['spec']['containers']} != set(pins)):
        raise RuntimeError('reviewed CSI chart resource or image contract changed')
    driver = [o for o in objects if o['kind'] == 'CSIDriver']
    if len(driver) != 1 or driver[0]['spec'].get('fsGroupPolicy') != 'File':
        raise RuntimeError('CSI File ownership policy changed')
    for workload in workloads:
        spec = workload['spec']['template']['spec']
        if spec.get('hostNetwork') is not True or spec.get('initContainers'):
            raise RuntimeError('CSI host-network or init-container contract changed')
        plugins = [c for c in spec['containers'] if c['name'] == 'nfs']
        if len(plugins) != 1 or plugins[0]['securityContext'].get('privileged') is not True:
            raise RuntimeError('upstream CSI plugin security contract changed')
        for container in spec['containers']:
            container['image'] = pins[container['image']]
            container['imagePullPolicy'] = 'Never'
    return objects


class Qualification(Kernel):
    def __init__(self, args):
        fedora.require_root(args.work_dir)
        if (not args.assets_dir.is_absolute() or not args.assets_dir.is_relative_to(args.work_dir) or
                any(p.is_symlink() for p in (args.assets_dir, *args.assets_dir.parents))):
            raise RuntimeError('native CSI assets outside the owned fixture')
        self.records = image_records()
        self.assets = {'k3s': K3S, 'airgap.tar.zst': AIRGAP, 'policy.rpm': POLICY,
                       'rancher-public.key': SELINUX_KEY, 'csi-chart.tgz': CHART}
        for number, record in enumerate(self.records):
            path = args.assets_dir / ('image-' + str(number) + '.tar')
            # Check path ownership/ancestry before opening an archive.
            if not path.is_file() or path.is_symlink():
                raise RuntimeError('native OCI asset is not a regular owned file')
            self.assets[path.name] = archive_identity(path, record)
        for name, digest in self.assets.items():
            fedora.require_media(args.work_dir, args.assets_dir / name, digest)
        super().__init__(args)

    def run(self):
        kernel = super().run()
        (self.root / 'kernel-result.json').write_text(json.dumps(kernel, indent=2))
        rendered = self.command([self.args.helm, 'template', 'qualification',
                                 str(self.args.assets_dir / 'csi-chart.tgz'), '--namespace', NAMESPACE,
                                 '--kube-version', '1.33.6',
                                 '--set', 'controller.enableSnapshotter=false',
                                 '--set', 'storageClass.create=false', '--set', 'externalSnapshotter.enabled=false',
                                 '--set', 'externalSnapshotter.customResourceDefinitions.enabled=false',
                                 '--set', 'driver.mountPermissions=0', '--set', 'feature.enableInlineVolume=false',
                                 '--set', 'feature.propagateHostMountOptions=false'])
        objects = reviewed_chart(list(yaml.safe_load_all(rendered)), self.records)
        payload = self.root / 'csi-input.json'
        payload.write_text(json.dumps({'records': self.records, 'objects': objects, 'assets': self.assets}))
        self.command(self.ssh + ['sudo mkdir -m 0700 /run/qualification-csi-assets'])
        for name, digest in self.assets.items():
            self.upload(self.args.assets_dir / name, '/run/qualification-csi-assets/' + name, digest)
        self.upload(payload, '/run/qualification-csi-assets/input.json', hashlib.sha256(payload.read_bytes()).hexdigest())
        installed = self.guest('''
mount=pathlib.Path('/mnt/qualification-repo')
native('mount','-t','iso9660','-o','ro','/dev/disk/by-id/virtio-qualification-repo',str(mount))
assets=pathlib.Path('/run/qualification-csi-assets')
native('rpmkeys','--import',str(assets/'rancher-public.key'))
signature=native('rpmkeys','--checksig','--verbose',str(assets/'policy.rpm'))
assert 'e257814a' in signature.lower() and 'NOKEY' not in signature and 'NOT OK' not in signature
assert native('rpm','-qp','--qf','%{VERSION}-%{RELEASE}.%{ARCH}',str(assets/'policy.rpm'))=='1.6-1.el9.noarch'
native('dnf5','--disable-repo=*','--enable-repo=qualification','--setopt=gpgcheck=True',
       '--setopt=localpkg_gpgcheck=True','--setopt=install_weak_deps=False','--assumeyes','install',
       'nfs-utils','container-selinux',str(assets/'policy.rpm'))
assert not native('rpm','-V','nfs-utils','container-selinux','k3s-selinux')
assert any(line.split()[:2]==['200','k3s']for line in native('semodule','--list=full').splitlines())
print(json.dumps({'signed_policy_and_dependencies':True,'policy':'1.6-1.el9.noarch','enforcing':True}))
''')
        source = Path(__file__).with_name('nfs_csi_native_runtime.py')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.upload(source, '/run/qualification-csi-runtime.py', digest)
        result = json.loads(self.command(self.ssh + ['sudo python3 -B /run/qualification-csi-runtime.py']))
        (self.root / 'csi-native-result.json').write_text(json.dumps(result, indent=2))
        if result.get('accepted') is not True:
            raise RuntimeError('native CSI runtime refused; inspect retained result')
        return {'accepted': True, 'kernel': kernel, 'installed': installed, 'runtime': result,
                'runtime_sha256': digest, 'assets': self.assets, 'production_or_nas_changes': False}


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
        raise RuntimeError('owned native CSI qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'csi-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
