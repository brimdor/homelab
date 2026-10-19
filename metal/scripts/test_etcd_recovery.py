#!/usr/bin/env python3
"""Refuse unsafe isolation before any restored credential or server is used."""

import copy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import etcd_recovery as RECOVERY


class IsolationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.scratch = Path(directory.name)
        self.container = {
            "Config": {"Labels": {"io.eaglepass.maintenance": "103", "io.eaglepass.recovery-run": "qualify-12345678"}},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "CapDrop": ["ALL"], "CapAdd": None, "SecurityOpt": ["no-new-privileges:true"],
                           "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": "",
                           "Devices": [], "DeviceRequests": None, "PortBindings": {},
                           "Tmpfs": {"/run": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev",
                                     "/etc/rancher": "rw,nosuid,nodev"}},
            "Mounts": [{"Type": "bind", "Source": str(self.scratch), "Destination": "/work", "RW": True},
                       {"Type": "bind", "Source": str(self.scratch / "data"),
                        "Destination": "/var/lib/rancher/k3s", "RW": True},
                       {"Type": "bind", "Source": str(self.scratch / "cni"), "Destination": "/var/lib/cni", "RW": True},
                       {"Type": "bind", "Source": str(self.scratch / "kubelet"), "Destination": "/var/lib/kubelet", "RW": True},
                       {"Type": "bind", "Source": str(self.scratch / "logs"), "Destination": "/var/log", "RW": True}],
        }

    def test_exact_owned_isolated_container_is_accepted(self):
        RECOVERY.require_isolation(self.container, self.scratch, "qualify-12345678")

    def test_network_privilege_namespace_device_and_port_changes_are_refused(self):
        changes = {"NetworkMode": "host", "ReadonlyRootfs": False, "Privileged": True,
                   "CapDrop": [], "CapAdd": ["NET_ADMIN"], "SecurityOpt": [], "PidMode": "host",
                   "IpcMode": "host", "UTSMode": "host", "UsernsMode": "host",
                   "Devices": [{"PathOnHost": "/dev/sda"}], "DeviceRequests": [{"Count": -1}],
                   "PortBindings": {"16443/tcp": [{"HostPort": "16443"}]},
                   "Tmpfs": {"/run": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev", "/etc": "rw"}}
        for key, value in changes.items():
            container = copy.deepcopy(self.container)
            container["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                RECOVERY.require_isolation(container, self.scratch, "qualify-12345678")

    def test_unknown_mount_and_changed_ownership_are_refused(self):
        for case in ("socket", "anonymous-volume", "foreign-source", "owner"):
            container = copy.deepcopy(self.container)
            if case == "socket":
                container["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock",
                                            "Destination": "/var/run/docker.sock", "RW": False})
            elif case == "anonymous-volume":
                container["Mounts"].append({"Type": "volume", "Destination": "/unknown", "RW": True})
            elif case == "foreign-source":
                container["Mounts"][0]["Source"] = "/var/lib/rancher/k3s"
            else:
                container["Config"]["Labels"]["io.eaglepass.recovery-run"] = "other"
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                RECOVERY.require_isolation(container, self.scratch, "qualify-12345678")

    def test_external_interfaces_and_ipv4_or_ipv6_routes_are_refused(self):
        links = [{"ifname": "lo"}]
        routes = [{"dst": "127.0.0.0/8", "dev": "lo", "table": "local"}]
        RECOVERY.require_network(links, routes)
        for changed_links, changed_routes in (
            (links + [{"ifname": "eth0"}], routes),
            (links, routes + [{"dst": "default", "dev": "lo"}]),
            (links, routes + [{"dst": "10.0.20.0/24", "dev": "eth0"}]),
            (links, routes + [{"dst": "::/0", "dev": "lo"}]),
            ([], []),
        ):
            with self.subTest(links=changed_links, routes=changed_routes), self.assertRaises(RuntimeError):
                RECOVERY.require_network(changed_links, changed_routes)

    def test_run_identifier_cannot_escape_owned_paths_or_shell_arguments(self):
        self.assertEqual(RECOVERY.run_identifier("qualify-12345678"), "qualify-12345678")
        for value in ("../other", "a;rm", "$(id)", "a/b", "", "UPPER", "a" * 81):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RECOVERY.run_identifier(value)

    def test_failed_remote_qualification_preserves_sanitized_receipt(self):
        receipt = {"accepted": False, "error": "synthetic qualification failed", "cleanup": {"scratch_absent": True}}
        result = subprocess.CompletedProcess([], 1, json.dumps(receipt).encode(), b"private diagnostic")
        output = io.StringIO()
        with patch("sys.argv", ["etcd_recovery.py", "qualify", "--run-id", "qualify-12345678"]), \
                patch.object(RECOVERY, "command", return_value=result), contextlib.redirect_stdout(output):
            self.assertEqual(RECOVERY.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), receipt)
        self.assertNotIn("private diagnostic", output.getvalue())

    def test_cancel_checks_exact_ownership_and_stops_only_that_container(self):
        identity = "a" * 64
        container = copy.deepcopy(self.container)
        container.update(Id=identity, State={"Running": False})
        container["Mounts"][0]["Source"] = str(self.scratch / "qualify-12345678-qualify-owned")
        result = subprocess.CompletedProcess([], 0, (identity + "\n").encode(), b"")
        with patch.object(RECOVERY, "docker", return_value=result) as docker, \
                patch.object(RECOVERY, "inspect", return_value=container), patch.object(RECOVERY, "ROOT", self.scratch):
            self.assertTrue(RECOVERY.cancel_qualification("qualify-12345678")["accepted"])
            self.assertIn((("kill", "--signal=KILL", identity), {}), docker.call_args_list)
        container["Config"]["Labels"]["io.eaglepass.recovery-run"] = "foreign-run"
        with patch.object(RECOVERY, "docker", return_value=result) as docker, \
                patch.object(RECOVERY, "inspect", return_value=container), self.assertRaises(RuntimeError):
            RECOVERY.cancel_qualification("qualify-12345678")
        self.assertEqual(docker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
