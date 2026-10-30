import io
import json
from pathlib import Path
import unittest
from unittest import mock

import maintenance_etcd_legacy as legacy
import maintenance_etcd_transfer as transfer
import test_maintenance_etcd_legacy as fixtures


class MemberTransferTests(unittest.TestCase):
    setUp = fixtures.LegacyCopyTests.setUp

    def stream(self, predicate=lambda: True):
        expected = legacy.member_manifest(self.source)
        output = io.BytesIO()
        transfer.send(self.source, output, {'owner': 'synthetic-only'}, expected, predicate)
        output.seek(0)
        return output, expected

    def receive(self, stream, expected, point=None, binding=None):
        return transfer.receive(stream, point or self.root / 'received',
                                binding or {'owner': 'synthetic-only'}, legacy.manifest_sha256(expected),
                                lambda *args: 'ext4')

    def test_full_transfer_preserves_source_and_every_member_file(self):
        confirm = mock.Mock(return_value=True)
        stream, expected = self.stream(confirm)
        result = self.receive(stream, expected)
        self.assertTrue(result['accepted'])
        self.assertEqual(confirm.call_count, 2)
        self.assertEqual(legacy.member_manifest(self.source), expected)
        self.assertEqual(legacy.contents(legacy.member_manifest(self.root / 'received/data')),
                         legacy.contents(expected))
        marker = self.root / 'received/verified.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(marker.read_bytes())['manifest'], expected)

    def test_not_stopped_refuses_before_any_bytes(self):
        stream = io.BytesIO()
        with self.assertRaisesRegex(RuntimeError, 'stopped-source proof'):
            transfer.send(self.source, stream, {'owner': 'synthetic-only'},
                          legacy.member_manifest(self.source), lambda: False)
        self.assertEqual(stream.getvalue(), b'')

    def test_source_change_or_return_before_commit_leaves_unverified_point(self):
        for change in (False, True):
            with self.subTest(change=change):
                expected = legacy.member_manifest(self.source);stream = io.BytesIO();calls = []
                def confirm():
                    calls.append(True)
                    if len(calls) == 2:
                        if change:
                            self.db.write_bytes(b'synthetic changed source')
                        else:
                            return False
                    return True
                with self.assertRaisesRegex(RuntimeError, 'before transfer commit'):
                    transfer.send(self.source, stream, {'owner': 'synthetic-only'}, expected, confirm)
                stream.seek(0)
                point = self.root / ('partial-' + str(change))
                with self.assertRaisesRegex(RuntimeError, 'transfer frame'):
                    self.receive(stream, expected, point)
                self.assertTrue((point / 'data/member/snap/db').exists())
                self.assertFalse((point / 'verified.json').exists())

    def test_truncated_or_corrupted_stream_never_commits(self):
        stream, expected = self.stream();raw = stream.getvalue()
        for name, value in (('truncated', raw[:-20]),
                            ('corrupt', raw.replace(b'synthetic-db', b'corrupted-db', 1)),
                            ('trailing', raw + b'extra')):
            with self.subTest(name=name):
                point = self.root / name
                with self.assertRaises(RuntimeError):
                    self.receive(io.BytesIO(value), expected, point)
                self.assertTrue(point.exists())
                self.assertFalse((point / 'verified.json').exists())

    def test_wrong_binding_or_manifest_refuses_before_destination(self):
        stream, expected = self.stream()
        with self.assertRaisesRegex(RuntimeError, 'binding differs'):
            self.receive(stream, expected, binding={'owner': 'other'})
        self.assertFalse((self.root / 'received').exists())
        stream.seek(0)
        with self.assertRaisesRegex(RuntimeError, 'binding differs'):
            transfer.receive(stream, self.root / 'received', {'owner': 'synthetic-only'},
                             '0' * 64, lambda *args: 'ext4')
        self.assertFalse((self.root / 'received').exists())

    def test_unsafe_path_and_parent_refuse_before_destination(self):
        for name in ('member/../outside', '/absolute', 'member/missing/file'):
            with self.subTest(name=name):
                manifest = legacy.member_manifest(self.source)
                manifest['entries'][name] = manifest['entries'].pop('member/snap/db')
                header = {'version': 1, 'binding': {'owner': 'synthetic-only'}, 'manifest': manifest}
                with self.assertRaises(RuntimeError):
                    self.receive(io.BytesIO(transfer.canonical(header) + b'\n'), manifest)
                self.assertFalse((self.root / 'received').exists())
                self.assertFalse((self.root / 'outside').exists())

    def test_existing_destination_is_preserved(self):
        stream, expected = self.stream()
        point = self.root / 'received';point.mkdir(mode=0o700)
        sentinel = point / 'keep';sentinel.write_bytes(b'protected original')
        with self.assertRaises(FileExistsError):
            self.receive(stream, expected)
        self.assertEqual(sentinel.read_bytes(), b'protected original')
        self.assertEqual(list(point.iterdir()), [sentinel])

    def test_non_ext4_refuses_without_reading_stream(self):
        stream = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, 'private ext4'):
            transfer.receive(stream, self.root / 'received', {'owner': 'synthetic-only'},
                             '0' * 64, lambda *args: 'nfs4')
        stream.readline.assert_not_called()
        self.assertFalse((self.root / 'received').exists())


if __name__ == '__main__':
    unittest.main()
