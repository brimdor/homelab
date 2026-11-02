#!/usr/bin/env python3
"""Scope, parser and attribution contracts for the aggregate observer."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import controlplane_io_capture as capture


def service(inode=100, written=0, read=0):
    return {"inode": inode, "name": "k3s.service", "root_device_observed": True,
            **dict.fromkeys(capture.IO_FIELDS, 0), "wbytes": written, "rbytes": read}


def raw_io(written=20, device="8:0"):
    return f"{device} rbytes=10 wbytes={written} rios=1 wios=2 dbytes=0 dios=0\n"


class CaptureContracts(unittest.TestCase):
    def test_device_parser_rejects_ambiguous_or_invalid_counters(self):
        self.assertEqual(capture.io_stat(raw_io())["8:0"]["wbytes"], 20)
        self.assertEqual(capture.io_stat(""), {})
        for invalid in (raw_io() * 2, raw_io().replace("wbytes=20", "wbytes=-1"),
                        raw_io().replace("8:0", "sda"), raw_io().replace("dios=0", ""),
                        raw_io().replace("dios=0", "dios=0 dios=1")):
            with self.assertRaises(RuntimeError):
                capture.io_stat(invalid)

    def test_only_physical_root_device_is_attributed_and_unknown_name_is_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-service.service"
            path.mkdir()
            (path / "io.stat").write_text(raw_io() + raw_io(99999, "8:2"))
            value = capture.service_io(path)
            self.assertEqual(value["wbytes"], 20)
            self.assertEqual(value["name"], "sha256:" + hashlib.sha256(path.name.encode()).hexdigest())
            self.assertTrue(value["root_device_observed"])

    def test_services_do_not_traverse_kubernetes_user_or_observer_cgroups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("kubepods.slice", "user.slice", "homelab-io-103.service", "k3s.service"):
                child = root / name
                child.mkdir()
                (child / "io.stat").write_text(raw_io() if name == "k3s.service" else "must not read")
            values, coverage = capture.services(root)
            self.assertEqual(set(values), {"k3s.service"})
            self.assertEqual(coverage["root_services_observed"], 1)

    def test_service_io_reads_no_process_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "io.stat").write_text(raw_io())
            with patch.object(capture.os, "open", wraps=capture.os.open) as opened:
                capture.service_io(path)
            self.assertEqual([c.args[0] for c in opened.call_args_list], [path, "io.stat"])

    def test_changed_cgroup_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "io.stat").write_text(raw_io())
            original = path.stat()
            with patch.object(Path, "stat", return_value=types.SimpleNamespace(
                    st_dev=original.st_dev, st_ino=original.st_ino + 1)):
                with self.assertRaisesRegex(RuntimeError, "cgroup changed"):
                    capture.service_io(path)

    def test_replaced_cgroups_and_reset_counters_are_not_attributed(self):
        before = {"a": service(written=10), "b": service(written=20), "c": service()}
        after = {"a": service(inode=101, written=1000), "b": service(written=2), "d": service()}
        value = capture.changes(before, after)
        self.assertEqual(value["top_host_services"], [])
        self.assertEqual(value["new_or_replaced_cgroups"], 2)
        self.assertEqual(value["counter_resets"], 1)
        self.assertEqual(value["exited_since_sample"], 1)

    def test_totals_include_services_outside_top_eight(self):
        before = {str(i): service(i) for i in range(20, 30)}
        after = {str(i): service(i, written=i) for i in range(20, 30)}
        value = capture.changes(before, after)
        self.assertEqual(len(value["top_host_services"]), 8)
        self.assertEqual(value["host_service_totals"]["wbytes"], sum(range(20, 30)))

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
                patch.object(capture, "services", return_value=({}, {})), \
                patch.object(capture, "output_file", return_value=(stream, "fixture.jsonl")), \
                patch.object(capture.signal, "signal", side_effect=lambda number, fn: handlers.update({number: fn})), \
                patch.object(capture.time, "monotonic", return_value=0), \
                patch.object(capture.time, "sleep", side_effect=lambda _delay: handlers[capture.signal.SIGTERM](15, None)), \
                patch.object(Path, "read_text", return_value="CapEff: 0000000000000000\nNoNewPrivs: 1\n"), \
                patch.object(capture, "disk", return_value=[]), \
                patch.object(capture, "pressure", return_value={}), \
                patch.object(capture.os, "fsync"):
            capture.capture(10)
        records = [json.loads(call.args[0]) for call in stream.write.call_args_list]
        self.assertEqual([r["type"] for r in records], ["header", "sample", "footer"])
        self.assertEqual(records[0]["format"], 2)
        self.assertEqual(records[0]["effective_capabilities"], 0)
        self.assertEqual(records[-1]["result"], "stopped")
        self.assertEqual(records[-1]["samples"], 1)
        stream.close.assert_called_once()

    def test_acceptance_requires_exact_source_successful_stop_and_complete_samples(self):
        host = {"node": "fixture"}
        header = {"type": "header", "format": 2, "host": host, "utc": "2026-11-02T22:00:00+00:00",
                  "source_sha256": hashlib.sha256(Path(capture.__file__).read_bytes()).hexdigest(),
                  "effective_capabilities": 0, "no_new_privileges": True, "device": "8:0"}
        sample = {"type": "sample", "root_services_observed": 1, "services_with_root_device": 1,
                  "interval_seconds": 1}
        state = Mock(parents=())
        state.is_symlink.return_value = False
        state.stat.return_value = types.SimpleNamespace(st_uid=0, st_mode=0o40700)
        state.glob.return_value = [Path("/synthetic/capture.jsonl")]

        class Stream(io.StringIO):
            def fileno(self):
                return 123

        cases = [(header, "stopped", 6, True), ({**header, "source_sha256": "wrong"}, "stopped", 6, False),
                 (header, "running", 6, False), (header, "stopped", 2, False)]
        for candidate, result, count, accepted in cases:
            data = [candidate] + [sample] * count + [{"type": "footer", "result": result, "samples": count}]
            with self.subTest(result=result, count=count, source=candidate["source_sha256"]), \
                    patch.object(capture, "identity", return_value=host), patch.object(capture, "STATE", state), \
                    patch.object(capture.os, "open", return_value=123), \
                    patch.object(capture.os, "fdopen", return_value=Stream("\n".join(map(json.dumps, data)))), \
                    patch.object(capture.os, "fstat", return_value=types.SimpleNamespace(st_mode=0o100600, st_uid=0)), \
                    patch("builtins.print"):
                if accepted:
                    capture.accept(1)
                else:
                    with self.assertRaises(RuntimeError):
                        capture.accept(1)


if __name__ == "__main__":
    unittest.main()
