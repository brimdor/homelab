#!/usr/bin/env python3
"""Reject foreign or unsanitized admission inputs before a runtime is created."""

import copy
import unittest

import ceph_admission_qualification as subject


class AdmissionInput(unittest.TestCase):
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
