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
from unittest.mock import patch

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
        for expected in (poststart, local_refusal, b"connect: connection refused", b"Error from server (ServiceUnavailable): server is currently unable to handle the request", b"net/http: TLS handshake timeout",
                         b"Error from server (InternalError): [-]etcd failed: reason withheld; readyz check failed"):
            self.assertTrue(q.startup_pending(expected))
            for denial in (b"Forbidden", b"Unauthorized", b"permission denied", b"x509: certificate failed", b"HTTP 403"):
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

    def test_fixture_failure_evidence_excludes_injected_data_and_termination_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = q.Qualification.__new__(q.Qualification)
            runner.work = Path(directory)
            runner.containers = {"synthetic-node": {}}
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
            with patch.object(runner, "fixture_failure_status", side_effect=RuntimeError("diagnostic failed")):
                runner.record_fixture_failure(q.CommandFailure(1, 1, b"synthetic test failed"))
            result = json.loads((runner.work / "fixture-diagnostic-error.json").read_text())
            self.assertTrue(result["original_failure_preserved"])
            self.assertNotIn("diagnostic failed", json.dumps(result))

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


if __name__ == "__main__":
    unittest.main()
