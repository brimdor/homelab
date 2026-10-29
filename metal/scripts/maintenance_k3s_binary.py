"""One journaled K3s binary replacement; uncertain activation is observation only."""

import base64
import hashlib
import os
from pathlib import Path
import stat
import urllib.request

import maintenance_actor_hold as actor
import maintenance_hop_journal as hops
import maintenance_k3s_contract as contract
from maintenance_node_drain import hashed, private_json


def record(path):
    actor.safe(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        actor.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                      before.st_nlink == 1 and not before.st_mode & 0o022,
                      'unsafe K3s executable')
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1048576), b''):
            digest.update(chunk)
        attributes = {key: base64.b64encode(os.getxattr(source.fileno(), key)).decode()
                      for key in os.listxattr(source.fileno())}
        actor.require(not {'security.ima', 'security.evm'}.intersection(attributes),
                      'K3s executable has a separate integrity signature')
        after = os.fstat(source.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    actor.require(identity(before) == identity(after), 'K3s executable changed while reading')
    return {'sha256': digest.hexdigest(), 'size': before.st_size,
            'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid, 'gid': before.st_gid,
            'xattrs': attributes}


def copy_executable(source, destination, metadata):
    """Exclusive destination; preserve executable metadata, not a stale integrity signature."""
    actor.safe(source);actor.safe(destination)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as target, source.open('rb') as origin:
        for chunk in iter(lambda: origin.read(1048576), b''):
            target.write(chunk)
        target.flush()
        # Do not use chown as an unprivileged synthetic test process.
        info = os.fstat(target.fileno())
        if (info.st_uid, info.st_gid) != (metadata['uid'], metadata['gid']):
            os.fchown(target.fileno(), metadata['uid'], metadata['gid'])
        os.fchmod(target.fileno(), metadata['mode'])
        for key in os.listxattr(target.fileno()):
            if key not in metadata['xattrs']:
                os.removexattr(target.fileno(), key)
        for key, value in metadata['xattrs'].items():
            os.setxattr(target.fileno(), key, base64.b64decode(value, validate=True))
        os.fsync(target.fileno())
    actor.fsync_directory(destination.parent)


def download(version, destination):
    actor.require(version in contract.SHA256, 'unreviewed K3s artifact')
    from urllib.parse import quote
    url = 'https://github.com/k3s-io/k3s/releases/download/' + quote(version, safe='') + '/k3s'
    with urllib.request.urlopen(url, timeout=60) as response, destination.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        for chunk in iter(lambda: response.read(1048576), b''):
            output.write(chunk)
        output.flush();os.fsync(output.fileno())
    actor.require(hashlib.sha256(destination.read_bytes()).hexdigest() == contract.SHA256[version],
                  'official K3s binary checksum differs')
    actor.fsync_directory(destination.parent)


class Binary:
    def __init__(self, journal, native, executable=Path('/usr/local/bin/k3s')):
        self.journal, self.native, self.executable = journal, native, Path(executable)
        self.parent = journal.hold.state / 'k3s-binaries'
        self.path = self.parent / journal.token
        self.stage = self.executable.parent / ('.k3s-' + journal.token)

    def owner(self):
        value = self.journal.owners(idle=True)['global']
        actor.require(value.get('component') == 'k3s' and
                      contract.reviewed(value['source'], value['target']), 'K3s binary owner differs')
        return value

    def prepared(self):
        hops.private_directory(self.parent);hops.private_directory(self.path)
        value = private_json(self.path / 'prepared.json')
        owner = self.owner()
        actor.require(value['owner'] == owner and value['executable'] == str(self.executable) and
                      value['original']['sha256'] == contract.SHA256[owner['source']] and
                      value['candidate']['sha256'] == contract.SHA256[owner['target']] and
                      record(self.path / 'original') == value['original'] and
                      record(self.path / 'candidate') == value['candidate'],
                      'prepared K3s artifact or original backup differs')
        actor.require({k: value['original'][k] for k in ('mode', 'uid', 'gid', 'xattrs')} ==
                      {k: value['candidate'][k] for k in ('mode', 'uid', 'gid', 'xattrs')},
                      'candidate executable metadata differs')
        return value

    def prepare(self, prerequisites_sha256, verify_prerequisites, fetch=download):
        owner = self.owner();original = record(self.executable)
        actor.require(original['sha256'] == contract.SHA256[owner['source']] and original['mode'] == 0o755,
                      'source K3s binary or executable mode differs')
        plan = {'owner': owner, 'executable': str(self.executable), 'original': original,
                'target_sha256': contract.SHA256[owner['target']]}
        state = self.journal.begin('prepare_binary', hashed(plan), prerequisites_sha256, verify_prerequisites)
        with self.journal.hold.serialized():
            self.journal.owners(idle=True)
            actor.require(record(self.executable) == original, 'source executable changed before preparation')
            if not self.parent.exists():
                actor.safe(self.parent);self.parent.mkdir(mode=0o700);actor.fsync_directory(self.parent.parent)
            hops.private_directory(self.parent)
            actor.safe(self.path);self.path.mkdir(mode=0o700);actor.fsync_directory(self.parent)
            copy_executable(self.executable, self.path / 'original', original)
            fetched = self.path / 'download'
            fetch(owner['target'], fetched)
            actor.require(record(fetched)['sha256'] == contract.SHA256[owner['target']], 'candidate checksum differs')
            copy_executable(fetched, self.path / 'candidate', original)
            candidate = record(self.path / 'candidate')
            actor.require(candidate['sha256'] == contract.SHA256[owner['target']], 'prepared checksum differs')
            # The extra downloaded copy is not original recovery material.
            fetched.unlink();actor.fsync_directory(self.path)
            value = {'owner': owner, 'executable': str(self.executable),
                     'original': original, 'candidate': candidate}
            actor.exclusive_file(self.path / 'prepared.json', hops.canonical(value), 0o600)
            actor.require(self.prepared() == value and record(self.executable) == original,
                          'preparation altered the installed executable')
        self.journal.accept(state['pending']['sha256'], hashed(value),
                            lambda step, digest: step == 'prepare_binary' and digest == hashed(self.prepared()))
        return value

    def activate(self, prerequisites_sha256, verify_prerequisites):
        value = self.prepared()
        actor.require(record(self.executable) == value['original'], 'installed source differs before activation')
        pid = int(self.native('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value'))
        actor.require(pid > 1 and self.native('systemctl', 'show', 'k3s', '-p', 'KillMode', '--value') == 'process',
                      'existing K3s service cannot preserve containers')
        plan = {'prepared_sha256': hashed(value), 'source_pid': pid, 'stage': str(self.stage)}
        state = self.journal.begin('activate_binary', hashed(plan), prerequisites_sha256, verify_prerequisites)
        with self.journal.hold.serialized():
            self.journal.owners(idle=True)
            actor.require(record(self.executable) == value['original'] and self.prepared() == value,
                          'K3s source or candidate changed before atomic replacement')
            actor.exclusive_file(self.path / 'activation.json', hops.canonical(plan), 0o600)
            copy_executable(self.path / 'candidate', self.stage, value['candidate'])
            actor.require(record(self.stage) == value['candidate'], 'same-filesystem candidate differs')
            actor.require(verify_prerequisites('activate_binary', prerequisites_sha256) is True,
                          'K3s activation prerequisites changed')
            actor.require(record(self.executable) == value['original'] and
                          int(self.native('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value')) == pid,
                          'installed K3s source or service changed before replacement')
            os.replace(self.stage, self.executable);actor.fsync_directory(self.executable.parent)
            actor.require(record(self.executable) == value['candidate'], 'atomic replacement differs')
            # Existing unit only; KillMode=process preserves container shims and workloads.
            self.native('systemctl', 'restart', 'k3s')
        return {'pending': state['pending'], 'activation': plan, 'accepted': False}

    def observe(self, verify_runtime):
        """No replacement or restart here, even after an interrupted first dispatch."""
        value = self.prepared();state = self.journal.inspect()
        actor.require(state['pending'] and state['pending']['step'] == 'activate_binary',
                      'exact pending K3s activation missing')
        plan = private_json(self.path / 'activation.json')
        intent = private_json(self.journal.path / (str(state['pending']['sequence']).zfill(8) + '.json'))
        actor.require(intent['inputs_sha256'] == hashed(plan) and plan['prepared_sha256'] == hashed(value) and
                      record(self.executable) == value['candidate'] and not self.stage.exists(),
                      'uncertain activation requires native diagnosis; never replay')
        pid = int(self.native('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value'))
        actor.require(pid > 1 and pid != plan['source_pid'] and
                      self.native('systemctl', 'is-active', 'k3s') == 'active', 'K3s restart not observed')
        receipt = verify_runtime(value['owner'], pid)
        actor.require(isinstance(receipt, dict) and receipt.get('accepted') is True,
                      'native K3s runtime acceptance refused')
        self.journal.accept(state['pending']['sha256'], hashed(receipt),
                            lambda step, digest: step == 'activate_binary' and digest == hashed(receipt) and
                            record(self.executable) == value['candidate'] and
                            verify_runtime(value['owner'], pid) == receipt)
        return receipt
