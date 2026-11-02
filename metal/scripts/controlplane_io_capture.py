#!/usr/bin/env python3
"""Private host-only I/O accounting for the Issue 103 control-plane investigation."""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import time
import uuid


MACHINE = "f61201c3e2ba4b8cbd31e09f77da2ad0"
ROOT_UUID = "2c59d1d1-d2d8-420e-b3a5-d87eb0437823"
STATE = Path("/var/lib/homelab-io-103")
PUBLIC_NAMES = {"k3s-server", "k3s", "containerd", "systemd-journal", "systemd", "crond"}
IO_FIELDS = ("read_bytes", "write_bytes", "cancelled_write_bytes")


def require(value, message):
    if not value:
        raise RuntimeError(message)


def identity():
    require(os.geteuid() == 0 and socket.gethostname() == "bulbasaur" and
            Path("/etc/machine-id").read_text().strip() == MACHINE, "unreviewed capture host")
    require(subprocess.check_output(["findmnt", "-n", "-o", "UUID", "/"], text=True).strip() == ROOT_UUID and
            subprocess.check_output(["getenforce"], text=True).strip() == "Enforcing", "root or SELinux changed")
    return {"node": "bulbasaur", "machine": MACHINE, "root_uuid": ROOT_UUID,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def process_stat(raw):
    before, separator, after = raw.rpartition(")")
    require(separator and "(" in before, "unrecognized process stat")
    pid, name = before.split("(", 1)
    fields = after.split()
    require(pid.strip().isdigit() and len(fields) >= 20 and fields[19].isdigit(), "invalid process identity")
    public = name if name in PUBLIC_NAMES else "sha256:" + hashlib.sha256(name.encode()).hexdigest()
    return {"pid": int(pid), "start_ticks": int(fields[19]), "name": public}


def process_io(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def read(name):
        with os.fdopen(os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)) as stream:
            return stream.read()

    try:
        # A retained proc directory descriptor cannot resolve to a reused PID.
        if "kubepods" in read("cgroup"):
            return None
        before = process_stat(read("stat"))
        counters = dict(line.split(":", 1) for line in read("io").splitlines())
        require(all(k in counters and counters[k].strip().isdigit() for k in IO_FIELDS), "invalid I/O counters")
        after = process_stat(read("stat"))
        require(before == after, "process changed during observation")
        return {**before, **{k: int(counters[k]) for k in IO_FIELDS}}
    finally:
        os.close(descriptor)


def processes(root=Path("/proc")):
    values, exited, skipped = {}, 0, 0
    for directory in root.iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            value = process_io(directory)
        except (FileNotFoundError, ProcessLookupError):
            exited += 1
            continue
        if value is None:
            skipped += 1
        else:
            values[value["pid"]] = value
    return values, {"exited_during_read": exited, "Kubernetes_processes_skipped": skipped}


def changes(before, after):
    result, new, resets = [], 0, 0
    for pid, value in after.items():
        old = before.get(pid)
        if old is None or old["start_ticks"] != value["start_ticks"]:
            new += 1
            continue
        delta = {k: value[k] - old[k] for k in IO_FIELDS}
        if any(v < 0 for v in delta.values()):
            resets += 1
            continue
        if any(delta.values()):
            result.append({**{k: value[k] for k in ("pid", "start_ticks", "name")}, **delta})
    result.sort(key=lambda v: (v["write_bytes"], v["read_bytes"]), reverse=True)
    return {"top_host_processes": result[:8], "host_process_totals": {k: sum(v[k] for v in result) for k in IO_FIELDS},
            "new_or_reused_PIDs": new, "counter_resets": resets, "exited_since_sample": len(set(before) - set(after))}


def pressure(raw):
    result = {}
    for line in raw.splitlines():
        name, *fields = line.split()
        require(name in ("some", "full") and name not in result, "unknown pressure format")
        value = dict(field.split("=", 1) for field in fields)
        require(set(value) == {"avg10", "avg60", "avg300", "total"} and value["total"].isdigit(), "invalid pressure fields")
        result[name] = {k: int(v) if k == "total" else float(v) for k, v in value.items()}
        require(all(math.isfinite(v) and 0 <= v <= 100 for k, v in result[name].items() if k != "total"),
                "invalid pressure average")
    require(set(result) == {"some", "full"}, "incomplete I/O pressure")
    return result


def disk(raw):
    fields = raw.split()
    require(len(fields) >= 11 and all(v.isdigit() for v in fields), "invalid disk counters")
    return [int(v) for v in fields]


def output_file(directory):
    require(not any(p.is_symlink() for p in (directory, *directory.parents)), "unsafe capture ancestry")
    meta = directory.stat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o700,
            "capture directory is not private")
    name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex + ".jsonl"
    descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return os.fdopen(descriptor, "w"), name


def capture(seconds):
    host = identity()
    stopped = False

    def stop(_number, _frame):
        nonlocal stopped
        stopped = True

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, stop)
    before, _ = processes()
    stream, name = output_file(STATE)
    started = previous = time.monotonic()
    samples, result = 0, "running"

    def write(value):
        value["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()

    try:
        write({"type": "header", "format": 1, "host": host, "observer_pid": os.getpid(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "seconds": seconds,
               "scope": "host processes only; no arguments, environment, application files or Kubernetes process I/O"})
        while not stopped and time.monotonic() - started < seconds:
            time.sleep(1)
            after, coverage = processes()
            instant = time.monotonic()
            write({"type": "sample", "elapsed_seconds": instant - started, "interval_seconds": instant - previous,
                   **changes(before, after), **coverage,
                   "sda_counters": disk(Path("/sys/block/sda/stat").read_text()),
                   "io_pressure": pressure(Path("/proc/pressure/io").read_text())})
            samples += 1
            if samples % 15 == 0:
                os.fsync(stream.fileno())
            before, previous = after, instant
        require(identity() == host, "host identity changed during capture")
        result = "stopped" if stopped else "complete"
    finally:
        try:
            write({"type": "footer", "result": result, "samples": samples,
                   "elapsed_seconds": time.monotonic() - started})
            os.fsync(stream.fileno())
        finally:
            stream.close()
    print(json.dumps({"capture": name, "samples": samples, "result": result}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=14400)
    args = parser.parse_args()
    require(1 <= args.seconds <= 14400, "unreviewed diagnostic window")
    os.umask(0o077)
    capture(args.seconds)
