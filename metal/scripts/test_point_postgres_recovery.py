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

    def test_error_classification_never_exports_sql_or_private_error_values(self):
        data = b'pg_restore: ERROR: database "private database" already exists\nDETAIL: private record\n'
        self.assertEqual(recovery.error_class(data), ["database_exists"])
        self.assertEqual(recovery.error_class(b'unknown private diagnostic'), ["unclassified"])
        self.assertEqual(recovery.error_class(b'ERROR: permission denied for private table'), ["permission_denied"])

    def test_data_diagnostic_preserves_duplicate_records_settings_sequences_and_unknown_sql(self):
        first = (b"SET statement_timeout = 0;\nCOPY public.t (v) FROM stdin;\n"
                 b"private first\n-- private second\nprivate first\n\\.\n"
                 b"SELECT pg_catalog.setval('public.s', 3, true);\n")
        reordered = first.replace(b"private first\n-- private second\nprivate first\n",
                                  b"private first\nprivate first\n-- private second\n")
        result = recovery.data_diagnostic(first, reordered)
        self.assertTrue(result["copy_multiset_equal"])
        self.assertFalse(result["copy_ordered_equal"])
        self.assertEqual(result["archived_rows"], 3)
        self.assertNotIn("private", json.dumps(result))
        for changed, field in ((first.replace(b"-- private second\n", b""), "copy_multiset_equal"),
                               (first.replace(b"statement_timeout = 0", b"statement_timeout = 1"), "session_settings_equal"),
                               (first.replace(b"3, true", b"4, true"), "sequence_commands_equal")):
            with self.subTest(field=field):
                self.assertFalse(recovery.data_diagnostic(first, changed)[field])
        with self.assertRaisesRegex(RuntimeError, "unknown executable"):
            recovery.data_sections(first + b"DELETE FROM public.t;\n")
        with self.assertRaisesRegex(RuntimeError, "duplicate COPY"):
            recovery.data_sections(first + first)

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

    def test_image_contract_canonicalizes_docker_official_short_names_only(self):
        image = {"RepoDigests": [recovery.IMAGE.removeprefix("docker.io/library/")],
                 "Architecture": "amd64", "Os": "linux", "Config": {"Volumes": {"/var/lib/postgresql/data": {}}}}
        recovery.require_image(image)
        for key, value in (("Architecture", "arm64"), ("RepoDigests", ["postgres@sha256:" + "b" * 64]),
                           ("Config", {"Volumes": {"/var/lib/postgresql": {}}})):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_image({**image, key: value})

    def test_candidate_is_exact_pinned_image_and_requires_accepted_original_restore(self):
        image = {"RepoDigests": [recovery.CANDIDATE.removeprefix("docker.io/library/")],
                 "Architecture": "amd64", "Os": "linux", "Config": {"Volumes": {"/var/lib/postgresql": {}}}}
        self.assertEqual(recovery.require_image(image, recovery.CANDIDATE), "/var/lib/postgresql")
        with self.assertRaises(RuntimeError):
            recovery.require_image(image, "postgres:latest")
        path = Mock()
        point = Mock()
        point.glob.return_value = [path]
        accepted = {"accepted": True, "manifest_sha256": "a" * 64, "version": "17.11", "image": recovery.IMAGE,
                    **{k: True for k in ("schema_matches", "logical_data_matches", "authorization_matches",
                        "offline_checksums_valid", "clean_shutdown", "protected_hashes_unchanged", "production_network_unroutable")},
                    "cleanup": {"scratch_absent": True, "owned_containers_absent": True}}
        with patch.object(recovery.protected, "protected_file"):
            path.read_bytes.return_value = json.dumps(accepted).encode()
            recovery.require_original_restore(point, "a" * 64)
            for key, value in (("accepted", False), ("manifest_sha256", "b" * 64), ("version", "18.6"),
                               ("logical_data_matches", False), ("cleanup", {"scratch_absent": False})):
                path.read_bytes.return_value = json.dumps({**accepted, key: value}).encode()
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    recovery.require_original_restore(point, "a" * 64)

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
