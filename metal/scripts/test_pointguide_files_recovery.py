"""Linux regressions use synthetic files only; never application credentials."""

import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pointguide_files_recovery as recovery


class CodexFilesRecovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = {'runtime': [{'processes': [{'pid': 2}]}]}
        self.profiles = patch.object(recovery, 'PROFILES', {'fixture': self.profile})
        self.profiles.start()
        self.addCleanup(self.profiles.stop)
        self.addCleanup(self.temporary.cleanup)

    def stream(self, root):
        tree, payloads = recovery.snapshot(root)
        value = {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID, 'profile': self.profile,
                 'tree': tree, 'pauses': [{'stopped_seconds': 0.25}], 'resumed': True}
        encoded = recovery.common.canonical(value)
        checksum = recovery.hashlib.sha256(encoded).hexdigest()
        wire = recovery.common.canonical({'manifest_bytes': len(encoded), 'sha256': checksum}) + b'\n'
        wire += encoded + b''.join(payloads[n] for n in sorted(payloads))
        wire += recovery.common.canonical({'commit': checksum}) + b'\n'
        return value, checksum, wire

    def test_full_metadata_links_and_independent_wal_recovery(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'directory').mkdir(mode=0o750)
        (source / 'directory/credential').write_bytes(b'synthetic credential only')
        (source / 'directory/empty').touch()
        os.setxattr(source / 'directory/credential', 'user.fixture', b'metadata')
        os.symlink('/never-read-external-target', source / 'external')
        os.symlink('directory', source / 'relative')
        connections = []
        try:
            for name in sorted(recovery.DATABASES):
                connection = sqlite3.connect(source / name)
                connections.append(connection)
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT, payload BLOB)')
                connection.execute('INSERT INTO records VALUES(7,?,?)', ('synthetic', b'\0\xff'))
                connection.commit()
                connection.execute('INSERT INTO records VALUES(8,?,NULL)', ('uncommitted',))
            value, checksum, wire = self.stream(source)
            point = self.root / 'protected'
            received = recovery.receive(io.BytesIO(wire), point, 'fixture')
            self.assertEqual(received['manifest_sha256'], checksum)
            self.assertFalse(any(p.is_symlink() for p in (point / 'data').iterdir()))
            copied = self.root / 'copy'
            recovery.materialize(point, copied, value)
            self.assertEqual(os.readlink(copied / 'external'), '/never-read-external-target')
            self.assertEqual(os.getxattr(copied / 'directory/credential', 'user.fixture'), b'metadata')
            accepted = recovery.restore(point, checksum, 'fixture')
            self.assertTrue(accepted['accepted'])
            self.assertTrue(accepted['cleanup']['scratch_absent'])
            self.assertTrue(all(r['rows'] == 1 for r in accepted['databases'].values()))
            self.assertFalse(list(self.root.glob('fixture-codex-restore-*')))
            first = next((point / 'data').iterdir())
            first.write_bytes(b'tamper')
            with self.assertRaises(RuntimeError):
                recovery.verify(point, checksum, 'fixture')
        finally:
            for connection in connections:
                connection.close()

    def test_missing_commit_truncation_and_trailing_data_refused(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'payload').write_bytes(b'owned synthetic payload')
        _, _, wire = self.stream(source)
        for number, broken in enumerate((wire[:-10], wire + b'extra')):
            with self.assertRaises(RuntimeError):
                recovery.receive(io.BytesIO(broken), self.root / str(number), 'fixture')
            self.assertFalse((self.root / str(number) / 'verified.json').exists())

    def test_link_descendants_and_noncanonical_paths_refused(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'file').write_bytes(b'fixture')
        value, _, _ = self.stream(source)
        for name in ('../escape', '/absolute', 'missing/file', 'file/child', 'a//b'):
            changed = json.loads(json.dumps(value))
            changed['tree'][name] = dict(changed['tree']['file'])
            with self.assertRaises(RuntimeError):
                recovery.validate(changed, 'fixture')
        changed = json.loads(json.dumps(value))
        changed['tree']['file'] = {**changed['tree'][''], 'kind': 'symlink', 'target': '/outside'}
        changed['tree']['file/child'] = dict(value['tree']['file'])
        with self.assertRaises(RuntimeError):
            recovery.validate(changed, 'fixture')

    def test_hardlinks_specials_and_changed_read_refused(self):
        source = self.root / 'source'
        source.mkdir()
        path = source / 'file'
        path.write_bytes(b'fixture')
        os.link(path, source / 'alias')
        with self.assertRaises(RuntimeError):
            recovery.inventory(source)
        (source / 'alias').unlink()
        real = recovery.process.file_identity
        with patch.object(recovery.process, 'file_identity', side_effect=[real(path), real(path), (0, 0, 0, 0, 0)]):
            with self.assertRaises(RuntimeError):
                recovery.read_payload(path)
        os.mkfifo(source / 'fifo')
        with self.assertRaises(RuntimeError):
            recovery.inventory(source)

    def test_restore_failure_cleans_only_scratch(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'credential').write_bytes(b'only synthetic')
        _, checksum, wire = self.stream(source)
        point = self.root / 'protected'
        recovery.receive(io.BytesIO(wire), point, 'fixture')
        with self.assertRaises(RuntimeError):
            recovery.restore(point, checksum, 'fixture')
        self.assertFalse(list(self.root.glob('fixture-codex-restore-*')))
        recovery.verify(point, checksum, 'fixture')

    def test_four_native_writers_resume_after_capture_failure(self):
        children = []
        try:
            for _ in range(4):
                child = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(3600)'],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
                children.append(child)
            identities = [recovery.process.process_identity(child.pid) for child in children]
            with self.assertRaisesRegex(RuntimeError, 'synthetic capture refusal'):
                with recovery.coordinated.stopped(identities, self.root / 'markers'):
                    self.assertTrue(all(all(state == 'T' for state in recovery.process.thread_states(p['pid']).values())
                                        for p in identities))
                    raise RuntimeError('synthetic capture refusal')
            self.assertTrue(all(recovery.process.process_identity(p['pid']) == p and all(
                state not in ('T', 't') for state in recovery.process.thread_states(p['pid']).values())
                for p in identities))
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
            self.assertTrue(all(child.poll() is not None for child in children))


if __name__ == '__main__':
    unittest.main()
