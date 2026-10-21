#!/usr/bin/env python3
"""Exercise HA identity, version-skew and synthetic datastore safety boundaries."""

import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import k3s_qualification as q


class Guards(unittest.TestCase):
    def setUp(self):
        self.name = "qualification-1234abcd"
        self.config = {"current-context": "k3d-" + self.name,
                       "clusters": [{"cluster": {"server": "https://127.0.0.1:64443"}}]}
        self.namespace = {"metadata": {"uid": "synthetic"}}
        self.versions = {"k3d-" + self.name + s: q.BASELINE for s in q.SUFFIXES}
        self.nodes = {"items": [{"metadata": {"name": name, "uid": name + "-uid"},
                                  "status": {"nodeInfo": {"kubeletVersion": version}}}
                                 for name, version in self.versions.items()]}

    def test_cli_version_must_match_before_fixture_creation(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(cilium="owned-cli")
        with patch.object(runner, "command", return_value=b"cilium-cli: v0.20.1-homelab.103 compiled with go1.27.3 on darwin/arm64\n") as command:
            runner.require_cli()
        command.assert_called_once_with(["owned-cli", "version", "--client"])
        for raw in (b"", b"cilium-cli: v0.16.24 compiled with go\n", b"cilium-cli: v0.20.10\n",
                    b"unknown client v0.20.1\n", b"cilium-cli: v0.20.1-custom\n", b"cilium-cli: v0.20.1 compiled with go\n",
                    b"cilium-cli: v0.20.1-homelab.103-custom\n"):
            with patch.object(runner, "command", return_value=raw), patch.object(runner, "create") as create:
                with self.assertRaisesRegex(RuntimeError, "pinned maintained"):
                    runner.run()
            create.assert_not_called()

    def test_ha_identity_rejects_production_extra_missing_and_changed_nodes(self):
        uids = {n["metadata"]["name"]: n["metadata"]["uid"] for n in self.nodes["items"]}
        self.assertEqual(q.require_nodes(self.config, self.name, self.namespace, self.nodes, self.versions, uids), "synthetic")
        for change in ("production", "extra", "missing", "uid", "version", "deleting", "endpoint"):
            config, nodes, namespace = copy.deepcopy((self.config, self.nodes, self.namespace))
            if change == "production":
                namespace["metadata"]["uid"] = q.cq.PRODUCTION_UID
            elif change == "extra":
                nodes["items"].append(copy.deepcopy(nodes["items"][0]))
            elif change == "missing":
                nodes["items"].pop()
            elif change == "uid":
                nodes["items"][0]["metadata"]["uid"] = "different"
            elif change == "version":
                nodes["items"][0]["status"]["nodeInfo"]["kubeletVersion"] = "v1.34.12+k3s1"
            elif change == "deleting":
                nodes["items"][0]["metadata"]["deletionTimestamp"] = "now"
            else:
                config["clusters"][0]["cluster"]["server"] = "https://10.0.20.50:6443"
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                q.require_nodes(config, self.name, namespace, nodes, self.versions, uids)

    def test_only_exact_consecutive_releases_can_move_forward(self):
        previous = q.BASELINE
        for target in q.BINARIES:
            q.require_transition(previous, target)
            previous = target
        for before, after in ((q.BASELINE, "v1.35.9+k3s1"), (previous, q.BASELINE),
                              ("v1.33.0+k3s1", next(iter(q.BINARIES))), (q.BASELINE, "v1.33.99+k3s1")):
            with self.assertRaises(RuntimeError):
                q.require_transition(before, after)

    def test_snapshot_paths_cannot_escape_owned_on_demand_directory(self):
        path = q.DATA + "/server/db/snapshots/qualification-0-k3d-synthetic-123"
        self.assertEqual(q.snapshot_path(path, "qualification-0"), path)
        for bad, prefix in ((path + "/../token", "qualification-0"),
                            (path.replace("snapshots/", ""), "qualification-0"),
                            (path, "qualification-1"), (path, "../qualification-0"),
                            ("/var/lib/production.db", "qualification-0")):
            with self.assertRaises(RuntimeError):
                q.snapshot_path(bad, prefix)

    def test_container_requires_owned_label_and_real_writable_datastore_volume(self):
        name = next(iter(self.versions))
        item = {"Id": "synthetic-container-id", "Name": "/" + name,
                "Config": {"Labels": {"k3d.cluster": self.name}, "Env": ["K3S_TOKEN=synthetic-not-a-credential"]},
                "HostConfig": {}, "Mounts": [{"Destination": q.DATA, "Type": "volume", "Name": "synthetic-volume", "RW": True}]}
        result = q.container_identity(item, name, self.name)
        self.assertNotIn("Env", json.dumps(result))
        self.assertNotIn("synthetic-not-a-credential", json.dumps(result))
        for field in ("label", "name", "volume", "writable", "duplicate"):
            bad = copy.deepcopy(item)
            if field == "label":
                bad["Config"]["Labels"]["k3d.cluster"] = "production"
            elif field == "name":
                bad["Name"] = "/production"
            elif field == "volume":
                bad["Mounts"][0]["Type"] = "bind"
            elif field == "writable":
                bad["Mounts"][0]["RW"] = False
            else:
                bad["Mounts"].append(copy.deepcopy(bad["Mounts"][0]))
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                q.container_identity(bad, name, self.name)

    def test_readiness_retry_never_masks_access_identity_or_unknown_failures(self):
        local_refusal = b"The connection to the server 127.0.0.1:6443 was refused - did you specify the right host or port?\n"
        self.assertEqual(q.failure_classes(local_refusal), ["connection-refused"])
        self.assertTrue(q.read_transport_pending(local_refusal))
        poststart = (b'Error from server (InternalError): an error on the server ("[+]etcd ok\\n'
                     b'[-]poststarthook/start-apiserver-admission-initializer failed: reason withheld\\n[-]postst") '
                     b'has prevented the request from succeeding\n')
        self.assertEqual(q.failure_classes(poststart), ["api-notready"])
        self.assertFalse(q.read_transport_pending(poststart))
        for expected in (poststart, local_refusal, b"connect: connection refused", b"connection reset by peer",
                         b"Unable to connect to the server: EOF", b"server sent GOAWAY; ErrCode=NO_ERROR",
                         b"Error from server (ServiceUnavailable): server is currently unable to handle the request", b"net/http: TLS handshake timeout",
                         b"Error from server (InternalError): [-]etcd failed: reason withheld; readyz check failed"):
            self.assertTrue(q.startup_pending(expected))
            for denial in (b"Forbidden", b"Unauthorized", b"permission denied", b"x509: certificate failed", b"HTTP 403", b"invalid configuration"):
                self.assertFalse(q.startup_pending(expected + b"\n" + denial))
                self.assertFalse(q.read_transport_pending(local_refusal + b"\n" + denial))
        for other in (b"", b"executable not found", b"unknown error"):
            self.assertFalse(q.startup_pending(other))
        self.assertFalse(q.startup_pending(local_refusal.replace(b"127.0.0.1", b"10.0.20.50")))

    def test_mount_enumeration_order_is_irrelevant_but_identity_is_not(self):
        name = next(iter(self.versions))
        item = {"Id": "synthetic-container-id", "Name": "/" + name,
                "Config": {"Labels": {"k3d.cluster": self.name}}, "HostConfig": {},
                "Mounts": [{"Destination": q.DATA, "Type": "volume", "Name": "owned-volume", "RW": True},
                           {"Destination": "/etc/qualification-resolv.conf", "Type": "bind", "Source": "/tmp/owned/resolv.conf", "RW": False}]}
        before = q.container_identity(item, name, self.name)
        item["Mounts"].reverse()
        self.assertEqual(q.container_identity(item, name, self.name), before)
        item["Mounts"][1]["Name"] = "different-volume"
        self.assertNotEqual(q.container_identity(item, name, self.name), before)

    def test_no_peer_may_share_the_restore_source_datastore(self):
        containers = {str(n): {"id": "container-" + str(n), "volume": "volume-" + str(n)} for n in range(5)}
        q.require_separate_datastores(containers)
        for field in ("id", "volume"):
            bad = copy.deepcopy(containers)
            bad["1"][field] = bad["0"][field]
            with self.assertRaisesRegex(RuntimeError, "distinct"):
                q.require_separate_datastores(bad)
        containers.pop("4")
        with self.assertRaisesRegex(RuntimeError, "distinct"):
            q.require_separate_datastores(containers)

    def test_binary_digest_change_is_refused_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            path = Path(directory) / "binary"
            path.write_bytes(b"changed")
            with patch.object(runner, "inspect", return_value={"Id": "synthetic"}), \
                    patch.object(runner, "binary", return_value=(path, "0" * 64)), \
                    patch.object(runner, "command") as command:
                with self.assertRaisesRegex(RuntimeError, "changed after verification"):
                    runner.replace_binary(next(iter(self.versions)), q.BASELINE)
                command.assert_not_called()

    def test_client_skew_is_checked_against_every_live_version(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(kubectl34="client34", kubectl35="client35")
        runner.versions = dict(self.versions)
        with patch.object(runner, "command", return_value=b'{"clientVersion":{"minor":"35"}}'):
            with self.assertRaisesRegex(RuntimeError, "skew"):
                runner.select_client("v1.36.5+k3s1")
        runner.versions = dict.fromkeys(runner.versions, "v1.35.9+k3s1")
        with patch.object(runner, "command", return_value=b'{"clientVersion":{"minor":"35"}}'):
            runner.select_client("v1.36.5+k3s1")
        self.assertEqual(runner.args.kubectl, "client35")

    def test_only_metadata_get_can_retry_classified_transport_without_changing_identity(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.read_retries, runner.count = [], 1
        error = q.CommandFailure(1, 1, b"Unable to connect to the server: read tcp: connection reset by peer")
        with patch.object(q.cq.Qualification, "kubectl", side_effect=[error, {"kind": "NodeList"}]) as native, \
                patch.object(runner, "persist"), patch.object(q.time, "sleep"):
            self.assertEqual(runner.kubectl("get", "nodes"), {"kind": "NodeList"})
            self.assertEqual(native.call_count, 2)
            self.assertEqual(native.call_args_list[0], native.call_args_list[1])
        self.assertEqual(runner.read_retries[0]["classes"], ["connection-reset"])
        for operation, stderr in (("patch", error.stderr), ("get", b"Forbidden: connection reset by peer"),
                                  ("get", b"x509: certificate failed; connection reset by peer"),
                                  ("get", b"unknown failure")):
            with patch.object(q.cq.Qualification, "kubectl", side_effect=q.CommandFailure(1, 1, stderr)) as native:
                with self.assertRaises(q.CommandFailure):
                    runner.kubectl(operation, "nodes")
                self.assertEqual(native.call_count, 1)

    def test_probe_failure_classes_are_diagnostic_only_and_never_retry_permission(self):
        for text, expected in ((b"TimeoutError: timed out\n", "probe-timeout"),
                               (b"socket.timeout: timed out\n", "probe-timeout"),
                               (b"ConnectionRefusedError: [Errno 111] Connection refused\n", "probe-connection-refused"),
                               (b"ConnectionResetError: [Errno 104] Connection reset by peer\n", "probe-connection-reset"),
                               (b"urllib.error.URLError: <urlopen error unknown>\n", "probe-url-error")):
            self.assertIn(expected, q.failure_classes(text))
            self.assertFalse(q.read_transport_pending(text))
            self.assertFalse(q.startup_pending(text))
            self.assertFalse(q.startup_pending(text + b"Forbidden: HTTP 403\n"))
        self.assertEqual(q.failure_classes(b"unknown failure"), ["unclassified"])

    def test_app_probe_records_primary_failure_and_preserves_original_exception(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.l2 = SimpleNamespace(get_lease=lambda: {"owned": True}, nodes={})
        error = q.CommandFailure(300, 1, b"TimeoutError: timed out\n")
        with patch.object(runner, "cilium_ready"), patch.object(runner, "kubectl"), \
                patch.object(runner, "l2_probe", side_effect=error) as probe, \
                patch.object(runner, "record_fixture_failure") as record:
            with self.assertRaises(q.CommandFailure) as caught:
                runner.app_probe()
        self.assertIs(caught.exception, error)
        probe.assert_called_once_with({"owned": True})
        record.assert_called_once_with(error)

    def test_semantic_probe_refusal_is_preserved_before_secondary_diagnostic_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.work = Path(directory)
            runner.l2 = SimpleNamespace(get_lease=lambda: {"owned": True}, nodes={})
            error = RuntimeError("private synthetic refusal")
            with patch.object(runner, "cilium_ready"), patch.object(runner, "kubectl"), \
                    patch.object(runner, "l2_probe", side_effect=error), \
                    patch.object(runner, "fixture_failure_status", side_effect=RuntimeError("secondary")):
                with self.assertRaises(RuntimeError) as caught:
                    runner.app_probe()
            self.assertIs(caught.exception, error)
            primary = (runner.work / "fixture-primary-failure.json").read_text()
            self.assertNotIn("private", primary)
            self.assertEqual(json.loads(primary)["classes"], ["acceptance-refused"])
            self.assertTrue(json.loads((runner.work / "fixture-diagnostic-error.json").read_text())["original_failure_preserved"])

    def test_cilium_recovery_requires_cli_wait_and_five_ready_agents(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(cilium="owned-cli", name=self.name)
        runner.env = {"KUBECONFIG": "owned-private-config"}
        runner.context = "k3d-" + self.name
        pods = [{"status": {"containerStatuses": [{"ready": True}]}} for _ in range(5)]
        with patch.object(runner, "command") as status, patch.object(runner, "kubectl", return_value={"items": pods}):
            self.assertEqual(runner.cilium_ready(), pods)
        self.assertIn("--wait", status.call_args.args[0])
        self.assertIn("--wait-duration=10m", status.call_args.args[0])
        bad_sets = [pods[:4], pods + [pods[0]], copy.deepcopy(pods), copy.deepcopy(pods)]
        bad_sets[2][0]["status"]["containerStatuses"][0]["ready"] = False
        bad_sets[3][0]["status"]["containerStatuses"] = []
        for bad in bad_sets:
            with patch.object(runner, "command"), patch.object(runner, "kubectl", return_value={"items": bad}):
                with self.assertRaisesRegex(RuntimeError, "five ready"):
                    runner.cilium_ready()

    def test_app_probe_waits_for_cilium_before_lease_or_traffic_and_stops_on_failure(self):
        runner = q.Qualification.__new__(q.Qualification)
        trace = []
        runner.l2 = SimpleNamespace(get_lease=lambda: trace.append("lease") or {"owned": True})
        with patch.object(runner, "cilium_ready", side_effect=lambda: trace.append("cilium")), \
                patch.object(runner, "kubectl", side_effect=lambda *a, **k: trace.append("rollout")), \
                patch.object(runner, "l2_probe", side_effect=lambda lease: trace.append("probe") or {"accepted": True}):
            self.assertEqual(runner.app_probe(), {"accepted": True})
        self.assertEqual(trace, ["cilium", "rollout", "lease", "probe"])
        trace.clear()
        failure = q.CommandFailure(1, 2, b"Forbidden")
        with patch.object(runner, "cilium_ready", side_effect=failure), patch.object(runner, "kubectl") as app, \
                patch.object(runner, "record_fixture_failure") as record:
            with self.assertRaises(q.CommandFailure) as caught:
                runner.app_probe()
        self.assertIs(caught.exception, failure)
        self.assertEqual(trace, [])
        app.assert_not_called()
        record.assert_called_once_with(failure)

    def test_l2_probe_measures_current_exact_holder_instead_of_cached_mac(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.args, runner.work, runner.count = SimpleNamespace(name=self.name), Path(directory), 10
            runner.l2_network_id = "a" * 64
            holder = next(iter(self.versions))
            mac = "02:02:03:04:05:06"
            runner.l2 = SimpleNamespace(nodes={holder: "02:01:02:03:04:05"}, external=Mock(return_value={"accepted": True}))
            lease = {"metadata": {"uid": "lease-uid"}, "spec": {"holderIdentity": holder,
                     "leaseTransitions": 3, "renewTime": "2026-10-21T00:00:00Z"}}
            item = {"Id": "owned-container-id", "State": {"Running": True}, "NetworkSettings": {
                "Networks": {"k3d-" + self.name: {"NetworkID": runner.l2_network_id, "EndpointID": "b" * 64,
                                                "MacAddress": mac}}}}
            with patch.object(runner, "inspect", return_value=item) as inspect, \
                    patch.object(runner, "command", return_value=(mac + "\n").encode()) as command:
                self.assertEqual(runner.l2_probe(lease), {"accepted": True})
            inspect.assert_called_once_with(holder)
            command.assert_called_once_with(["docker", "exec", "owned-container-id", "cat", "/sys/class/net/eth0/address"])
            runner.l2.external.assert_called_once_with(lease)
            self.assertEqual(runner.l2.nodes[holder], mac)
            evidence = json.loads((runner.work / "l2-node-network-10.json").read_text())
            self.assertEqual((evidence["container_id"], evidence["mac"], evidence["native_mac_verified"]),
                             (item["Id"], mac, True))
            for fault in ("holder", "container", "network", "endpoint", "extra-network", "missing-mac", "malformed-mac", "zero-mac", "native", "stopped"):
                bad_lease, bad_item = copy.deepcopy((lease, item))
                network = bad_item["NetworkSettings"]["Networks"]["k3d-" + self.name]
                if fault == "holder":
                    bad_lease["spec"]["holderIdentity"] = "unknown-node"
                elif fault == "network":
                    network["NetworkID"] = "c" * 64
                elif fault == "endpoint":
                    network["EndpointID"] = ""
                elif fault == "extra-network":
                    bad_item["NetworkSettings"]["Networks"]["other"] = {}
                elif fault in ("missing-mac", "malformed-mac", "zero-mac"):
                    network["MacAddress"] = {"missing-mac": None, "malformed-mac": "private unexpected value",
                                             "zero-mac": "00:00:00:00:00:00"}[fault]
                elif fault == "stopped":
                    bad_item["State"]["Running"] = False
                runner.l2.external.reset_mock()
                before = (runner.work / "l2-node-network-10.json").read_bytes()
                with self.subTest(fault=fault), patch.object(runner, "inspect", return_value=bad_item,
                        side_effect=RuntimeError("container identity changed") if fault == "container" else None), \
                        patch.object(runner, "command", return_value=b"02:ff:ff:ff:ff:ff\n" if fault == "native" else (mac + "\n").encode()):
                    with self.assertRaises(RuntimeError):
                        runner.l2_probe(bad_lease)
                runner.l2.external.assert_not_called()
                self.assertEqual((runner.work / "l2-node-network-10.json").read_bytes(), before)

    def test_private_merged_capture_reaps_child_without_persisting_stderr(self):
        children = []
        real_popen = subprocess.Popen

        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.work, runner.env, runner.count = Path(directory), os.environ.copy(), 0
            with patch.object(q.subprocess, "Popen", side_effect=start):
                raw = runner.command([sys.executable, "-c", "import os;os.write(2,b'private synthetic restore status')"], merge_stderr=True)
            self.assertEqual(raw, b"private synthetic restore status")
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(all(stream.closed for stream in (children[0].stdin, children[0].stdout)))
        with self.assertRaises(ProcessLookupError):
            os.kill(children[0].pid, 0)

    def test_restore_address_requires_exact_running_owned_bridge_endpoint(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(name=self.name)
        runner.l2_network_id = "a" * 64
        node = next(iter(self.versions))
        item = {"State": {"Running": True}, "NetworkSettings": {"Networks": {
            "k3d-" + self.name: {"NetworkID": runner.l2_network_id, "EndpointID": "b" * 64,
                                 "IPAddress": "172.31.240.3", "IPAMConfig": {"IPv4Address": "172.31.240.3"}}}}}
        with patch.object(runner, "inspect", return_value=item) as inspect:
            self.assertEqual(runner.node_ip(node), "172.31.240.3")
        inspect.assert_called_once_with(node)
        for fault in ("network", "endpoint", "extra-network", "stopped", "dynamic", "static-mismatch", "missing", "invalid", "outside", "ipv6",
                      "network-address", "gateway", "broadcast", "client", "vip"):
            bad = copy.deepcopy(item)
            network = bad["NetworkSettings"]["Networks"]["k3d-" + self.name]
            if fault == "network":
                network["NetworkID"] = "c" * 64
            elif fault == "endpoint":
                network["EndpointID"] = ""
            elif fault == "extra-network":
                bad["NetworkSettings"]["Networks"]["other"] = {}
            elif fault == "stopped":
                bad["State"]["Running"] = False
            elif fault in ("dynamic", "static-mismatch"):
                network["IPAMConfig"] = None if fault == "dynamic" else {"IPv4Address": "172.31.240.20"}
            else:
                network["IPAddress"] = {"missing": "", "invalid": "unexpected private text", "outside": "10.0.20.10",
                    "ipv6": "fd00::3", "network-address": "172.31.240.0", "gateway": "172.31.240.1",
                    "broadcast": "172.31.240.255", "client": "172.31.240.10", "vip": "172.31.240.226"}[fault]
            with self.subTest(fault=fault), patch.object(runner, "inspect", return_value=bad):
                with self.assertRaises(RuntimeError):
                    runner.node_ip(node)

    def test_agent_static_setup_preserves_full_configuration_and_exact_addresses(self):
        for fault in (None, "null-aliases", "empty-aliases", "alias", "alias-type", "existing-static", "configuration", "wrong-subnet"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                runner, nodes, _ = self.affinity_fixture(directory)
                runner.containers = {n: q.container_identity(item, n, self.name) for n, item in nodes.items()}
                network_id = "a" * 64
                for i, (name, item) in enumerate(nodes.items()):
                    address = "172.31.240." + str(i + 3)
                    item["State"] = {"Running": True, "Status": "running"}
                    item["NetworkSettings"] = {"Networks": {"k3d-" + self.name: {
                        "NetworkID": network_id, "EndpointID": "b" * 64, "IPAddress": address,
                        "Aliases": [name], "IPAMConfig": {"IPv4Address": address} if "-server-" in name else None}}}
                agent = "k3d-" + self.name + "-agent-0"
                endpoint = nodes[agent]["NetworkSettings"]["Networks"]["k3d-" + self.name]
                if fault in ("null-aliases", "empty-aliases", "alias-type"):
                    endpoint["Aliases"] = {"null-aliases": None, "empty-aliases": [], "alias-type": {}}[fault]
                elif fault == "alias":
                    endpoint["Aliases"] = ["unexpected-private-alias"]
                elif fault == "existing-static":
                    endpoint["IPAMConfig"] = {"IPv4Address": endpoint["IPAddress"]}
                calls = []

                def command(argv):
                    calls.append(argv)
                    if argv[:3] == ["docker", "network", "inspect"]:
                        return json.dumps([{"Id": network_id, "IPAM": {"Config": [{"Subnet": "10.0.20.0/24" if fault == "wrong-subnet" else q.l2.NETWORK}]}}]).encode()
                    if argv[:2] == ["docker", "inspect"]:
                        return json.dumps([nodes[argv[2]]]).encode()
                    item = next(n for n in nodes.values() if n["Id"] == argv[-1])
                    if argv[1] in ("stop", "start"):
                        item["State"] = {"Running": argv[1] == "start", "Status": "running" if argv[1] == "start" else "exited"}
                    elif argv[:3] == ["docker", "network", "disconnect"]:
                        item["NetworkSettings"]["Networks"] = {}
                    else:
                        self.assertEqual(argv[:3], ["docker", "network", "connect"])
                        address = argv[3].split("=", 1)[1]
                        item["NetworkSettings"]["Networks"] = {"k3d-" + self.name: {
                            "NetworkID": network_id, "EndpointID": "c" * 64, "IPAddress": address,
                            "IPAMConfig": {"IPv4Address": address}}}
                        if fault == "configuration":
                            item["HostConfig"]["Memory"] = 1
                    return b""

                runner.command = command
                if fault not in (None, "null-aliases", "empty-aliases"):
                    with self.assertRaises(RuntimeError):
                        runner.pin_agent_ips()
                    self.assertFalse((runner.work / "guest-static-node-ips.json").exists())
                    self.assertEqual(sum(c[:2] == ["docker", "stop"] for c in calls), 1 if fault == "configuration" else 0)
                else:
                    runner.pin_agent_ips()
                    evidence = json.loads((runner.work / "guest-static-node-ips.json").read_text())
                    self.assertEqual(len(evidence["node_ips"]), 5)
                    self.assertTrue(evidence["same_container_configuration"])
                    self.assertEqual(sum(c[:3] == ["docker", "network", "connect"] for c in calls), 2)
                    self.assertEqual({n: q.container_identity(item, n, self.name) for n, item in nodes.items()}, runner.containers)

    def test_restore_advertises_original_node_ip_and_refuses_changed_identity(self):
        for fault in (None, "kubernetes-address", "duplicate-address", "extra-node", "restart-address"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                runner = q.Qualification.__new__(q.Qualification)
                runner.work, runner.versions = Path(directory), dict(self.versions)
                runner.l2_network_id = "a" * 64
                names = list(runner.versions)
                addresses = {n: "172.31.240." + str(i + 3) for i, n in enumerate(names)}
                nodes = [{"metadata": {"name": n}, "status": {"addresses": [{"type": "InternalIP", "address": ip}]},
                          "spec": {}} for n, ip in addresses.items()]
                if fault == "kubernetes-address":
                    nodes[0]["status"]["addresses"][0]["address"] = "172.31.240.20"
                elif fault == "duplicate-address":
                    addresses[names[1]] = addresses[names[0]]
                elif fault == "extra-node":
                    nodes.append(copy.deepcopy(nodes[0]))
                snapshot = {"previous": q.BASELINE, "target": next(iter(q.BINARIES)), "prefix": "qualification-0",
                            "path": q.DATA + "/server/db/snapshots/qualification-0-owned-123", "sha256": "c" * 64,
                            "marker_data": {"value": "before"}, "marker_uid": "marker-uid"}

                def native(command):
                    if command[:2] == ["docker", "exec"]:
                        return (("c" if command[-1] == snapshot["path"] else "d") * 64).encode()
                    return b""

                def kubectl(*args, **_kwargs):
                    if args[:2] == ("get", "nodes"):
                        return {"items": nodes}
                    if args[:2] == ("get", "configmap"):
                        return {"metadata": {"uid": snapshot["marker_uid"]}, "data": snapshot["marker_data"]}
                    return b""

                measured = list(addresses.values()) + [addresses[n] for n in names]
                if fault == "restart-address":
                    measured[5] = "172.31.240.20"
                with patch.object(runner, "ready"), patch.object(runner, "node_ip", side_effect=measured), \
                        patch.object(runner, "inspect", side_effect=lambda n, **kw: {"Id": n}), \
                        patch.object(runner, "command", side_effect=native) as command, \
                        patch.object(runner, "kubectl", side_effect=kubectl) as api, \
                        patch.object(runner, "replace_binary"), patch.object(runner, "helper") as helper, \
                        patch.object(runner, "select_client"), patch.object(runner, "wait_api") as wait_api, \
                        patch.object(runner, "binary", return_value=(None, "d" * 64)), \
                        patch.object(runner, "checkpoint") as checkpoint:
                    if fault:
                        with self.assertRaises(RuntimeError):
                            runner.rollback(snapshot)
                        checkpoint.assert_not_called()
                        wait_api.assert_not_called()
                        self.assertFalse(snapshot.get("matching_version_restore_accepted", False))
                        if fault != "restart-address":
                            helper.assert_not_called()
                            self.assertFalse(any(c.args[0] == "drain" for c in api.call_args_list))
                            self.assertFalse(any(c.args[0][:2] == ["docker", "stop"] for c in command.call_args_list))
                            continue
                    else:
                        runner.rollback(snapshot)
                        checkpoint.assert_called_once_with(q.BASELINE, "rollback-" + snapshot["target"])
                        self.assertTrue(snapshot["matching_version_restore_accepted"])
                    reset = helper.call_args_list[0]
                    self.assertEqual(reset.args[0], names[0])
                    self.assertIn("--node-ip=" + addresses[names[0]], reset.args[1])
                    self.assertIn("--token-file=" + q.DATA + "/server/token", reset.args[1])
                    self.assertEqual(reset.kwargs, {"version": q.BASELINE, "restore": True})

    def test_fixture_failure_evidence_excludes_injected_data_and_termination_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.work = Path(directory)
            runner.containers = {"synthetic-node": {}}
            runner.l2 = SimpleNamespace(service_uid="owned-service", nodes={"synthetic-node": "02:01:02:03:04:05"}, get_lease=lambda: {
                "metadata": {"uid": "owned-lease"}, "spec": {"holderIdentity": "synthetic-node",
                "leaseTransitions": 1, "renewTime": "2026-10-21T00:00:00Z"}})
            node = {"Id": "owned-container", "RestartCount": 1,
                    "State": {"Running": True, "Status": "running", "OOMKilled": False,
                              "ExitCode": 0, "StartedAt": "now", "FinishedAt": "before", "Error": "private runtime error"}}
            pod = {"metadata": {"name": "echo-same-node-synthetic", "namespace": "cilium-test-1", "uid": "owned-pod"},
                   "spec": {"containers": [{"name": "echo-same-node", "image": q.ECHO_IMAGE, "env": copy.deepcopy(q.ECHO_ENV)}]},
                   "status": {"phase": "Running", "containerStatuses": [{"name": "echo-same-node", "ready": False,
                       "restartCount": 3, "state": {"waiting": {"message": "private waiting text"}},
                       "lastState": {"terminated": {"exitCode": 134, "reason": "Error", "message": "private termination text"}}}]}}
            for injected in (None, "env", "envFrom", "volumeMounts", "image", "namespace"):
                fixture = copy.deepcopy(pod)
                spec = fixture["spec"]["containers"][0]
                if injected == "image":
                    spec["image"] = "unknown-image"
                elif injected == "namespace":
                    fixture["metadata"]["namespace"] = "kube-system"
                elif injected:
                    spec[injected] = [{"name": "application-data"}]
                with patch.object(runner, "identity") as identity, patch.object(runner, "inspect", return_value=node), \
                        patch.object(runner, "kubectl", side_effect=[{"items": [fixture]}, b"public fixture failure"]) as native:
                    runner.fixture_failure_status()
                identity.assert_called_once()
                self.assertEqual(native.call_count, 2 if injected is None else 1)
                text = (Path(directory) / "fixture-failure-status.json").read_text()
                self.assertNotIn("private", text)
                self.assertNotIn("private", (Path(directory) / "fixture-node-failure-status.json").read_text())
                self.assertIn('"last_exit_code": 134', text)
                for path in Path(directory).glob("*.log.gz"):
                    path.unlink()

    def test_failure_diagnostics_stop_on_access_and_preserve_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.work = Path(directory)
            for stderr in (b"Forbidden", b"x509: certificate failed"):
                with patch.object(runner, "fixture_failure_status") as diagnostic:
                    runner.record_fixture_failure(q.CommandFailure(1, 1, stderr))
                diagnostic.assert_not_called()
                primary = json.loads((runner.work / "fixture-primary-failure.json").read_text())
                self.assertEqual(primary["number"], 1)
                self.assertEqual(primary["stderr_sha256"], q.hashlib.sha256(stderr).hexdigest())
                self.assertNotIn(stderr.decode(), json.dumps(primary))
            with patch.object(runner, "fixture_failure_status", side_effect=RuntimeError("diagnostic failed")):
                runner.record_fixture_failure(q.CommandFailure(56, 2, b"private synthetic primary failure"))
            result = json.loads((runner.work / "fixture-diagnostic-error.json").read_text())
            self.assertTrue(result["original_failure_preserved"])
            self.assertNotIn("diagnostic failed", json.dumps(result))
            primary = json.loads((runner.work / "fixture-primary-failure.json").read_text())
            self.assertEqual((primary["number"], primary["exit_code"]), (56, 2))
            self.assertEqual(primary["stderr_sha256"], q.hashlib.sha256(b"private synthetic primary failure").hexdigest())
            self.assertNotIn("private", json.dumps(primary))

    def test_server_log_evidence_keeps_only_bounded_typed_events_and_hashes(self):
        sentinel = b"private-synthetic-sentinel"
        lines = [b"2026-10-21T07:04:51.261207337Z leaderelection lost " + sentinel,
                 b"2026-02-30T07:04:51Z kubelet exited " + sentinel,
                 b"2026-10-21T07:04:51.1234567890Z containerd exited " + sentinel,
                 sentinel + b" panic: signal: killed",
                 b"2026-10-21T07:05:00Z failed to renew lease " + sentinel]
        raw = b"\n".join(lines)
        result = q.server_log_evidence(raw)
        self.assertNotIn(sentinel.decode(), json.dumps(result))
        self.assertEqual(result["sha256"], q.hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["bytes"], len(raw))
        self.assertEqual(result["matching_lines"], 5)
        self.assertFalse(result["raw_retained"])
        self.assertEqual(result["last_events"][0]["timestamp"], "2026-10-21T07:04:51.261207337Z")
        self.assertEqual([e["timestamp"] for e in result["last_events"]][1:4], [None, None, None])
        self.assertEqual(result["last_events"][-1]["timestamp"], "2026-10-21T07:05:00Z")
        self.assertEqual(result["last_events"][3]["categories"], ["panic", "out-of-memory"])
        self.assertEqual(result["last_events"][0]["line_sha256"], q.hashlib.sha256(lines[0]).hexdigest())
        many = [b"2026-10-21T07:05:00Z LEADERELECTION LOST " + str(i).encode() for i in range(25)]
        bounded = q.server_log_evidence(b"\n".join(many))
        self.assertEqual(bounded["matching_lines"], 25)
        self.assertEqual(bounded["counts"], {"leader-election-lost": 25})
        self.assertEqual(len(bounded["last_events"]), 20)
        self.assertEqual(bounded["last_events"][0]["line_sha256"], q.hashlib.sha256(many[5]).hexdigest())
        self.assertEqual(q.server_log_evidence(sentinel)["last_events"], [])
        self.assertEqual(q.server_log_evidence(b"x" * (4 * 1024 * 1024))["matching_lines"], 0)
        for invalid in ("not bytes", None, b"x" * (4 * 1024 * 1024 + 1)):
            with self.assertRaisesRegex(RuntimeError, "byte contract"):
                q.server_log_evidence(invalid)

    def test_server_failure_logs_require_original_owned_server_and_private_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, nodes, _ = self.affinity_fixture(directory)
            node = next(iter(self.versions))
            runner.containers = {name: q.container_identity(item, name, self.name) for name, item in nodes.items()}
            item = nodes[node]
            expected = ["docker", "logs", "--timestamps", "--tail=1000", item["Id"]]

            def command(argv, **kwargs):
                if argv == ["docker", "inspect", node]:
                    return json.dumps([item]).encode()
                self.assertEqual(argv, expected)
                self.assertEqual(kwargs, {"private": True, "merge_stderr": True})
                return b"2026-10-21T07:04:51Z leaderelection lost private-synthetic-sentinel\n"

            with patch.object(runner, "command", side_effect=command) as capture:
                runner.server_failure_logs(node)
                self.assertEqual(capture.call_count, 2)
            result = json.loads((runner.work / (node + "-server-failure.json")).read_text())
            self.assertEqual(result["container_id"], item["Id"])
            self.assertNotIn("private-synthetic-sentinel", json.dumps(result))
            for foreign in ("production-server-0", "k3d-" + self.name + "-agent-0"):
                with patch.object(runner, "command") as capture, self.assertRaises(RuntimeError):
                    runner.server_failure_logs(foreign)
                capture.assert_not_called()
            with patch.object(runner, "containers", {}), patch.object(runner, "command") as capture:
                with self.assertRaises(RuntimeError):
                    runner.server_failure_logs(node)
            capture.assert_not_called()
            for field in ("Id", "Config", "Mounts"):
                bad = copy.deepcopy(nodes[node])
                if field == "Id":
                    bad[field] = "replaced-container"
                elif field == "Config":
                    bad[field]["Labels"]["k3d.cluster"] = "foreign"
                else:
                    bad[field][0]["Name"] = "foreign-data"
                with patch.object(runner, "command", return_value=json.dumps([bad]).encode()) as capture:
                    with self.assertRaises(RuntimeError):
                        runner.server_failure_logs(node)
                capture.assert_called_once_with(["docker", "inspect", node])

    def test_guest_kernel_configuration_never_reaches_wrong_or_occupied_daemon(self):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(docker_server="colima-q")
        for responses, count in (([b"production-docker"], 1), ([b"colima-q", b"existing-container"], 2)):
            with patch.object(runner, "command", side_effect=responses) as command:
                with self.assertRaisesRegex(RuntimeError, "expected empty owned VM"):
                    runner.create()
                self.assertEqual(command.call_count, count)
                self.assertFalse(any("run" in call.args[0] for call in command.call_args_list))

    def test_native_api_uses_multicall_alias_without_redundant_subcommand(self):
        runner = q.Qualification.__new__(q.Qualification)
        node = next(iter(self.versions))
        with patch.object(runner, "inspect") as inspect, \
                patch.object(runner, "command", return_value=b"[+]etcd ok\nreadyz check passed\n") as command:
            runner.wait_api(node)
        inspect.assert_called_once_with(node)
        self.assertEqual(command.call_args.args[0][:5], ["docker", "exec", node, "/bin/kubectl", "get"])
        self.assertNotIn("kubectl", command.call_args.args[0])

    def test_kubelet_cgroup_wait_requires_exact_positive_predicate(self):
        runner = q.Qualification.__new__(q.Qualification)
        node = "k3d-" + self.name + "-agent-0"
        absent = q.CommandFailure(1, 1, b"")
        with patch.object(runner, "inspect") as inspect, \
                patch.object(runner, "command", side_effect=[absent, b""]) as command, \
                patch.object(q.time, "monotonic", side_effect=[0, 1]), patch.object(q.time, "sleep") as sleep:
            self.assertEqual(runner.wait_kubelet_cgroup(node), 2)
        self.assertEqual(inspect.call_count, 2)
        self.assertTrue(all(call.args[0] == ["docker", "exec", node, "test", "-d", "/sys/fs/cgroup/kubepods"]
                            for call in command.call_args_list))
        sleep.assert_called_once_with(1)
        for error in (q.CommandFailure(1, 2, b""), q.CommandFailure(1, 1, b"permission denied"),
                      q.CommandFailure(1, 1, b"Forbidden"), q.CommandFailure(1, 1, b"x509: certificate failed"),
                      q.CommandFailure(1, 1, b"unknown error"), absent):
            with self.subTest(code=error.code, stderr=error.stderr), patch.object(runner, "inspect"), \
                    patch.object(runner, "command", side_effect=error) as command, \
                    patch.object(q.time, "monotonic", side_effect=[0, 600]), patch.object(q.time, "sleep") as sleep:
                with self.assertRaises(q.CommandFailure):
                    runner.wait_kubelet_cgroup(node)
                command.assert_called_once()
                sleep.assert_not_called()
        with patch.object(runner, "inspect", side_effect=RuntimeError("identity changed")), \
                patch.object(runner, "command") as command:
            with self.assertRaises(RuntimeError):
                runner.wait_kubelet_cgroup(node)
        command.assert_not_called()

    def affinity_fixture(self, directory, fault=None):
        runner = q.Qualification.__new__(q.Qualification)
        runner.args = SimpleNamespace(name=self.name)
        runner.work, runner.versions, runner.containers = Path(directory), dict(self.versions), {}
        nodes = {name: {"Id": name + "-container", "Name": "/" + name,
                        "Config": {"Labels": {"k3d.cluster": self.name}},
                        "HostConfig": {"CpusetCpus": "", "Memory": 0},
                        "Mounts": [{"Destination": q.DATA, "Type": "volume", "Name": name + "-data", "RW": True}]}
                 for name in self.versions}
        first = next(iter(nodes.values()))
        if fault == "owner":
            first["Config"]["Labels"]["k3d.cluster"] = "production"
        elif fault == "existing":
            first["HostConfig"]["CpusetCpus"] = "0"
        updates = []

        def command(argv):
            if argv[:2] == ["docker", "info"]:
                return b"6" if fault == "guest" else b"8"
            if argv[:2] == ["docker", "inspect"]:
                return json.dumps([nodes[argv[2]]]).encode()
            self.assertEqual(argv[:2], ["docker", "update"])
            item = next(n for n in nodes.values() if n["Id"] == argv[3])
            item["HostConfig"]["CpusetCpus"] = argv[2].split("=", 1)[1]
            if fault == "configuration":
                item["HostConfig"]["Memory"] = 1
            updates.append(argv[3])
            return b""

        runner.command = command
        return runner, nodes, updates

    def test_cpu_affinity_covers_distinct_owned_nodes_without_shared_cpus(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, nodes, updates = self.affinity_fixture(directory)
            runner.bind_cpus()
            bindings = json.loads((Path(directory) / "guest-cpu-affinity.json").read_text())
            assigned = []
            for name, binding in bindings.items():
                self.assertEqual(binding["id"], nodes[name]["Id"])
                bounds = list(map(int, binding["cpus"].split("-")))
                cpus = list(range(bounds[0], bounds[-1] + 1))
                self.assertEqual(len(cpus), 2 if "-server-" in name else 1)
                assigned.extend(cpus)
            self.assertEqual(sorted(assigned), list(range(8)))
            self.assertEqual(set(updates), {n["Id"] for n in nodes.values()})

    def test_cpu_affinity_refuses_wrong_guest_owner_existing_limits_or_other_changes(self):
        for fault in ("guest", "owner", "existing", "configuration"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                runner, _, updates = self.affinity_fixture(directory, fault)
                with self.assertRaises(RuntimeError):
                    runner.bind_cpus()
                self.assertEqual(len(updates), 1 if fault == "configuration" else 0)
                self.assertFalse((Path(directory) / "guest-cpu-affinity.json").exists())


if __name__ == "__main__":
    unittest.main()
