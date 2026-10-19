#!/usr/bin/env python3
"""Fail closed on writer, archive and migration ownership changes."""

import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import point_postgres_migration as migration
import point_postgres_recovery as recovery


class PointMigrationTests(unittest.TestCase):
    def test_quiescence_requires_zero_writers_cron_suspension_and_no_database_clients(self):
        objects = [{"kind": "Deployment", "metadata": {"name": "pointview-canary"},
                    "spec": {"replicas": 0}, "status": {"replicas": 0}},
                   {"kind": "CronJob", "spec": {"suspend": True}, "status": {}},
                   {"kind": "Pod", "metadata": {"name": "pointview-canary-postgres-0"},
                    "status": {"phase": "Running"}}]
        def output(value):
            return subprocess.CompletedProcess([], 0, stdout=value, stderr=b"")
        with patch.object(recovery.common, "command", side_effect=[output(json.dumps({"items": objects}).encode()), output(b"0\n")]):
            recovery.require_quiescence("pointview-canary")
        for index, field, value in ((0, "replicas", 1), (1, "suspend", False)):
            changed = copy.deepcopy(objects)
            changed[index]["spec"][field] = value
            with patch.object(recovery.common, "command", return_value=output(json.dumps({"items": changed}).encode())), \
                    self.assertRaisesRegex(RuntimeError, "not quiesced"):
                recovery.require_quiescence("pointview-canary")
        with patch.object(recovery.common, "command", side_effect=[output(json.dumps({"items": objects}).encode()), output(b"1\n")]), \
                self.assertRaisesRegex(RuntimeError, "another client"):
            recovery.require_quiescence("pointview-canary")

    def test_stopped_database_requires_exact_uids_and_no_other_consumer(self):
        ns = "pointguide-canary"
        identities = recovery.SOURCES[ns]
        records = [{"metadata": {"uid": recovery.common.CLUSTER_UID}},
                   {"metadata": {"uid": identities[1]}, "spec": {"replicas": 0}, "status": {}},
                   {"metadata": {"uid": identities[2]}, "spec": {"volumeName": "pv", "storageClassName": "standard-rwo"},
                    "status": {"phase": "Bound"}},
                   {"metadata": {"uid": identities[3]}, "spec": {"csi": {"driver": "rook-ceph.rbd.csi.ceph.com"}}},
                   {"items": [{"kind": "Deployment", "metadata": {"name": ns}, "spec": {"replicas": 0}, "status": {}}]}]
        with patch.object(migration, "kube", side_effect=records):
            self.assertEqual(migration.require_stopped(ns), identities[2])
        for index in (0, 1, 2, 3):
            changed = copy.deepcopy(records)
            changed[index]["metadata"]["uid"] = "changed"
            with patch.object(migration, "kube", side_effect=changed), self.assertRaises(RuntimeError):
                migration.require_stopped(ns)
        changed = copy.deepcopy(records)
        changed[4]["items"].append({"kind": "Pod", "metadata": {"name": "unknown"}, "status": {"phase": "Running"}})
        with patch.object(migration, "kube", side_effect=changed), self.assertRaisesRegex(RuntimeError, "consumer"):
            migration.require_stopped(ns)

    def test_role_and_data_comparison_refuses_missing_duplicate_record(self):
        manifest = {"before": {"schema_sha256": recovery.digest(b"schema\n"), "roles_sha256": "r", "features": {"user_tables": 1}}}
        archive = b"COPY public.t (v) FROM stdin;\na\na\n\\.\n"
        values = [b"schema\n", b"r\n", archive, archive, b"18.6\n", b"2\n"]
        with patch.object(migration, "execute", side_effect=values):
            self.assertTrue(migration.compare("pointguide-canary", "owned", manifest)["logical_data_matches"])
        values[3] = b"COPY public.t (v) FROM stdin;\na\n\\.\n"
        with patch.object(migration, "execute", side_effect=values), self.assertRaisesRegex(RuntimeError, "logical data"):
            migration.compare("pointguide-canary", "owned", manifest)

    def test_chart_native_scripts_match_reviewed_canonical_bytes(self):
        root = Path(__file__).resolve().parents[2]
        original = Path(migration.__file__).with_suffix(".sh").read_bytes()
        for namespace in recovery.SOURCES:
            self.assertEqual((root / "apps" / namespace / "files/postgres-migration.sh").read_bytes(), original)

    def test_protected_delivery_is_known_host_ssh_and_never_contains_credentials(self):
        command = migration.protected_command("pointguide-canary-20261019-b", "a" * 64, "database.dump")
        self.assertEqual(command[0], "ssh")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("UserKnownHostsFile=/Users/chris/.ssh/homelab_known_hosts", command)
        self.assertIn("root@10.0.20.14", command)
        self.assertNotIn("PGPASSWORD=", " ".join(command))
        self.assertNotIn("StrictHostKeyChecking=no", command)


if __name__ == "__main__":
    unittest.main()
