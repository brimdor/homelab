#!/usr/bin/env python3
"""Refusal and API command tests; no network or production credentials."""

import copy
import json
from types import SimpleNamespace
import unittest

import cilium_pool_migration as subject


def pool():
    return {"kind": "CiliumLoadBalancerIPPool", "apiVersion": "cilium.io/v2alpha1",
            "metadata": {"name": "default", "uid": subject.UID, "resourceVersion": "123"},
            "spec": copy.deepcopy(subject.LEGACY)}


class FakeAPI:
    def __init__(self):
        self.pool = pool()
        self.commands = []
        self.server = subject.SERVER
        self.denied = False
        self.concurrent = False

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if "config" in command:
            return SimpleNamespace(returncode=0, stdout=self.server, stderr="")
        if "get" in command:
            result = self.pool
        else:
            if self.denied or self.concurrent:
                return SimpleNamespace(returncode=1, stdout="", stderr="forbidden private-sentinel-value")
            patch = json.loads(kwargs["input"])
            for operation in patch[:3]:
                parts = operation["path"].strip("/").split("/")
                observed = self.pool
                for key in parts:
                    observed = observed[key]
                if observed != operation["value"]:
                    raise AssertionError("missing compare-and-swap guard")
            result = copy.deepcopy(self.pool)
            result["spec"] = patch[3]["value"]
            if "--dry-run=server" not in command:
                result["metadata"]["resourceVersion"] = "124"
                self.pool = result
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")


class MigrationTests(unittest.TestCase):
    def run_mode(self, api, mode):
        args = SimpleNamespace(kubectl="fake-kubectl", kubeconfig="unchanged-config", cache_dir="owned-cache", mode=mode)
        return subject.execute(args, api)

    def test_inspect_and_server_dry_run_cannot_write(self):
        for mode in ("inspect", "dry-run"):
            api = FakeAPI()
            before = copy.deepcopy(api.pool)
            self.assertFalse(self.run_mode(api, mode)["changed"])
            self.assertEqual(api.pool, before)
            writes = [c for c in api.commands if "patch" in c]
            self.assertEqual(len(writes), int(mode == "dry-run"))
            self.assertTrue(all("--dry-run=server" in c for c in writes))

    def test_apply_and_exact_rollback_preserve_uid_and_original_spec(self):
        api = FakeAPI()
        self.assertTrue(self.run_mode(api, "apply")["changed"])
        self.assertEqual(api.pool["spec"], subject.CURRENT)
        self.assertFalse(self.run_mode(api, "rollback-dry-run")["changed"])
        self.assertTrue(self.run_mode(api, "rollback")["changed"])
        self.assertEqual(api.pool["spec"], subject.LEGACY)
        self.assertEqual(api.pool["metadata"]["uid"], subject.UID)

    def test_foreign_api_stops_before_resource_read(self):
        api = FakeAPI()
        api.server = "https://foreign.invalid"
        with self.assertRaises(RuntimeError):
            self.run_mode(api, "apply")
        self.assertEqual(len(api.commands), 1)

    def test_changed_identity_range_reservations_or_extra_intent_refused(self):
        for field, value in (("uid", "replacement"), ("deletionTimestamp", "now")):
            value_pool = pool()
            value_pool["metadata"][field] = value
            with self.assertRaises(RuntimeError):
                subject.transition(value_pool, "apply")
        for spec in ({"cidrs": [{"cidr": "10.0.0.0/8"}], "disabled": False},
                     {**subject.LEGACY, "allowFirstLastIPs": "Yes"},
                     {**subject.LEGACY, "serviceSelector": {}}, subject.CURRENT):
            value_pool = pool()
            value_pool["spec"] = spec
            with self.assertRaises(RuntimeError):
                subject.transition(value_pool, "apply")

    def test_denial_and_concurrent_patch_fail_once_without_raw_output(self):
        for field in ("denied", "concurrent"):
            api = FakeAPI()
            setattr(api, field, True)
            with self.assertRaises(RuntimeError) as caught:
                self.run_mode(api, "apply")
            self.assertNotIn("private-sentinel-value", str(caught.exception))
            self.assertEqual(len([c for c in api.commands if "patch" in c]), 1)
            self.assertEqual(api.pool["spec"], subject.LEGACY)


if __name__ == "__main__":
    unittest.main()
