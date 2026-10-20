#!/usr/bin/env python3
"""Refuse unsafe store identities and prove unconditional exact-process resumption."""

from contextlib import ExitStack
import hashlib
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
