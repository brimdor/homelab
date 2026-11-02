#!/usr/bin/env python3
"""Exercise physical backup member and database identity refusals."""

import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

import central_postgres_recovery as recovery


class ArchiveIdentityTests(unittest.TestCase):
    def archive(self, directory, extra=None, identifier=recovery.SYSTEM_ID):
        path = Path(directory) / "base.tar"
        members = {"PG_VERSION": b"17\n", "global/pg_control": struct.pack("<Q", int(identifier)),
                   "backup_label": b"fixture", "pg_wal/000000010000000000000001": b"wal",
                   "backup_manifest": json.dumps({"PostgreSQL-Backup-Manifest-Version": 2,
                       "System-Identifier": int(identifier), "Files": [{"Path": "PG_VERSION"}],
                       "WAL-Ranges": [{"Timeline": 1}]}).encode()}
        if extra:
            members.update(extra)
        with tarfile.open(path, "w") as archive:
            for name, content in members.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
        return path

    def test_complete_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            value = recovery.archive_identity(self.archive(directory))
            self.assertEqual(value["system_identifier"], recovery.SYSTEM_ID)
            self.assertEqual(value["wal_files"], 1)

    def test_other_database_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "system identifier"):
                recovery.archive_identity(self.archive(directory, identifier="7701641525365469222"))

    def test_escape_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                recovery.archive_identity(self.archive(directory, {"../outside": b"bad"}))

    def test_changed_native_container_refused(self):
        value = {"status": {"id": recovery.SOURCE_CONTAINER, "state": "CONTAINER_RUNNING",
                           "imageRef": recovery.IMAGE,
                           "labels": {"io.kubernetes.pod.uid": recovery.SOURCE_UID,
                                      "io.kubernetes.pod.namespace": "postgres",
                                      "io.kubernetes.container.name": "main"}}, "info": {"pid": 123}}
        self.assertEqual(recovery.source_runtime(value), 123)
        value["status"]["labels"]["io.kubernetes.pod.uid"] = "another-pod"
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            recovery.source_runtime(value)


class RecoveryProfileTests(unittest.TestCase):
    def setUp(self):
        for name in ("SOURCE_UID", "SOURCE_CONTAINER", "CAPTURE_VERSION", "RESTORE_VERSION"):
            self.addCleanup(setattr, recovery, name, getattr(recovery, name))

    def profile(self, source, receiver):
        return {
            "format": 1, "node": "totodile",
            "node_uid": "83e0e536-e94a-45a1-8dfb-1cedac1e9bd7",
            "pvc_uid": recovery.PVC_UID, "pv_uid": recovery.PV_UID,
            "system_identifier": recovery.SYSTEM_ID, "image": recovery.IMAGE,
            "pod_uid": "00000000-0000-4000-8000-000000000001",
            "container_id": "a" * 64,
            "source_version": source, "receiver_version": receiver,
        }

    def test_existing_adjacent_profiles_remain_valid(self):
        versions = recovery.k3s.VERSIONS
        for source, receiver in zip(versions, versions[1:]):
            with self.subTest(source=source, receiver=receiver):
                profile = self.profile(source, receiver)
                recovery.configure_profile(profile)
                self.assertEqual(recovery.CAPTURE_VERSION, source)
                self.assertEqual(recovery.RESTORE_VERSION, receiver)
                self.assertEqual(recovery.SOURCE_UID, profile["pod_uid"])
                self.assertEqual(recovery.SOURCE_CONTAINER, profile["container_id"])

    def test_completed_pikachu_receives_remaining_totodile_bridges(self):
        for source in recovery.k3s.VERSIONS[2:-1]:
            with self.subTest(source=source):
                receiver = recovery.k3s.VERSIONS[-1]
                recovery.configure_profile(self.profile(source, receiver))
                self.assertEqual(recovery.CAPTURE_VERSION, source)
                self.assertEqual(recovery.RESTORE_VERSION, receiver)

    def test_unreviewed_receiver_pairs_are_refused(self):
        versions = recovery.k3s.VERSIONS
        pairs = [
            (versions[1], versions[-1]), (versions[2], versions[4]),
            (versions[3], versions[2]), (versions[-1], versions[-1]),
            ("v1.32.0+k3s1", versions[-1]), (versions[2], "v1.37.0+k3s1"),
        ]
        for source, receiver in pairs:
            with self.subTest(source=source, receiver=receiver):
                with self.assertRaisesRegex(RuntimeError, "unreviewed protected PostgreSQL"):
                    recovery.configure_profile(self.profile(source, receiver))

    def test_exact_completed_source_can_use_matching_final_receiver(self):
        final = recovery.k3s.VERSIONS[-1]
        profile = self.profile(final, final)
        profile['pod_uid'], profile['container_id'] = recovery.POST_MAINTENANCE_SOURCE
        recovery.configure_profile(profile)
        self.assertEqual(recovery.CAPTURE_VERSION, final)
        self.assertEqual(recovery.RESTORE_VERSION, final)
        for key in ('pod_uid', 'container_id'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.configure_profile({**profile, key: self.profile(final, final)[key]})

    def test_later_receiver_keeps_all_database_and_native_identity_guards(self):
        profile = self.profile(recovery.k3s.VERSIONS[2], recovery.k3s.VERSIONS[-1])
        for key, value in {
            "format": True, "node": "other", "node_uid": "other", "pvc_uid": "other",
            "pv_uid": "other", "system_identifier": "other", "image": "other",
            "pod_uid": "other", "container_id": "other",
        }.items():
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, "unreviewed protected PostgreSQL"):
                    recovery.configure_profile({**profile, key: value})
        with self.assertRaisesRegex(RuntimeError, "unreviewed protected PostgreSQL"):
            recovery.configure_profile({**profile, "unexpected": True})


if __name__ == "__main__":
    unittest.main()
