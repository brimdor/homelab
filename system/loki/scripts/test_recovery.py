#!/usr/bin/env python3
"""Exercise store preservation and refusal boundaries with synthetic files."""

import importlib.util
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("recovery", Path(__file__).with_name("recovery.py"))
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


class StoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        (self.source / "loki/index").mkdir(parents=True)
        (self.source / "loki/index/db").write_bytes(b"index\x00data")
        (self.source / "loki/chunk").write_bytes(b"preserved log record\n")

    def test_complete_copy_preserves_bytes_and_source(self):
        before = RECOVERY.inventory(self.source)
        target = self.root / "restored"
        RECOVERY.copy_verified(self.source, target, before)
        self.assertEqual(RECOVERY.inventory(target), before)
        self.assertEqual(RECOVERY.inventory(self.source), before)
        self.assertEqual((target / "loki/chunk").stat().st_mode & 0o777, 0o600)

    def test_changed_source_refuses_verified_copy(self):
        before = RECOVERY.inventory(self.source)
        (self.source / "loki/chunk").write_bytes(b"concurrent write")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            RECOVERY.copy_verified(self.source, self.root / "changed", before)

    def test_existing_destination_never_overwritten(self):
        before = RECOVERY.inventory(self.source)
        with self.assertRaisesRegex(RuntimeError, "overwrite"):
            RECOVERY.copy_verified(self.source, self.source, before)
        self.assertEqual(RECOVERY.inventory(self.source), before)

    def test_symlink_and_traversal_refused(self):
        (self.source / "link").symlink_to(self.source / "loki/chunk")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            RECOVERY.inventory(self.source)
        with self.assertRaisesRegex(RuntimeError, "manifest path"):
            RECOVERY.copy_verified(self.source, self.root / "unsafe", [{"path": "../escape"}])
        self.assertFalse((self.root / "escape").exists())

    def test_service_verification_keeps_recovery_read_only(self):
        proof = {"historical": {"rows": 100, "sha256": "proof"}}
        value = {"timestamp": 123, "queries": proof, "manifest_sha256": "manifest"}
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(RECOVERY, "recovery_point", return_value=(self.root, value)), \
                patch.object(RECOVERY, "query_proof", return_value=proof) as query, \
                patch.object(RECOVERY.urllib.request, "urlopen", return_value=response):
            RECOVERY.verify(service=True)
        query.assert_called_once_with("http://loki.loki:3100", 123)
        self.assertFalse((self.root / "restore-proof.json").exists())

    def test_candidate_checks_version_and_does_not_overwrite_original_proof(self):
        proof = {"historical": {"rows": 100, "sha256": "proof"}}
        value = {"timestamp": 123, "queries": proof, "manifest_sha256": "manifest"}
        original = self.root / "restore-proof.json"
        original.write_text("original verified recovery")
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(RECOVERY, "recovery_point", return_value=(self.root, value)), \
                patch.object(RECOVERY, "query_proof", return_value=proof), \
                patch.object(RECOVERY, "get_json", return_value={"version": "3.7.8"}), \
                patch.object(RECOVERY.Path, "read_bytes", return_value=b"candidate configuration"), \
                patch.object(RECOVERY.urllib.request, "urlopen", return_value=response):
            RECOVERY.verify(candidate=True)
        self.assertEqual(original.read_text(), "original verified recovery")
        with patch.object(RECOVERY, "recovery_point", return_value=(self.root, value)), \
                patch.object(RECOVERY, "get_json", return_value={"version": "2.6.1"}), \
                patch.object(RECOVERY.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "candidate version"):
                RECOVERY.verify(candidate=True)

    def test_fresh_restores_use_separate_subdirectories_without_overwriting(self):
        target = self.root / "target"
        target.mkdir()
        (target / "loki").mkdir()
        (target / "loki/original").write_text("preserved prior candidate")
        value = {"manifest": RECOVERY.inventory(self.source), "manifest_sha256": "manifest"}

        def path(value):
            return target if value == "/target" else Path(value)

        def chown_after_copy(directory, uid, group):
            if Path(directory).name in ("pre-upgrade-20261019-old", "pre-upgrade-20261019-new"):
                self.assertTrue((Path(directory) / "loki/chunk").is_file(),
                                "changing ownership before copy removes root's write access")

        with patch.object(RECOVERY, "recovery_point", return_value=(self.root, value)), \
                patch.object(RECOVERY, "Path", side_effect=path), \
                patch.object(RECOVERY.os, "chown", side_effect=chown_after_copy) as chown:
            for suffix in ("old", "new"):
                RECOVERY.prepare("pre-upgrade-20261019", "pre-upgrade-20261019-" + suffix)
            with self.assertRaises(FileExistsError):
                RECOVERY.prepare("pre-upgrade-20261019", "pre-upgrade-20261019-old")
        chown.assert_any_call(target / "pre-upgrade-20261019-old", 10001, 10001)
        self.assertEqual((target / "loki/original").read_text(), "preserved prior candidate")
        self.assertEqual(RECOVERY.inventory(target / "pre-upgrade-20261019-old"),
                         RECOVERY.inventory(target / "pre-upgrade-20261019-new"))

    def test_pvc_backup_guard_requires_quiescence_and_exact_live_identities(self):
        pod = {"metadata": {"uid": "pod-uid"}, "spec": {"nodeName": "pikachu", "volumes": [
            {"name": "storage", "persistentVolumeClaim": {"claimName": "loki-data"}}]}}
        ds = {"metadata": {"generation": 2}, "status": {
            "observedGeneration": 2, "desiredNumberScheduled": 0, "currentNumberScheduled": 0}}
        claim = {"metadata": {"uid": "claim-uid"}, "status": {"phase": "Bound"}}
        cases = [(pod, ds, {"items": []}, claim)]
        for changed in ("uid", "deleting", "unbound", "collectors", "generation", "node", "mount"):
            p, d, c = copy.deepcopy(pod), copy.deepcopy(ds), copy.deepcopy(claim)
            pods = {"items": []}
            if changed == "uid":
                c["metadata"]["uid"] = "replacement"
            elif changed == "deleting":
                c["metadata"]["deletionTimestamp"] = "now"
            elif changed == "unbound":
                c["status"]["phase"] = "Lost"
            elif changed == "collectors":
                pods["items"] = [{"metadata": {"name": "still-running"}}]
            elif changed == "generation":
                d["status"]["observedGeneration"] = 1
            elif changed == "node":
                p["spec"]["nodeName"] = "totodile"
            else:
                p["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = "other"
            cases.append((p, d, pods, c))
        for index, responses in enumerate(cases):
            with self.subTest(index=index), \
                    patch.object(RECOVERY.Path, "read_text", return_value="synthetic-token"), \
                    patch.object(RECOVERY.ssl, "create_default_context"), \
                    patch.object(RECOVERY, "get_json", side_effect=responses):
                if index == 0:
                    RECOVERY.require_quiesced("pod-uid", "claim-uid")
                else:
                    with self.assertRaises(RuntimeError):
                        RECOVERY.require_quiesced("pod-uid", "claim-uid")


if __name__ == "__main__":
    unittest.main()
