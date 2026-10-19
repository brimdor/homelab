#!/usr/bin/env python3
"""Reject host networking, production mounts and extra privileges in qualification."""

import copy
from pathlib import Path
import unittest

import kubevip_qualify as QUALIFY


class CandidateIsolationTests(unittest.TestCase):
    def setUp(self):
        self.parent = "a" * 64
        self.scratch = Path("/owned/synthetic")
        self.run = "kubevip-12345678"
        self.container = {
            "Config": {"Image": QUALIFY.IMAGE, "Labels": {
                "io.eaglepass.maintenance": "103", "io.eaglepass.recovery-run": self.run}},
            "HostConfig": {"NetworkMode": "container:" + self.parent, "ReadonlyRootfs": True,
                           "Privileged": False, "CapDrop": ["ALL"], "CapAdd": ["NET_ADMIN", "NET_RAW"],
                           "SecurityOpt": ["no-new-privileges:true"], "PidMode": "", "UTSMode": "",
                           "UsernsMode": "", "Devices": [], "DeviceRequests": None, "PortBindings": {},
                           "IpcMode": "private", "RestartPolicy": {"Name": "no"},
                           "Memory": 67108864, "NanoCpus": 200000000, "PidsLimit": 64,
                           "Tmpfs": {"/tmp": "rw,nosuid,nodev"}},
            "Mounts": [{"Type": "bind", "Source": str(self.scratch / "kubeconfig"),
                        "Destination": "/etc/kubernetes/admin.conf", "RW": False}]
        }

    def test_exact_owned_candidate_is_accepted(self):
        QUALIFY.require_candidate(self.container, self.parent, self.scratch, self.run)

    def test_extra_privileges_namespaces_devices_ports_or_restarts_are_refused(self):
        for key, value in {"NetworkMode": "host", "ReadonlyRootfs": False, "Privileged": True,
                           "CapAdd": ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"], "CapDrop": [],
                           "SecurityOpt": [], "PidMode": "host", "UTSMode": "host", "UsernsMode": "host",
                           "Devices": [{"PathOnHost": "/dev/sda"}], "DeviceRequests": [{"Count": -1}],
                           "PortBindings": {"2112/tcp": [{"HostPort": "2112"}]}, "IpcMode": "host",
                           "RestartPolicy": {"Name": "always"}, "Tmpfs": {"/etc": "rw"}}.items():
            container = copy.deepcopy(self.container)
            container["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                QUALIFY.require_candidate(container, self.parent, self.scratch, self.run)

    def test_foreign_image_owner_or_mount_is_refused(self):
        for case in ("image", "owner", "write", "production", "extra"):
            container = copy.deepcopy(self.container)
            if case == "image":
                container["Config"]["Image"] = "candidate:latest"
            elif case == "owner":
                container["Config"]["Labels"]["io.eaglepass.recovery-run"] = "another-run"
            elif case == "write":
                container["Mounts"][0]["RW"] = True
            elif case == "production":
                container["Mounts"][0]["Source"] = "/etc/rancher/k3s/k3s.yaml"
            else:
                container["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock"})
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                QUALIFY.require_candidate(container, self.parent, self.scratch, self.run)


if __name__ == "__main__":
    unittest.main()
