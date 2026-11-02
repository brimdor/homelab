#!/usr/bin/env python3
"""Synthetic provenance and isolation refusals; no production data or subprocesses."""

import copy
from pathlib import Path
import subprocess
import shlex
import unittest
from unittest.mock import patch

import outline_valkey_recovery as recovery


def manifest():
    return {"format": 1, "cluster_uid": recovery.common.CLUSTER_UID, "image": recovery.IMAGE,
            "source_quiesced": False, "snapshot": {"bytes": 100, "sha256": "a" * 64},
            "source": {"pod_uid": recovery.POD_UID, "deployment_uid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                       "module_list_sha256": recovery.MODULES_SHA256,
                       "containers": {"redis": {"containerID": "containerd://" + recovery.CONTAINER,
                                                "imageID": recovery.IMAGE},
                                      "main": {"containerID": "containerd://" + "d" * 64,
                                               "imageID": "docker.io/outlinewiki/outline@sha256:" + "e" * 64}}}}


def container():
    return {"Config": {"Image": recovery.IMAGE, "User": "1001:1001", "Labels": {recovery.LABEL: "test-point"}},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": "",
                           "SecurityOpt": ["no-new-privileges:true"], "PidsLimit": 64, "Memory": 134217728,
                           "NanoCpus": 500000000, "LogConfig": {"Type": "none", "Config": {}},
                           "Tmpfs": {"/tmp": "rw,nosuid,nodev,uid=1001,gid=1001,mode=0700,size=16777216"}},
            "Mounts": [{"Type": "bind", "Source": "/owned/data", "Destination": "/data", "RW": True, "Mode": "rw,Z"}]}


class OutlineValkeyRecoveryTests(unittest.TestCase):
    def test_exact_manifest_and_changed_source_refusals(self):
        original = manifest()
        recovery.require_manifest(original)
        for path, value in ((["format"], True), (["image"], "valkey:latest"),
                            (["cluster_uid"], "foreign"), (["source_quiesced"], True),
                            (["source", "pod_uid"], "foreign"),
                            (["source", "module_list_sha256"], "a" * 64),
                            (["source", "containers", "redis", "containerID"], "containerd://" + "f" * 64),
                            (["snapshot", "bytes"], True), (["snapshot", "bytes"], recovery.MAX_SNAPSHOT + 1),
                            (["snapshot", "sha256"], "not-a-hash")):
            with self.subTest(path=path):
                changed = copy.deepcopy(original)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(RuntimeError):
                    recovery.require_manifest(changed)
        changed = copy.deepcopy(original)
        changed["source"]["containers"]["extra"] = changed["source"]["containers"]["main"]
        with self.assertRaises(RuntimeError):
            recovery.require_manifest(changed)

    def test_isolation_rejects_routes_privilege_logging_and_unowned_storage(self):
        original = container()
        recovery.isolation(original, Path("/owned"), "test-point")
        for key, value in (("NetworkMode", "host"), ("ReadonlyRootfs", False), ("Privileged", True),
                           ("CapDrop", []), ("SecurityOpt", []), ("Devices", ["foreign"]),
                           ("LogConfig", {"Type": "json-file"}), ("PortBindings", {"6379": [{}]})):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed["HostConfig"][key] = value
                with self.assertRaises(RuntimeError):
                    recovery.isolation(changed, Path("/owned"), "test-point")
        for key, value in (("Source", "/protected-original"), ("Mode", "rw"), ("Type", "volume")):
            changed = copy.deepcopy(original)
            changed["Mounts"][0][key] = value
            with self.assertRaises(RuntimeError):
                recovery.isolation(changed, Path("/owned"), "test-point")
        changed = copy.deepcopy(original)
        changed["Mounts"].append(copy.deepcopy(changed["Mounts"][0]))
        with self.assertRaises(RuntimeError):
            recovery.isolation(changed, Path("/owned"), "test-point")

    def test_expired_keys_accounted_without_claiming_live_values(self):
        result = recovery.valkey.load_counts({"rdb_last_load_keys_loaded": "0", "rdb_last_load_keys_expired": "3"}, {}, 3)
        self.assertEqual(result["expired_at_load"], 3)
        self.assertEqual(result["current_keys"], 0)
        with self.assertRaises(RuntimeError):
            recovery.valkey.load_counts({"rdb_last_load_keys_loaded": "0", "rdb_last_load_keys_expired": "2"}, {}, 3)

    def test_exact_valkey_9_and_compatible_legacy_snapshot_headers(self):
        for header in (b"VALKEY080", b"REDIS0011"):
            recovery.require_header(header)
        for header in (b"VALKEY081", b"REDIS0080", b"VALKEY08", b"not-a-rdb"):
            with self.assertRaises(RuntimeError):
                recovery.require_header(header)

    def test_rdb_checker_requires_native_success_and_exact_inventory(self):
        good = subprocess.CompletedProcess([], 0, stdout=b"Checksum OK\n3 keys read\n")
        self.assertEqual(recovery.valkey.checked_keys(good), 3)
        for bad in (subprocess.CompletedProcess([], 1, stdout=good.stdout),
                    subprocess.CompletedProcess([], 0, stdout=b"Checksum OK\n")):
            with self.assertRaises(RuntimeError):
                recovery.valkey.checked_keys(bad)

    def test_changed_manifest_refuses_before_image_or_container_actions(self):
        with patch.object(recovery, "point_path", return_value=Path("/protected")), \
                patch.object(recovery, "verify_point", side_effect=RuntimeError("changed manifest")), \
                patch.object(recovery.common, "docker", side_effect=AssertionError("Docker must not run")):
            with self.assertRaisesRegex(RuntimeError, "changed manifest"):
                recovery.restore("test-point", "a" * 64)

    def test_receiver_refuses_foreign_host_before_creating_point(self):
        with patch.object(recovery.common, "require_host", side_effect=RuntimeError("foreign host")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("No directory must be created")):
            with self.assertRaisesRegex(RuntimeError, "foreign host"):
                recovery.point_path("test-point")

    def test_transport_preserves_strict_ssh_and_fits_linux_argument_limit(self):
        command = recovery.remote("internal-receive", "test-point")
        self.assertEqual(command[:-1], recovery.common.SSH)
        self.assertLess(len(command[-1].encode()), 100000)
        arguments = shlex.split(command[-1])
        self.assertEqual(arguments[:3], ["python3", "-B", "-c"])
        compile(arguments[3], "<transport>", "exec")
        self.assertEqual(arguments[4:], ["internal-receive", "--run-id", "test-point"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
