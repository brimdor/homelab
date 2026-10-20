"""Real synthetic btree damage and refusal regressions; no application records."""

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

import radarr_log_reconstruction as recovery


class RadarrLogReconstruction(unittest.TestCase):
    def source(self, root):
        (root / 'copy').mkdir()
        path = root / 'copy/logs.db'
        db = sqlite3.connect(path)
        for sql in (
            'CREATE TABLE "Logs" ("Id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "Message" TEXT NOT NULL, "Time" DATETIME NOT NULL, "Logger" TEXT NOT NULL, "Exception" TEXT, "ExceptionType" TEXT, "Level" TEXT NOT NULL)',
            'CREATE TABLE "UpdateHistory" ("Id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "Date" DATETIME NOT NULL, "Version" TEXT NOT NULL, "EventType" INTEGER NOT NULL)',
            'CREATE TABLE "VersionInfo" ("Version" INTEGER NOT NULL, "AppliedOn" DATETIME, "Description" TEXT)',
            'CREATE INDEX "IX_Logs_Time" ON "Logs" ("Time" ASC)',
            'CREATE INDEX "IX_UpdateHistory_Date" ON "UpdateHistory" ("Date" ASC)',
            'CREATE UNIQUE INDEX "UC_Version" ON "VersionInfo" ("Version" ASC)',
        ):
            db.execute(sql)
        db.executemany('INSERT INTO Logs VALUES(?,?,?,?,?,?,?)', [
            (-2, 'synthetic', 1.5, 'test', None, b'\x00\xff', 'Info'),
            (7, 'synthetic', 1.5, 'test', None, b'\x00\xff', 'Info'),
            (99, b'binary', 'date-text', 'test', 'exception', None, 'Info'),
        ])
        db.execute("INSERT INTO UpdateHistory VALUES(4,'date','version',3)")
        db.execute("INSERT INTO VersionInfo(rowid,Version,AppliedOn,Description) VALUES(19,138,2.5,'fixture')")
        db.execute("UPDATE sqlite_sequence SET rowid=45,seq=1000 WHERE name='Logs'")
        db.execute('PRAGMA user_version=123')
        db.execute('PRAGMA application_id=456')
        root_page = db.execute("SELECT rootpage FROM sqlite_schema WHERE name='Logs'").fetchone()[0]
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        db.commit()
        db.close()
        return path, root_page, page_size

    def test_reconstructs_out_of_order_btree_without_losing_types_rows_or_rowids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, page, size = self.source(root)
            db = sqlite3.connect(path)
            expected = recovery.fingerprint(db)
            db.close()
            data = bytearray(path.read_bytes())
            offset = (page - 1) * size
            self.assertEqual(data[offset], 13)
            self.assertGreaterEqual(int.from_bytes(data[offset + 3:offset + 5], 'big'), 2)
            first = bytes(data[offset + 8:offset + 10])
            data[offset + 8:offset + 10] = data[offset + 10:offset + 12]
            data[offset + 10:offset + 12] = first
            path.write_bytes(data)
            original = hashlib.sha256(data).hexdigest()
            db = sqlite3.connect(path)
            self.assertNotEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(recovery.fingerprint(db), expected)
            db.close()
            result = recovery.reconstruct(root)
            self.assertEqual(result['source'], expected)
            self.assertEqual(result['source'], result['output'])
            self.assertTrue(result['output_integrity_ok'])
            self.assertFalse(result['accepted_recovery'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)

    def test_refuses_existing_output_and_unreviewed_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, _, _ = self.source(root)
            output = root / 'rebuilt.db'
            output.write_bytes(b'preserve existing output')
            with self.assertRaisesRegex(RuntimeError, 'paths'):
                recovery.reconstruct(root)
            self.assertEqual(output.read_bytes(), b'preserve existing output')
            output.unlink()
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE unreviewed(value)')
            db.close()
            with self.assertRaisesRegex(RuntimeError, 'schema'):
                recovery.reconstruct(root)
            self.assertFalse(output.exists())

    def test_refuses_symlink_source_and_does_not_accept_unreadable_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, _, _ = self.source(root)
            saved = root / 'saved.db'
            path.rename(saved)
            path.symlink_to(saved)
            with self.assertRaisesRegex(RuntimeError, 'paths'):
                recovery.reconstruct(root)
            path.unlink()
            path.write_bytes(b'not a database')
            with self.assertRaises(sqlite3.DatabaseError):
                recovery.reconstruct(root)
            self.assertFalse((root / 'rebuilt.db').exists())


if __name__ == '__main__':
    unittest.main()
