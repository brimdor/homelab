"""Fixed private Fedora endpoints for native maintenance qualification only."""

import base64
import hashlib

import yaml

import fedora_release_upgrade_qualification as upgrade
import maintenance_actor_hold as actors


def endpoint(index, port):
    actors.require(type(index) is int and index in (0, 1, 2), 'foreign native endpoint index')
    actors.require(type(port) is int and 1 <= port <= 65535, 'invalid owned hub port')
    return {'hostname': 'qualification-native-' + str(index),
            'management_mac': '52:54:00:10:40:0' + str(index),
            'cluster_mac': '52:54:00:10:41:0' + str(index),
            'address': '192.0.2.' + str(11 + index),
            'root_serial': 'maint103-root-' + str(index), 'port': port}


class Endpoint(upgrade.Qualification):
    def __init__(self, args, index, port):
        self.endpoint = endpoint(index, port)
        self.hostname = self.endpoint['hostname']
        self.management_mac = self.endpoint['management_mac']
        self.runtime_name = 'runtime-' + str(index)
        self.repository_name = 'repositories-' + str(index)
        self.preparation_started = False
        self.network_attached = False
        super().__init__(args)

    def extra_seed_files(self):
        interfaces = [
            {'type': 'physical', 'name': 'management0', 'mac_address': self.management_mac,
             'subnets': [{'type': 'dhcp4'}]},
            {'type': 'physical', 'name': 'cluster0', 'mac_address': self.endpoint['cluster_mac'],
             'subnets': [{'type': 'static', 'address': self.endpoint['address'], 'netmask': '255.255.255.0'}]},
        ]
        return (('network-config', 'NET_CONF', yaml.safe_dump({'version': 1, 'config': interfaces}).encode()),)

    def prepare(self):
        actors.require(not self.preparation_started, 'endpoint preparation already started; never replay')
        self.preparation_started = True
        super().prepare()

    def boot(self):
        if not self.network_attached:
            original = 'virtio-blk-pci,drive=root,serial=qualification-root,bootindex=1'
            actors.require(self.qemu_argv.count(original) == 1 and
                           not any('id=cluster' in value for value in self.qemu_argv),
                           'endpoint root or network arguments differ')
            self.qemu_argv[self.qemu_argv.index(original)] = (
                'virtio-blk-pci,drive=root,serial=' + self.endpoint['root_serial'] + ',bootindex=1')
            self.qemu_argv += ['-netdev', 'socket,id=cluster,connect=127.0.0.1:' + str(self.endpoint['port']),
                               '-device', 'virtio-net-pci,netdev=cluster,mac=' + self.endpoint['cluster_mac']]
            self.network_attached = True
        super().boot()

    def prepared_keys(self):
        result = {}
        for name in ('host', 'login'):
            path = self.root / (name + '.pub')
            actors.safe(path)
            fields = path.read_text().split()
            actors.require(len(fields) >= 2 and fields[0] == 'ssh-ed25519', 'foreign prepared public key')
            raw = base64.b64decode(fields[1], validate=True)
            actors.require(len(raw) == 51 and raw[:19] == bytes.fromhex('0000000b7373682d6564323535313900000020'),
                           'invalid prepared Ed25519 public packet')
            result[name] = hashlib.sha256(raw).hexdigest()
        return result

    def private_identity(self):
        stable = self.identity()
        observed = self.guest('expected=' + repr(self.endpoint) + '\n' + '''
import re
assert socket.gethostname()==expected['hostname']
assert pathlib.Path('/sys/class/net/management0/address').read_text().strip()==expected['management_mac']
assert pathlib.Path('/sys/class/net/cluster0/address').read_text().strip()==expected['cluster_mac']
interfaces=json.loads(native('ip','-j','address','show','dev','cluster0'))
assert len(interfaces)==1 and 'UP' in interfaces[0]['flags']
assert [(a['local'],a['prefixlen'])for a in interfaces[0]['addr_info']if a['family']=='inet']==[(expected['address'],24)]
routes=json.loads(native('ip','-j','route','show','default'))
assert all(route['dev']!='cluster0'for route in routes)
source=native('findmnt','-n','-o','SOURCE','/').strip().split('[')[0]
assert re.fullmatch('/dev/vda[1-9][0-9]*',source)
assert native('lsblk','-dn','-o','PKNAME',source).strip()=='vda'
assert pathlib.Path('/sys/class/block/vda/serial').read_text().strip()==expected['root_serial']
print(json.dumps({'hostname':socket.gethostname(),'root_serial':expected['root_serial'],
 'management_mac':expected['management_mac'],'cluster_mac':expected['cluster_mac'],
 'cluster_address':expected['address'],'cluster_has_no_default_route':True,'enforcing':True}))
''')
        return {'stable': stable, 'private_endpoint': observed}
