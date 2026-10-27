"""Durable one-hop intent/acceptance records; never execute or replay an operation."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat

import maintenance_actor_hold as actor
import maintenance_coordination as global_owner


STEPS = ('cordon', 'drain', 'prepare_source', 'download_release', 'offline_transaction',
         'trusted_reconnect', 'verify_infrastructure', 'restore_scheduling', 'accept_applications')
SECURITY_STEPS = ('cordon', 'drain', 'security_default', 'trusted_reconnect',
                  'verify_infrastructure', 'restore_scheduling', 'accept_applications')


def steps(owner):
    if owner['source'] == owner['target'] == 44:
        actor.require(owner['node'] == 'totodile', 'unreviewed security follow-up node')
        return SECURITY_STEPS
    return STEPS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checksum(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def canonical(value):
    return global_owner.encoded(value).encode()


def private_directory(path):
    actor.safe(path)
    value = path.stat()
    actor.require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.geteuid() and
                  stat.S_IMODE(value.st_mode) == 0o700, 'unsafe hop journal directory')


class Journal:
    def __init__(self, ownership, hold, token):
        actor.require(isinstance(token, str) and re.fullmatch(
            r'homelab-maintenance-103-[0-9a-f-]{36}', token), 'invalid hop owner')
        self.ownership, self.hold, self.token = ownership, hold, token
        self.parent = hold.state / 'transactions'
        self.path = self.parent / token

    def owners(self, idle=False):
        owner = self.ownership.resume(self.token)
        host = self.hold.observed(self.token)
        actor.require(host['revision'] == owner['revision'], 'global and host revisions differ')
        self.hold.guards(install=False)
        if idle:
            self.hold.systemd.idle(self.hold.marker)
        return {'global': owner, 'host': host}

    def initialize(self):
        with self.hold.serialized():
            owners = self.owners(idle=True)
            if not self.parent.exists():
                actor.safe(self.parent)
                self.parent.mkdir(mode=0o700)
                actor.fsync_directory(self.parent.parent)
            private_directory(self.parent)
            actor.safe(self.path)
            self.path.mkdir(mode=0o700)
            actor.fsync_directory(self.parent)
            record = {'version': 1, 'sequence': 0, 'previous': None,
                      'kind': 'header', 'owners': owners}
            self.append(record)
            return self.read()

    def append(self, record):
        # Immutable link creation plus fsync is shared with the qualified actor journal.
        path = self.path / (str(record['sequence']).zfill(8) + '.json')
        actor.exclusive_file(path, canonical(record), 0o600)

    def read(self):
        owners = self.owners()
        sequence = steps(owners['global'])
        private_directory(self.parent)
        private_directory(self.path)
        names = sorted(p.name for p in self.path.iterdir())
        actor.require(names and len(names) <= 1 + len(sequence) * 2 and names == [
            str(i).zfill(8) + '.json' for i in range(len(names))], 'incomplete or foreign hop records')
        previous, pending, completed = None, None, []
        for index, name in enumerate(names):
            path = self.path / name
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as source:
                before = os.fstat(source.fileno())
                actor.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                              before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600 and
                              0 < before.st_size < 65536, 'unsafe hop record')
                raw = source.read()
                after = os.fstat(source.fileno())
                actor.require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                               before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                               after.st_mtime_ns, after.st_ctime_ns), 'hop record changed during read')
            record = json.loads(raw)
            actor.require(isinstance(record, dict) and raw == canonical(record) and
                          type(record.get('version')) is int and record['version'] == 1 and
                          type(record.get('sequence')) is int and record['sequence'] == index and
                          record.get('previous') == previous, 'hop sequence or hash chain changed')
            base = {'version', 'sequence', 'previous', 'kind'}
            if index == 0:
                actor.require(set(record) == base | {'owners'} and record['kind'] == 'header' and
                              record['owners'] == owners, 'hop owner or header differs')
            elif record.get('kind') == 'intent':
                actor.require(set(record) == base | {'step', 'inputs_sha256', 'prerequisites_sha256'} and
                              pending is None and len(completed) < len(sequence) and
                              record['step'] == sequence[len(completed)] and
                              checksum(record['inputs_sha256']) and checksum(record['prerequisites_sha256']),
                              'invalid or overlapping hop intent')
                pending = {'step': record['step'], 'sha256': digest(raw), 'sequence': index}
            elif record.get('kind') == 'accepted':
                actor.require(set(record) == base | {'step', 'intent_sha256', 'receipt_sha256'} and
                              pending is not None and record['step'] == pending['step'] and
                              record['intent_sha256'] == pending['sha256'] and checksum(record['receipt_sha256']),
                              'hop acceptance lacks exact pending intent')
                completed.append(record['step'])
                pending = None
            else:
                raise RuntimeError('invalid hop record kind')
            previous = digest(raw)
        actor.require(self.owners() == owners, 'hop ownership changed during read')
        return {'owners': owners, 'records': len(names), 'head_sha256': previous,
                'pending': pending, 'completed': completed}

    def inspect(self):
        with self.hold.serialized():
            return self.read()

    def begin(self, step, inputs_sha256, prerequisites_sha256, verify_prerequisites):
        sequence = steps(self.owners()['global'])
        actor.require(step in sequence and checksum(inputs_sha256) and checksum(prerequisites_sha256),
                      'unreviewed hop step or evidence digest')
        with self.hold.serialized():
            state = self.read()
            actor.require(state['pending'] is None and len(state['completed']) < len(sequence) and
                          step == sequence[len(state['completed'])], 'pending or out-of-order hop; observe, never replay')
            self.owners(idle=True)
            actor.require(verify_prerequisites(step, prerequisites_sha256) is True,
                          'hop prerequisite evidence refused')
            actor.require(self.read() == state, 'hop changed during prerequisite verification')
            self.append({'version': 1, 'sequence': state['records'], 'previous': state['head_sha256'],
                         'kind': 'intent', 'step': step, 'inputs_sha256': inputs_sha256,
                         'prerequisites_sha256': prerequisites_sha256})
            return self.read()

    def accept(self, intent_sha256, receipt_sha256, verify_observed):
        actor.require(checksum(intent_sha256) and checksum(receipt_sha256), 'invalid hop acceptance digest')
        with self.hold.serialized():
            state = self.read()
            pending = state['pending']
            actor.require(pending is not None and pending['sha256'] == intent_sha256,
                          'exact pending hop intent missing')
            actor.require(verify_observed(pending['step'], receipt_sha256) is True,
                          'observed hop result refused; retain pending intent')
            self.owners(idle=True)
            actor.require(self.read() == state, 'hop changed during acceptance verification')
            self.append({'version': 1, 'sequence': state['records'], 'previous': state['head_sha256'],
                         'kind': 'accepted', 'step': pending['step'], 'intent_sha256': intent_sha256,
                         'receipt_sha256': receipt_sha256})
            return self.read()
