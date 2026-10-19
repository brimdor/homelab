#!/usr/bin/env python3
"""Native SQLite snapshot regression: complete types, metadata and framing."""
import io
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import sqlite_recovery as recovery

NODE = os.environ.get("NODE") or shutil.which("node")
PROGRAM = Path(recovery.__file__).with_suffix(".cjs").read_text()


@unittest.skipUnless(NODE, "native Node.js >=22.16 is required")
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.database = self.root / "source.sqlite"
        fixture = r"""const {DatabaseSync}=require('node:sqlite');const db=new DatabaseSync(process.argv[1]);
        db.exec("PRAGMA journal_mode=WAL;CREATE TABLE parent(id INTEGER PRIMARY KEY, content TEXT);CREATE TABLE child(id INTEGER, parent_id INTEGER REFERENCES parent(id), n REAL, b BLOB);CREATE TABLE no_rowid(id TEXT PRIMARY KEY, payload TEXT) WITHOUT ROWID;CREATE VIEW summary AS SELECT count(*) AS n FROM child;CREATE TRIGGER parent_added AFTER INSERT ON parent BEGIN INSERT INTO no_rowid VALUES (CAST(new.id AS TEXT),'trigger');END;");
        db.prepare('INSERT INTO parent VALUES (?,?)').run(9007199254740993n,'NUL\u0000 Unicode é 🚀');
        const insert=db.prepare('INSERT INTO child VALUES (?,?,?,?)');
        for(let i=0;i<2;i++)insert.run(7,9007199254740993n,1.25,Buffer.from([0,255,1]));db.close();"""
        self.native(fixture, str(self.database))

    def native(self, program, *args, success=True):
        result = subprocess.run([NODE, "--disable-warning=ExperimentalWarning", "-e", program, *args], capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b"")
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stdout

    def capture(self):
        return self.native(PROGRAM, "capture", str(self.database), str(self.root))

    def test_native_copy_preserves_types_duplicates_rowids_schema_and_metadata(self):
        data = self.capture()
        header = recovery.receive_database(io.BytesIO(data), self.root / "copy.sqlite")
        self.assertEqual(header["snapshot"]["tables"], 3)
        self.assertEqual(header["snapshot"]["rows"], 4)
        readonly = self.root / "readonly"; readonly.mkdir()
        original = readonly / "database.sqlite"; (self.root / "copy.sqlite").rename(original)
        original.chmod(0o400); readonly.chmod(0o500)
        try:
            result = json.loads(self.native(PROGRAM, "restore", str(original), str(self.root), json.dumps(header["snapshot"])))
            self.assertEqual([p.name for p in readonly.iterdir()], ["database.sqlite"])
        finally:
            readonly.chmod(0o700); original.chmod(0o600)
        self.assertTrue(result["accepted"])
        self.assertTrue(result["integrity_valid"])
        self.assertEqual(result["snapshot"], header["snapshot"])
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_invalid_frames_and_symlink_destinations_refused(self):
        data = self.capture()
        for name, damaged in (("truncated", data[:-20]), ("trailing", data + b"extra"),
                              ("corrupt", data.replace(b"SQLite format 3", b"SQLite FORMAT 3", 1))):
            with self.subTest(name=name), self.assertRaises((RuntimeError, ValueError)):
                recovery.receive_database(io.BytesIO(damaged), self.root / (name + ".sqlite"))
        link = self.root / "link.sqlite"; link.symlink_to(self.database)
        with self.assertRaises(RuntimeError):
            recovery.receive_database(io.BytesIO(data), link)

    def test_wrong_snapshot_refused_and_owned_native_scratch_removed(self):
        header = recovery.receive_database(io.BytesIO(self.capture()), self.root / "copy.sqlite")
        header["snapshot"]["data_sha256"] = "0" * 64
        self.native(PROGRAM, "restore", str(self.root / "copy.sqlite"), str(self.root), json.dumps(header["snapshot"]), success=False)
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_missing_source_never_initializes_database(self):
        missing = self.root / "missing.sqlite"
        self.native(PROGRAM, "capture", str(missing), str(self.root), success=False)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])


class KeyBindingTest(unittest.TestCase):
    def test_declared_key_must_match_same_secret_uid_and_running_process(self):
        data = b"synthetic-encryption-material"
        key = recovery.SOURCES["second-brain"]["key"]
        secret = {"metadata": {"uid": key["uid"]}, "data": {key["field"]: base64.b64encode(data).decode()}}
        command = SimpleNamespace(stdout=hashlib.sha256(data).hexdigest().encode())
        with patch.object(recovery, "kube", return_value=secret), patch.object(recovery.common, "command", return_value=command):
            self.assertEqual(recovery.declared_key("second-brain", {"pod": "reviewed-source"}), data)
            command.stdout = b"0" * 64
            with self.assertRaisesRegex(RuntimeError, "differs from the running application"):
                recovery.declared_key("second-brain", {"pod": "reviewed-source"})
            secret["metadata"]["uid"] = "another-secret"
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                recovery.declared_key("second-brain", {"pod": "reviewed-source"})


class ImageContractTest(unittest.TestCase):
    def test_exact_architecture_digest_and_existing_emulation_required(self):
        source = recovery.SOURCES["second-brain"]
        image = {"Architecture": "arm64", "Os": "linux", "Config": {"Volumes": None},
                 "RepoDigests": [source["image"]]}
        handler = ("enabled\ninterpreter /usr/bin/qemu-aarch64-static\nflags: F\noffset 0\n"
                   "magic 7f454c460201010000000000000000000200b700\n"
                   "mask ffffffffffffff00fffffffffffffffffeffffff\n").encode()
        with patch.object(Path, "read_bytes", return_value=handler):
            self.assertEqual(recovery.require_image(image, "second-brain")["architecture"], "arm64")
            for key, wrong in (("Architecture", "amd64"), ("Os", "other"), ("RepoDigests", []),
                               ("Config", {"Volumes": {"/unexpected": {}}})):
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    recovery.require_image({**image, key: wrong}, "second-brain")
        with patch.object(Path, "read_bytes", return_value=handler.replace(b"flags: F", b"flags:")):
            with self.assertRaisesRegex(RuntimeError, "emulation changed"):
                recovery.require_image(image, "second-brain")


if __name__ == "__main__":
    unittest.main()
