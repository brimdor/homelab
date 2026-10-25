#!/usr/bin/env python3
"""Qualify private peer survival across one actual Fedora VM shutdown/restart."""

import argparse
import json
from pathlib import Path
import re
import signal
import socket
import time

import maintenance_actor_hold as actors
from maintenance_fedora_endpoint import Endpoint
from maintenance_vm_network import Hub
from fedora_target_qualification import require_root


SERVER = '''import socketserver,sys
class Handler(socketserver.BaseRequestHandler):
 def handle(self):
  with self.request.makefile('rb')as source:raw=source.readline(513)
  assert len(raw)<=512 and raw.endswith(b'\\n')
  self.request.sendall(raw)
class Server(socketserver.ThreadingTCPServer):
 daemon_threads=True
with Server((sys.argv[1],18087),Handler)as server:server.serve_forever()
'''


class Qualification:
    node_class = Endpoint

    def __init__(self, args):
        require_root(args.work_dir)
        actors.require(isinstance(args.revision, str) and re.fullmatch('[a-f0-9]{40}', args.revision),
                       'exact published endpoint revision required')
        self.args = args
        self.root = args.work_dir / 'fleet'
        self.root.mkdir(mode=0o700)
        self.endpoints, self.hub = [], None
        self.result = {'accepted': False, 'revision': args.revision, 'stages': [], 'production_changes': False}

    def persist(self, stage, **values):
        self.result['stages'].append({'stage': stage, 'at_ns': time.time_ns(), **values})
        (self.root / 'result.json').write_text(json.dumps(self.result, indent=2))

    def ownership(self):
        value = {'hub_pid': self.hub.child.pid if self.hub and self.hub.child else None,
                 'hub_argv': self.hub.argv if self.hub else [],
                 'endpoints': [{'pid': node.child.pid if node.child else None,
                                'disk': str(node.disk) if hasattr(node, 'disk') else None,
                                'argv': getattr(node, 'qemu_argv', []),
                                'prepared_public_keys': node.prepared_keys()} for node in self.endpoints]}
        (self.root / 'ownership.json').write_text(json.dumps(value, indent=2))

    def prepare(self):
        actors.require(not self.endpoints and self.hub is None, 'native fleet already prepared; never replay')
        reservations = [socket.socket() for _ in range(3)]
        try:
            for item in reservations:item.bind(('127.0.0.1', 0))
            ports = [item.getsockname()[1] for item in reservations]
        finally:
            for item in reservations:item.close()
        self.hub = Hub(self.args.qemu, ports, self.root / 'hub.log')
        self.hub.start()
        self.ownership()
        # Observe startup only; never restart the hub or change a port after dispatch.
        for port in ports:
            while True:
                self.hub.running()
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=1):pass
                except ConnectionRefusedError:time.sleep(.1)
                else:break
        self.hub.running()
        for index, port in enumerate(ports):
            node = self.node_class(self.args, index, port)
            self.endpoints.append(node)
            node.prepare()
            self.ownership()
        for node in self.endpoints:node.wait_ready()

    def peer(self, node):
        return node.guest('server=' + repr(SERVER) + '\naddress=' + repr(node.endpoint['address']) + '\n' + '''
root=pathlib.Path('/var/lib/qualification-native-peer');assert not root.exists();root.mkdir(mode=0o700)
script=root/'server.py';script.write_text(server);script.chmod(0o600)
native('systemd-run','--unit=qualification-peer','--service-type=exec','--property=Restart=no',
 '/usr/bin/python3','-B',str(script),address)
import time
while True:
 fields=dict(line.split('=',1)for line in native('systemctl','show','qualification-peer.service',
  '--property=ActiveState','--property=SubState','--property=NRestarts').splitlines())
 assert fields['ActiveState']in('activating','active')and fields['NRestarts']=='0'
 try:connection=socket.create_connection((address,18087),timeout=10)
 except ConnectionRefusedError:time.sleep(.1);continue
 with connection:
  connection.sendall(b'owned-native-peer-ready\\n')
  with connection.makefile('rb')as source:answer=source.readline(513)
 assert answer==b'owned-native-peer-ready\\n'
 break
print(json.dumps({'owned_native_peer_started':True,'address':address,'port':18087}))
''')

    def exchange(self, sender, receiver, phase):
        node = self.endpoints[sender]
        value = {'maintenance': 103, 'sender': sender, 'receiver': receiver, 'phase': phase}
        return node.guest('address=' + repr(self.endpoints[receiver].endpoint['address']) +
                          '\nvalue=' + repr(value) + '\n' + '''
raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\\n'
with socket.create_connection((address,18087),timeout=10)as connection:
 connection.sendall(raw)
 with connection.makefile('rb')as source:answer=source.readline(513)
assert answer==raw
print(json.dumps({'payload':value,'sha256':hashlib.sha256(answer).hexdigest(),'bytes':len(answer)}))
''')

    def identities(self):
        values = [node.private_identity() for node in self.endpoints]
        for key in ('machine', 'boot'):
            actors.require(len({v['stable'][key] for v in values}) == 3, 'native VM identity collision')
        for key in ('hostname', 'root_serial', 'management_mac', 'cluster_mac', 'cluster_address'):
            actors.require(len({v['private_endpoint'][key] for v in values}) == 3,
                           'native private endpoint identity collision')
        return values

    def run(self):
        self.prepare()
        initial = self.identities()
        keys = [node.prepared_keys() for node in self.endpoints]
        actors.require(len({value for record in keys for value in record.values()}) == 6,
                       'prepared native public-key identity collision')
        peers = [self.peer(node) for node in self.endpoints]
        first = [self.exchange(sender, receiver, 'initial') for sender in range(3)
                 for receiver in range(3) if sender != receiver]
        hub_pid = self.hub.running()
        survivor_pids = [node.child.pid for node in self.endpoints[1:]]
        self.persist('three-distinct-native-endpoints', identities=initial, prepared_public_keys=keys, peers=peers,
                     exchanges=first, hub_pid=hub_pid, survivor_pids=survivor_pids)
        target = self.endpoints[0]
        target.stop()
        actors.require(target.child.poll() == 0, 'target shutdown not complete')
        during = [self.exchange(1, 2, 'target-powered-off'), self.exchange(2, 1, 'target-powered-off')]
        actors.require(self.hub.running() == hub_pid and
                       all(node.child.poll() is None and node.child.pid == pid
                           for node, pid in zip(self.endpoints[1:], survivor_pids)),
                       'surviving native processes changed during target shutdown')
        self.persist('peer-traffic-while-target-powered-off', exchanges=during)
        target.boot();self.ownership();target.wait_ready()
        returned = self.identities()
        actors.require([node.prepared_keys() for node in self.endpoints] == keys,
                       'prepared native public keys changed')
        for index, (before, after) in enumerate(zip(initial, returned)):
            actors.require(before['private_endpoint'] == after['private_endpoint'] and
                           all(before['stable'][key] == after['stable'][key]
                               for key in ('machine', 'root_uuid', 'architecture', 'kernel')),
                           'native endpoint stable identity changed')
            actors.require((before['stable']['boot'] != after['stable']['boot']) == (index == 0),
                           'target did not reboot or a surviving peer rebooted')
        # The peer service is transient, so only the restarted target gets a fresh explicit dispatch.
        target.guest('''
root=pathlib.Path('/var/lib/qualification-native-peer');assert root.is_dir()
script=root/'server.py';assert script.is_file();script.unlink();root.rmdir()
print(json.dumps({'previous_owned_peer_source_removed':True}))
''')
        restarted = self.peer(target)
        after = [self.exchange(sender, receiver, 'target-returned') for sender in range(3)
                 for receiver in range(3) if sender != receiver]
        actors.require(self.hub.running() == hub_pid and
                       all(node.child.poll() is None and node.child.pid == pid
                           for node, pid in zip(self.endpoints[1:], survivor_pids)),
                       'surviving native processes changed after target return')
        self.persist('target-returned-with-surviving-peers', identities=returned, prepared_public_keys=keys,
                     exchanges=after, target_peer=restarted)
        self.result.update(accepted=True, actual_native_private_peer_exchanges=14,
                           actual_target_shutdown_and_restart=True,
                           filesystem_UUIDs_may_match_verified_cloned_media=True,
                           Kubernetes_packages_recovery_or_production_qualified=False)
        (self.root / 'result.json').write_text(json.dumps(self.result, indent=2))
        return self.result

    def cleanup(self):
        errors = []
        for node in reversed(self.endpoints):
            try:node.cleanup()
            except BaseException as error:errors.append(error)
        if self.hub is not None:
            try:self.hub.stop()
            except BaseException as error:errors.append(error)
        if errors:raise BaseExceptionGroup('owned native fleet cleanup failed', errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'keys-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    for name in ('qemu', 'qemu-img'):parser.add_argument('--' + name, required=True)
    fixture = Qualification(parser.parse_args())
    def interrupted(_number, _frame):raise InterruptedError('owned native fleet cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):signal.signal(number, interrupted)
    try:print(json.dumps(fixture.run()), flush=True)
    finally:fixture.cleanup()


if __name__ == '__main__':
    main()
