#!/usr/bin/env python3
"""Exercise HA identity, version-skew and synthetic datastore safety boundaries."""

import copy
import json
from pathlib import Path
import tempfile
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
        for expected in (b"connect: connection refused", b"Error from server (ServiceUnavailable): server is currently unable to handle the request", b"net/http: TLS handshake timeout",
                         b"Error from server (InternalError): [-]etcd failed: reason withheld; readyz check failed"):
            self.assertTrue(q.startup_pending(expected))
            for denial in (b"Forbidden", b"Unauthorized", b"permission denied", b"x509: certificate failed", b"HTTP 403"):
                self.assertFalse(q.startup_pending(expected + b"\n" + denial))
        for other in (b"", b"executable not found", b"unknown error"):
            self.assertFalse(q.startup_pending(other))

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


if __name__ == "__main__":
    unittest.main()
