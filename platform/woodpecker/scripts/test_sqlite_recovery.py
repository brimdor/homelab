from contextlib import closing
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).with_name("sqlite-recovery.py"))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
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
