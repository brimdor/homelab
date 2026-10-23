#!/usr/bin/env python3
"""Reject incomplete or contradictory native L2 evidence."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
import socket
import struct
import unittest

import cilium_l2_qualification as l2
import cilium_qualification as cq


class L2Guards(unittest.TestCase):
    def test_client_requires_one_network_exact_raw_capability_and_no_mounts(self):
        client = {"NetworkSettings": {"Networks": {"k3d-fixture": {"IPAddress": "172.31.240.10"}}},
                  "Mounts": [], "HostConfig": {"CapAdd": ["NET_RAW"], "CapDrop": ["ALL"],
                                               "Privileged": False, "ReadonlyRootfs": True}}
        for capability in ("NET_RAW", "CAP_NET_RAW"):
            client["HostConfig"]["CapAdd"] = [capability]
            l2.validate_client(client, "fixture")
        for change in ({"CapAdd": ["SYS_ADMIN"]}, {"CapAdd": ["NET_RAW", "NET_ADMIN"]},
                       {"CapDrop": []}, {"Privileged": True}, {"ReadonlyRootfs": False}):
            bad = copy.deepcopy(client)
            bad["HostConfig"].update(change)
            with self.assertRaises(RuntimeError):
                l2.validate_client(bad, "fixture")
        for mutate in (lambda c: c["Mounts"].append({"Source": "/original"}),
                       lambda c: c["NetworkSettings"]["Networks"].update(other={"IPAddress": "1.2.3.4"}),
                       lambda c: c["NetworkSettings"]["Networks"]["k3d-fixture"].update(IPAddress="172.31.240.11")):
            bad = copy.deepcopy(client)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                l2.validate_client(bad, "fixture")

    def test_probe_evidence_excludes_unexpected_strings_and_fields(self):
        result = {"vip": "private unexpected value", "arp_macs": ["private unexpected value"],
                  "http_statuses": ["private unexpected value"], "extra": "private unexpected value"}
        evidence = l2.probe_evidence(result)
        self.assertNotIn("private", json.dumps(evidence))
        self.assertFalse(evidence["vip_matches"])
        self.assertIsNone(evidence["arp_macs"])
        self.assertIsNone(evidence["http_statuses"])
        self.assertIsNone(l2.probe_evidence([])["arp_macs"])
        with self.assertRaises(RuntimeError):
            l2.validate_probe([], "02:01:02:03:04:05")

    def test_rejected_probe_preserves_observation_before_raising(self):
        client = {"NetworkSettings": {"Networks": {"k3d-fixture": {"IPAddress": "172.31.240.10"}}},
                  "Mounts": [], "HostConfig": {"CapAdd": ["NET_RAW"], "CapDrop": ["ALL"],
                                               "Privileged": False, "ReadonlyRootfs": True}}
        result = {"vip": l2.VIP, "arp_macs": ["02:02:03:04:05:06"], "http_statuses": [200] * 10}
        with tempfile.TemporaryDirectory() as directory:
            q = SimpleNamespace(args=SimpleNamespace(name="fixture"), work=Path(directory), count=300,
                identity=Mock(), command=Mock(side_effect=[json.dumps([client]).encode(),
                    b'{"CapEff":8192,"CapBnd":8192}', json.dumps(result).encode()]))
            fixture = l2.L2Qualification(q)
            fixture.nodes = {"node-a": "02:01:02:03:04:05", "node-b": "02:02:03:04:05:06"}
            with self.assertRaisesRegex(RuntimeError, "ARP/HTTP"):
                fixture.external(self.lease())
            evidence = json.loads((q.work / "l2-probe-300.json").read_text())
            self.assertEqual(evidence["arp_macs"], result["arp_macs"])
            self.assertEqual(evidence["holder"], "node-a")
            self.assertEqual(q.command.call_count, 3)

    def pool(self):
        return {"metadata": {"uid": "pool-uid", "resourceVersion": "37"},
                "spec": {"cidrs": [{"cidr": l2.CIDR}], "allowFirstLastIPs": "No"}}

    def lease(self, holder="node-a", transitions=2):
        return {"metadata": {"uid": "lease-uid"},
                "spec": {"holderIdentity": holder, "leaseTransitions": transitions,
                         "renewTime": "2026-10-20T12:00:00Z"}}

    def test_native_arp_parser_rejects_wrong_and_truncated_frames(self):
        mac = bytes.fromhex("020102030405")
        raw = b"\xff" * 6 + mac + struct.pack("!H", 0x0806)
        raw += struct.pack("!HHBBH", 1, 0x0800, 6, 4, 2) + mac + socket.inet_aton(l2.VIP)
        raw += b"\x00" * 6 + socket.inet_aton("172.31.240.10")
        self.assertEqual(l2.arp_response(raw, l2.VIP), "02:01:02:03:04:05")
        for length in range(42):
            self.assertIsNone(l2.arp_response(raw[:length], l2.VIP))
        for index in (6, 12, 14, 16, 18, 19, 21, 28):
            changed = bytearray(raw)
            changed[index] ^= 1
            self.assertIsNone(l2.arp_response(bytes(changed), l2.VIP))
        self.assertIsNone(l2.arp_response(raw, "172.31.240.227"))
        compile(l2.PROBE, "<native-probe>", "exec")
        compile(l2.SERVER, "<native-server>", "exec")

    def test_arp_http_acceptance_requires_exact_single_holder_and_ten_successes(self):
        proof = {"vip": l2.VIP, "arp_macs": ["02:01:02:03:04:05"], "http_statuses": [200] * 10}
        l2.validate_probe(proof, "02:01:02:03:04:05")
        for key, value in [("vip", "10.0.20.226"), ("arp_macs", []),
                           ("arp_macs", ["02:01:02:03:04:05", "02:02:03:04:05:06"]),
                           ("arp_macs", ["02:02:03:04:05:06"]), ("http_statuses", [200] * 9),
                           ("http_statuses", [200] * 9 + [503])]:
            bad = dict(proof, **{key: value})
            with self.assertRaises(RuntimeError):
                l2.validate_probe(bad, "02:01:02:03:04:05")

    def test_migration_tests_uid_revision_and_original_range(self):
        pool = self.pool()
        patch = l2.migration_patch(pool)
        self.assertEqual(patch[:3], [
            {"op": "test", "path": "/metadata/uid", "value": "pool-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "37"},
            {"op": "test", "path": "/spec/cidrs", "value": [{"cidr": l2.CIDR}]}])
        self.assertEqual(patch[-2:], [{"op": "add", "path": "/spec/blocks", "value": [{"cidr": l2.CIDR}]},
                                     {"op": "remove", "path": "/spec/cidrs"}])
        for changes in ({"blocks": [{"cidr": l2.CIDR}]}, {"cidrs": [{"cidr": "10.0.20.224/27"}]},
                        {"allowFirstLastIPs": "Yes"}):
            bad = self.pool()
            bad["spec"].update(changes)
            with self.assertRaises(RuntimeError):
                l2.migration_patch(bad)
        for key in ("uid", "resourceVersion"):
            bad = self.pool()
            del bad["metadata"][key]
            with self.assertRaises(RuntimeError):
                l2.migration_patch(bad)

    def test_migrated_pool_must_preserve_uid_range_and_boundary_reservation(self):
        pool = self.pool()
        pool["spec"]["blocks"] = pool["spec"].pop("cidrs")
        l2.validate_pool(pool, "pool-uid", migrated=True)
        for key, value in [("blocks", [{"cidr": "172.31.240.0/24"}]), ("allowFirstLastIPs", "Yes"),
                           ("cidrs", [{"cidr": l2.CIDR}])]:
            bad = copy.deepcopy(pool)
            bad["spec"][key] = value
            with self.assertRaises(RuntimeError):
                l2.validate_pool(bad, "pool-uid", migrated=True)
        with self.assertRaises(RuntimeError):
            l2.validate_pool(pool, "replacement-uid", migrated=True)

    def test_service_replacement_or_new_vip_never_counts_as_preserved_allocation(self):
        service = {"metadata": {"uid": "service-uid"},
                   "spec": {"type": "LoadBalancer", "externalTrafficPolicy": "Cluster"},
                   "status": {"loadBalancer": {"ingress": [{"ip": l2.VIP}]}}}
        l2.validate_service(service, "service-uid")
        service["status"]["loadBalancer"]["ingress"][0]["ipMode"] = "VIP"
        l2.validate_service(service, "service-uid")
        for mutator in [lambda s: s["metadata"].update(uid="replacement"),
                        lambda s: s["spec"].update(externalTrafficPolicy="Local"),
                        lambda s: s["status"]["loadBalancer"]["ingress"][0].update(ipMode="Proxy"),
                        lambda s: s["status"]["loadBalancer"].update(ingress=[{"ip": l2.VIP}] * 2),
                        lambda s: s["status"]["loadBalancer"].update(ingress=[]),
                        lambda s: s["status"]["loadBalancer"].update(ingress=[{"ip": "172.31.240.227"}])]:
            bad = copy.deepcopy(service)
            mutator(bad)
            with self.assertRaises(RuntimeError):
                l2.validate_service(bad, "service-uid")

    def test_failover_requires_same_lease_new_eligible_holder_and_transition(self):
        first = self.lease()
        second = self.lease("node-b", 3)
        l2.validate_lease(second, {"node-a", "node-b"}, previous=first)
        for bad in (self.lease("node-a", 3), self.lease("node-b", 2), self.lease("unknown", 3)):
            with self.assertRaises(RuntimeError):
                l2.validate_lease(bad, {"node-a", "node-b"}, previous=first)
        second["metadata"]["uid"] = "replacement-lease"
        with self.assertRaises(RuntimeError):
            l2.validate_lease(second, {"node-a", "node-b"}, previous=first)

    def test_recreated_lease_requires_observed_gap_exact_identity_and_new_renewal(self):
        first = self.lease()
        second = self.lease("node-b", 0)
        second["metadata"].update(uid="replacement-lease", namespace="kube-system",
                                  name="cilium-l2announce-" + l2.NAMESPACE + "-" + l2.NAME,
                                  creationTimestamp="2026-10-20T12:00:00Z")
        second["spec"]["renewTime"] = "2026-10-20T12:00:00.500Z"
        l2.validate_lease(second, {"node-a", "node-b"}, previous=first, observed_absence=True)
        for field, value in (("namespace", "other"), ("name", "other"), ("deletionTimestamp", "now"),
                             ("creationTimestamp", "2026-10-20T11:59:59Z"),
                             ("creationTimestamp", "2026-10-20T12:00:01Z"),
                             ("creationTimestamp", "invalid")):
            bad = copy.deepcopy(second)
            bad["metadata"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                l2.validate_lease(bad, {"node-a", "node-b"}, previous=first, observed_absence=True)
        second["spec"]["renewTime"] = first["spec"]["renewTime"]
        with self.assertRaises(RuntimeError):
            l2.validate_lease(second, {"node-a", "node-b"}, previous=first, observed_absence=True)

    def test_transfer_observes_absence_but_never_suppresses_access_failures(self):
        q = SimpleNamespace(args=SimpleNamespace(name="qualification-test"),
                            kubectl=Mock(side_effect=[b"", json.dumps(self.lease("node-b", 3)).encode()]))
        runner = l2.L2Qualification(q)
        runner.nodes = {"node-a": "unused", "node-b": "unused"}
        with patch.object(l2.time, "sleep"):
            self.assertEqual(runner.wait_transfer(self.lease())["spec"]["holderIdentity"], "node-b")
        self.assertTrue(all(call.kwargs == {"json_output": False} and
                            "--ignore-not-found" in call.args for call in q.kubectl.call_args_list))
        denial = RuntimeError("Forbidden")
        q.kubectl.side_effect = denial
        with self.assertRaises(RuntimeError) as caught:
            runner.wait_transfer(self.lease())
        self.assertIs(caught.exception, denial)

    def test_optional_lease_uses_actual_cli_json_output_without_parsing_empty_result(self):
        q = cq.Qualification.__new__(cq.Qualification)
        q.args = SimpleNamespace(name="qualification-test", kubectl="owned-kubectl")
        q.work, q.env, q.context = Path("/owned"), {"KUBECONFIG": "/owned/kubeconfig"}, "owned-context"
        q.command = Mock(side_effect=[b"", json.dumps(self.lease("node-b", 3)).encode()])
        runner = l2.L2Qualification(q)
        self.assertIsNone(runner.get_lease(optional=True))
        self.assertEqual(runner.get_lease(optional=True), self.lease("node-b", 3))
        for call in q.command.call_args_list:
            self.assertEqual(call.args[0][-3:], ["--ignore-not-found", "-o", "json"])
            self.assertEqual(call.args[0].count("-o"), 1)

    def test_manifest_is_synthetic_nonroot_and_has_no_credentials_or_host_mounts(self):
        objects = l2.manifest()["items"]
        deployment = next(x for x in objects if x["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 65532)
        self.assertNotIn("volumes", pod)
        c = pod["containers"][0]
        self.assertNotIn("env", c)
        self.assertIn("@sha256:", c["image"])
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertNotIn("10.0.20.", str(objects))


if __name__ == "__main__":
    unittest.main()
