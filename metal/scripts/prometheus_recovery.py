#!/usr/bin/env python3
"""Capture a briefly stopped, identity-bound Prometheus store without replacing its Pod."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import signal
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

import etcd_recovery as common


POD_UID = "8c8708ed-dd73-4a5e-baee-9431663553f2"
IMAGE = "quay.io/prometheus/prometheus@sha256:f39df5334dee301b885f77e0ff1159f5d8a43bf9db518f885544594799a1e3c2"
DATA = Path("/var/lib/kubelet/pods") / POD_UID / "volumes/kubernetes.io~empty-dir/prometheus-monitoring-system-kube-pro-prometheus-db"
RETAINED = {'pod_uid': 'd069f1b1-5380-4527-8ff0-05dfc0756da2', 'node': 'growlithe', 'container_id': 'fd2c7f47a2b49dcfc6180828b13c78d0d2a181715377cd411f3c1c3bf3ed265c', 'claim_uid': '5d3f4f44-6907-4ccf-adb3-0bb6923649a1', 'pv_name': 'pvc-5d3f4f44-6907-4ccf-adb3-0bb6923649a1', 'pv_uid': 'c3d3fdf7-6204-4942-826a-b139a43fa185', 'csi_driver': 'rook-ceph.rbd.csi.ceph.com', 'volume_handle': '0001-0009-rook-ceph-0000000000000001-62a05c78-e139-4ef8-84d1-c09c96cc0bd2'}
RETAINED_METADATA_SHA256 = 'c0e4925add3585806f60bf875950f7341e326453dd2f68efdfe7f3698b04e8e3'
RETAINED_DATA = Path('/var/lib/kubelet/pods/d069f1b1-5380-4527-8ff0-05dfc0756da2/volumes/kubernetes.io~csi/pvc-5d3f4f44-6907-4ccf-adb3-0bb6923649a1/mount/prometheus-db')
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


def preparation_files(inventory):
    prepared = {name for name in inventory if BLOCK.fullmatch(Path(name).parts[0])}
    for parent in ("wal", "chunks_head"):
        segments = [name for name in inventory if Path(name).parent == Path(parent) and Path(name).name.isdigit()]
        if segments:
            newest = max(segments, key=lambda name: int(Path(name).name))
            prepared.update(name for name in segments if name != newest)
    return prepared


def retained_source_identity():
    common.require_host(RETAINED["node"])
    runtime = json.loads(common.command(["/usr/local/bin/crictl", "inspect", RETAINED["container_id"]]).stdout)
    status = runtime["status"]
    labels = status["labels"]
    root = RETAINED_DATA.parent.parent
    metadata = root / "vol_data.json"
    if (any(p.is_symlink() for p in (metadata, *metadata.parents)) or
            hashlib.sha256(metadata.read_bytes()).hexdigest() != RETAINED_METADATA_SHA256):
        raise RuntimeError("reviewed retained CSI metadata changed")
    value = json.loads(metadata.read_bytes())
    if (value.get("driverName") != RETAINED["csi_driver"] or
            value.get("volumeHandle") != RETAINED["volume_handle"] or
            status["state"] != "CONTAINER_RUNNING" or status["imageRef"] != IMAGE or
            labels.get("io.kubernetes.pod.uid") != RETAINED["pod_uid"] or
            labels.get("io.kubernetes.pod.namespace") != "monitoring-system" or
            labels.get("io.kubernetes.container.name") != "prometheus"):
        raise RuntimeError("reviewed retained runtime or CSI volume changed")
    process = process_identity(runtime["info"]["pid"])
    target = Path("/proc") / str(process["pid"]) / "root/prometheus"
    original = RETAINED_DATA.stat()
    if (any(p.is_symlink() for p in (RETAINED_DATA, *RETAINED_DATA.parents)) or
            (target.stat().st_dev, target.stat().st_ino) != (original.st_dev, original.st_ino) or
            process["exe"] != "/usr/bin/prometheus" or
            RETAINED["pod_uid"].replace("-", "_") not in process["cgroup"]):
        raise RuntimeError("reviewed process does not own the retained store")
    return {"pod_uid": RETAINED["pod_uid"], "image": IMAGE, "container_id": RETAINED["container_id"],
            "retained_storage": RETAINED, "csi_metadata_sha256": RETAINED_METADATA_SHA256,
            "data_device": original.st_dev, "data_inode": original.st_ino, "process": process}


def capture(run_id, container_id):
    return capture_store(run_id, lambda: source_identity(container_id), DATA, True)


def capture_retained(run_id):
    return capture_store(run_id, retained_source_identity, RETAINED_DATA, False)


def capture_store(run_id, identify, data, local_source):
    identity = identify()
    common.private_root()
    if common.ROOT.stat().st_dev != Path("/").stat().st_dev or (local_source and identity["data_device"] != Path("/").stat().st_dev):
        raise RuntimeError("reviewed source and recovery roots must remain on the local host filesystem")
    point = common.ROOT / ("prometheus-" + common.run_identifier(run_id))
    point.mkdir(mode=0o700)
    target = point / "data"
    target.mkdir(mode=0o700)
    initial = files(data)
    if sum(v[2] for v in initial.values()) > shutil.disk_usage(point).free:
        raise RuntimeError("insufficient actual capture capacity")
    records = {}
    for name in sorted(preparation_files(initial)):
        records[name] = copy_file(data / name, target / name, initial[name])
    if identify() != identity:
        raise RuntimeError("source changed during immutable-block preparation")
    with frozen(identity["process"], point / "watchdog-fired") as pause:
        current = files(data)
        if any(name not in current or current[name] != initial[name] for name in records):
            raise RuntimeError("prepared block or closed segment changed; candidate remains unaccepted")
        for name, metadata in current.items():
            if name not in records:
                records[name] = copy_file(data / name, target / name, metadata)
        if files(data) != current or identify() != identity:
            raise RuntimeError("stopped source changed during capture")
        for parent, _, _ in os.walk(target, topdown=False):
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    if identify() != identity:
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


def valid_source_manifest(source):
    if source.get("pod_uid") == POD_UID:
        return "retained_storage" not in source
    return (source.get("pod_uid") == RETAINED["pod_uid"] and source.get("retained_storage") == RETAINED and
            source.get("container_id") == RETAINED["container_id"] and
            source.get("csi_metadata_sha256") == RETAINED_METADATA_SHA256)


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("source"), dict) or
            manifest.get("format") != 1 or not valid_source_manifest(manifest["source"]) or
            manifest["source"].get("image") != IMAGE or
            not isinstance(manifest.get("files"), dict) or not manifest["files"] or
            len(manifest["files"]) > 10000 or not 0 < manifest.get("stopped_seconds", 0) < 10):
        raise RuntimeError("protected store manifest identity changed")
    for name, record in manifest["files"].items():
        if not isinstance(name, str) or not name or len(name) > 512:
            raise RuntimeError("unsafe protected store filename")
        path = PurePosixPath(name)
        if (not path.parts or path.is_absolute() or
                str(path) != name or any(part in (".", "..") for part in path.parts) or
                path.parts[0] not in ("wal", "chunks_head", "lock", "queries.active") and
                not BLOCK.fullmatch(path.parts[0]) or
                (path.parts[0] in ("lock", "queries.active")) != (len(path.parts) == 1) or
                not isinstance(record, dict) or set(record) != {"bytes", "sha256"} or
                type(record["bytes"]) is not int or record["bytes"] < 0 or
                not isinstance(record["sha256"], str) or
                not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])):
            raise RuntimeError("unsafe protected store file manifest")
    if manifest.get("bytes") != sum(v["bytes"] for v in manifest["files"].values()):
        raise RuntimeError("protected store byte accounting changed")
    if not any(PurePosixPath(name).parts[0] == "wal" for name in manifest["files"]):
        raise RuntimeError("protected store WAL is missing")
    return manifest


def verify_point(point, expected_hash):
    if any(p.is_symlink() for p in (point, *point.parents)):
        raise RuntimeError("protected point has symlink ancestry")
    common.source_record("verified.json", point / "verified.json")
    descriptor = os.open(point / "verified.json", os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        encoded = source.read(1048577)
    if len(encoded) > 1048576:
        raise RuntimeError("protected manifest exceeds framing contract")
    if hashlib.sha256(encoded).hexdigest() != expected_hash:
        raise RuntimeError("protected manifest hash changed")
    manifest = validate_manifest(json.loads(encoded))
    actual = files(point / "data")
    if set(actual) != set(manifest["files"]):
        raise RuntimeError("protected store file set changed")
    for name, expected in manifest["files"].items():
        path = point / "data" / name
        before = file_identity(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise RuntimeError("protected store file permissions changed")
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1048576), b""):
                digest.update(chunk)
        if file_identity(path) != before or {"bytes": before[2], "sha256": digest.hexdigest()} != expected:
            raise RuntimeError("protected store file hash changed")
    return manifest, encoded


def send_point(output, point, expected_hash):
    manifest, encoded = verify_point(point, expected_hash)
    if len(encoded) > 1048576 or b"\n" in encoded:
        raise RuntimeError("protected manifest exceeds framing contract")
    output.write(encoded + b"\n")
    for name in sorted(manifest["files"]):
        descriptor = os.open(point / "data" / name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            for chunk in iter(lambda: source.read(1048576), b""):
                output.write(chunk)
    verify_point(point, expected_hash)
    output.write(common.canonical({"commit": expected_hash}) + b"\n")
    output.flush()


def receive_point(source, point, expected_hash):
    encoded = source.readline(1048578)
    if not encoded.endswith(b"\n") or len(encoded) > 1048577:
        raise RuntimeError("invalid protected store framing")
    encoded = encoded[:-1]
    if hashlib.sha256(encoded).hexdigest() != expected_hash:
        raise RuntimeError("incoming protected manifest hash changed")
    manifest = validate_manifest(json.loads(encoded))
    if any(p.is_symlink() for p in (point.parent, *point.parent.parents)):
        raise RuntimeError("recovery destination ancestry contains a symlink")
    if manifest["bytes"] > shutil.disk_usage(point.parent).free:
        raise RuntimeError("insufficient actual off-master recovery capacity")
    point.mkdir(mode=0o700)
    data = point / "data"
    data.mkdir(mode=0o700)
    for name, record in sorted(manifest["files"].items()):
        target = data / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        remaining = record["bytes"]
        with target.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            while remaining:
                chunk = source.read(min(remaining, 1048576))
                if not chunk:
                    raise RuntimeError("protected store transfer truncated")
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != record["sha256"]:
            raise RuntimeError("incoming protected store file hash changed")
    if common.read_frame(source) != {"commit": expected_hash} or source.read(1):
        raise RuntimeError("protected store transfer commit missing or trailing data present")
    with (point / "verified.json").open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    for parent, _, _ in os.walk(point, topdown=False):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    verify_point(point, expected_hash)
    return {"manifest_sha256": expected_hash, "bytes": manifest["bytes"], "files": len(manifest["files"])}


def query_fingerprint(value):
    if (value.get("status") != "success" or value.get("data", {}).get("resultType") != "vector" or
            not isinstance(value["data"].get("result"), list) or not value["data"]["result"]):
        raise RuntimeError("nonempty successful native query evidence is required")
    rows = sorted(value["data"]["result"], key=common.canonical)
    return {"rows": len(rows), "sha256": hashlib.sha256(common.canonical(rows)).hexdigest()}


def log_diagnostic(data):
    findings = []
    replayed = False
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            fields = dict(word.split("=", 1) for word in shlex.split(line) if "=" in word)
        except ValueError:
            raise RuntimeError("native recovery log format is unparseable") from None
        message = fields.get("msg", "")
        replayed = replayed or message == "WAL replay completed"
        classification = "error" if fields.get("level", "").upper() == "ERROR" else next(
            (word for word in ("corrupt", "repair", "discard") if word in message.lower()), None)
        if classification:
            source = fields.get("source", "")
            findings.append({"class": classification, "level": fields.get("level"),
                             "source": source if re.fullmatch(r"[a-zA-Z0-9_.-]+\.go:\d+", source) else "unavailable",
                             "message_sha256": hashlib.sha256(message.encode()).hexdigest()})
    return {"findings": findings, "wal_replay_completed": replayed}


def restore(point, expected_hash, run_id, probes):
    common.require_host("pikachu")
    common.private_root()
    common.run_identifier(run_id)
    manifest, _ = verify_point(point, expected_hash)
    if not probes or any(set(p) != {"query", "time", "expected"} for p in probes):
        raise RuntimeError("fixed native query probes are required")
    label = "io.eaglepass.prometheus-recovery"
    if common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip():
        raise RuntimeError("another owned Prometheus recovery is active")
    if manifest["bytes"] > shutil.disk_usage(common.ROOT).free:
        raise RuntimeError("insufficient actual isolated restore capacity")
    previous_images = set(common.docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + "-restore-", dir=common.ROOT))
    container = image_id = None
    result = {"accepted": False, "manifest_sha256": expected_hash}
    stage = "copy_and_start"
    try:
        scratch.chmod(0o700)
        shutil.copytree(point / "data", scratch / "data")
        config = scratch / "prometheus.yml"
        config.write_text("global:\n  scrape_interval: 1m\nscrape_configs: []\n")
        config.chmod(0o600)
        common.docker("pull", IMAGE)
        image = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        if image["Architecture"] != "amd64" or image["Os"] != "linux" or image["Config"].get("Volumes"):
            raise RuntimeError("reviewed image architecture or volume contract changed")
        args = ["create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=0:0",
                "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=256",
                "--cpus=2", "--memory=2g", "--label=" + label + "=" + run_id,
                "--mount=type=bind,source=" + str(scratch) + ",target=/work",
                "--tmpfs=/tmp:rw,nosuid,nodev", "--entrypoint=/usr/bin/prometheus", IMAGE,
                "--config.file=/work/prometheus.yml", "--storage.tsdb.path=/work/data",
                "--storage.tsdb.retention.time=10d", "--web.listen-address=127.0.0.1:9090"]
        container = common.docker(*args).stdout.decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise RuntimeError("invalid owned restore container identity")
        state = common.inspect(container)
        host = state["HostConfig"]
        if (state["Config"].get("Labels", {}).get(label) != run_id or
                host["NetworkMode"] != "none" or not host["ReadonlyRootfs"] or host["Privileged"] or
                host["CapDrop"] != ["ALL"] or host.get("CapAdd") or host.get("Devices") or
                host.get("DeviceRequests") or host.get("PortBindings") or host.get("PidMode") or
                host.get("IpcMode") != "private" or host.get("UTSMode") or host.get("UsernsMode") or
                host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev"} or
                host["SecurityOpt"] != ["no-new-privileges:true"] or
                [(m.get("Type"), m.get("Source"), m.get("Destination"), m.get("RW"))
                 for m in state["Mounts"]] != [("bind", str(scratch), "/work", True)]):
            raise RuntimeError("native restore isolation contract changed")
        common.docker("start", container)
        pid = str(common.inspect(container)["State"]["Pid"])
        network = ["nsenter", "--target", pid, "--net", "--"]
        links = json.loads(common.command(network + ["ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command(network + ["ip", family, "-j", "route", "show", "table", "all"]).stdout)
                      for family in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command(network + ["ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("native restore can route to production")
        read = "import sys,urllib.request;sys.stdout.buffer.write(urllib.request.urlopen(sys.argv[1],timeout=60).read())"
        def request(path, check=True):
            return common.command(network + ["python3", "-B", "-c", read, "http://127.0.0.1:9090" + path], check=check)
        while request("/-/ready", check=False).returncode:
            if not common.inspect(container)["State"]["Running"]:
                raise RuntimeError("native recovery exited before readiness")
            time.sleep(1)
        version = json.loads(request("/api/v1/status/buildinfo").stdout)["data"]["version"]
        if version != "3.12.0":
            raise RuntimeError("native Prometheus version changed")
        result["version"] = version
        stage = "historical_queries"
        checks = []
        result["queries"] = checks
        for probe in probes:
            value = json.loads(request("/api/v1/query?" + urllib.parse.urlencode(
                {"query": probe["query"], "time": probe["time"]})).stdout)
            actual = query_fingerprint(value)
            checks.append({"query_sha256": hashlib.sha256(probe["query"].encode()).hexdigest(),
                           "time": probe["time"], **actual, "matches": actual == probe["expected"]})
            if actual != probe["expected"]:
                raise RuntimeError("native restored historical query differs")
        native_logs = common.docker("logs", container)
        logs = native_logs.stdout + native_logs.stderr
        stage = "native_log_acceptance"
        result["native_log_diagnostic"] = log_diagnostic(logs)
        if result["native_log_diagnostic"]["findings"]:
            raise RuntimeError("native TSDB recovery emitted an error or repair diagnostic")
        if not result["native_log_diagnostic"]["wal_replay_completed"]:
            raise RuntimeError("native WAL replay completion is unproven")
        result.update(accepted=True, version=version, queries=checks, network_none=True,
                      no_scrape_alert_or_remote_write_config=True, native_wal_replay_completed=True)
    except Exception as error:
        result.update(accepted=False, failed_stage=stage, failure_class=type(error).__name__)
    finally:
        if container is not None:
            if common.inspect(container)["Config"].get("Labels", {}).get(label) != run_id:
                raise RuntimeError("owned restore container identity changed during cleanup")
            common.docker("rm", "-f", "--volumes", container)
        shutil.rmtree(scratch)
        removed = False
        if image_id and image_id not in previous_images:
            if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
                removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
                if not removed:
                    raise RuntimeError("new native restore image remains")
        verify_point(point, expected_hash)
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_image_removed": removed,
                             "owned_container_absent": not common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip(),
                             "protected_original_unchanged": True}
    return result


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
