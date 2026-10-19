#!/usr/bin/env python3
"""Exercise production trust boundaries and byte-preserving recovery checks."""

import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

import point_postgres_recovery as recovery


class PointPostgresRecoveryTests(unittest.TestCase):
    def manifest(self):
        return {"format": 1, "namespace": "pointguide-canary", "image": recovery.IMAGE,
                "cluster_uid": recovery.common.CLUSTER_UID,
                "identity": list(recovery.SOURCES["pointguide-canary"]), "before": {"schema": "same"},
                "after": {"schema": "same"}, "files": {
                    name: {"bytes": 50, "sha256": "a" * 64} for name in ("globals.sql", "database.dump")}}

    def test_manifest_refuses_changed_source_partial_export_and_unknown_files(self):
        original = self.manifest()
        recovery.require_manifest(original)
        for key, value in (("namespace", "unreviewed"), ("image", "postgres:latest"),
                           ("cluster_uid", "other"), ("identity", ["other"]),
                           ("after", {"schema": "changed"}), ("files", {"database.dump": {}})):
            changed = copy.deepcopy(original)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_manifest(changed)
        for key, value in (("bytes", 0), ("bytes", True), ("sha256", "invalid")):
            changed = copy.deepcopy(original)
            changed["files"]["database.dump"][key] = value
            with self.subTest(field=key), self.assertRaises(RuntimeError):
                recovery.require_manifest(changed)

    def test_normalization_keeps_copy_records_and_sql_byte_exact(self):
        original = (b"-- Dumped from database version 17.11\n\\restrict TOKEN123\n"
                    b"CREATE TABLE public.t (v text);\nCOPY public.t (v) FROM stdin;\n"
                    b"-- Dumped from database version private record\n"
                    b"\\restrict PRIVATE123\nactual record\n\\.\n"
                    b"ALTER TABLE public.t OWNER TO app;\n\\unrestrict TOKEN123\n")
        expected = (b"CREATE TABLE public.t (v text);\nCOPY public.t (v) FROM stdin;\n"
                    b"-- Dumped from database version private record\n"
                    b"\\restrict PRIVATE123\nactual record\n\\.\n"
                    b"ALTER TABLE public.t OWNER TO app;\n")
        self.assertEqual(recovery.normalized_dump(original), expected)
        self.assertNotEqual(recovery.digest(recovery.normalized_dump(original.replace(b"actual record", b"changed"))),
                            recovery.digest(expected))
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            recovery.normalized_dump(b"COPY public.t FROM stdin;\nrecord\n")

    def test_source_client_uses_only_declared_password_same_principal_and_readonly(self):
        arguments = recovery.source_client("pointguide-canary", "pg_dump", "--format=custom", database="pointguide")
        shell = arguments[-1]
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', shell)
        self.assertIn("default_transaction_read_only=on", shell)
        self.assertIn("-h 127.0.0.1 -U pointguide", shell)
        self.assertIn("pointguide-canary-postgres-0", arguments)
        self.assertNotIn("password", " ".join(arguments[:-1]).lower())
        self.assertNotIn("sudo", shell)

    def test_source_metadata_rejects_unsupported_features_or_other_database_data(self):
        features = {"version": "17.11", "database": "pointguide", "role": "pointguide", "encoding": "UTF8",
                    "locale": ["en_US.utf8", "en_US.utf8", "c"], "databases": ["pointguide", "postgres"],
                    "roles": ["pointguide"], "extensions": ["plpgsql"], "foreign_tables": 0,
                    "large_objects": 0, "custom_tablespaces": 0, "prepared_transactions": 0,
                    "subscriptions": 0, "replication_slots": 0}
        def result(value):
            return subprocess.CompletedProcess([], 0, stdout=value, stderr=b"")
        outputs = [result(json.dumps(features).encode()), result(b"0\n0\n"), result(b"0\n0\n"),
                   result(b"CREATE TABLE synthetic (n int);\n"), result(b"a" * 64 + b"\n")]
        with patch.object(recovery.common, "command", side_effect=outputs):
            value = recovery.source_metadata("pointguide-canary")
            self.assertEqual(value["roles_sha256"], "a" * 64)
        for key, changed in (("version", "18.0"), ("roles", ["pointguide", "other"]),
                             ("extensions", ["unreviewed"]), ("foreign_tables", 1),
                             ("databases", ["pointguide", "postgres", "other"])):
            rejected = {**features, key: changed}
            with self.subTest(key=key), patch.object(recovery.common, "command",
                    return_value=result(json.dumps(rejected).encode())), self.assertRaises(RuntimeError):
                recovery.source_metadata("pointguide-canary")
        with patch.object(recovery.common, "command", side_effect=[outputs[0], result(b"1\n0\n")]), \
                self.assertRaisesRegex(RuntimeError, "unprotected"):
            recovery.source_metadata("pointguide-canary")

    def test_isolation_refuses_host_routes_ports_devices_unowned_mounts_and_user(self):
        scratch = Path("/owned")
        container = {"Config": {"Labels": {recovery.LABEL: "synthetic"}, "User": "70:70"},
                     "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                         "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": "",
                         "SecurityOpt": ["no-new-privileges:true"], "Tmpfs": {"/tmp": "rw,nosuid,nodev"}},
                     "Mounts": [{"Type": "bind", "Source": "/owned/data",
                                 "Destination": "/var/lib/postgresql/data", "RW": True}]}
        recovery.require_isolation(container, scratch, "synthetic")
        for field, value in (("NetworkMode", "host"), ("ReadonlyRootfs", False), ("Privileged", True),
                             ("CapDrop", []), ("PidMode", "host"), ("Devices", [{}]),
                             ("PortBindings", {"5432/tcp": [{}]}), ("SecurityOpt", [])):
            changed = copy.deepcopy(container)
            changed["HostConfig"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                recovery.require_isolation(changed, scratch, "synthetic")
        for field, value in (("Source", "/production"), ("Type", "volume"), ("RW", False)):
            changed = copy.deepcopy(container)
            changed["Mounts"][0][field] = value
            with self.subTest(mount=field), self.assertRaises(RuntimeError):
                recovery.require_isolation(changed, scratch, "synthetic")
        container["Config"]["User"] = "0"
        with self.assertRaises(RuntimeError):
            recovery.require_isolation(container, scratch, "synthetic")

    def test_finalization_never_marks_changed_bytes_complete(self):
        manifest = self.manifest()
        with patch.object(recovery, "point_path", return_value=Path("/protected")), \
                patch.object(recovery.protected, "file_digest", return_value={"bytes": 51, "sha256": "a" * 64}), \
                patch.object(recovery.protected, "write_json") as write, self.assertRaises(RuntimeError):
            recovery.finalize("synthetic-run", manifest)
        write.assert_not_called()

    def test_failed_export_reaps_both_owned_clients_and_never_finalizes(self):
        producer = Mock(returncode=1, stdout=Mock())
        producer.communicate.return_value = (None, b"private failure")
        receiver = Mock(returncode=None)
        receiver.communicate.side_effect = OSError("synthetic interrupted stream")
        producer.poll.return_value = None
        receiver.poll.return_value = None
        with patch.object(recovery, "source_identity", return_value=["identity"]), \
                patch.object(recovery, "source_metadata", return_value={}), \
                patch.object(recovery, "remote", return_value=["ssh", "protected"]), \
                patch.object(recovery.subprocess, "Popen", side_effect=[producer, receiver]), \
                patch.object(recovery.common, "command") as command, self.assertRaises(OSError):
            recovery.backup("pointguide-canary", "synthetic-run")
        for process in (producer, receiver):
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=10)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
