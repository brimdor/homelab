#!/usr/bin/env python3
"""Refuse changed GPU inputs before creating a native runtime."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gpu_admission_qualification as subject


class GPUAdmissionInput(unittest.TestCase):
    def bundle(self):
        stages = []
        for index, version in enumerate(subject.VERSIONS):
            names = subject.BASE | (subject.ADDED if index == 4 else set())
            stages.append({"version": version, "archive_sha256": "a" * 64,
                           "crds": [{"apiVersion": "apiextensions.k8s.io/v1",
                                     "kind": "CustomResourceDefinition", "metadata": {"name": name},
                                     "spec": {"group": name.split(".", 1)[1]}} for name in sorted(names)],
                           "policy": {"apiVersion": "nvidia.com/v1", "kind": "ClusterPolicy",
                                      "metadata": {"name": "cluster-policy"}, "spec": {}}})
        return {"values_sha256": "b" * 64, "stages": stages}

    def test_unreviewed_bundle_never_starts_runtime(self):
        with patch.object(subject.common, "qualify") as native, self.assertRaisesRegex(RuntimeError, "bundle changed"):
            subject.qualify(self.bundle(), "gpu-12345678")
        native.assert_not_called()

    def test_reviewed_input_still_requires_safe_shapes(self):
        bundle = self.bundle()
        with patch.object(subject, "BUNDLE_SHA256", hashlib.sha256(subject.common.canonical(bundle)).hexdigest()):
            subject.validate_bundle(bundle)
        for mutate in (lambda b: b["stages"].reverse(),
                       lambda b: b["stages"][0]["crds"][0]["metadata"].update(uid="production"),
                       lambda b: b["stages"][0]["crds"][0]["spec"].update(conversion={"strategy": "Webhook"}),
                       lambda b: b["stages"][0]["policy"].update(kind="Secret"),
                       lambda b: b["stages"][0]["crds"].pop()):
            bad = copy.deepcopy(bundle)
            mutate(bad)
            with patch.object(subject, "BUNDLE_SHA256", hashlib.sha256(subject.common.canonical(bad)).hexdigest()):
                with self.assertRaises(RuntimeError):
                    subject.validate_bundle(bad)

    def test_native_sequence_replaces_only_owned_crds_and_never_persists_policy(self):
        bundle = self.bundle()
        for foreign_uid in (False, True):
            stored = {}
            policy_dry_runs = []
            with tempfile.TemporaryDirectory() as directory:
                scratch = Path(directory)

                def docker(*args, **_kwargs):
                    operation = args[0]
                    if operation == "wait":
                        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
                    if operation == "get":
                        value = copy.deepcopy(stored[args[2]]) if args[1] == "crd" else {"items": []}
                        if foreign_uid and args[1] == "crd":
                            value["metadata"]["uid"] = "another-owner"
                    else:
                        self.assertIn("--validate=strict", args)
                        value = json.loads((scratch / "gpu-schema.json").read_bytes())
                        name = value["metadata"]["name"]
                        if value["kind"] == "ClusterPolicy":
                            self.assertIn("--dry-run=server", args)
                            policy_dry_runs.append(name)
                        else:
                            self.assertEqual(value["kind"], "CustomResourceDefinition")
                            if operation == "replace":
                                self.assertEqual(value["metadata"]["uid"], stored[name]["metadata"]["uid"])
                                self.assertEqual(value["metadata"]["resourceVersion"], stored[name]["metadata"]["resourceVersion"])
                            else:
                                self.assertEqual(operation, "create")
                                self.assertNotIn(name, stored)
                            value["metadata"].update(uid="owned-" + name,
                                                     resourceVersion=str(int(stored.get(name, {}).get("metadata", {}).get("resourceVersion", "0")) + 1))
                            stored[name] = copy.deepcopy(value)
                    return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b"")

                def runtime(run_id, synthetic_check):
                    return synthetic_check("owned", scratch, [], run_id)

                with patch.object(subject, "BUNDLE_SHA256", hashlib.sha256(subject.common.canonical(bundle)).hexdigest()), \
                        patch.object(subject.common, "qualify", side_effect=runtime), \
                        patch.object(subject.common, "docker", side_effect=docker):
                    result = subject.qualify(bundle, "gpu-12345678")
                self.assertEqual(result["accepted"], not foreign_uid)
                self.assertEqual(len(policy_dry_runs), 1 if foreign_uid else 5)
                if foreign_uid:
                    self.assertEqual(result["error"], "owned GPU schema identity changed")


if __name__ == "__main__":
    unittest.main()
