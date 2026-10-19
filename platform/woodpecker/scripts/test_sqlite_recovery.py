from contextlib import closing
import hashlib
import importlib.util
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).with_name("sqlite-recovery.py"))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_repair_preserves_records_and_never_enables_trust(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY,trusted TEXT,name TEXT)")
            connection.execute("CREATE TABLE users (id INTEGER,token TEXT)")
            connection.execute("INSERT INTO users VALUES (7,'synthetic-credential')")
            connection.execute("INSERT INTO repos VALUES (1,'0','preserve-me')")
            self.assertEqual(recovery.normalize_trusted(connection), [1])
            trusted, name = connection.execute("SELECT trusted,name FROM repos").fetchone()
            self.assertEqual(json.loads(trusted), {
                "network": False, "volumes": False, "security": False,
            })
            self.assertEqual(name, "preserve-me")
            self.assertEqual(connection.execute("SELECT token FROM users").fetchone()[0], "synthetic-credential")

    def test_bound_repair_exercises_restore_and_preserves_recovery_point(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "woodpecker.sqlite"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY,trusted TEXT)")
                connection.execute("INSERT INTO repos VALUES (1,'0')")
                connection.commit()
            original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = root / "recovery/pre-repair.sqlite"
            point = recovery.backup(source, destination, True)
            result = recovery.repair(source, destination, point["sha256"], original_sha)
            self.assertEqual(result["repaired_repository_ids"], [1])
            self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), point["sha256"])
            with closing(sqlite3.connect(source)) as connection:
                self.assertEqual(json.loads(connection.execute("SELECT trusted FROM repos").fetchone()[0]), {
                    "network": False, "volumes": False, "security": False,
                })
            self.assertFalse((destination.parent / "repair-work").exists())

    def test_elevated_or_ambiguous_trust_stops_before_any_update(self):
        for bad in ("1", "false", "null", '"unknown"'):
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY,trusted TEXT)")
                connection.executemany("INSERT INTO repos VALUES (?,?)", [(1, "0"), (2, bad)])
                before = recovery.snapshot(connection)
                with self.assertRaises(AssertionError):
                    recovery.normalize_trusted(connection)
                self.assertEqual(recovery.snapshot(connection), before)

    def test_wal_copy_preserves_committed_rows_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "woodpecker.sqlite"
            with closing(sqlite3.connect(source)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY, trusted INTEGER)")
                writer.executemany("INSERT INTO repos VALUES (?,?)", [(1, 0), (2, 1)])
                writer.commit()
                # Keep the WAL present but perform no writes during the copy.
                paths = [source, root / "woodpecker.sqlite-wal"]
                before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
                result = recovery.backup(source, root / "protected/pre-repair.sqlite", True)
                self.assertEqual(result["numeric_trusted"], [(1, 0), (2, 1)])
                self.assertEqual(result["isolated_restore"], "passed")
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
                self.assertEqual(set(before), set(result["raw_source_hashes"]))
                self.assertFalse((root / "protected/recovery-work").exists())
                self.assertFalse((root / "protected/pre-repair.restore.sqlite").exists())

    def test_existing_recovery_point_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, destination = root / "source.sqlite", root / "existing.sqlite"
            source.touch()
            destination.write_bytes(b"original recovery material")
            with self.assertRaises(AssertionError):
                recovery.backup(source, destination, True)
            self.assertEqual(destination.read_bytes(), b"original recovery material")


if __name__ == "__main__":
    unittest.main()
