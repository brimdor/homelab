#!/usr/bin/env python3
"""Check timestamp fidelity, CRI refusal and complete query pagination."""

import importlib.util
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("continuity", Path(__file__).with_name("continuity.py"))
CONTINUITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTINUITY)


class ContinuityTests(unittest.TestCase):
    def test_audit_never_sends_and_repair_uses_verified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            recovery = root / "recovery"
            source.mkdir()
            recovery.mkdir()
            original = source / "source.log"
            original.write_text("1970-01-01T00:00:01Z stderr F original message\n")
            config = {"name": "test", "file": "source.log", "inode": original.stat().st_ino,
                      "uncompressed_bytes": original.stat().st_size,
                      "start": 10**9, "end": 10**9, "labels": {"pod": "test"}}
            with patch.object(CONTINUITY, "existing", return_value=set()), \
                    patch.object(CONTINUITY.urllib.request, "urlopen") as send:
                CONTINUITY.recover(config, False, recovery, source)
                send.assert_not_called()
            archived = recovery / "test/source.log"
            before = CONTINUITY.checksum(archived)
            original.unlink()
            present = {(10**9, CONTINUITY.hashlib.sha256(b"original message").hexdigest())}
            response = MagicMock()
            response.__enter__.return_value.status = 204
            with patch.object(CONTINUITY, "existing", side_effect=[set(), present]), \
                    patch.object(CONTINUITY.urllib.request, "urlopen", return_value=response) as send:
                CONTINUITY.recover(config, True, recovery, source)
                body = json.loads(send.call_args.args[0].data)
                self.assertEqual(body["streams"], [{"stream": {"pod": "test", "stream": "stderr"},
                                                    "values": [["1000000000", "original message"]]}])
            with patch.object(CONTINUITY, "existing", return_value=present), \
                    patch.object(CONTINUITY.urllib.request, "urlopen") as send:
                CONTINUITY.recover(config, True, recovery, source)
                send.assert_not_called()
            self.assertEqual(CONTINUITY.checksum(archived), before)

    def test_gzip_preserves_exact_cri_bytes_and_source_handle(self):
        content = b"1970-01-01T00:00:01Z stderr F original message\n"
        original = io.BytesIO(gzip.compress(content))
        target = io.BytesIO()
        CONTINUITY.copy_log(original, target, compressed=True)
        self.assertEqual(target.getvalue(), content)
        self.assertFalse(original.closed)

    def test_nanosecond_timestamp_is_exact(self):
        self.assertEqual(CONTINUITY.timestamp("1970-01-01T00:00:01.123456789Z"), 1123456789)
        self.assertEqual(CONTINUITY.timestamp("1970-01-01T00:00:01.1Z"), 1100000000)
        self.assertEqual(CONTINUITY.timestamp("1970-01-01T01:00:01.123456789+01:00"), 1123456789)
        self.assertEqual(CONTINUITY.timestamp("1969-12-31T19:00:01.123456789-05:00"), 1123456789)
        with self.assertRaisesRegex(RuntimeError, "timestamp"):
            CONTINUITY.timestamp("1970-01-01 00:00:01+00:00")

    def test_only_complete_original_records_in_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.log"
            path.write_text("1970-01-01T00:00:01Z stderr F original message\n"
                            "1970-01-01T00:00:02Z stdout F later message\n")
            self.assertEqual(CONTINUITY.records(path, 10**9, 10**9),
                             [(10**9, "stderr", "original message")])
            path.write_text("1970-01-01T00:00:01Z stderr P partial\n")
            with self.assertRaisesRegex(RuntimeError, "partial CRI"):
                CONTINUITY.records(path, 0, 3 * 10**9)

    def test_full_query_page_splits_without_boundary_overlap(self):
        pages = [5000, 1, 1]
        urls = []

        def response(url, timeout):
            urls.append(url)
            rows = [[str(n), "synthetic"] for n in range(pages.pop(0))]
            return io.BytesIO(json.dumps({"status": "success", "data": {
                "result": [{"values": rows}]}}).encode())

        with patch.object(CONTINUITY.urllib.request, "urlopen", side_effect=response):
            result = CONTINUITY.existing("http://example", {"pod": "test"}, 0, 10)
        self.assertEqual(len(result), 1)
        self.assertIn("start=0&end=5", urls[1])
        self.assertIn("start=6&end=10", urls[2])


if __name__ == "__main__":
    unittest.main()
