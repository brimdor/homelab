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


if __name__ == "__main__":
    unittest.main()
