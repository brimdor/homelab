#!/usr/bin/env python3
"""Refuse writable consumers, changed source identity and unverified copy data."""

import copy
import json
import unittest
from unittest.mock import patch

import buffer_transfer
import frozen_query_copy as subject


class FrozenCopyTests(unittest.TestCase):
    def fixture(self):
        source = {"metadata": {"uid": subject.cold_recovery.BUFFER_POD_UID,
                              "annotations": {"checksum/config": subject.CONFIG_SHA}},
                  "spec": {"nodeName": "totodile"}, "status": {"containerStatuses": [{
                      "ready": True, "restartCount": 0,
                      "containerID": "containerd://6b449c1357b0ccf232ec9cd784739a2c773dd929c7231a45759925d011bcae12"}]}}
        mount = {"name": "frozen-source", "mountPath": "/frozen-original", "readOnly": True}
        own = {"metadata": {"uid": "owned", "ownerReferences": [{"kind": "Job", "uid": "job",
                       "name": "loki-buffer-continuation-audit-20261019-29"}]},
               "spec": {"nodeName": "totodile", "serviceAccountName": "loki-store-recovery",
                        "automountServiceAccountToken": False,
                        "containers": [{"name": "transfer", "image": subject.PYTHON,
                                        "args": ["--phase=continuation"], "volumeMounts": [mount]}],
                        "initContainers": [{"name": "copy-frozen-source", "image": subject.PYTHON,
                                            "command": ["python3", "-B", "/scripts/frozen_query_copy.py"],
                                            "volumeMounts": [mount]},
                                           {"name": "frozen-query-reader", "image": subject.LOKI,
                                            "args": subject.READER_ARGS, "restartPolicy": "Always", "volumeMounts": []}],
                        "volumes": [{"name": "frozen-source", "persistentVolumeClaim": {
                            "claimName": "loki-cutover-buffer", "readOnly": True}}]}}
        return source, own

    def test_writable_apply_unknown_owner_and_reader_credentials_are_refused(self):
        source, own = self.fixture()
        with patch.dict(subject.os.environ, {"POD_UID": "owned"}):
            self.assertEqual(subject.require_consumer([source, own]), "owned")
            for change in (lambda p: p["spec"]["volumes"][0]["persistentVolumeClaim"].update(readOnly=False),
                           lambda p: p["spec"]["containers"][0]["args"].append("--apply"),
                           lambda p: p["metadata"]["ownerReferences"][0].update(name="foreign-job"),
                           lambda p: p["spec"]["initContainers"][1]["volumeMounts"].append({"name": "api-access"})):
                bad = copy.deepcopy(own)
                change(bad)
                with self.assertRaises(RuntimeError):
                    subject.require_consumer([source, bad])
            source["status"]["containerStatuses"][0]["restartCount"] = 1
            with self.assertRaises(RuntimeError):
                subject.require_consumer([source, own])

    def test_source_manifest_and_accounting_are_required(self):
        manifest = [{"path": "fake", "size": 3, "sha256": "a" * 64}]
        proof = {"source_uid": subject.cold_recovery.BUFFER_POD_UID,
                 "claim_uid": subject.cold_recovery.BUFFER_CLAIM_UID, "config_sha256": subject.CONFIG_SHA,
                 "source_accounting": {"accepted_records": 3}, "manifest_sha256": subject.recovery.digest(manifest),
                 "files": 1, "bytes": 3}
        with patch.object(subject.Path, "read_bytes", return_value=json.dumps(proof).encode()), \
                patch.object(subject.recovery, "inventory", return_value=manifest):
            self.assertEqual(subject.require_copy({"accepted_records": 3}), proof)
            with self.assertRaises(RuntimeError):
                subject.require_copy({"accepted_records": 4})
            with patch.object(subject.recovery, "inventory", return_value=[{**manifest[0], "size": 4}]):
                with self.assertRaises(RuntimeError):
                    subject.require_copy({"accepted_records": 3})

    def test_copy_cannot_enable_writes_and_routes_only_source_queries(self):
        with patch.object(buffer_transfer, "FROZEN_QUERY_COPY", True):
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                buffer_transfer.run("target", "continuation", 30, True)
            empty = {"status": "success", "data": {"resultType": "streams", "result": []}}
            with patch.object(buffer_transfer, "get_json", return_value=empty) as get:
                buffer_transfer.query(buffer_transfer.SOURCE, 1, 2)
                self.assertTrue(get.call_args.args[0].startswith("http://127.0.0.1:3100/"))
                buffer_transfer.query(buffer_transfer.TARGET, 1, 2)
                self.assertTrue(get.call_args.args[0].startswith(buffer_transfer.TARGET + "/"))


if __name__ == "__main__":
    unittest.main()
