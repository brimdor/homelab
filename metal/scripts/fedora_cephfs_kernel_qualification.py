#!/usr/bin/env python3
"""Add native CephFS to the exact signed, disconnected kernel/RBD profile."""

import argparse
import hashlib
import json
from pathlib import Path
import signal

from fedora_ceph_kernel_qualification import Qualification as Ceph, TARGETS


class Qualification(Ceph):
    targets = [*TARGETS, 'ceph-mds-2:20.2.4-1.fc44.x86_64']

    def native_runtime(self):
        files = {}
        for name in ('ceph_kernel_runtime.py', 'ceph_runtime_qualification.py', 'etcd_recovery.py',
                     'cephfs_kernel_runtime.py'):
            path = Path(__file__).with_name(name).resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            destination = '/run/qualification-cephfs-runtime.py' if name == 'cephfs_kernel_runtime.py' else '/work/' + name
            self.upload(path, destination, digest)
            files[name] = digest
        result = json.loads(self.command(self.ssh + ['sudo python3 -B /run/qualification-cephfs-runtime.py']))
        return result, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'kernel-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = Qualification(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned CephFS qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'cephfs-kernel-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
