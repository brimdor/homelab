import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import maintenance_etcd_legacy as legacy


class LegacyCopyTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(os, 'listxattr'):
            # macOS Python lacks this Linux API; native attribute coverage is a separate test.
            patcher = mock.patch.object(legacy, 'attributes', return_value={})
            patcher.start();self.addCleanup(patcher.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'protected'
        self.scratch = self.root / 'scratch'
        for directory in (self.source, self.scratch, self.source / 'member',
                          self.source / 'member/snap', self.source / 'member/wal'):
            directory.mkdir(mode=0o700)
        self.db = self.source / 'member/snap/db'
        self.wal = self.source / 'member/wal/0000000000000000-0000000000000001.wal'
        self.preallocated = self.source / 'member/wal/0.tmp'
        for path, value in ((self.db, b'synthetic-db'), (self.wal, b'synthetic-wal'),
                            (self.preallocated, b'synthetic-preallocation')):
            path.write_bytes(value);path.chmod(0o600)
        snapshot = self.source / 'member/snap/0000000000000001-0000000000000001.snap'
        snapshot.write_bytes(b'synthetic-snapshot');snapshot.chmod(0o644)
        self.tool = self.root / 'etcdutl'
        self.tool.write_bytes(b'synthetic-checker');self.tool.chmod(0o500)

    def check(self, run, native=lambda *args: 'ext4'):
        with mock.patch.object(legacy, 'BINARY_SHA256', hashlib.sha256(self.tool.read_bytes()).hexdigest()), \
                mock.patch.object(legacy, 'BINARY_BYTES', self.tool.stat().st_size):
            return legacy.check_copy(self.source, legacy.member_manifest(self.source),
                                     self.tool, self.scratch, native, run)

    def test_manifest_and_copy_preserve_every_file_and_original(self):
        before = legacy.member_manifest(self.source)
        destination = self.root / 'copy'
        legacy.copy_member(self.source, destination, before)
        self.assertEqual(legacy.member_manifest(self.source), before)
        self.assertEqual(legacy.contents(legacy.member_manifest(destination)), legacy.contents(before))
        self.assertEqual((destination / 'member/wal/0.tmp').read_bytes(), self.preallocated.read_bytes())
        self.assertIn('xattrs', before['entries']['member/snap/db'])

    @unittest.skipUnless(hasattr(os, 'listxattr'), 'Linux native xattr API required')
    def test_native_original_attribute_changes_are_detected(self):
        os.setxattr(self.db, 'user.maintenance-legacy-test', b'original')
        before = legacy.member_manifest(self.source)
        os.setxattr(self.db, 'user.maintenance-legacy-test', b'changed')
        with self.assertRaisesRegex(RuntimeError, 'changed before copy'):
            legacy.copy_member(self.source, self.root / 'copy', before)

    def test_missing_database_or_wal_and_empty_files_refuse(self):
        for path, missing in ((self.db, True), (self.wal, True), (self.db, False), (self.wal, False)):
            with self.subTest(path=path.name, missing=missing):
                content = path.read_bytes()
                if missing:
                    path.unlink()
                else:
                    path.write_bytes(b'')
                with self.assertRaises((RuntimeError, FileNotFoundError)):
                    legacy.member_manifest(self.source)
                path.write_bytes(content);path.chmod(0o600)

    def test_unsafe_symlink_hardlink_special_file_and_mode_refuse(self):
        extra = self.source / 'member/snap/unsafe'
        for kind in ('symlink', 'hardlink', 'fifo', 'writable'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    extra.symlink_to(self.db)
                elif kind == 'hardlink':
                    os.link(self.db, extra)
                elif kind == 'fifo':
                    os.mkfifo(extra, 0o600)
                else:
                    extra.write_bytes(b'unsafe');extra.chmod(0o666)
                with self.assertRaises(RuntimeError):
                    legacy.member_manifest(self.source)
                extra.unlink()

    def test_changed_source_refuses_before_creating_copy(self):
        before = legacy.member_manifest(self.source)
        self.db.write_bytes(b'changed')
        destination = self.root / 'copy'
        with self.assertRaisesRegex(RuntimeError, 'changed before copy'):
            legacy.copy_member(self.source, destination, before)
        self.assertFalse(destination.exists())

    def test_existing_destination_is_never_overwritten(self):
        destination = self.root / 'copy';destination.mkdir(mode=0o700)
        sentinel = destination / 'keep';sentinel.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            legacy.copy_member(self.source, destination, legacy.member_manifest(self.source))
        self.assertEqual(sentinel.read_bytes(), b'original')

    def test_nested_copy_refuses_before_mutating_original(self):
        before = legacy.member_manifest(self.source)
        with self.assertRaisesRegex(RuntimeError, 'outside protected source'):
            legacy.copy_member(self.source, self.source / 'nested', before)
        self.assertEqual(legacy.member_manifest(self.source), before)
        self.assertFalse((self.source / 'nested').exists())

    def test_checker_mutates_only_disposable_copy_and_cleanup_runs(self):
        before = legacy.member_manifest(self.source)
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[:3], [str(self.tool), 'check', 'v2store'])
            isolated = Path(argv[3].split('=', 1)[1])
            self.assertNotEqual(isolated, self.source)
            snapshot = next((isolated / 'member/snap').glob('*.snap'))
            snapshot.rename(snapshot.with_suffix('.snap.broken'))
            return subprocess.CompletedProcess(argv, 0, legacy.SUCCESS, b'')
        result = self.check(run)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(legacy.member_manifest(self.source), before)
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(result['cleanup'], {'scratch_absent': True})

    def test_nonzero_checker_result_keeps_only_hashes_and_cleans(self):
        raw = b'private synthetic datastore diagnostics'
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 1, raw, raw))
        result = self.check(run)
        self.assertFalse(result['accepted'])
        self.assertNotIn(raw.decode(), str(result))
        self.assertEqual(result['stderr_sha256'], hashlib.sha256(raw).hexdigest())
        run.assert_called_once()
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_unexpected_success_output_is_not_acceptance(self):
        result = self.check(mock.Mock(return_value=subprocess.CompletedProcess([], 0, b'', b'')))
        self.assertFalse(result['accepted'])

    def test_exception_still_removes_owned_copy(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
            self.check(mock.Mock(side_effect=RuntimeError('synthetic failure')))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_original_change_during_checker_refuses_and_cleans(self):
        def run(argv, **kwargs):
            self.db.write_bytes(b'changed original')
            return subprocess.CompletedProcess(argv, 0, legacy.SUCCESS, b'')
        with self.assertRaisesRegex(RuntimeError, 'changed protected'):
            self.check(run)
        self.assertEqual(self.db.read_bytes(), b'changed original')
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_tool_change_during_checker_refuses_and_cleans(self):
        def run(argv, **kwargs):
            self.tool.chmod(0o700);self.tool.write_bytes(b'changed checker')
            return subprocess.CompletedProcess(argv, 0, legacy.SUCCESS, b'')
        with self.assertRaisesRegex(RuntimeError, 'checker changed'):
            self.check(run)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_non_ext4_wrong_checksum_and_nested_scratch_refuse_without_dispatch(self):
        run = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, 'private ext4'):
            self.check(run, native=lambda *args: 'nfs4')
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            legacy.check_copy(self.source, legacy.member_manifest(self.source),
                              self.tool, self.scratch, lambda *args: 'ext4', run)
        with self.assertRaisesRegex(RuntimeError, 'outside protected'):
            legacy.check_copy(self.source, legacy.member_manifest(self.source),
                              self.tool, self.source / 'nested', lambda *args: 'ext4', run)
        run.assert_not_called()
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
