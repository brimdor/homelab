#!/usr/bin/env python3
"""Guard TLS evidence parsing, fixed sample size and immediate refusal."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cilium_tls_diagnostic as d


GOOD = b"301 0 0.010000 0.040000 0.050000 0.060000 10.0.1.2 30000 1.0.0.1 443\n"


class Guards(unittest.TestCase):
    def pods(self):
        return [{"metadata": {"name": name + "-pod", "namespace": d.NAMESPACE, "uid": name + "-uid",
                              "labels": {"name": name}},
                 "spec": {"nodeName": "owned-agent-0", "containers": [{"name": name, "image": d.IMAGE}]},
                 "status": {"phase": "Running", "podIP": "10.0.1." + str(index + 2), "containerStatuses": [
                     {"name": name, "ready": True, "state": {"running": {}}, "restartCount": 0,
                      "containerID": name + "-id", "imageID": "exact-image"}]}}
                for index, name in enumerate(("client", "client2", "client3"))]

    def test_timing_and_security_refusals(self):
        self.assertEqual(d.observation(GOOD, "1.0.0.1")["ssl_verify_result"], 0)
        for old, new in ((b"301", b"403"), (b"301 0", b"301 60"), (b"0.040000", b"nan"),
                         (b"0.040000", b"inf"), (b"0.040000", b"0.001000"),
                         (b"0.060000", b"11.000000"), (b"10.0.1.2", b"127.0.0.1"),
                         (b"1.0.0.1 443", b"1.1.1.1 443"), (b" 443", b" 80")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                d.observation(GOOD.replace(old, new), "1.0.0.1")
        with self.assertRaises(RuntimeError):
            d.observation(GOOD + b"injected-private-output", "1.0.0.1")

    def test_clients_and_policy_require_exact_identity(self):
        original = self.pods()
        self.assertEqual(len(d.clients(original, {"owned-agent-0"})), 3)
        for part, key, value in (("metadata", "deletionTimestamp", "now"), ("spec", "nodeName", "production"),
                                 ("spec", "hostNetwork", True), ("status", "phase", "Pending")):
            pods = copy.deepcopy(original)
            pods[0][part][key] = value
            with self.assertRaises(RuntimeError):
                d.clients(pods, {"owned-agent-0"})
        policy = copy.deepcopy(d.POLICY)
        policy["metadata"]["uid"] = "owned-policy"
        d.require_policy(policy, "owned-policy")
        for bad in ("", "foreign"):
            with self.assertRaises(RuntimeError):
                d.require_policy(policy, bad)
        policy["spec"]["ingress"] = []
        with self.assertRaises(RuntimeError):
            d.require_policy(policy, "owned-policy")

    def fixture(self, directory, fail_at=None):
        calls = []
        policy = copy.deepcopy(d.POLICY)
        policy["metadata"]["uid"] = "owned-policy"

        def kubectl(*args, **kwargs):
            if args[:2] == ("get", "pods"):
                return {"items": self.pods()}
            if args[0] == "get":
                return policy if args[1] == "ciliumnetworkpolicy" else {"items": []}
            if args[0] == "create":
                self.assertEqual(json.loads(kwargs["data"]), d.POLICY)
                return policy
            self.assertEqual(args[0], "exec")
            calls.append(args)
            if len(calls) == fail_at:
                raise d.CommandFailure(1, 28, b"curl: (28) SSL connection timeout\n")
            ip = next(p["status"]["podIP"] for p in self.pods() if p["metadata"]["name"] == args[3])
            return GOOD.replace(b"10.0.1.2", ip.encode()).replace(
                b"1.0.0.1 443", args[-1].removeprefix("https://").replace(":", " ").encode())

        return SimpleNamespace(identity=lambda: None, versions={"owned-agent-0": "v1.33.6+k3s1"},
                               work=Path(directory), kubectl=kubectl), calls

    def test_fixed_sample_and_no_retry_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, calls = self.fixture(directory)
            result = d.run(fixture)
            self.assertEqual(len(calls), 36)
            self.assertTrue(result["sample_completed"])
            self.assertFalse(result["full_ha_acceptance"])
            self.assertTrue(all("--retry" in call and "--noproxy" in call and "--insecure" not in call for call in calls))
        with tempfile.TemporaryDirectory() as directory:
            fixture, calls = self.fixture(directory, fail_at=2)
            with self.assertRaises(d.CommandFailure):
                d.run(fixture)
            result = json.loads((Path(directory) / "tls-diagnostic.json").read_text())
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["observations"][-1]["exit_code"], 28)
            self.assertNotIn("sample_completed", result)
            self.assertNotIn("SSL connection timeout", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
