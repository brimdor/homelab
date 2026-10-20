#!/usr/bin/env python3
"""Exercise native snapshot boundaries with synthetic bytes only."""

import io
import json
from pathlib import Path
import tempfile
import unittest

import alertmanager_recovery as recovery


class NativeSnapshots(unittest.TestCase):
    def fixture(self):
        payloads = {"nflog": b"\x03one\x03two", "silences": b""}
        value = {"format": 1, "kind": "alertmanager-native-persisted-snapshots", "image": recovery.IMAGE,
                 "pod_uid": recovery.POD_UID, "captured_at": 1000, "unsnapshotted_ram_proven": False,
                 "files": {n: {"bytes": len(data), "sha256": recovery.digest(data), "snapshot_mtime": 900}
                           for n, data in payloads.items()}}
        return value, payloads

    def test_native_record_multiset_ignores_order_and_keeps_values_and_multiplicity(self):
        expected = recovery.records(b"\x03one\x03two")
        self.assertEqual(expected, recovery.records(b"\x03two\x03one"))
        self.assertNotEqual(expected, recovery.records(b"\x03two\x03two"))
        self.assertNotEqual(expected, recovery.records(b"\x03one\x03two\x03two"))
        for data in (b"\x00", b"\x80", b"\x05one", b"\x80" * 10, b"\x01x\x03a"):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                recovery.records(data)

    def test_native_snapshot_age_ram_and_empty_silence_contracts_refuse_changed_evidence(self):
        value, _ = self.fixture()
        recovery.validate_manifest(value)
        for name, content in (("unsnapshotted_ram_proven", True), ("image", "another-image"),
                              ("captured_at", 1801), ("captured_at", 899)):
            changed = json.loads(json.dumps(value))
            changed[name] = content
            with self.subTest(name=name, content=content), self.assertRaises(RuntimeError):
                recovery.validate_manifest(changed)
        value["files"]["silences"]["bytes"] = 1
        with self.assertRaises(RuntimeError):
            recovery.validate_manifest(value)

    def test_complete_protected_transfer_and_corrupt_or_truncated_stream_refusal(self):
        value, payloads = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original"
            expected = recovery.write_point(original, value, payloads)
            output = io.BytesIO()
            recovery.send_point(output, original, expected)
            data = output.getvalue()
            recovery.receive_point(io.BytesIO(data), root / "received", expected)
            self.assertEqual(recovery.verify_point(root / "received", expected), (value, payloads))
            for index, stream in enumerate((data[:-2], data + b"extra", data.replace(b"A29u", b"AAAA"))):
                candidate = root / ("invalid-" + str(index))
                # Make corruption independent of the particular base64 representation.
                if index == 2:
                    changed = json.loads(data)
                    changed["files"]["nflog"] = "Y29ycnVwdA=="
                    stream = json.dumps(changed).encode() + b"\n"
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    recovery.receive_point(io.BytesIO(stream), candidate, expected)
                self.assertFalse((candidate / "verified.json").exists())
            with self.assertRaises(FileExistsError):
                recovery.write_point(original, value, payloads)

    def test_protected_material_refuses_mutation_permissions_symlinks_and_extra_files(self):
        value, payloads = self.fixture()
        for change in ("bytes", "mode", "symlink", "extra"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                point = Path(directory) / "point"
                expected = recovery.write_point(point, value, payloads)
                if change == "bytes":
                    (point / "nflog").write_bytes(b"changed")
                elif change == "mode":
                    (point / "nflog").chmod(0o644)
                elif change == "symlink":
                    (point / "nflog").unlink()
                    (point / "nflog").symlink_to(point / "silences")
                else:
                    (point / "unexpected").touch()
                with self.assertRaises(RuntimeError):
                    recovery.verify_point(point, expected)


if __name__ == "__main__":
    unittest.main()
