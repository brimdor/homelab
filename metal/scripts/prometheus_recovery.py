#!/usr/bin/env python3
"""Capture a briefly stopped, identity-bound Prometheus store without replacing its Pod."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import stat
import subprocess
import sys
import time

import etcd_recovery as common


POD_UID = "8c8708ed-dd73-4a5e-baee-9431663553f2"
IMAGE = "quay.io/prometheus/prometheus@sha256:f39df5334dee301b885f77e0ff1159f5d8a43bf9db518f885544594799a1e3c2"
DATA = Path("/var/lib/kubelet/pods") / POD_UID / "volumes/kubernetes.io~empty-dir/prometheus-monitoring-system-kube-pro-prometheus-db"
BLOCK = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
WATCHDOG = """import os,pathlib,signal,sys,time
handle,ready=int(sys.argv[1]),int(sys.argv[2])
deadline=float(sys.argv[3]);fired=pathlib.Path(sys.argv[4])
os.write(ready,b'1');os.close(ready)
time.sleep(max(0,deadline-time.monotonic()))
signal.pidfd_send_signal(handle,signal.SIGCONT)
with fired.open('x') as output:
 output.write('resumed');output.flush();os.fsync(output.fileno())
"""


def process_identity(pid):
    if type(pid) is not int or pid <= 1:
        raise RuntimeError("invalid source process")
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start_ticks": fields[19], "exe": str((root / "exe").resolve()),
            "cgroup": (root / "cgroup").read_text()}


def thread_states(pid):
    return {int(task.name): next(line.split()[1] for line in (task / "status").read_text().splitlines()
                                if line.startswith("State:"))
            for task in (Path("/proc") / str(pid) / "task").iterdir()}


@contextmanager
def frozen(identity, marker):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("native pidfd support is required")
    if marker.exists() or process_identity(identity["pid"]) != identity:
        raise RuntimeError("source process or watchdog marker changed")
    if not thread_states(identity["pid"]) or any(s in ("T", "t", "Z", "X") for s in thread_states(identity["pid"]).values()):
        raise RuntimeError("source process is already stopped or unhealthy")
    handle = os.pidfd_open(identity["pid"])
    ready, notify = os.pipe()
    watchdog = None
    stopped = False
    result = {}
    try:
        if process_identity(identity["pid"]) != identity:
            raise RuntimeError("source process changed after pidfd open")
        rescue_deadline = time.monotonic() + 12
        watchdog = subprocess.Popen([sys.executable, "-B", "-c", WATCHDOG, str(handle), str(notify),
                                     str(rescue_deadline), str(marker)], pass_fds=(handle, notify),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(notify)
        notify = None
        if not select.select([ready], [], [], 1.5)[0] or os.read(ready, 1) != b"1" or watchdog.poll() is not None:
            raise RuntimeError("independent resume watchdog did not become ready")
        started = time.monotonic()
        deadline = min(started + 10, rescue_deadline - 0.5)
        if deadline - started < 9.5:
            raise RuntimeError("watchdog startup exhausted the safe pause budget")
        signal.pidfd_send_signal(handle, signal.SIGSTOP)
        stopped = True
        while True:
            states = thread_states(identity["pid"])
            if states and all(s == "T" for s in states.values()):
                break
            if time.monotonic() - started > 1:
                raise RuntimeError("source threads did not all stop")
            time.sleep(0.01)
        yield result
        if (time.monotonic() >= deadline or marker.exists() or watchdog.poll() is not None or
                process_identity(identity["pid"]) != identity or
                not thread_states(identity["pid"]) or
                any(s != "T" for s in thread_states(identity["pid"]).values())):
            raise RuntimeError("capture exceeded its safe stopped-source contract")
        result["stopped_seconds"] = time.monotonic() - started
    finally:
        try:
            resume_failed = False
            if stopped:
                try:
                    signal.pidfd_send_signal(handle, signal.SIGCONT)
                    resumed_deadline = time.monotonic() + 1
                    while any(s in ("T", "t") for s in thread_states(identity["pid"]).values()):
                        if time.monotonic() >= resumed_deadline:
                            raise RuntimeError("direct process resumption was not observed")
                        time.sleep(0.01)
                except BaseException:
                    resume_failed = True
            if watchdog is not None:
                if resume_failed:
                    # Keep the independent rescue alive when direct SIGCONT is uncertain.
                    watchdog.wait(timeout=14)
                    raise RuntimeError("direct resumption failed; independent watchdog retained until exit")
                else:
                    if watchdog.poll() is None:
                        watchdog.terminate()
                    try:
                        watchdog.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        watchdog.kill()
                        watchdog.wait()
        finally:
            os.close(handle)
            os.close(ready)
            if notify is not None:
                os.close(notify)
    if process_identity(identity["pid"]) != identity or any(s in ("T", "t") for s in thread_states(identity["pid"]).values()):
        raise RuntimeError("original source process has not resumed")


def file_identity(path):
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise RuntimeError("store contains a symlink or special file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def files(root):
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise RuntimeError("store root is missing or has a symlink ancestry")
    result = {}
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories:
            if not stat.S_ISDIR((Path(parent) / name).lstat().st_mode):
                raise RuntimeError("store directory is a symlink or special file")
        for name in names:
            path = Path(parent) / name
            relative = str(path.relative_to(root))
            top = Path(relative).parts[0]
            if top not in ("wal", "chunks_head", "lock", "queries.active") and not BLOCK.fullmatch(top):
                raise RuntimeError("unexpected store path")
            result[relative] = file_identity(path)
    if not result or not any(Path(name).parts[0] == "wal" for name in result):
        raise RuntimeError("complete nonempty WAL-backed store is required")
    return result


def copy_file(source, target, expected):
    if file_identity(source) != expected or target.exists():
        raise RuntimeError("source changed or recovery file already exists")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as original, target.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        for chunk in iter(lambda: original.read(1048576), b""):
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if file_identity(source) != expected or target.stat().st_size != expected[2]:
        raise RuntimeError("source changed during protected copy")
    return {"bytes": expected[2], "sha256": digest.hexdigest()}


def source_identity(container_id):
    common.require_host("totodile")
    if not re.fullmatch(r"[a-f0-9]{64}", container_id):
        raise RuntimeError("invalid reviewed runtime container ID")
    runtime = json.loads(common.command(["/usr/local/bin/crictl", "inspect", container_id]).stdout)
    status = runtime["status"]
    labels = status["labels"]
    if (status["state"] != "CONTAINER_RUNNING" or status["imageRef"] != IMAGE or
            labels.get("io.kubernetes.pod.uid") != POD_UID or
            labels.get("io.kubernetes.pod.namespace") != "monitoring-system" or
            labels.get("io.kubernetes.container.name") != "prometheus"):
        raise RuntimeError("reviewed Prometheus container identity changed")
    process = process_identity(runtime["info"]["pid"])
    target = Path("/proc") / str(process["pid"]) / "root/prometheus"
    before = DATA.stat()
    if ((target.stat().st_dev, target.stat().st_ino) != (before.st_dev, before.st_ino) or
            process["exe"] != "/usr/bin/prometheus" or POD_UID.replace("-", "_") not in process["cgroup"]):
        raise RuntimeError("process does not own the reviewed emptyDir")
    return {"pod_uid": POD_UID, "image": IMAGE, "container_id": container_id,
            "data_device": before.st_dev, "data_inode": before.st_ino, "process": process}


def capture(run_id, container_id):
    identity = source_identity(container_id)
    common.private_root()
    if common.ROOT.stat().st_dev != Path("/").stat().st_dev or identity["data_device"] != Path("/").stat().st_dev:
        raise RuntimeError("reviewed source and recovery roots must remain on the local host filesystem")
    point = common.ROOT / ("prometheus-" + common.run_identifier(run_id))
    point.mkdir(mode=0o700)
    target = point / "data"
    target.mkdir(mode=0o700)
    initial = files(DATA)
    if sum(v[2] for v in initial.values()) > shutil.disk_usage(point).free:
        raise RuntimeError("insufficient actual capture capacity")
    records = {}
    for name, metadata in initial.items():
        if BLOCK.fullmatch(Path(name).parts[0]):
            records[name] = copy_file(DATA / name, target / name, metadata)
    if source_identity(container_id) != identity:
        raise RuntimeError("source changed during immutable-block preparation")
    with frozen(identity["process"], point / "watchdog-fired") as pause:
        current = files(DATA)
        if any(name not in current or current[name] != initial[name] for name in records):
            raise RuntimeError("prepared immutable block changed; candidate remains unaccepted")
        for name, metadata in current.items():
            if name not in records:
                records[name] = copy_file(DATA / name, target / name, metadata)
        if files(DATA) != current or source_identity(container_id) != identity:
            raise RuntimeError("stopped source changed during capture")
        for parent, _, _ in os.walk(target, topdown=False):
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    if source_identity(container_id) != identity:
        raise RuntimeError("source changed after resumption")
    manifest = {"format": 1, "source": identity, "files": records,
                "bytes": sum(r["bytes"] for r in records.values()), **pause}
    data = common.canonical(manifest)
    with (point / "verified.json").open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(point, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"point": str(point), "manifest_sha256": hashlib.sha256(data).hexdigest(),
            "bytes": manifest["bytes"], "files": len(records), **pause}


def interrupted(number, frame):
    raise RuntimeError("owned recovery capture interrupted")


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--container-id", required=True)
    args = parser.parse_args()
    for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(number, interrupted)
    print(json.dumps(capture(args.run_id, args.container_id)), flush=True)
