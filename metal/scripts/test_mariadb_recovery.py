#!/usr/bin/env python3
"""Check database export identity and restore isolation before real data is used."""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mariadb_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.container = {
            "Config": {"User": "999:999", "Labels": {recovery.LABEL: "reviewed-12345678"}},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "",
                           "UsernsMode": "", "SecurityOpt": ["no-new-privileges:true"],
                           "Tmpfs": {"/tmp": "rw,nosuid,nodev"}},
            "Mounts": [{"Type": "bind", "Source": str(self.root / "data"),
                        "Destination": "/var/lib/mysql", "RW": True}],
        }

    def test_exact_owned_container_passes(self):
        recovery.require_isolation(self.container, self.root, "reviewed-12345678")

    def test_network_privilege_namespace_device_and_mount_bypasses_fail(self):
        changes = {"NetworkMode": "host", "ReadonlyRootfs": False, "Privileged": True,
                   "CapDrop": [], "PidMode": "host", "IpcMode": "host", "UTSMode": "host", "UsernsMode": "host",
                   "CapAdd": ["NET_ADMIN"], "Devices": [{}], "DeviceRequests": [{}], "PortBindings": {"3306/tcp": []},
                   "SecurityOpt": [], "Tmpfs": {"/tmp": "rw", "/etc": "rw"}}
        for key, value in changes.items():
            altered = copy.deepcopy(self.container)
            altered["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_isolation(altered, self.root, "reviewed-12345678")
        for field, value in (("Source", "/var/lib/mysql"), ("Destination", "/work"), ("Type", "volume"), ("RW", False)):
            altered = copy.deepcopy(self.container)
            altered["Mounts"][0][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                recovery.require_isolation(altered, self.root, "reviewed-12345678")

    def test_owner_and_extra_mounts_are_refused(self):
        for field in ("user", "label", "mount"):
            altered = copy.deepcopy(self.container)
            if field == "user":
                altered["Config"]["User"] = "0"
            elif field == "label":
                altered["Config"]["Labels"][recovery.LABEL] = "another-run"
            else:
                altered["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock"})
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                recovery.require_isolation(altered, self.root, "reviewed-12345678")

    def test_password_is_only_expanded_inside_existing_container(self):
        args = recovery.source_client("backlog", "existing-pod", *recovery.DUMP)
        self.assertIn('MYSQL_PWD="$MYSQL_ROOT_PASSWORD"', args[-1])
        self.assertNotIn("-p$MYSQL_ROOT_PASSWORD", args[-1])
        self.assertIn("--single-transaction", args[-1])

    def test_source_refuses_changed_version_and_nontransactional_application_tables(self):
        for version, engines in ((b"11.0.1\n", b"InnoDB\t18\n"), (b"10.11.11\n", b"MyISAM\t1\n")):
            values = [subprocess.CompletedProcess([], 0, version), subprocess.CompletedProcess([], 0, engines)]
            with patch.object(recovery.common, "command", side_effect=values), self.assertRaises(RuntimeError):
                recovery.source_metadata("backlog", "existing-pod")

    def test_unknown_namespace_is_refused_before_access(self):
        with patch.object(recovery.common, "command") as command, self.assertRaises(RuntimeError):
            recovery.backup("another-app", "pod", "reviewed-12345678")
        command.assert_not_called()

    def test_file_protection_and_symlinks_are_enforced(self):
        source = self.root / "cluster.sql"
        source.write_bytes(b"synthetic recovery only")
        source.chmod(0o600)
        with patch.object(recovery.os, "getuid", return_value=os.getuid()):
            # The production workflow deliberately requires root-owned Linux files.
            if os.getuid() != 0:
                with self.assertRaises(RuntimeError):
                    recovery.file_digest(source)
        link = self.root / "link"
        link.symlink_to(source)
        with self.assertRaises(RuntimeError):
            recovery.file_digest(link)

    def test_failed_remote_restore_keeps_sanitized_receipt(self):
        receipt = {"accepted": False, "error": "isolated import failed", "cleanup": {"scratch_absent": True}}
        response = subprocess.CompletedProcess([], 1, json.dumps(receipt).encode(), b"private diagnostic")
        with patch.object(recovery.sys, "argv", ["mariadb_recovery.py", "restore", "--run-id", "reviewed-12345678", "--manifest", "0" * 64]), \
                patch.object(recovery, "remote", return_value=["ssh", "fixed-host"]), \
                patch.object(recovery.common, "command", return_value=response), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(recovery.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), receipt)
        self.assertNotIn("private diagnostic", output.getvalue())


if __name__ == "__main__":
    unittest.main()
