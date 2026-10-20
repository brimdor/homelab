#!/usr/bin/env python3
"""Qualify Fedora 44 target primitives in an owned, disconnected AMD64 QEMU VM."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import stat
import subprocess
import time

import pycdlib
import yaml


AUTOMATIC_RPM_SHA256 = '59940bf52907d6dee1fd018338b90b7519143d9f4e78c48d136e8ee8a9869990'


MEDIA = {
    'cloud': '28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f',
    'server': '85837793bfa36db6bc709b4cecd2ec116951b87d9c53c3d95eb2fac8dcf7cf1f',
}


def require_root(root):
    if (not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)) or
            any(c in str(root) for c in ',\n\r')):
        raise RuntimeError('qualification requires an absolute nonsymlink root')
    mode = root.stat()
    if (not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.getuid() or
            stat.S_IMODE(mode.st_mode) != 0o700 or root.is_relative_to(Path.cwd()) or
            Path.cwd().is_relative_to(root)):
        raise RuntimeError('qualification root must be private, owned and outside the checkout')


def require_media(root, path, expected):
    if (not path.is_absolute() or not path.is_relative_to(root) or
            any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()):
        raise RuntimeError('fixture media must be regular files beneath the owned root')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError('signed fixture media hash differs')


def qemu_arguments(args, overlay, seed, port, serial):
    return [args.qemu, '-no-user-config', '-nodefaults', '-machine', 'q35',
            '-accel', 'tcg,thread=multi', '-cpu', 'max', '-smp', '2', '-m', '4096',
            '-display', 'none', '-monitor', 'none', '-serial', 'file:' + str(serial),
            '-drive', 'if=none,id=root,format=qcow2,file=' + str(overlay),
            '-device', 'virtio-blk-pci,drive=root,serial=qualification-root,bootindex=1',
            '-drive', 'if=none,id=seed,format=raw,readonly=on,file=' + str(seed),
            '-device', 'virtio-blk-pci,drive=seed,serial=qualification-seed',
            '-drive', 'if=none,id=repo,format=raw,readonly=on,file=' + str(args.server_image),
            '-device', 'virtio-blk-pci,drive=repo,serial=qualification-repo',
            '-netdev', 'user,id=fixture,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:' + str(port) + '-:22',
            '-device', 'virtio-net-pci,netdev=fixture,mac=52:54:00:10:03:44',
            '-object', 'rng-random,id=random,filename=/dev/urandom',
            '-device', 'virtio-rng-pci,rng=random']


class Qualification:
    def __init__(self, args):
        require_root(args.work_dir)
        for name in MEDIA:
            require_media(args.work_dir, getattr(args, name + '_image'), MEDIA[name])
        require_media(args.work_dir, args.automatic_rpm, AUTOMATIC_RPM_SHA256)
        self.args = args
        self.root = args.work_dir / 'runtime'
        self.root.mkdir(mode=0o700)
        self.number = 0
        self.child = None
        self.ssh = None

    def command(self, argv, *, data=None, env=None, expected=0):
        self.number += 1
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=env, start_new_session=True)
        try:
            stdout, stderr = child.communicate(data)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        # Only synthetic VM data and reviewed controller output enter these logs.
        (self.root / (str(self.number) + '.log')).write_bytes(stdout + stderr)
        if child.returncode != expected:
            raise RuntimeError('qualification command ' + str(self.number) + ' exit ' + str(child.returncode))
        return stdout

    def prepare(self):
        info = json.loads(self.command([self.args.qemu_img, 'info', '--output=json', str(self.args.cloud_image)]))
        if info['format'] != 'qcow2' or any(k in info for k in ('backing-filename', 'data-file')):
            raise RuntimeError('signed cloud image has an unexpected external backing file')
        for name in ('login', 'host'):
            self.command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.root / name)])
        public = (self.root / 'login.pub').read_text().strip()
        user = {'hostname': 'qualification-fedora44', 'preserve_hostname': False,
                'ssh_pwauth': False, 'disable_root': True, 'ssh_deletekeys': False,
                'ssh_keys': {'ed25519_private': (self.root / 'host').read_text(),
                             'ed25519_public': (self.root / 'host.pub').read_text().strip()},
                'users': [{'name': 'fixture', 'groups': ['wheel'], 'shell': '/bin/bash',
                           'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'lock_passwd': True,
                           'ssh_authorized_keys': [public]}], 'package_update': False, 'package_upgrade': False}
        seed = self.root / 'seed.iso'
        iso = pycdlib.PyCdlib()
        try:
            iso.new(interchange_level=3, joliet=3, rock_ridge='1.09', vol_ident='CIDATA')
            for name, iso_name, raw in (
                ('user-data', 'USER_DAT', ('#cloud-config\n' + yaml.safe_dump(user)).encode()),
                ('meta-data', 'META_DAT', b'instance-id: qualification-fedora44\nlocal-hostname: qualification-fedora44\n'),
            ):
                iso.add_fp(io.BytesIO(raw), len(raw), iso_path='/' + iso_name + '.;1',
                           rr_name=name, joliet_path='/' + name)
            iso.add_file(str(self.args.automatic_rpm), iso_path='/AUTOMATIC.RPM;1',
                         rr_name='automatic.rpm', joliet_path='/automatic.rpm')
            iso.write(str(seed))
        finally:
            iso.close()
        overlay = self.root / 'disk.qcow2'
        self.command([self.args.qemu_img, 'create', '-f', 'qcow2', '-F', 'qcow2',
                      '-b', str(self.args.cloud_image), str(overlay)])
        self.command([self.args.qemu_img, 'resize', str(overlay), '20G'])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        known = self.root / 'known_hosts'
        known.write_text('[127.0.0.1]:' + str(port) + ' ' + (self.root / 'host.pub').read_text())
        common = ['-F', '/dev/null', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                  '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                  '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
                  '-o', 'ControlMaster=no', '-o', 'ControlPersist=no', '-o', 'IdentityAgent=none',
                  '-o', 'ConnectTimeout=10']
        self.ssh = ['ssh', *common, '-i', str(self.root / 'login'), '-p', str(port), 'fixture@127.0.0.1']
        inventory = {'all': {'hosts': {'fixture': {'ansible_host': '127.0.0.1', 'ansible_port': port,
                      'ansible_user': 'fixture', 'ansible_ssh_private_key_file': str(self.root / 'login'),
                      'ansible_python_interpreter': '/usr/bin/python3',
                      'ansible_ssh_common_args': shlex.join(common)}}}}
        (self.root / 'inventory.yml').write_text(yaml.safe_dump(inventory))
        serial = self.root / 'serial.log'
        serial.touch(mode=0o600, exist_ok=False)
        argv = qemu_arguments(self.args, overlay, seed, port, serial)
        output = (self.root / 'qemu.log').open('wb')
        try:
            self.child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                                          stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            output.close()
        print(json.dumps({'phase': 'boot', 'pid': self.child.pid, 'port': port,
                          'architecture': 'x86_64', 'egress': 'restricted'}), flush=True)

    def wait_ready(self):
        # No overall VM deadline: stop on process exit, cancellation or an evidenced fault.
        while True:
            if self.child.poll() is not None:
                raise RuntimeError('owned QEMU exited before trusted SSH became ready')
            serial = (self.root / 'serial.log').read_bytes()[-65536:]
            if any(s in serial for s in (b'Kernel panic', b'No bootable device', b'grub rescue>')):
                raise RuntimeError('owned fixture has an evidenced boot failure')
            probe = subprocess.run(self.ssh + ['true'], capture_output=True)
            if probe.returncode == 0:
                break
            error = probe.stderr.decode()
            if any(s in error for s in ('REMOTE HOST IDENTIFICATION HAS CHANGED', 'Permission denied',
                                        'Host key verification failed')):
                raise RuntimeError('fixture SSH authentication or pinned host identity refused')
            time.sleep(5)
        self.command(self.ssh + ['sudo cloud-init status --wait'])

    def identity(self):
        script = """import json,pathlib,subprocess,socket
