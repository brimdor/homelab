#!/usr/bin/env python3
"""Exercise cold-copy identity, exclusive mount, preservation and refusal gates."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cold_recovery as COLD
import recovery


class ColdRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = COLD.BUFFER_URL + "\n"
        checksum = hashlib.sha256(self.config.encode()).hexdigest()
        self.ds = {"metadata": {"uid": "ds", "generation": 3}, "spec": {"template": {
            "metadata": {"annotations": {"checksum/alloy-config": checksum}}}}, "status": {
                "observedGeneration": 3, "desiredNumberScheduled": 7, "currentNumberScheduled": 7,
                "numberReady": 7, "updatedNumberScheduled": 7}}
        self.claim = {"metadata": {"uid": "claim"}, "status": {"phase": "Bound"}}
        self.buffer_claim = {"metadata": {"uid": COLD.BUFFER_CLAIM_UID}, "status": {"phase": "Bound"}}
        self.pods = [{"metadata": {"name": "collector-" + n, "uid": n,
                      "labels": {"app.kubernetes.io/name": "promtail"},
                      "annotations": {"checksum/alloy-config": checksum},
                      "ownerReferences": [{"uid": "ds"}]},
                      "spec": {"nodeName": n, "volumes": []},
                      "status": {"containerStatuses": [{"ready": True}]}} for n in sorted(COLD.NODES)]
        self.source_pod = {"metadata": {"name": "loki-0", "uid": "old-pod"}, "spec": {
            "nodeName": "pikachu", "volumes": [{"name": "storage", "persistentVolumeClaim": {
                "claimName": "loki-data"}}]}}
        self.buffer = {"metadata": {"name": "loki-cutover-buffer-0", "uid": COLD.BUFFER_POD_UID},
                       "spec": {"volumes": []}, "status": {"containerStatuses": [{"ready": True}]}}
        self.pods += [self.source_pod, self.buffer]
        self.controller = {"metadata": {"generation": 4}, "spec": {"replicas": 0},
                           "status": {"observedGeneration": 4, "replicas": 0}}

    def api(self, path):
        if path.endswith("/persistentvolumeclaims/loki-data"):
            return self.claim
        if path.endswith("/persistentvolumeclaims/loki-cutover-buffer"):
            return self.buffer_claim
        if path.endswith("/daemonsets/loki-promtail"):
            return self.ds
        if path.endswith("/configmaps/loki-alloy"):
            return {"data": {"config.alloy": self.config}}
        if path.endswith("/statefulsets/loki"):
            return self.controller
        self.assertTrue(path.endswith("/pods"))
        return {"items": self.pods}

    def test_fully_rolled_buffer_route_accepts_exact_original_source(self):
        with patch.object(COLD, "api", side_effect=self.api):
            COLD.require_buffered("old-pod", "claim")
            with self.assertRaises(RuntimeError):
                COLD.require_buffered("replacement-pod", "claim")
            with self.assertRaises(RuntimeError):
                COLD.require_buffered("old-pod", "replacement-claim")

    def test_stale_collectors_and_unhealthy_or_replaced_buffer_are_refused(self):
        original = copy.deepcopy((self.pods, self.ds, self.buffer_claim, self.config))
        for case in ("stale", "deleting", "unready", "duplicate-node", "generation",
                     "old-route", "buffer-unready", "buffer-replaced"):
            self.pods, self.ds, self.buffer_claim, self.config = copy.deepcopy(original)
            if case == "stale":
                self.pods[0]["metadata"]["annotations"]["checksum/alloy-config"] = "old"
            elif case == "deleting":
                self.pods[0]["metadata"]["deletionTimestamp"] = "now"
            elif case == "unready":
                self.pods[0]["status"]["containerStatuses"][0]["ready"] = False
            elif case == "duplicate-node":
                self.pods[0]["spec"]["nodeName"] = self.pods[1]["spec"]["nodeName"]
            elif case == "generation":
                self.ds["status"]["observedGeneration"] = 2
            elif case == "old-route":
                self.config += COLD.OLD_URL
            elif case == "buffer-unready":
                self.pods[-1]["status"]["containerStatuses"][0]["ready"] = False
            else:
                self.buffer_claim["metadata"]["uid"] = "replacement"
            with self.subTest(case=case), patch.object(COLD, "api", side_effect=self.api):
                with self.assertRaises(RuntimeError):
                    COLD.require_buffered("old-pod", "claim")

    def offline(self):
        self.pods = [p for p in self.pods if p["metadata"]["name"] != "loki-0"]
        self.backup = {"metadata": {"name": "backup", "uid": "backup-uid"}, "spec": {
            "nodeName": "pikachu", "volumes": [{"name": "source", "persistentVolumeClaim": {
                "claimName": "loki-data"}}], "containers": [{"name": "backup", "volumeMounts": [
                    {"name": "source", "mountPath": "/source", "readOnly": True}]}]}}
        self.pods.append(self.backup)

    def test_offline_copy_requires_observed_stopped_writer_and_only_own_read_only_mount(self):
        self.offline()
        with patch.object(COLD, "api", side_effect=self.api), patch.dict(COLD.os.environ, {"POD_UID": "backup-uid"}):
            COLD.require_buffered("old-pod", "claim", offline=True)
            for case in ("writer", "generation", "other-consumer", "writable", "other-container"):
                pods, controller = copy.deepcopy((self.pods, self.controller))
                if case == "writer":
                    self.controller["spec"]["replicas"] = 1
                elif case == "generation":
                    self.controller["status"]["observedGeneration"] = 3
                elif case == "other-consumer":
                    self.pods.append(self.source_pod)
                elif case == "writable":
                    self.pods[-1]["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] = False
                else:
                    self.pods[-1]["spec"]["containers"].append({"name": "other"})
                with self.subTest(case=case), self.assertRaises(RuntimeError):
                    COLD.require_buffered("old-pod", "claim", offline=True)
                self.pods, self.controller = pods, controller

    def test_captured_contract_is_exclusive_and_requires_unchanged_ingestion(self):
        point = self.root / "point"
        proof = {"historical": {"rows": 100, "sha256": "fixed"}}
        with patch.object(COLD, "require_buffered"), patch.object(COLD, "flush_old", return_value=42), \
                patch.object(COLD, "metrics", return_value=(0, 42)), \
                patch.object(recovery, "query_proof", return_value=proof):
            COLD.capture("old-pod", "claim", point)
            self.assertEqual(json.loads((point / "capture.json").read_text())["queries"], proof)
            with self.assertRaises(FileExistsError):
                COLD.capture("old-pod", "claim", point)
        with patch.object(COLD, "require_buffered"), patch.object(COLD, "flush_old", return_value=42), \
                patch.object(COLD, "metrics", return_value=(0, 43)), \
                patch.object(recovery, "query_proof", return_value=proof):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                COLD.capture("old-pod", "claim", self.root / "changed")
        self.assertFalse((self.root / "changed").exists())

    def test_cold_copy_preserves_source_and_manifest_and_never_overwrites(self):
        point, source = self.root / "point", self.root / "source"
        point.mkdir()
        (source / "loki/wal").mkdir(parents=True)
        (source / "loki/wal/00000097").write_bytes(b"synthetic stopped WAL")
        value = {"source_pod_uid": "old-pod", "source_pvc_uid": "claim", "timestamp": 123,
                 "queries": {"historical": {"sha256": "fixed", "rows": 100}}}
        (point / "capture.json").write_text(json.dumps(value))
        before = recovery.inventory(source)
        with patch.object(COLD, "require_buffered") as guard:
            COLD.copy_store("old-pod", "claim", point, source)
            self.assertEqual(guard.call_count, 2)
            with self.assertRaises(RuntimeError):
                COLD.copy_store("old-pod", "claim", point, source)
        verified = json.loads((point / "verified.json").read_text())
        self.assertEqual(verified["manifest"], before)
        self.assertEqual(recovery.inventory(source), before)
        self.assertEqual(recovery.inventory(point / "source"), before)
        with self.assertRaisesRegex(RuntimeError, "identity differs"):
            COLD.copy_store("other-pod", "claim", point, source)


if __name__ == "__main__":
    unittest.main()
