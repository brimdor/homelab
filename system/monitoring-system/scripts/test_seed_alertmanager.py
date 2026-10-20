#!/usr/bin/env python3
"""Synthetic native copy, identity and partial-cleanup boundaries."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


for name, filename in (("seed_common", "seed-prometheus.py"), ("seed_alertmanager", "seed-alertmanager.py")):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
seed = sys.modules["seed_alertmanager"]


class AlertmanagerSeed(unittest.TestCase):
    def fixture(self, root):
        source, target = root / "source", root / "target"
        source.mkdir()
        target.mkdir()
        (source / "nflog").write_bytes(b"\x03one")
        (source / "silences").write_bytes(b"")
        value = {"format": 1, "kind": "alertmanager-native-persisted-snapshots", "image": seed.IMAGE,
                 "pod_uid": seed.SOURCE_UID, "current_persisted_ram_proven": True,
                 "files": seed.seed_common.inventory(source)}
        encoded = json.dumps(value, sort_keys=True).encode()
        (source / "verified.json").write_bytes(encoded)
        return source, target, hashlib.sha256(encoded).hexdigest()

    def test_complete_exact_copy_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, expected = self.fixture(Path(directory))
            result = seed.seed(source, target, expected, lambda: None, owner=(os.getuid(), os.getgid()))
            self.assertTrue(result["accepted"])
            self.assertEqual((target / "alertmanager-db/nflog").read_bytes(), b"\x03one")
            self.assertEqual((target / "alertmanager-db/silences").read_bytes(), b"")
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                seed.seed(source, target, expected, lambda: None)

    def test_changed_source_and_storage_refuse_before_target_write(self):
        for changed in ("hash", "source", "storage", "symlink"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                source, target, expected = self.fixture(Path(directory))
                if changed == "hash":
                    expected = "0" * 64
                elif changed == "source":
                    (source / "nflog").write_bytes(b"different")
                elif changed == "symlink":
                    (source / "silences").unlink()
                    (source / "silences").symlink_to(source / "nflog")
                def guard():
                    if changed == "storage":
                        raise RuntimeError("synthetic storage changed")
                with self.assertRaises(RuntimeError):
                    seed.seed(source, target, expected, guard)
                self.assertEqual(list(target.iterdir()), [])

    def test_final_guard_failure_preserves_original_and_removes_only_owned_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, expected = self.fixture(Path(directory))
            (target / "lost+found").mkdir()
            calls = 0
            def guard():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("synthetic transient guard failure")
            with self.assertRaisesRegex(RuntimeError, "guard failure"):
                seed.seed(source, target, expected, guard, owner=(os.getuid(), os.getgid()))
            self.assertEqual([p.name for p in target.iterdir()], ["lost+found"])
            self.assertEqual(seed.protected_source(source, expected)[1]["nflog"]["bytes"], 4)


if __name__ == "__main__":
    unittest.main()
