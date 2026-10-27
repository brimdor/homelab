"""Explicit ordered owner release; interrupted intents permit observation only."""

import copy

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
from maintenance_node_drain import hashed, private_json


KINDS = ('header', 'host-intent', 'host-accepted', 'global-intent', 'global-accepted')


class Release:
    def __init__(self, journal):
        self.journal, self.hold, self.ownership = journal, journal.hold, journal.ownership
        self.parent = self.hold.state / 'releases'
        self.path = self.parent / journal.token

    def prepare(self, evidence_sha256, verify_safe):
        actors.require(hops.checksum(evidence_sha256), 'invalid release evidence digest')
        with self.hold.serialized():
            state = self.journal.read()
            actors.require(state['pending'] is None and state['completed'] == list(hops.steps(state['owners']['global'])),
                           'release requires every accepted hop step')
            self.journal.owners(idle=True)
            files = {p.name: hashed(private_json(p)) for p in sorted(self.journal.path.iterdir())}
            header = {'version': 1, 'sequence': 0, 'previous': None, 'kind': 'header',
                      'owners': state['owners'], 'hop_records': files,
                      'hop_head_sha256': state['head_sha256'], 'evidence_sha256': evidence_sha256}
            actors.require(verify_safe(copy.deepcopy(header), evidence_sha256) is True,
                           'current safe release evidence refused')
            actors.require(self.journal.read() == state, 'hop changed during release preparation')
            self.journal.owners(idle=True)
            if not self.parent.exists():
                actors.safe(self.parent);self.parent.mkdir(mode=0o700);actors.fsync_directory(self.parent.parent)
            hops.private_directory(self.parent)
            actors.safe(self.path);self.path.mkdir(mode=0o700);actors.fsync_directory(self.parent)
            actors.exclusive_file(self.path / '00000000.json', hops.canonical(header), 0o600)
            return self.read()

    def read(self):
        hops.private_directory(self.parent);hops.private_directory(self.path)
        names = sorted(p.name for p in self.path.iterdir())
        actors.require(0 < len(names) <= len(KINDS) and names == [
            str(i).zfill(8) + '.json' for i in range(len(names))], 'incomplete or foreign release records')
        previous, header = None, None
        for index, filename in enumerate(names):
            record = private_json(self.path / filename)
            fields = {'version', 'sequence', 'previous', 'kind', 'evidence_sha256'}
            if index == 0:fields |= {'owners', 'hop_records', 'hop_head_sha256'}
            actors.require(set(record) == fields and type(record['version']) is int and
                           record['version'] == 1 and type(record['sequence']) is int and
                           record['sequence'] == index and record['previous'] == previous and
                           record['kind'] == KINDS[index] and hops.checksum(record['evidence_sha256']),
                           'release record order, schema or hash chain differs')
            if index == 0:header = record
            previous = hashed(record)
        actors.require(header['owners']['global']['owner'] == self.journal.token and
                       header['owners']['host']['owner'] == self.journal.token and
                       header['owners']['host']['revision'] == header['owners']['global']['revision'] and
                       self.hold.identity() == header['owners']['host']['identity'],
                       'release original owner or host identity differs')
        hops.private_directory(self.journal.parent);hops.private_directory(self.journal.path)
        files = header['hop_records']
        expected = [str(i).zfill(8) + '.json' for i in range(1 + 2 * len(hops.steps(header['owners']['global'])))]
        actors.require(isinstance(files, dict) and sorted(files) == expected and
                       sorted(p.name for p in self.journal.path.iterdir()) == expected,
                       'original complete hop files differ')
        for filename in expected:
            actors.require(hops.checksum(files[filename]) and
                           hashed(private_json(self.journal.path / filename)) == files[filename],
                           'original hop record changed after release preparation')
        original = private_json(self.journal.path / expected[0])
        actors.require(original['owners'] == header['owners'] and
                       files[expected[-1]] == header['hop_head_sha256'], 'release hop binding differs')
        self.hold.guards(install=False)
        return {'header': header, 'kinds': list(KINDS[:len(names)]), 'head_sha256': previous}

    def host_held(self, header):
        actors.safe(self.hold.marker)
        self.hold.systemd.idle(self.hold.marker)
        if self.hold.marker.exists():
            actors.require(self.hold.observed(self.journal.token) == header['owners']['host'],
                           'host release owner differs')
            return True
        return False

    def global_held(self, header):
        ds = self.ownership.observed()
        annotations = ds['metadata'].get('annotations', {})
        if coordination.LOCK not in annotations and coordination.JOURNAL not in annotations:
            return False
        saved_window = header['owners']['global'].get('restore_window_lock')
        if (coordination.JOURNAL not in annotations and saved_window is not None and
                annotations.get(coordination.LOCK) == coordination.encoded(saved_window)):
            return False
        actors.require(self.ownership.resume(self.journal.token) == header['owners']['global'],
                       'global release owner differs')
        return True

    def verified(self, state, evidence_sha256, verify_safe):
        actors.require(hops.checksum(evidence_sha256) and
                       verify_safe(copy.deepcopy(state['header']), evidence_sha256) is True,
                       'current safe release evidence refused')
        actors.require(self.read() == state, 'release state changed during verification')
        return True

    def append(self, state, kind, evidence_sha256):
        index = len(state['kinds'])
        actors.require(index < len(KINDS) and kind == KINDS[index], 'out-of-order release action')
        actors.exclusive_file(self.path / (str(index).zfill(8) + '.json'), hops.canonical({
            'version': 1, 'sequence': index, 'previous': state['head_sha256'], 'kind': kind,
            'evidence_sha256': evidence_sha256}), 0o600)

    def release_host(self, evidence_sha256, verify_safe):
        with self.hold.serialized():
            state = self.read();header = state['header']
            actors.require(state['kinds'] == ['header'] and self.global_held(header) and self.host_held(header),
                           'host release is pending, completed or ownership differs; observe only')
            self.verified(state, evidence_sha256, verify_safe)
            actors.require(self.global_held(header) and self.host_held(header), 'release ownership changed')
            self.append(state, 'host-intent', evidence_sha256)
        def verify(value):
            pending = self.read()
            return (value == header['owners']['host'] and pending['kinds'] == list(KINDS[:2]) and
                    self.verified(pending, evidence_sha256, verify_safe) and self.global_held(header))
        self.hold.release(self.journal.token, verify)
        return self.observe(evidence_sha256, verify_safe)

    def release_global(self, evidence_sha256, verify_safe):
        with self.hold.serialized():
            state = self.read();header = state['header']
            actors.require(state['kinds'] == list(KINDS[:3]) and not self.host_held(header) and
                           self.global_held(header), 'global release requires accepted host release; observe only')
            self.verified(state, evidence_sha256, verify_safe)
            actors.require(not self.host_held(header) and self.global_held(header), 'release ownership changed')
            self.append(state, 'global-intent', evidence_sha256)
            def verify(value):
                pending = self.read()
                return (value == header['owners']['global'] and pending['kinds'] == list(KINDS[:4]) and
                        self.verified(pending, evidence_sha256, verify_safe) and not self.host_held(header))
            self.ownership.release(self.journal.token, verify)
        return self.observe(evidence_sha256, verify_safe)

    def observe(self, evidence_sha256, verify_safe):
        with self.hold.serialized():
            state = self.read();header = state['header'];count = len(state['kinds'])
            host, global_owner = self.host_held(header), self.global_held(header)
            if count in (1, 2):
                actors.require(global_owner, 'global owner disappeared before accepted host release')
                if count == 1:actors.require(host, 'host marker disappeared without release intent')
                if count == 2 and not host:
                    self.verified(state, evidence_sha256, verify_safe)
                    actors.require(not self.host_held(header) and self.global_held(header), 'release observation changed')
                    self.append(state, 'host-accepted', evidence_sha256)
            else:
                actors.require(not host, 'released host marker returned')
                if count == 3:actors.require(global_owner, 'global owner disappeared without release intent')
                if count == 4 and not global_owner:
                    self.verified(state, evidence_sha256, verify_safe)
                    actors.require(not self.host_held(header) and not self.global_held(header), 'release observation changed')
                    self.append(state, 'global-accepted', evidence_sha256)
                if count == 5:
                    actors.require(not global_owner, 'released global owner returned')
                    self.verified(state, evidence_sha256, verify_safe)
            after = self.read()
            return {'complete': after['kinds'] == list(KINDS), 'state': after,
                    'mutation_replayed': False}
