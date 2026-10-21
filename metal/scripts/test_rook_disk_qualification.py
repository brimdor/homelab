#!/usr/bin/env python3
"""Protect raw disk identity and reject VM/guest attachment drift."""

import copy
from pathlib import Path
import tempfile
import shlex
import unittest

import rook_disk_qualification as subject


class DiskGuardTests(unittest.TestCase):
    def test_explicit_qemu_arguments_bind_only_owned_raw_files_and_serials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identities = {}
            for number in range(3):
                name = 'rook-12345678-' + str(number)
                path = root / 'l/_disks' / name / 'datadisk'
                path.parent.mkdir(parents=True)
                with path.open('xb') as stream:
                    stream.truncate(subject.DISK_BYTES)
                identities[name] = {'path': str(path), **subject.file_identity(path)}
            arguments = shlex.split(subject.qemu_arguments(identities, root))
            self.assertEqual(arguments[0], '/opt/homebrew/bin/qemu-system-aarch64')
            self.assertEqual(arguments.count('-drive'), 3)
            self.assertEqual(arguments.count('-device'), 3)
            self.assertIn('virtio-blk-pci,drive=rook-12345678-2,id=rook-12345678-2,serial=lima-rook-12345678-2',
                          arguments)
            for field, value in [('inode', -1), ('bytes', 0), ('path', '/dev/disk0')]:
                changed = copy.deepcopy(identities)
                changed['rook-12345678-0'][field] = value
                with self.assertRaises(RuntimeError):
                    subject.qemu_arguments(changed, root)
            with self.assertRaises(RuntimeError):
                subject.qemu_arguments(dict(list(identities.items())[:2]), root)

    def test_qemu_native_backend_must_match_every_declared_file_and_device(self):
        identities = {'rook-12345678-' + str(n): {'path': '/owned/' + str(n)} for n in range(3)}
        rows = [{'device': name, 'qdev': '/machine/peripheral/' + name + '/virtio-backend',
                 'inserted': {'file': value['path'], 'drv': 'raw', 'ro': False,
                              'image': {'filename': value['path'], 'format': 'raw',
                                        'virtual-size': subject.DISK_BYTES}}}
                for name, value in identities.items()]
        self.assertEqual(len(subject.require_qemu_backends(rows, identities)), 3)
        for field, value in [('file', '/dev/disk0'), ('drv', 'qcow2'), ('ro', True),
                             ('image', {'format': 'raw', 'virtual-size': 4096})]:
            changed = copy.deepcopy(rows)
            changed[0]['inserted'][field] = value
            with self.assertRaises(RuntimeError):
                subject.require_qemu_backends(changed, identities)
        for changed in [rows[:-1], rows + [rows[0]], [rows[0] | {'qdev': '/foreign'}, *rows[1:]]]:
            with self.assertRaises(RuntimeError):
                subject.require_qemu_backends(changed, identities)

    def test_owned_environment_refuses_symlink_or_foreign_root_before_commands(self):
        with tempfile.TemporaryDirectory(prefix='v-') as directory:
            root = Path(directory)
            root.chmod(0o700)
            for name in ('h', 'l', 'd'):
                (root / name).mkdir(mode=0o700)
            subject.Fixture(root, 'rook-12345678')
            with self.assertRaises(RuntimeError):
                subject.Fixture(root, 'foreign')
            (root / 'l').rmdir()
            (root / 'l').symlink_to(root / 'h', target_is_directory=True)
            with self.assertRaises(RuntimeError):
                subject.Fixture(root, 'rook-12345678')

    def test_raw_file_refuses_wrong_size_link_or_nonzero_sector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'datadisk'
            with path.open('xb') as output:
                output.truncate(subject.DISK_BYTES)
            self.assertEqual(subject.file_identity(path)['bytes'], subject.DISK_BYTES)
            with path.open('r+b') as output:
                output.write(b'foreign')
            with self.assertRaises(RuntimeError):
                subject.file_identity(path)
            path.write_bytes(b'wrong size')
            with self.assertRaises(subject.DiskIdentityError) as rejected:
                subject.file_identity(path)
            self.assertEqual(rejected.exception.observation,
                             {'regular_file': True, 'owned_by_current_user': True,
                              'bytes': 10, 'expected_bytes': subject.DISK_BYTES,
                              'symlink': False, 'ancestor_symlink': False})
            path.unlink()
            path.symlink_to('/etc/hosts')
            with self.assertRaises(RuntimeError):
                subject.file_identity(path)

    def test_attachment_preserves_every_other_vm_field(self):
        before = {'vmType': 'vz', 'cpus': 2, 'memory': '2048MiB',
                  'mounts': [], 'ssh': {'forwardAgent': False},
                  'additionalDisks': [{'name': 'existing-owned-docker-disk'}]}
        names = ['rook-12345678-' + str(n) for n in range(3)]
        after = copy.deepcopy(before)
        after['additionalDisks'] += [{'name': name, 'format': False, 'mount': False} for name in names]
        subject.added_config(before, after, names)
        for fields in ({'mounts': [{'location': '/Users'}]}, {'blockDevices': ['/dev/disk0']},
                       {'cpus': 3}, {'ssh': {'forwardAgent': True}}):
            with self.assertRaises(RuntimeError):
                subject.added_config(before, after | fields, names)
        for key in ('format', 'mount'):
            changed = copy.deepcopy(after)
            changed['additionalDisks'][1][key] = True
            with self.assertRaises(RuntimeError):
                subject.added_config(before, changed, names)
        subject.require_config(before | {'vmType': 'qemu'}, 'qemu')
        storage = before | {'vmType': 'qemu', 'cpus': 8, 'memory': '12288MiB'}
        subject.require_config(storage, 'qemu', 'storage')
        for value, backend, profile in [(storage, 'qemu', 'substrate'),
                                        (storage | {'vmType': 'vz'}, 'vz', 'storage'),
                                        (storage, 'qemu', 'unreviewed')]:
            with self.assertRaises(RuntimeError):
                subject.require_config(value, backend, profile)
        for value, expected in [(before, 'qemu'), (before | {'vmType': 'qemu'}, 'vz'),
                                (before, 'unreviewed')]:
            with self.assertRaises(RuntimeError):
                subject.require_config(value, expected)

    def test_guest_requires_three_distinct_blank_serial_bound_whole_devices(self):
        names = ['rook-12345678-' + str(n) for n in range(3)]
        rows = [{'path': '/dev/vd' + letter, 'type': 'disk', 'size': subject.DISK_BYTES,
                 'serial': 'lima-' + name, 'fstype': None, 'mountpoints': [None],
                 'pkname': None, 'maj:min': '254:' + str(number * 16), 'ro': False}
                for number, (letter, name) in enumerate(zip('cde', names))]
        self.assertEqual(len(subject.guest_disks({'blockdevices': rows}, names)), 3)
        for fields in ({'fstype': 'ext4'}, {'mountpoints': ['/']}, {'children': [{}]},
                       {'serial': 'foreign'}, {'pkname': '/dev/vda'}, {'type': 'part'},
                       {'size': 4096}, {'path': '/dev/disk0'}, {'ro': True}, {'maj:min': '254:16'}):
            changed = copy.deepcopy(rows)
            changed[0].update(fields)
            with self.assertRaises(RuntimeError):
                subject.guest_disks({'blockdevices': changed}, names)
        with self.assertRaises(RuntimeError):
            subject.guest_disks({'blockdevices': rows + [rows[0]]}, names)

        changed = copy.deepcopy(rows)
        changed[0]['serial'] = 'different-native-serial'
        with self.assertRaises(subject.GuestDiskIdentityError) as rejected:
            subject.guest_disks({'blockdevices': changed}, names)
        self.assertEqual(rejected.exception.observation['whole_device_count'], 3)
        self.assertEqual(rejected.exception.observation['devices'][0]['serial'], 'different-native-serial')
        self.assertEqual(rejected.exception.observation['expected_serials'][0], 'lima-' + names[0])
        changed[0]['serial'] = 'unexpected\nfield'
        with self.assertRaises(subject.GuestDiskIdentityError) as rejected:
            subject.guest_disks({'blockdevices': changed}, names)
        self.assertEqual(rejected.exception.observation['devices'][0]['serial'], 'unclassified')

    def test_native_import_must_preserve_raw_format_size_and_name(self):
        value = {'Name': 'rook-12345678-0', 'Format': 'raw', 'Size': subject.DISK_BYTES}
        subject.require_imported_disk(value, value['Name'])
        for changed in [None, {}, value | {'Format': 'qcow2'},
                        value | {'Size': 196736}, value | {'Name': 'foreign'}]:
            with self.subTest(value=changed), self.assertRaises(RuntimeError):
                subject.require_imported_disk(changed, value['Name'])


if __name__ == '__main__':
    unittest.main()
