#!/usr/bin/env python3
"""Private host-service aggregate I/O evidence for Issue 103."""

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
PUBLIC_NAMES = {"k3s.service", "containerd.service", "docker.service", "systemd-journald.service", "crond.service"}
IO_FIELDS = ("rbytes", "wbytes", "rios", "wios", "dbytes", "dios")
DEVICE = "8:0"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def identity():
    require(os.geteuid() == 0 and socket.gethostname() == "bulbasaur" and
            Path("/etc/machine-id").read_text().strip() == MACHINE, "unreviewed capture host")
    require(subprocess.check_output(["findmnt", "-n", "-o", "UUID", "/"], text=True).strip() == ROOT_UUID and
            subprocess.check_output(["getenforce"], text=True).strip() == "Enforcing", "root or SELinux changed")
    require(Path("/sys/block/sda/dev").read_text().strip() == DEVICE, "physical root device changed")
    return {"node": "bulbasaur", "machine": MACHINE, "root_uuid": ROOT_UUID,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def io_stat(raw):
    devices = {}
    for line in raw.splitlines():
        device, *fields = line.split()
        require(len(device.split(":")) == 2 and all(v.isdigit() for v in device.split(":")) and
                device not in devices, "invalid or duplicate I/O device")
        pairs = [field.split("=", 1) for field in fields]
        require(all(len(pair) == 2 for pair in pairs), "invalid I/O field")
        value = dict(pairs)
        require(len(value) == len(pairs) and all(k in value and value[k].isdigit() for k in IO_FIELDS),
                "invalid service I/O counters")
        devices[device] = {k: int(value[k]) for k in IO_FIELDS}
    return devices


def service_io(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        original = os.fstat(descriptor)
        with os.fdopen(os.open("io.stat", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)) as stream:
            devices = io_stat(stream.read())
        current = directory.stat(follow_symlinks=False)
        require((original.st_dev, original.st_ino) == (current.st_dev, current.st_ino), "service cgroup changed")
        name = directory.name
        public = name if name in PUBLIC_NAMES else "sha256:" + hashlib.sha256(name.encode()).hexdigest()
        return {"inode": original.st_ino, "name": public, "root_device_observed": DEVICE in devices,
                **devices.get(DEVICE, dict.fromkeys(IO_FIELDS, 0))}
    finally:
        os.close(descriptor)


def services(root=Path("/sys/fs/cgroup/system.slice")):
    values, exited = {}, 0
    for directory in root.iterdir():
        if not directory.name.endswith(".service") or directory.name == "homelab-io-103.service":
            continue
        try:
            values[directory.name] = service_io(directory)
        except FileNotFoundError:
            exited += 1
    require("k3s.service" in values and values["k3s.service"]["root_device_observed"], "K3s root-device accounting absent")
    return values, {"exited_during_read": exited, "root_services_observed": len(values),
                    "services_with_root_device": sum(v["root_device_observed"] for v in values.values())}


def changes(before, after):
    result, new, resets = [], 0, 0
    for name, value in after.items():
        old = before.get(name)
        if old is None or old["inode"] != value["inode"]:
            new += 1
            continue
        delta = {k: value[k] - old[k] for k in IO_FIELDS}
        if any(v < 0 for v in delta.values()):
            resets += 1
            continue
        if any(delta.values()):
            result.append({"name": value["name"], "inode": value["inode"], **delta})
    result.sort(key=lambda v: (v["wbytes"], v["rbytes"]), reverse=True)
    return {"top_host_services": result[:8], "host_service_totals": {k: sum(v[k] for v in result) for k in IO_FIELDS},
            "new_or_replaced_cgroups": new, "counter_resets": resets, "exited_since_sample": len(set(before) - set(after))}


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
    own = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    require(int(own["CapEff"].strip(), 16) == 0 and own["NoNewPrivs"].strip() == "1", "observer has unexpected privilege")
    before, _ = services()
    stream, name = output_file(STATE)
    started = previous = time.monotonic()
    samples, result = 0, "running"

    def write(value):
        value["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()

    try:
        write({"type": "header", "format": 2, "host": host, "observer_pid": os.getpid(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "seconds": seconds,
               "effective_capabilities": 0, "no_new_privileges": True, "device": DEVICE,
               "scope": "immediate host service aggregates; no per-process I/O or Kubernetes cgroup traversal"})
        while not stopped and time.monotonic() - started < seconds:
            time.sleep(1)
            after, coverage = services()
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


def accept(after):
    require(math.isfinite(after) and after > 0, "invalid qualification timestamp")
    host = identity()
    require(not any(p.is_symlink() for p in (STATE, *STATE.parents)), "unsafe evidence ancestry")
    meta = STATE.stat()
    require(meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o700, "evidence directory is not private")
    expected = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    accepted = []
    for path in STATE.glob("*.jsonl"):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as stream:
            meta = os.fstat(stream.fileno())
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o600,
                    "evidence file is not private")
            header = json.loads(stream.readline())
            if datetime.datetime.fromisoformat(header["utc"]).timestamp() < after:
                continue
            require(header["type"] == "header" and header["format"] == 2 and header["host"] == host and
                    header["source_sha256"] == expected and header["effective_capabilities"] == 0 and
                    header["no_new_privileges"] and header["device"] == DEVICE, "qualification header changed")
            records = [json.loads(line) for line in stream]
            require(records and records[-1]["type"] == "footer" and records[-1]["result"] == "stopped",
                    "qualification did not stop successfully")
            samples = records[:-1]
            require(len(samples) >= 5 and records[-1]["samples"] == len(samples), "incomplete qualification")
            require(all(r["type"] == "sample" and r["root_services_observed"] > 0 and
                        r["services_with_root_device"] > 0 and r["interval_seconds"] > 0 for r in samples),
                    "qualification lacks service coverage")
            accepted.append({"capture": path.name, "samples": len(samples), "source_sha256": expected,
                             "device": DEVICE, "format": 2, "effective_capabilities": 0})
    require(len(accepted) == 1, "qualification capture is absent or ambiguous")
    print(json.dumps(accepted[0]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=14400)
    parser.add_argument("--accept-after", type=float)
    args = parser.parse_args()
    require(1 <= args.seconds <= 14400, "unreviewed diagnostic window")
    os.umask(0o077)
    if args.accept_after is not None:
        accept(args.accept_after)
    else:
        capture(args.seconds)
