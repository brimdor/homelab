"""Verify empty-store metadata recovery and fail-closed protected framing."""

import copy
import hashlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import empty_store_recovery as recovery


class EmptyStoreRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def manifest(self):
        source = self.root / 'source'
        source.mkdir(mode=0o750)
        (source / 'empty').mkdir(mode=0o710)
        os.setxattr(source, 'user.maintenance103', b'synthetic\0metadata', follow_symlinks=False)
        os.utime(source, ns=(1234567890, 1234567890))
        return source, {'format': 1, 'cluster_uid': recovery.common.CLUSTER_UID,
                        'profile': recovery.PROFILES['jovo'], 'directories': recovery.tree(source),
                        'pause': {'stopped_seconds': 0.1}, 'resumed': True}

    def framed(self, value):
        raw = recovery.common.canonical(value)
        return raw + b'\n' + recovery.common.canonical({'commit': hashlib.sha256(raw).hexdigest()}) + b'\n'

    def test_protected_empty_metadata_round_trip_and_copy_cleanup(self):
        _source, value = self.manifest()
        point = self.root / 'point'
        result = recovery.receive(io.BytesIO(self.framed(value)), point, 'jovo')
        with patch.object(recovery, 'copied_write') as probe:
            restored = recovery.restore(point, result['manifest_sha256'], 'jovo')
        probe.assert_called_once()
        self.assertTrue(restored['accepted'])
        self.assertTrue(restored['cleanup']['scratch_absent'])
        self.assertEqual(recovery.verify(point, result['manifest_sha256'], 'jovo'), value)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['point', 'source'])

    def test_nonempty_symlink_and_changed_metadata_refuse(self):
        source, value = self.manifest()
        (source / 'file').write_bytes(b'synthetic')
        with self.assertRaisesRegex(RuntimeError, 'no longer empty'):
            recovery.tree(source)
        (source / 'file').unlink()
        (source / 'link').symlink_to(source / 'empty', target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            recovery.tree(source)
        (source / 'link').unlink()
        original = Path.lstat
        def foreign_device(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return SimpleNamespace(st_dev=value.st_dev + 1) if path == source / 'empty' else value
        with patch.object(Path, 'lstat', foreign_device), self.assertRaisesRegex(RuntimeError, 'crosses a device'):
            recovery.tree(source)
        point = self.root / 'point'
        result = recovery.receive(io.BytesIO(self.framed(value)), point, 'jovo')
        with patch.object(recovery, 'copied_write', side_effect=RuntimeError('injected write refusal')):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                recovery.restore(point, result['manifest_sha256'], 'jovo')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['point', 'source'])
        with (point / 'verified.json').open('ab') as output:
            output.write(b' ')
        with self.assertRaisesRegex(RuntimeError, 'manifest changed'):
            recovery.verify(point, result['manifest_sha256'], 'jovo')

    def test_uncommitted_framing_unsafe_paths_and_identity_refuse(self):
        _source, value = self.manifest()
        raw = self.framed(value)
        for index, broken in enumerate((raw[:-1], raw + b'extra')):
            point = self.root / str(index)
            with self.assertRaises(RuntimeError):
                recovery.receive(io.BytesIO(broken), point, 'jovo')
            self.assertFalse(point.exists())
        for name in ('../escape', '/absolute', 'missing/child'):
            changed = copy.deepcopy(value)
            changed['directories'][name] = changed['directories']['']
            with self.assertRaises(RuntimeError):
                recovery.validate(changed, 'jovo')
        for key, bad in [('resumed', False), ('pause', {'stopped_seconds': 10}), ('cluster_uid', 'foreign')]:
            changed = {**value, key: bad}
            with self.assertRaises(RuntimeError):
                recovery.validate(changed, 'jovo')


if __name__ == '__main__':
    unittest.main()