p=pathlib.Path
for address in ('10.0.20.50','1.1.1.1'):
 try:
  with socket.create_connection((address,443),timeout=2):pass
 except OSError:pass
 else:raise RuntimeError('restricted fixture has an external route')
print(json.dumps({'machine':p('/etc/machine-id').read_text().strip(),
 'boot':p('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'root_uuid':subprocess.check_output(['findmnt','-n','-o','UUID','/']).decode().strip(),
 'architecture':subprocess.check_output(['uname','-m']).decode().strip(),
 'kernel':subprocess.check_output(['uname','-r']).decode().strip()}))
"""
        value = json.loads(self.command(self.ssh + ['python3 -'], data=script.encode()))
        if not value['machine'] or not value['root_uuid'] or value['architecture'] != 'x86_64':
            raise RuntimeError('missing fixture OS identity')
        return value

    def run(self):
        self.prepare()
        self.wait_ready()
        before = self.identity()
        env = {**os.environ, 'ANSIBLE_CONFIG': str(Path('metal/maintenance/ansible.cfg').resolve()),
               'ANSIBLE_COLLECTIONS_PATH': str(self.args.collection_dir), 'ANSIBLE_HOST_KEY_CHECKING': 'True',
               'ANSIBLE_LOCAL_TEMP': str(self.root / 'ansible-tmp'),
               'ANSIBLE_SSH_ARGS': '-o ControlMaster=no -o ControlPersist=no'}
        argv = [str(self.args.ansible_playbook), '-i', str(self.root / 'inventory.yml'),
                'metal/maintenance/fedora-target.yml', '--limit', 'fixture']
        refusal = self.command(argv + ['-e', 'qualification_refuse=true'], env=env, expected=2)
        if b'INTENTIONAL_QUALIFICATION_PREFLIGHT_REFUSAL' not in refusal or self.identity() != before:
            raise RuntimeError('preflight refusal did not preserve the exact fixture boot/identity')
        print(json.dumps({'phase': 'preflight-refusal-accepted'}), flush=True)
        self.command(argv, env=env)
        after = self.identity()
        if (before['boot'] == after['boot'] or
                any(before[k] != after[k] for k in ('machine', 'root_uuid', 'architecture', 'kernel'))):
            raise RuntimeError('fixture reboot or preserved identity failed')
        return {'target_primitive_qualification': True, 'before': before, 'after': after,
                'strict_ssh_identity': True, 'network_restricted': True, 'signed_offline_media': MEDIA,
                'production_changes': False, 'release_upgrade_and_gpu_csi_unqualified': True}

    def cleanup(self):
        if self.child:
            if self.child.poll() is None:
                os.killpg(self.child.pid, signal.SIGTERM)
            try:
                self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait()
            if self.child.poll() is None:
                raise RuntimeError('owned QEMU process was not reaped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir', 'automatic-rpm'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    args = parser.parse_args()
    qualification = Qualification(args)

    def cancel(_number, _frame):
        raise RuntimeError('owned Fedora qualification cancelled')

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        print(json.dumps(result), flush=True)
        (qualification.root / 'result.json').write_text(json.dumps(result, indent=2))
    finally:
        qualification.cleanup()
        # The tracked caller removes owned media, disk, credentials and controller scratch.


if __name__ == '__main__':
    main()
