"""One-shot SOURCE stop/start intents, independent of Ready-dependent hop reads.

The parent supplies exact current ownership and quorum checks. This module does
not copy data, run a checker, activate TARGET, or release maintenance ownership.
"""

import hashlib

import maintenance_actor_hold as actors
import maintenance_etcd_stopped as stopped
import maintenance_hop_journal as hops
from maintenance_node_drain import private_json


class Cycle:
    def __init__(self, hold, owner, header, before, native, confirm_owned):
        self.hold, self.owner, self.header, self.before = hold, owner, header, before
        self.native, self.confirm_owned = native, confirm_owned
        self.parent = hold.state / 'etcd-cycles'
        self.path = self.parent / owner['owner']

    def guard(self):
        actors.require(self.owner.get('component') == 'k3s' and
                       self.owner.get('node') in ('charmander', 'squirtle', 'bulbasaur') and
                       (self.owner['source'], self.owner['target']) == ('v1.33.10+k3s1', 'v1.33.13+k3s2') and
                       self.before['version'] == self.owner['source'] and
                       self.header['owners']['global'] == self.owner and
                       self.header['owners']['host']['owner'] == self.owner['owner'] and
                       self.header['owners']['host']['revision'] == self.owner['revision'] and
                       self.header['pending']['step'] == 'check_legacy_etcd' and
                       self.header['completed'] == ['cordon', 'drain'] and
                       hops.checksum(self.header['pending']['sha256']), 'legacy cycle binding differs')
        actors.require(self.hold.identity() == self.header['owners']['host']['identity'] and
                       private_json(self.hold.marker, security_receipt=True) == self.header['owners']['host'] and
                       self.confirm_owned() is True, 'legacy cycle ownership changed')
        # Ordinary Journal.read requires Ready; bind its already validated immutable chain instead.
        parent = self.hold.state / 'transactions'
        path = parent / self.owner['owner']
        hops.private_directory(parent);hops.private_directory(path)
        names = [str(index).zfill(8) + '.json' for index in range(6)]
        actors.require(self.header['records'] == 6 and
                       sorted(p.name for p in path.iterdir()) == names,
                       'legacy cycle original hop records changed')
        previous = None
        for index, name in enumerate(names):
            value = private_json(path / name)
            actors.require(value['sequence'] == index and value['previous'] == previous,
                           'legacy cycle original hop chain changed')
            if index == 0:
                actors.require(value['kind'] == 'header' and value['owners'] == self.header['owners'],
                               'legacy cycle original hop owner changed')
            previous = hops.digest(hops.canonical(value))
        actors.require(previous == self.header['head_sha256'] == self.header['pending']['sha256'] and
                       value['kind'] == 'intent' and value['step'] == 'check_legacy_etcd' and
                       self.header['pending']['sequence'] == 5,
                       'legacy cycle original pending hop changed')
        self.hold.guards(install=False)
        self.hold.systemd.idle(self.hold.marker)
        return True

    def initialize(self):
        with self.hold.serialized():
            self.guard()
            if not self.parent.exists():
                actors.safe(self.parent);self.parent.mkdir(mode=0o700);actors.fsync_directory(self.parent.parent)
            hops.private_directory(self.parent)
            actors.safe(self.path);self.path.mkdir(mode=0o700);actors.fsync_directory(self.parent)
            value = {'version': 1, 'owner': self.owner, 'hop': self.header, 'before': self.before}
            actors.exclusive_file(self.path / 'header.json', hops.canonical(value), 0o600)
            return self.read()

    def read(self):
        self.guard();hops.private_directory(self.parent);hops.private_directory(self.path)
        names = {p.name for p in self.path.iterdir()}
        expected = {'header.json', 'stop-intent.json', 'stopped.json', 'start-intent.json', 'source-returned.json'}
        actors.require('header.json' in names and names <= expected, 'foreign legacy cycle record')
        records = {name: private_json(self.path / name) for name in names}
        header = records['header.json']
        actors.require(header == {'version': 1, 'owner': self.owner, 'hop': self.header, 'before': self.before},
                       'original legacy cycle header changed')
        previous = hashlib.sha256(hops.canonical(header)).hexdigest()
        if 'stop-intent.json' in names:
            value = records['stop-intent.json']
            actors.require(value == {'header_sha256': previous, 'command': ['systemctl', 'stop', 'k3s']},
                           'legacy stop intent changed')
        actors.require(not (names - {'header.json', 'stop-intent.json'}) or 'stop-intent.json' in names,
                       'legacy stop intent missing')
        if 'stopped.json' in names:
            value = records['stopped.json']
            actors.require(value['stop_intent_sha256'] == hops.digest(hops.canonical(records['stop-intent.json'])) and
                           value['proof'].get('accepted') is True and value['proof']['source'] == self.owner['source'] and
                           value['proof']['original_identity'] == self.header['owners']['host']['identity'] and
                           value['proof']['original_boot'] == self.before['boot'], 'legacy stopped receipt changed')
        if 'start-intent.json' in names:
            actors.require('stopped.json' in names and records['start-intent.json'] == {
                'stopped_sha256': hops.digest(hops.canonical(records['stopped.json'])),
                'command': ['systemctl', 'start', 'k3s']}, 'legacy start intent changed')
        if 'source-returned.json' in names:
            actors.require('start-intent.json' in names and records['source-returned.json']['start_intent_sha256'] ==
                           hops.digest(hops.canonical(records['start-intent.json'])), 'legacy SOURCE return lacks intent')
            self.returned_runtime(records['source-returned.json']['runtime'])
        self.guard()
        return records

    def dispatch_stop(self, confirm_three_voters, source_runtime):
        with self.hold.serialized():
            state = self.read()
            actors.require(set(state) == {'header.json'} and confirm_three_voters() is True and
                           source_runtime() == self.before, 'legacy stop pending or prerequisites differ; observe only')
            self.guard()
            value = {'header_sha256': hops.digest(hops.canonical(state['header.json'])),
                     'command': ['systemctl', 'stop', 'k3s']}
            actors.exclusive_file(self.path / 'stop-intent.json', hops.canonical(value), 0o600)
            self.native(*value['command'])
            return {'dispatched_once': True, 'accepted': False}

    def observe_stopped(self):
        with self.hold.serialized():
            state = self.read()
            actors.require('stop-intent.json' in state and 'start-intent.json' not in state,
                           'legacy stopped observation lacks pending stop')
            proof = stopped.observe(self.native, self.before, self.header['owners']['host']['identity'], self.guard)
            value = {'stop_intent_sha256': hops.digest(hops.canonical(state['stop-intent.json'])), 'proof': proof}
            if 'stopped.json' not in state:
                actors.exclusive_file(self.path / 'stopped.json', hops.canonical(value), 0o600)
            actors.require(private_json(self.path / 'stopped.json') == value, 'stopped SOURCE proof changed')
            return proof

    def dispatch_start(self, confirm_two_voters):
        # Copy failure must not prevent this original SOURCE recovery path.
        with self.hold.serialized():
            state = self.read()
            actors.require('stopped.json' in state and 'start-intent.json' not in state and
                           confirm_two_voters() is True, 'legacy start pending or surviving quorum differs; observe only')
            proof = stopped.observe(self.native, self.before, self.header['owners']['host']['identity'], self.guard)
            actors.require(proof == state['stopped.json']['proof'], 'stopped SOURCE changed before start')
            value = {'stopped_sha256': hops.digest(hops.canonical(state['stopped.json'])),
                     'command': ['systemctl', 'start', 'k3s']}
            actors.exclusive_file(self.path / 'start-intent.json', hops.canonical(value), 0o600)
            self.native(*value['command'])
            return {'dispatched_once': True, 'accepted': False}

    def returned_runtime(self, value):
        actors.require(set(value) == set(self.before) and value['pid'] > 1 and value['pid'] != self.before['pid'] and
                       all(value[k] == v for k, v in self.before.items() if k != 'pid'),
                       'returned SOURCE runtime differs beyond its new PID')

    def observe_returned(self, source_runtime, confirm_three_voters):
        with self.hold.serialized():
            state = self.read()
            actors.require('start-intent.json' in state, 'legacy SOURCE start intent missing')
            runtime = source_runtime();self.returned_runtime(runtime)
            actors.require(confirm_three_voters() is True and source_runtime() == runtime,
                           'original three voters or SOURCE runtime not recovered')
            self.guard()
            value = {'start_intent_sha256': hops.digest(hops.canonical(state['start-intent.json'])), 'runtime': runtime}
            if 'source-returned.json' not in state:
                actors.exclusive_file(self.path / 'source-returned.json', hops.canonical(value), 0o600)
            actors.require(private_json(self.path / 'source-returned.json') == value, 'accepted SOURCE return changed')
            return value
