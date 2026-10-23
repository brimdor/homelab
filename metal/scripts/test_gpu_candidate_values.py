#!/usr/bin/env python3
"""Keep GPU candidates confined to the five reviewed version fields."""

import copy
import unittest

import gpu_candidate_values as subject


class CandidateValues(unittest.TestCase):
    def source(self):
        return {"driver": {"enabled": False, "version": "host-ownership-preserved"},
                "toolkit": {"version": "v1.17.9-ubuntu20.04", "env": [{"name": "CONTAINERD_SOCKET", "value": "owned"}]},
                "devicePlugin": {"version": "old"}, "gfd": {"version": "old"},
                "dcgmExporter": {"version": "old"}, "migManager": {"version": "old"},
                "node-feature-discovery": {"worker": {"config": {"core": {"featureSources": ["all", "-usb"]}}}}}

    def test_candidates_preserve_source_and_every_nonversion_field(self):
        source = self.source()
        original = copy.deepcopy(source)
        operands = ("toolkit", "devicePlugin", "gfd", "dcgmExporter", "migManager")
        for version in subject.PINS:
            candidate = subject.candidate_values(source, version)
            self.assertEqual(source, original)
            for name in operands:
                self.assertTrue(candidate[name].pop("version"))
            comparison = copy.deepcopy(original)
            for name in operands:
                comparison[name].pop("version")
            self.assertEqual(candidate, comparison)

    def test_refuse_foreign_family_or_changed_driver_ownership(self):
        for version, source in (("99.1.0", self.source()),
                                ("26.7.2", {**self.source(), "driver": {"enabled": True}}),
                                ("26.7.2", {**self.source(), "toolkit": {"version": "different"}})):
            with self.assertRaises(RuntimeError):
                subject.candidate_values(source, version)


if __name__ == "__main__":
    unittest.main()
