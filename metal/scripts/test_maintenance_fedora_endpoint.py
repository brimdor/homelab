"""Check actual generated seeds/arguments without booting or changing a host."""

import ast
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pycdlib
import yaml

import fedora_release_upgrade_qualification as upgrade
import maintenance_fedora_endpoint as fleet


class Endpoints(unittest.TestCase):
    def test_fixed_identity_and_bad_input_refusal_before_media_or_process(self):
        values = [fleet.endpoint(i, 23000 + i) for i in range(3)]
        for key in ('hostname', 'management_mac', 'cluster_mac', 'address', 'root_serial', 'port'):
            self.assertEqual(len({v[key] for v in values}), 3)
        self.assertTrue(all(len(v['root_serial'].encode())<=20 for v in values))
        self.assertEqual(len({v[key] for v in values for key in ('management_mac', 'cluster_mac')}), 6)
        with patch.object(upgrade.Qualification, '__init__') as parent:
            for index in (-1, 3, True, '0', None):
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    fleet.Endpoint(None, index, 23000)
            for port in (0, 65536, True, '23000', None):
                with self.subTest(port=port), self.assertRaises(RuntimeError):
                    fleet.Endpoint(None, 0, port)
            parent.assert_not_called()
        for name in (None, 'production', 'qualification-native-3', "x';raise Exception()"):
            with self.subTest(hostname=name), self.assertRaises(RuntimeError):
                upgrade.guest_source(name)
        self.assertEqual(upgrade.GUEST, upgrade.guest_source())
        for name in [upgrade.HOSTNAME] + [v['hostname'] for v in values]:
            header = upgrade.guest_source(name)
            tree = ast.parse(header)
            self.assertEqual(ast.literal_eval(tree.body[0].value), name)
            self.assertIn('socket.gethostname()==fixture_hostname', header)

    def test_actual_seed_private_paths_arguments_and_reboot_without_duplicate_nic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(work_dir=root, qemu_img='/owned/qemu-img',
                                   cloud_image=root / 'image.qcow2', keys_dir=root, qemu='/owned/qemu')
            def initialize(instance, selected):
                instance.args = selected;instance.root = root / instance.runtime_name
                instance.root.mkdir(mode=0o700);instance.contract = {'keys': {}}
                instance.child = None
            for index in range(3):
                with self.subTest(index=index), patch.object(upgrade.Qualification, '__init__', initialize):
                    instance = fleet.Endpoint(args, index, 23000 + index)
                    def command(argv):
                        if argv[1]=='info':return json.dumps({'format':'qcow2'}).encode()
                        if argv[0]=='ssh-keygen':
                            key=Path(argv[-1]);key.write_text('owned synthetic key');key.with_suffix('.pub').write_text('ssh-ed25519 synthetic\n')
                        return b''
                    instance.command = command
                    with patch.object(upgrade, 'RepositoryServer') as server, \
                            patch.object(upgrade.threading, 'Thread'), patch.object(upgrade.Qualification, 'boot') as boot:
                        server.return_value.server_address=('127.0.0.1', 24000 + index)
                        instance.prepare()
                        boot.assert_called_once_with()
                        server.assert_called_once_with(root / ('repositories-' + str(index)))
                        original=list(instance.qemu_argv);instance.boot()
                        self.assertEqual(instance.qemu_argv, original)
                        self.assertEqual(boot.call_count, 2)
                        with self.assertRaisesRegex(RuntimeError, 'already started'):instance.prepare()
                    self.assertEqual(sum('socket,id=cluster,connect=127.0.0.1:' in v for v in original), 1)
                    self.assertIn('socket,id=cluster,connect=127.0.0.1:' + str(23000+index), original)
                    self.assertIn('virtio-net-pci,netdev=fixture,mac=' + instance.management_mac, original)
                    self.assertIn('virtio-blk-pci,drive=root,serial=' + instance.endpoint['root_serial'] + ',bootindex=1', original)
                    self.assertFalse(any(v in ('-net', '-nic', '-enable-kvm') or 'tap,' in v or 'bridge,' in v for v in original))
                    self.assertIn('restrict=on', next(v for v in original if v.startswith('user,id=fixture')))
                    iso=pycdlib.PyCdlib();iso.open(str(instance.root/'seed.iso'))
                    try:
                        data={}
                        for name in ('user-data','meta-data','network-config'):
                            value=io.BytesIO();iso.get_file_from_iso_fp(value,rr_path='/'+name)
                            data[name]=yaml.safe_load(value.getvalue())
                    finally:iso.close()
                    self.assertEqual(data['user-data']['hostname'],instance.hostname)
                    self.assertEqual(data['meta-data']['instance-id'],instance.hostname)
                    self.assertEqual(data['network-config']['version'],1)
                    interfaces={v['name']:v for v in data['network-config']['config']}
                    self.assertEqual(set(interfaces),{'management0','cluster0'})
                    self.assertEqual(interfaces['management0']['subnets'],[{'type':'dhcp4'}])
                    self.assertEqual(interfaces['cluster0']['mac_address'],instance.endpoint['cluster_mac'])
                    self.assertEqual(interfaces['cluster0']['subnets'],[{'type':'static','address':instance.endpoint['address'],'netmask':'255.255.255.0'}])
                    for interface in interfaces.values():
                        self.assertFalse(set(interface)&{'routes','gateway4','gateway6','nameservers'})
                        for subnet in interface['subnets']:
                            self.assertFalse(set(subnet)&{'gateway','dns_nameservers','routes'})
                    self.assertIn('StrictHostKeyChecking=yes',instance.ssh)
                    self.assertIn('UpdateHostKeys=no',instance.ssh)
                    self.assertIn('IdentityAgent=none',instance.ssh)
                    self.assertEqual(yaml.safe_load((instance.root/'inventory.yml').read_bytes())['hostname'],instance.hostname)

    def test_original_defaults_and_generated_native_identity_program(self):
        self.assertEqual((upgrade.Qualification.hostname, upgrade.Qualification.runtime_name,
                          upgrade.Qualification.repository_name, upgrade.Qualification.management_mac),
                         (upgrade.HOSTNAME,'runtime','repositories','52:54:00:10:03:39'))
        self.assertEqual(upgrade.Qualification.extra_seed_files(None),())
        instance=object.__new__(fleet.Endpoint);instance.endpoint=fleet.endpoint(0,23000)
        instance.identity=lambda:{'machine':'synthetic'}
        programs=[]
        def guest(body):programs.append(compile(upgrade.guest_source(instance.endpoint['hostname'])+body,'<native-identity>','exec'));return {'synthetic':True}
        instance.guest=guest
        self.assertEqual(instance.private_identity()['stable'],{'machine':'synthetic'})
        self.assertEqual(len(programs),1)


if __name__ == '__main__':
    unittest.main()
