#!/usr/bin/env python3
"""Refuse unsafe store identities and prove unconditional exact-process resumption."""

from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import prometheus_recovery as recovery


class RecoveryGuards(unittest.TestCase):
    def test_retained_source_manifest_requires_exact_pod_container_storage_and_csi_binding(self):
        value = {"pod_uid": recovery.RETAINED["pod_uid"], "container_id": recovery.RETAINED["container_id"],
                 "retained_storage": dict(recovery.RETAINED),
                 "csi_metadata_sha256": recovery.RETAINED_METADATA_SHA256}
        self.assertTrue(recovery.valid_source_manifest(value))
        for name in value:
            changed = dict(value)
            changed[name] = "changed"
            with self.subTest(name=name):
                self.assertFalse(recovery.valid_source_manifest(changed))
        self.assertTrue(recovery.valid_source_manifest({"pod_uid": recovery.POD_UID}))
        self.assertFalse(recovery.valid_source_manifest({"pod_uid": recovery.POD_UID, "retained_storage": {}}))

    def test_native_log_acceptance_checks_message_and_level_not_unrelated_query_fields(self):
        value = recovery.log_diagnostic(b'time=now level=INFO source=head.go:1 msg="WAL replay completed" duration=1s\n'
                                       b'time=now level=INFO source=tracker.go:2 msg="Recovered queries" query="rate(discarded_samples_total[5m])"\n')
        self.assertEqual(value, {"findings": [], "wal_replay_completed": True})
        for line, category in ((b'level=ERROR source=db.go:42 msg="Opening storage failed"', "error"),
                               (b'level=WARN source=head.go:12 msg="Corrupted WAL detected"', "corrupt"),
                               (b'level=INFO source=repair.go:17 msg="Repair completed"', "repair")):
            result = recovery.log_diagnostic(line)
            self.assertEqual(result["findings"][0]["class"], category)
            self.assertNotIn("msg", result["findings"][0])

    def test_only_blocks_and_older_numbered_segments_are_prepared_live(self):
        names = ["01ARZ3NDEKTSV4RRFFQ69G5FAV/index", "wal/00000009", "wal/00000010",
                 "chunks_head/000001", "chunks_head/000002", "wal/checkpoint.00000008/00000000",
                 "queries.active", "lock"]
        self.assertEqual(recovery.preparation_files(dict.fromkeys(names)),
                         {names[0], "wal/00000009", "chunks_head/000001"})

    def test_native_query_fingerprint_preserves_values_and_ignores_vector_order(self):
        rows = [{"metric": {"instance": "synthetic-a"}, "value": [123, "1"]},
                {"metric": {"instance": "synthetic-b"}, "value": [123, "2"]}]
        def result(values):
            return {"status": "success", "data": {"resultType": "vector", "result": values}}
        expected = recovery.query_fingerprint(result(rows))
        self.assertEqual(recovery.query_fingerprint(result(list(reversed(rows)))), expected)
        changed = json.loads(json.dumps(rows))
        changed[1]["value"][1] = "3"
        self.assertNotEqual(recovery.query_fingerprint(result(changed)), expected)
        for value in ({"status": "error"}, result([])):
            with self.assertRaises(RuntimeError):
                recovery.query_fingerprint(value)

    def test_stream_preserves_complete_store_and_refuses_truncation_corruption_and_trailing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            point = root / "original"
            (point / "data/wal").mkdir(parents=True)
            payloads = {"wal/00000000": b"synthetic WAL", "lock": b""}
            for name, value in payloads.items():
                path = point / "data" / name
                path.write_bytes(value)
                path.chmod(0o600)
            manifest = {"format": 1, "source": {"pod_uid": recovery.POD_UID, "image": recovery.IMAGE},
                        "stopped_seconds": 0.1, "bytes": sum(map(len, payloads.values())),
                        "files": {name: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                                  for name, value in payloads.items()}}
            encoded = recovery.common.canonical(manifest)
            (point / "verified.json").write_bytes(encoded)
            (point / "verified.json").chmod(0o600)
            expected = hashlib.sha256(encoded).hexdigest()
            output = io.BytesIO()
            recovery.send_point(output, point, expected)
            stream = output.getvalue()
            recovery.receive_point(io.BytesIO(stream), root / "received", expected)
            self.assertEqual(recovery.verify_point(root / "received", expected)[0], manifest)
            for index, value in enumerate((stream[:-8], stream.replace(b"synthetic WAL", b"corrupted WAL"), stream + b"extra")):
                destination = root / ("invalid-" + str(index))
                with self.assertRaises(RuntimeError):
                    recovery.receive_point(io.BytesIO(value), destination, expected)
                self.assertFalse((destination / "verified.json").exists())
            for name in ("../escape", "/absolute", "wal/../escape", "wal//segment", "", "wal"):
                changed = json.loads(encoded)
                changed["files"] = {name: manifest["files"]["wal/00000000"]}
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    recovery.validate_manifest(changed)

    @unittest.skipUnless(sys.platform == "linux", "native Linux pidfd qualification runs on the owned remote fixture")
    def test_native_watchdog_resumes_owned_fixture_after_capture_parent_is_killed(self):
        import ctypes
        library = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(library.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(library.prctl(36, 1, 0, 0, 0), 0)
        worker = watcher = None
        reaped = set()
        try:
            with tempfile.TemporaryDirectory(prefix="homelab-prometheus-watchdog-", dir="/run") as directory:
                root = Path(directory)
                progress = root / "progress"
                ready = root / "ready"
                marker = root / "watchdog-fired"
                code = "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n p.write_text(str(time.monotonic()));time.sleep(0.05)\n"
                target = subprocess.Popen([sys.executable, "-B", "-c", code, str(progress)],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, start_new_session=True)
                try:
                    deadline = time.monotonic() + 3
                    while not progress.exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    identity = recovery.process_identity(target.pid)
                    worker = os.fork()
                    if worker == 0:
                        try:
                            with recovery.frozen(identity, marker):
                                ready.write_text("stopped")
                                time.sleep(30)
                        finally:
                            os._exit(1)
                    deadline = time.monotonic() + 4
                    while not ready.exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    children = (Path("/proc") / str(worker) / "task" / str(worker) / "children").read_text().split()
                    self.assertEqual(len(children), 1)
                    watcher = int(children[0])
                    self.assertTrue(all(state == "T" for state in recovery.thread_states(target.pid).values()))
                    stopped_progress = progress.read_text()
                    os.kill(worker, signal.SIGKILL)
                    _, status = os.waitpid(worker, 0)
                    reaped.add(worker)
                    self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
                    deadline = time.monotonic() + 14
                    while not marker.exists() or progress.read_text() == stopped_progress:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.05)
                    self.assertEqual(recovery.process_identity(target.pid), identity)
                    self.assertTrue(all(state not in ("T", "t") for state in recovery.thread_states(target.pid).values()))
                    _, status = os.waitpid(watcher, 0)
                    reaped.add(watcher)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                finally:
                    if worker is not None and worker not in reaped:
                        try:
                            os.kill(worker, signal.SIGSTOP)
                            deadline = time.monotonic() + 2
                            while any(s not in ("T", "Z") for s in recovery.thread_states(worker).values()):
                                if time.monotonic() >= deadline:
                                    raise RuntimeError("owned fixture worker did not stop for cleanup")
                                time.sleep(0.01)
                            children = (Path("/proc") / str(worker) / "task" / str(worker) / "children").read_text().split()
                            if children:
                                self.assertEqual(len(children), 1)
                                watcher = int(children[0])
                        except ProcessLookupError:
                            pass
                    if target.poll() is None:
                        target.send_signal(signal.SIGCONT)
                        target.terminate()
                        try:
                            target.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            target.kill()
                            target.wait()
                    for child in (worker, watcher):
                        if child is not None and child not in reaped:
                            try:
                                os.kill(child, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            os.waitpid(child, 0)
                    self.assertFalse(any((Path("/proc") / str(pid)).exists()
                                         for pid in (target.pid, worker, watcher) if pid is not None))
                self.assertTrue(root.exists())
            self.assertFalse(root.exists())
        finally:
            self.assertEqual(library.prctl(36, previous.value, 0, 0, 0), 0)

    def test_complete_store_copy_hashes_bytes_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "wal").mkdir(parents=True)
            original = source / "wal/00000000"
            original.write_bytes(b"synthetic WAL records")
            before = recovery.files(source)
            target = root / "copy/wal/00000000"
            result = recovery.copy_file(original, target, before["wal/00000000"])
            self.assertEqual(target.read_bytes(), original.read_bytes())
            self.assertEqual(result, {"bytes": 21, "sha256": hashlib.sha256(original.read_bytes()).hexdigest()})
            self.assertEqual(recovery.files(source), before)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                recovery.copy_file(original, target, before["wal/00000000"])

    def test_store_refuses_symlinks_unknown_roots_and_missing_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wal").mkdir()
            (root / "wal/segment").write_bytes(b"synthetic")
            (root / "wal/link").symlink_to(root / "wal/segment")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                recovery.files(root)
            (root / "wal/link").unlink()
            (root / "unexpected").write_bytes(b"synthetic")
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                recovery.files(root)
            (root / "unexpected").unlink()
            (root / "wal/segment").unlink()
            with self.assertRaisesRegex(RuntimeError, "nonempty WAL"):
                recovery.files(root)

    def freezer(self, stack, marker, *, ready=True):
        identity = {"pid": 222, "start_ticks": "123", "exe": "synthetic", "cgroup": "synthetic"}
        state = {"value": "S"}
        watchdog = Mock()
        watchdog.poll.return_value = None
        watchdog.terminate.side_effect = lambda: setattr(watchdog.poll, "return_value", 0)
        signals = []
        def send(handle, number):
            signals.append((handle, number))
            state["value"] = "T" if number == signal.SIGSTOP else "S"
        def start(*args, **kwargs):
            if ready:
                os.write(kwargs["pass_fds"][1], b"1")
            return watchdog
        stack.enter_context(patch.object(recovery, "process_identity", return_value=identity))
        stack.enter_context(patch.object(recovery, "thread_states", side_effect=lambda _: {222: state["value"]}))
        stack.enter_context(patch.object(recovery.os, "pidfd_open", create=True,
                                        side_effect=lambda _: os.open(os.devnull, os.O_RDONLY)))
        stack.enter_context(patch.object(recovery.signal, "pidfd_send_signal", create=True, side_effect=send))
        stack.enter_context(patch.object(recovery.subprocess, "Popen", side_effect=start))
        if not ready:
            stack.enter_context(patch.object(recovery.select, "select", return_value=([], [], [])))
        return identity, signals, watchdog, state

    def test_capture_exception_always_resumes_exact_handle_and_reaps_watchdog(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            marker = Path(directory) / "fired"
            identity, signals, watchdog, state = self.freezer(stack, marker)
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                with recovery.frozen(identity, marker):
                    raise RuntimeError("synthetic interruption")
            self.assertEqual([number for _, number in signals], [signal.SIGSTOP, signal.SIGCONT])
            self.assertEqual(signals[0][0], signals[1][0])
            self.assertEqual(state["value"], "S")
            watchdog.wait.assert_called_once()

    def test_watchdog_firing_invalidates_capture_and_still_resumes(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            marker = Path(directory) / "fired"
            identity, signals, _, _ = self.freezer(stack, marker)
            with self.assertRaisesRegex(RuntimeError, "safe stopped-source"):
                with recovery.frozen(identity, marker):
                    marker.write_text("synthetic watchdog fired")
            self.assertEqual(signals[-1][1], signal.SIGCONT)

    def test_watchdog_must_be_ready_before_source_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            marker = Path(directory) / "fired"
            identity, signals, watchdog, _ = self.freezer(stack, marker, ready=False)
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                with recovery.frozen(identity, marker):
                    self.fail("unready watchdog entered capture")
            self.assertEqual(signals, [])
            watchdog.wait.assert_called_once()

    def test_pid_reuse_is_refused_before_any_signal(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            marker = Path(directory) / "fired"
            identity, signals, _, _ = self.freezer(stack, marker)
            with patch.object(recovery, "process_identity", side_effect=[identity, {**identity, "start_ticks": "124"}]):
                with self.assertRaisesRegex(RuntimeError, "changed after pidfd"):
                    with recovery.frozen(identity, marker):
                        self.fail("changed process entered capture")
            self.assertEqual(signals, [])

    def test_uncertain_direct_resume_never_terminates_independent_watchdog(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            marker = Path(directory) / "fired"
            identity, _, watchdog, state = self.freezer(stack, marker)
            def send(handle, number):
                if number == signal.SIGCONT:
                    raise OSError("synthetic direct resume failure")
                state["value"] = "T"
            watchdog.wait.side_effect = lambda **_: state.update(value="S")
            with patch.object(recovery.signal, "pidfd_send_signal", side_effect=send):
                with self.assertRaisesRegex(RuntimeError, "independent watchdog retained"):
                    with recovery.frozen(identity, marker):
                        pass
            watchdog.terminate.assert_not_called()
            watchdog.kill.assert_not_called()
            watchdog.wait.assert_called_once_with(timeout=14)
            self.assertEqual(state["value"], "S")


if __name__ == "__main__":
    unittest.main()
