#!/usr/bin/env python3
"""Reject foreign or unsanitized admission inputs before a runtime is created."""

import copy
import unittest
from unittest.mock import patch

import ceph_admission_qualification as subject


class AdmissionInput(unittest.TestCase):
    def test_unreviewed_minor_bundle_never_starts_a_runtime(self):
        bundle = {"crds": [{} for _ in range(25)], "resources": [{} for _ in range(10)]}
        with patch.object(subject.common, "qualify") as native, self.assertRaisesRegex(RuntimeError, "minor Ceph admission bundle changed"):
            subject.qualify(bundle, "test-12345678")
        native.assert_not_called()

    def test_native_output_accepts_multiple_documents_without_dropping_one(self):
        self.assertEqual(subject.command_objects(b'{"kind":"A"}\n{"kind":"B"}\n'),
                         [{"kind": "A"}, {"kind": "B"}])
        self.assertEqual(subject.command_objects(b'{"kind":"List","items":[{"kind":"A"}]}'),
                         [{"kind": "A"}])
        with self.assertRaises(ValueError):
            subject.command_objects(b'{"kind":"A"} invalid')

    def test_rejects_foreign_and_production_metadata(self):
        bundle = {"crds": [{"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition",
                            "metadata": {"name": "things" + str(i) + ".ceph.rook.io"},
                            "spec": {"group": "ceph.rook.io", "names": {"kind": "Thing" + str(i)},
                                     "versions": [{"name": "v1", "served": True}]}} for i in range(24)],
                  "resources": [{"apiVersion": "ceph.rook.io/v1", "kind": "Thing0",
                                 "metadata": {"name": "example" + str(i)}, "spec": {}} for i in range(10)]}
        self.assertEqual(len(subject.validate_bundle(bundle)), 24)
        for change in (lambda b: b["resources"][0]["metadata"].update(uid="production"),
                       lambda b: b["resources"][0].update(kind="Secret"),
                       lambda b: b["resources"].__setitem__(1, b["resources"][0]),
                       lambda b: b["crds"][0]["spec"].update(group="foreign.example")):
            bad = copy.deepcopy(bundle)
            change(bad)
            with self.assertRaises(RuntimeError):
                subject.validate_bundle(bad)


if __name__ == "__main__":
    unittest.main()
