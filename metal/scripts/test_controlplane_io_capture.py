#!/usr/bin/env python3
"""Refusal and attribution contracts for the passive host observer."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import controlplane_io_capture as capture


def process(pid=42, start=100, written=0, read=0, cancelled=0):
    return {"pid": pid, "start_ticks": start, "name": "k3s", "write_bytes": written,
            "read_bytes": read, "cancelled_write_bytes": cancelled}


def raw_stat(name="k3s", start=100):
    return f"42 ({name}) S " + "0 " * 18 + str(start) + " 0 0"


class CaptureContracts(unittest.TestCase):
    def test_stat_handles_parentheses_and_redacts_unknown_names(self):
        name = "private ) process"
        value = capture.process_stat(raw_stat(name))
        self.assertEqual(value, {"pid": 42, "start_ticks": 100,
                                "name": "sha256:" + hashlib.sha256(name.encode()).hexdigest()})
        self.assertEqual(capture.process_stat(raw_stat())["name"], "k3s")

    def test_kubernetes_process_is_skipped_before_stat_or_io(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "cgroup").write_text("0::/kubepods.slice/private\n")
            self.assertIsNone(capture.process_io(path))

    def test_process_reuse_during_read_refuses_attribution(self):
        values = ["0::/system.slice/k3s.service", raw_stat(),
                  "read_bytes: 1\nwrite_bytes: 2\ncancelled_write_bytes: 0", raw_stat(start=101)]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(capture.os, "fdopen", side_effect=[io.StringIO(v) for v in values]):
                with patch.object(capture.os, "open", side_effect=[123, 124, 125, 126, 127]):
                    with patch.object(capture.os, "close") as close:
                        with self.assertRaisesRegex(RuntimeError, "process changed"):
                            capture.process_io(Path(directory))
                        close.assert_called_once_with(123)

    def test_reused_and_reset_counters_are_not_attributed(self):
        before = {42: process(written=10), 43: process(43, written=20), 44: process(44)}
        after = {42: process(start=101, written=1000), 43: process(43, written=2), 45: process(45)}
        value = capture.changes(before, after)
        self.assertEqual(value["top_host_processes"], [])
        self.assertEqual(value["new_or_reused_PIDs"], 2)
        self.assertEqual(value["counter_resets"], 1)
        self.assertEqual(value["exited_since_sample"], 1)

    def test_totals_include_processes_outside_top_eight(self):
        before = {i: process(i) for i in range(20, 30)}
        after = {i: process(i, written=i, cancelled=1) for i in before}
        value = capture.changes(before, after)
        self.assertEqual(len(value["top_host_processes"]), 8)
        self.assertEqual(value["host_process_totals"]["write_bytes"], sum(before))
        self.assertEqual(value["host_process_totals"]["cancelled_write_bytes"], 10)

    def test_incomplete_or_nonfinite_pressure_is_rejected(self):
        valid = "some avg10=0.1 avg60=0.0 avg300=0.0 total=42\nfull avg10=0.0 avg60=0.0 avg300=0.0 total=1"
        self.assertEqual(capture.pressure(valid)["some"]["total"], 42)
        for invalid in (valid.splitlines()[0], valid.replace("0.1", "nan"), valid.replace("0.1", "101")):
            with self.assertRaises(RuntimeError):
                capture.pressure(invalid)
        with self.assertRaises(RuntimeError):
            capture.disk("0 " * 10)

    def test_output_rejects_nonprivate_directory_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            path.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "not private"):
                capture.output_file(path)
            link = path / "link"
            link.symlink_to(path, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "ancestry"):
                capture.output_file(link)

    def test_signal_shutdown_writes_footer_and_closes_owned_stream(self):
        stream = Mock()
        handlers = {}
        with patch.object(capture, "identity", return_value={"node": "fixture"}), \
                patch.object(capture, "processes", return_value=({}, {})), \
                patch.object(capture, "output_file", return_value=(stream, "fixture.jsonl")), \
                patch.object(capture.signal, "signal", side_effect=lambda number, fn: handlers.update({number: fn})), \
                patch.object(capture.time, "monotonic", return_value=0), \
                patch.object(capture.time, "sleep", side_effect=lambda _delay: handlers[capture.signal.SIGTERM](15, None)), \
                patch.object(Path, "read_text", return_value=""), \
                patch.object(capture, "disk", return_value=[]), \
                patch.object(capture, "pressure", return_value={}), \
                patch.object(capture.os, "fsync"):
            capture.capture(10)
        records = [json.loads(call.args[0]) for call in stream.write.call_args_list]
        self.assertEqual([r["type"] for r in records], ["header", "sample", "footer"])
        self.assertEqual(records[-1]["result"], "stopped")
        self.assertEqual(records[-1]["samples"], 1)
        stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
