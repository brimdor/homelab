"""Real temporary files and journal interruption tests; no production operation."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_actor_hold as actors
import maintenance_hop_journal as hops
import maintenance_k3s_binary as binary
import maintenance_k3s_contract as contract
from test_maintenance_actor_hold import IDENTITY, Systemd
from test_maintenance_coordination import API


class K3sBinaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # macOS Python lacks the Linux fd-xattr API. These local tests exercise
        # native file/journal operations; actual SELinux/xattrs need Linux acceptance.
        if not hasattr(os, 'listxattr'):
            for name, function in (('listxattr', lambda _fd: []),
                                   ('getxattr', lambda *_: b''),
                                   ('setxattr', lambda *_: None),
                                   ('removexattr', lambda *_: None)):
                replacement = patch.object(binary.os, name, function, create=True)
                replacement.start();self.addCleanup(replacement.stop)
        self.api = API()
        self.source, self.target = contract.VERSIONS[:2]
        self.owner = self.api.controller().acquire('fixture-a', self.source, self.target,
                                                    'a' * 40, component='k3s')
        units = self.root / 'units';units.mkdir()
        hold = actors.Hold(Systemd(), lambda: dict(IDENTITY),
                           lambda token: self.api.controller().resume(token) == self.owner,
                           self.root / 'state', units)
        hold.acquire(self.owner['owner'], IDENTITY, 'a' * 40)
        self.journal = hops.Journal(self.api.controller(), hold, self.owner['owner'])
        self.journal.initialize()
        for step in ('cordon', 'drain'):
            state = self.journal.begin(step, 'b' * 64, 'c' * 64, lambda *_: True)
            self.journal.accept(state['pending']['sha256'], 'd' * 64, lambda *_: True)
        self.executable = self.root / 'k3s'
        self.old, self.new = b'old official fixture executable', b'new official fixture executable'
        self.executable.write_bytes(self.old);self.executable.chmod(0o755)
        hashes = {self.source: hashlib.sha256(self.old).hexdigest(),
                  self.target: hashlib.sha256(self.new).hexdigest()}
        self.hash_patch = patch.dict(contract.SHA256, hashes)
        self.hash_patch.start();self.addCleanup(self.hash_patch.stop)
        self.pid, self.restarts = 100, 0
        self.interrupt_restart = False
        self.worker = binary.Binary(self.journal, self.native, self.executable)

    def native(self, *argv):
        if argv == ('systemctl', 'show', 'k3s', '-p', 'MainPID', '--value'):
            return str(self.pid)
        if argv == ('systemctl', 'show', 'k3s', '-p', 'KillMode', '--value'):
            return 'process'
        if argv == ('systemctl', 'is-active', 'k3s'):
            return 'active'
        if argv == ('systemctl', 'restart', 'k3s'):
            self.restarts += 1;self.pid += 1
            if self.interrupt_restart:
                raise RuntimeError('lost restart response')
            return ''
        raise AssertionError(argv)

    def fetch(self, version, destination):
        self.assertEqual(version, self.target)
        destination.write_bytes(self.new);destination.chmod(0o600)

    def prepare(self):
        return self.worker.prepare('c' * 64, lambda *_: True, self.fetch)

    def runtime(self, owner, pid):
        self.assertEqual(owner, self.owner)
        self.assertEqual(pid, 101)
        return {'accepted': True, 'pid': pid, 'version': self.target}

    def test_preserves_original_and_metadata_then_replaces_atomically(self):
        before = binary.record(self.executable)
        prepared = self.prepare()
        self.assertEqual(binary.record(self.executable), before)
        self.assertEqual((self.worker.path / 'original').read_bytes(), self.old)
        self.assertEqual(prepared['original']['mode'], prepared['candidate']['mode'])
        self.assertEqual(prepared['original']['xattrs'], prepared['candidate']['xattrs'])
        self.worker.activate('c' * 64, lambda *_: True)
        self.assertEqual(self.executable.read_bytes(), self.new)
        self.assertEqual(self.restarts, 1)
        self.worker.observe(self.runtime)
        self.assertEqual(self.journal.inspect()['completed'][-1], 'activate_binary')
        self.assertIsNone(self.journal.inspect()['pending'])
        self.assertEqual((self.worker.path / 'original').read_bytes(), self.old)

    def test_lost_restart_response_observes_without_second_restart(self):
        self.prepare();self.interrupt_restart = True
        with self.assertRaisesRegex(RuntimeError, 'lost restart response'):
            self.worker.activate('c' * 64, lambda *_: True)
        with self.assertRaises(RuntimeError):
            self.worker.activate('c' * 64, lambda *_: True)
        fresh = binary.Binary(self.journal, self.native, self.executable)
        fresh.observe(self.runtime)
        self.assertEqual(self.restarts, 1)

    def test_interrupted_replace_retains_source_pending_intent_and_never_restarts(self):
        self.prepare()
        with patch.object(binary.os, 'replace', side_effect=OSError('replace refused')):
            with self.assertRaisesRegex(OSError, 'replace refused'):
                self.worker.activate('c' * 64, lambda *_: True)
        self.assertEqual(self.executable.read_bytes(), self.old)
        self.assertEqual(self.restarts, 0)
        self.assertEqual(self.journal.inspect()['pending']['step'], 'activate_binary')
        with self.assertRaisesRegex(RuntimeError, 'never replay'):
            self.worker.observe(self.runtime)
        self.assertEqual(self.restarts, 0)

    def test_wrong_download_or_changed_original_never_activates(self):
        def corrupt(_version, destination):
            destination.write_bytes(b'wrong');destination.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            self.worker.prepare('c' * 64, lambda *_: True, corrupt)
        self.assertEqual(self.executable.read_bytes(), self.old)
        self.assertEqual(self.restarts, 0)
        self.assertEqual(self.journal.inspect()['pending']['step'], 'prepare_binary')

    def test_refuses_metadata_tampering_symlink_and_runtime_refusal(self):
        self.prepare()
        original = self.worker.path / 'original';original.chmod(0o700)
        with self.assertRaisesRegex(RuntimeError, 'backup differs'):
            self.worker.activate('c' * 64, lambda *_: True)
        original.chmod(0o755)
        self.worker.activate('c' * 64, lambda *_: True)
        with self.assertRaisesRegex(RuntimeError, 'runtime acceptance'):
            self.worker.observe(lambda *_: {'accepted': False})
        self.assertEqual(self.journal.inspect()['pending']['step'], 'activate_binary')
        link = self.root / 'link';link.symlink_to(self.executable)
        with self.assertRaisesRegex(RuntimeError, 'unsafe actor'):
            binary.record(link)
        self.assertEqual(self.restarts, 1)

    def test_integrity_signed_binary_requires_its_own_supported_plan(self):
        with patch.object(binary.os, 'listxattr', return_value=['security.ima']), \
                patch.object(binary.os, 'getxattr', return_value=b'fixture-signature'):
            with self.assertRaisesRegex(RuntimeError, 'integrity signature'):
                binary.record(self.executable)
        self.assertEqual(self.restarts, 0)

    def test_source_mode_change_refuses_before_preparation_intent(self):
        self.executable.chmod(0o4755)
        before = self.journal.inspect()
        with self.assertRaisesRegex(RuntimeError, 'executable mode'):
            self.prepare()
        self.assertEqual(self.journal.inspect(), before)
        self.assertEqual(self.restarts, 0)

    def test_native_linux_user_xattr_survives_backup_and_candidate(self):
        if not hasattr(os, 'uname') or os.uname().sysname != 'Linux':
            self.skipTest('Linux fd-xattr native acceptance runs separately before production')
        os.setxattr(self.executable, 'user.maintenance-fixture', b'fixture-value')
        value = self.prepare()
        self.assertEqual(os.getxattr(self.worker.path / 'original', 'user.maintenance-fixture'), b'fixture-value')
        self.assertEqual(os.getxattr(self.worker.path / 'candidate', 'user.maintenance-fixture'), b'fixture-value')
        self.assertEqual(value['original']['xattrs'], value['candidate']['xattrs'])


if __name__ == '__main__':
    unittest.main()
