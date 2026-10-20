#!/usr/bin/env python3
"""Exercise exact protected originals and empty, identity-bound destinations."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


SPEC = importlib.util.spec_from_file_location("seed", Path(__file__).with_name("seed-prometheus.py"))
SEED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEED)


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        (self.source / "data/wal").mkdir(parents=True)
        self.target.mkdir()
        (self.source / "data/wal/00000000").write_bytes(b"synthetic-wal")
        (self.source / "data/queries.active").write_bytes(b"synthetic-query")
        self.manifest = {"format": 1, "source": {"pod_uid": SEED.SOURCE_UID, "image": SEED.IMAGE},
                         "files": SEED.inventory(self.source / "data")}
        encoded = json.dumps(self.manifest).encode()
        (self.source / "verified.json").write_bytes(encoded)
        self.expected = hashlib.sha256(encoded).hexdigest()

    def seed(self, guard=None):
        return SEED.seed(self.source, self.target, guard or Mock(),
                         owner=(os.getuid(), os.getgid()), expected=self.expected)

    def test_complete_seed_preserves_every_original_and_refuses_overwrite(self):
        guard = Mock()
        result = self.seed(guard)
        self.assertTrue(result["accepted"])
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(SEED.inventory(self.target / "prometheus-db"), self.manifest["files"])
        self.assertEqual(SEED.inventory(self.source / "data"), self.manifest["files"])
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            self.seed()

    def test_changed_manifest_or_source_refuses_before_target_write(self):
        (self.source / "verified.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "manifest changed"):
            self.seed()
        (self.source / "verified.json").write_text(json.dumps(self.manifest))
        (self.source / "data/wal/00000000").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "source files changed"):
            self.seed()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_symlink_and_nonempty_lost_found_refuse_without_copy(self):
        path = self.source / "data/queries.active"
        path.unlink()
        path.symlink_to(self.source / "data/wal/00000000")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.seed()
        path.unlink()
        path.write_bytes(b"synthetic-query")
        (self.target / "lost+found").mkdir()
        (self.target / "lost+found/unrelated").write_text("protected")
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            self.seed()
        self.assertEqual((self.target / "lost+found/unrelated").read_text(), "protected")

    def test_owned_failed_copy_is_removed_only_while_guard_still_accepts(self):
        guard = Mock(side_effect=[None, RuntimeError("transient proof failure"), None])
        with self.assertRaisesRegex(RuntimeError, "transient proof failure"):
            self.seed(guard)
        self.assertFalse((self.target / "prometheus-db").exists())
        guard = Mock(side_effect=[None, RuntimeError("consumer changed"), RuntimeError("consumer changed")])
        with self.assertRaisesRegex(RuntimeError, "consumer changed"):
            self.seed(guard)
        self.assertTrue((self.target / "prometheus-db").is_dir())
        self.assertEqual(SEED.inventory(self.source / "data"), self.manifest["files"])

    def test_storage_uid_binding_and_active_consumer_guard(self):
        env = {"CLAIM_NAME": "claim", "CLAIM_UID": "claim-uid", "PV_NAME": "pv",
               "PV_UID": "pv-uid", "POD_UID": "self"}
        claim = {"metadata": {"uid": "claim-uid"}, "status": {"phase": "Bound"},
                 "spec": {"volumeName": "pv", "storageClassName": "standard-rwo", "accessModes": ["ReadWriteOnce"]}}
        volume = {"metadata": {"uid": "pv-uid"}, "spec": {"claimRef": {"uid": "claim-uid"}}}
        SEED.validate_storage(claim, volume, [], env)
        for obj in (claim, volume):
            changed = copy.deepcopy(obj)
            changed["metadata"]["uid"] = "different"
            with self.assertRaisesRegex(RuntimeError, "storage identity changed"):
                SEED.validate_storage(changed if obj is claim else claim,
                                      changed if obj is volume else volume, [], env)
        pod = {"metadata": {"uid": "other"}, "status": {"phase": "Pending"},
               "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "claim"}}]}}
        with self.assertRaisesRegex(RuntimeError, "another retained claim consumer"):
            SEED.validate_storage(claim, volume, [pod], env)
        pod["status"]["phase"] = "Succeeded"
        SEED.validate_storage(claim, volume, [pod], env)


if __name__ == "__main__":
    unittest.main()
