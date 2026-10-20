#!/usr/bin/env python3
"""Preserve dated native snapshots; never equate them with unsnapshotted RAM."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time

import etcd_recovery as common
import prometheus_recovery as shared


POD_UID = "318d7270-40b8-4b7d-a2d5-da168801b4e3"
CONTAINER = "3a862b98a802ed981362b21365c589a4ed3023648f10e905a636d4cbe8307a7f"
IMAGE = "quay.io/prometheus/alertmanager@sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286"
DATA = Path("/var/lib/kubelet/pods") / POD_UID / "volumes/kubernetes.io~empty-dir/alertmanager-monitoring-system-kube-pro-alertmanager-db"
NAMES = {"nflog", "silences"}
LIMIT = 32 * 1024 * 1024
METRICS = {"alertmanager_cluster_enabled", "alertmanager_nflog_maintenance_total",
           "alertmanager_nflog_maintenance_errors_total", "alertmanager_nflog_snapshot_size_bytes",
           "alertmanager_silences_maintenance_total", "alertmanager_silences_maintenance_errors_total",
           "alertmanager_silences_snapshot_size_bytes", "alertmanager_silences_state_size",
           "alertmanager_silences_version_index_size", "process_start_time_seconds"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def records(data):
    """Fingerprint every opaque protobuf-delimited record without retaining its contents."""
    offset = 0
    values = []
    while offset < len(data):
        length = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise RuntimeError("truncated native record length")
            byte = data[offset]
            offset += 1
            length |= (byte & 127) << shift
            if not byte & 128:
                break
        else:
            raise RuntimeError("oversized native record length")
        if not length or length > LIMIT or offset + length > len(data):
            raise RuntimeError("invalid or truncated native record")
        values.append(digest(data[offset:offset + length]))
        offset += length
    return {"records": len(values), "sha256": digest(common.canonical(sorted(values)))}


def source_identity():
    common.require_host("totodile")
    runtime = json.loads(common.command(["/usr/local/bin/crictl", "inspect", CONTAINER]).stdout)
    status = runtime["status"]
    labels = status["labels"]
    if (status["state"] != "CONTAINER_RUNNING" or status["imageRef"] != IMAGE or
            labels.get("io.kubernetes.pod.uid") != POD_UID or
            labels.get("io.kubernetes.pod.namespace") != "monitoring-system" or
            labels.get("io.kubernetes.container.name") != "alertmanager"):
        raise RuntimeError("reviewed Alertmanager source identity changed")
    process = shared.process_identity(runtime["info"]["pid"])
    root = Path("/proc") / str(process["pid"])
    arguments = (root / "cmdline").read_bytes().split(b"\0")
    target = (root / "root/alertmanager").stat()
    original = DATA.stat()
    if (any(p.is_symlink() for p in (DATA, *DATA.parents)) or
            (target.st_dev, target.st_ino) != (original.st_dev, original.st_ino) or
            original.st_dev != Path("/").stat().st_dev or
            process["exe"] not in ("/bin/alertmanager", "/usr/bin/alertmanager") or
            POD_UID.replace("-", "_") not in process["cgroup"] or
            b"--cluster.listen-address=" not in arguments or b"--storage.path=/alertmanager" not in arguments):
        raise RuntimeError("source process, local storage or disabled cluster contract changed")
    return {"pod_uid": POD_UID, "image": IMAGE, "container_id": CONTAINER, "process": process,
            "data_device": original.st_dev, "data_inode": original.st_ino}


def request(pid, path, check=True):
    code = "import sys,urllib.request;sys.stdout.buffer.write(urllib.request.urlopen(sys.argv[1],timeout=15).read())"
    return common.command(["nsenter", "--target", str(pid), "--net", "--", "python3", "-B", "-c", code,
                           "http://127.0.0.1:9093" + path], check=check)


def state(pid):
    lines = request(pid, "/metrics").stdout.decode().splitlines()
    selected = {line.split()[0]: float(line.split()[1]) for line in lines if line.split() and line.split()[0] in METRICS}
    if set(selected) != METRICS:
        raise RuntimeError("native persistence metrics are incomplete")
    status = json.loads(request(pid, "/api/v2/status").stdout)
    if (status["versionInfo"]["version"] != "0.32.1" or
            json.loads(request(pid, "/api/v2/silences").stdout) != [] or
            any(selected[k] != 0 for k in METRICS if k.endswith(("errors_total", "state_size", "index_size", "cluster_enabled"))) or
            any(selected[k] <= 0 for k in METRICS if k.endswith("maintenance_total"))):
        raise RuntimeError("native snapshot health, version, silences or cluster contract changed")
    return selected


def quiet_state(pid, config_sha256):
    """Require the reviewed integration-free config and exact notification counters."""
    status = json.loads(request(pid, "/api/v2/status").stdout)
    config = status["config"]["original"]
    if (digest(config.encode()) != config_sha256 or "maintenance-null" not in config or
            re.search(r"(?m)^\s*\w+_configs:", config)):
        raise RuntimeError("reviewed notification hold config changed")
    lines = request(pid, "/metrics").stdout.decode().splitlines()
    counters = {line.split()[0]: float(line.split()[1]) for line in lines
                if line.startswith(("alertmanager_notifications_total{", "alertmanager_notifications_failed_total{",
                                    "alertmanager_nflog_queries_total "))}
    if "alertmanager_nflog_queries_total" not in counters or len(counters) < 3:
        raise RuntimeError("notification hold counters are incomplete")
    return counters


def protected_write(path, data):
    with path.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def read_file(path):
    identity = shared.file_identity(path)
    if identity[2] > LIMIT:
        raise RuntimeError("snapshot exceeds reviewed bounded stream contract")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        data = source.read(LIMIT + 1)
    if len(data) != identity[2] or shared.file_identity(path) != identity:
        raise RuntimeError("native snapshot changed while reading")
    return data, identity


def validate_manifest(value):
    if (value.get("format") != 1 or value.get("kind") != "alertmanager-native-persisted-snapshots" or
            value.get("image") != IMAGE or value.get("pod_uid") != POD_UID or
            value.get("unsnapshotted_ram_proven") is not False or set(value.get("files", {})) != NAMES or
            not isinstance(value.get("captured_at"), (int, float))):
        raise RuntimeError("native snapshot manifest contract changed")
    for name, item in value["files"].items():
        if (set(item) != {"bytes", "sha256", "snapshot_mtime"} or type(item["bytes"]) is not int or
                not 0 <= item["bytes"] <= LIMIT or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) or
                not isinstance(item["snapshot_mtime"], (int, float)) or
                not 0 <= value["captured_at"] - item["snapshot_mtime"] <= 900):
            raise RuntimeError("native snapshot size, hash or capture age is invalid")
        if name == "silences" and item["bytes"] != 0:
            raise RuntimeError("nonempty silences require a separate native comparison contract")
    if "current_persisted_ram_proven" in value:
        hold = value.get("quiescence", {})
        if (value["current_persisted_ram_proven"] is not True or
                set(hold) != {"held_at", "config_sha256", "counters_before", "counters_after",
                              "maintenance_before", "maintenance_after"} or
                not re.fullmatch(r"[a-f0-9]{64}", hold.get("config_sha256", "")) or
                not isinstance(hold.get("held_at"), (int, float)) or
                hold["counters_before"] != hold["counters_after"] or
                "alertmanager_nflog_queries_total" not in hold["counters_before"] or
                set(hold["maintenance_before"]) != {"nflog", "silences"} or
                set(hold["maintenance_after"]) != {"nflog", "silences"} or
                any(hold["maintenance_after"][n] <= hold["maintenance_before"][n] or
                    value["files"][n]["snapshot_mtime"] <= hold["held_at"] for n in NAMES)):
            raise RuntimeError("fresh full-state snapshot evidence is incomplete or changed")


def verify_point(point, expected):
    info = point.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700 or
            any(p.is_symlink() for p in point.parents) or {p.name for p in point.iterdir()} != NAMES | {"verified.json"}):
        raise RuntimeError("protected point ownership or file set changed")
    for path in point.iterdir():
        item = path.lstat()
        if not stat.S_ISREG(item.st_mode) or item.st_uid != os.geteuid() or stat.S_IMODE(item.st_mode) != 0o600:
            raise RuntimeError("protected snapshot file ownership changed")
    data, _ = read_file(point / "verified.json")
    if digest(data) != expected:
        raise RuntimeError("protected manifest hash differs")
    value = json.loads(data)
    validate_manifest(value)
    payloads = {}
    for name, item in value["files"].items():
        payloads[name], _ = read_file(point / name)
        if len(payloads[name]) != item["bytes"] or digest(payloads[name]) != item["sha256"]:
            raise RuntimeError("protected native snapshot hash differs")
    return value, payloads


def write_point(point, value, payloads):
    validate_manifest(value)
    if any(p.is_symlink() for p in (point.parent, *point.parent.parents)):
        raise RuntimeError("native recovery destination ancestry contains a symlink")
    if set(payloads) != NAMES or any(len(payloads[n]) != value["files"][n]["bytes"] or
                                   digest(payloads[n]) != value["files"][n]["sha256"] for n in NAMES):
        raise RuntimeError("native bundle is incomplete or corrupt")
    if sum(map(len, payloads.values())) > shutil.disk_usage(point.parent).free:
        raise RuntimeError("insufficient actual protected recovery capacity")
    point.mkdir(mode=0o700)
    for name, data in payloads.items():
        protected_write(point / name, data)
    manifest = common.canonical(value)
    protected_write(point / "verified.json", manifest)
    for parent in (point, point.parent):
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    verify_point(point, digest(manifest))
    return digest(manifest)


def capture(run_id, hold=None):
    identity = source_identity()
    before = state(identity["process"]["pid"])
    if hold is not None:
        quiet_before = quiet_state(identity["process"]["pid"], hold["config_sha256"])
        if quiet_before != hold["counters"]:
            raise RuntimeError("notification counters changed after the reviewed hold")
    payloads, identities = {}, {}
    for name in sorted(NAMES):
        payloads[name], identities[name] = read_file(DATA / name)
    captured = time.time()
    value = {"format": 1, "kind": "alertmanager-native-persisted-snapshots", "image": IMAGE,
             "pod_uid": POD_UID, "source": identity, "captured_at": captured,
             "unsnapshotted_ram_proven": False, "metrics": before,
             "files": {n: {"bytes": len(data), "sha256": digest(data), "snapshot_mtime": identities[n][3] / 1e9}
                       for n, data in payloads.items()}}
    if hold is not None:
        value.update(current_persisted_ram_proven=True, quiescence={
            "held_at": hold["held_at"], "config_sha256": hold["config_sha256"],
            "counters_before": quiet_before,
            "counters_after": quiet_state(identity["process"]["pid"], hold["config_sha256"]),
            "maintenance_before": hold["maintenance"],
            "maintenance_after": {n: before["alertmanager_" + n + "_maintenance_total"] for n in NAMES}})
    validate_manifest(value)
    if (any(shared.file_identity(DATA / n) != identities[n] for n in NAMES) or
            state(identity["process"]["pid"]) != before or source_identity() != identity or
            any(before["alertmanager_" + n + "_snapshot_size_bytes"] != len(payloads[f])
                for n, f in (("nflog", "nflog"), ("silences", "silences")))):
        raise RuntimeError("source snapshot or maintenance changed across capture")
    common.private_root()
    if common.ROOT.stat().st_dev != Path("/").stat().st_dev:
        raise RuntimeError("protected recovery root must be on local storage")
    point = common.ROOT / ("alertmanager-" + common.run_identifier(run_id))
    expected = write_point(point, value, payloads)
    return {"manifest_sha256": expected, "bytes": sum(map(len, payloads.values())),
            "snapshot_ages_seconds": {n: captured - value["files"][n]["snapshot_mtime"] for n in NAMES},
            "nflog": records(payloads["nflog"]), "silences": 0, "unsnapshotted_ram_proven": False,
            "current_persisted_ram_proven": hold is not None}


def send_point(output, point, expected):
    value, payloads = verify_point(point, expected)
    data = common.canonical({"manifest": value, "files": {n: base64.b64encode(v).decode() for n, v in payloads.items()}})
    if len(data) > LIMIT:
        raise RuntimeError("native bundle exceeds reviewed stream bound")
    output.write(data + b"\n")
    output.flush()
    verify_point(point, expected)


def receive_point(source, point, expected):
    data = source.readline(LIMIT + 1)
    if len(data) > LIMIT or not data.endswith(b"\n") or source.read(1):
        raise RuntimeError("incomplete or trailing native snapshot stream")
    value = json.loads(data)
    if set(value) != {"manifest", "files"} or set(value["files"]) != NAMES or digest(common.canonical(value["manifest"])) != expected:
        raise RuntimeError("stream manifest or file set differs")
    payloads = {n: base64.b64decode(v, validate=True) for n, v in value["files"].items()}
    return {"manifest_sha256": write_point(point, value["manifest"], payloads), "verified": True}


def restore(point, expected, run_id):
    common.require_host("pikachu")
    common.private_root()
    if common.ROOT.stat().st_dev != Path("/").stat().st_dev:
        raise RuntimeError("restore root must be on local storage")
    _, payloads = verify_point(point, expected)
    label = "io.eaglepass.alertmanager-recovery"
    if common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip():
        raise RuntimeError("another owned Alertmanager restore exists")
    previous = set(common.docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=common.run_identifier(run_id) + "-am-restore-", dir=common.ROOT))
    container = image_id = None
    capture = None
    result = {"accepted": False, "manifest_sha256": expected, "unsnapshotted_ram_proven": False}
    try:
        (scratch / "data").mkdir(mode=0o700)
        for name, data in payloads.items():
            protected_write(scratch / "data" / name, data)
        protected_write(scratch / "config.yml", b"route:\n  receiver: empty\nreceivers:\n  - name: empty\n")
        common.docker("pull", IMAGE)
        image = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        if image["Architecture"] != "amd64" or image["Os"] != "linux" or set(image["Config"].get("Volumes") or {}) - {"/alertmanager"}:
            raise RuntimeError("native image architecture or volume contract changed")
        container = common.docker("create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=0:0",
                                  "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=128",
                                  "--cpus=1", "--memory=512m", "--label=" + label + "=" + run_id,
                                  "--mount=type=bind,source=" + str(scratch) + ",target=/work",
                                  "--mount=type=bind,source=" + str(scratch / "data") + ",target=/alertmanager",
                                  "--entrypoint=/bin/alertmanager", IMAGE, "--config.file=/work/config.yml",
                                  "--storage.path=/alertmanager", "--data.retention=120h", "--cluster.listen-address=",
                                  "--web.listen-address=127.0.0.1:9093").stdout.decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise RuntimeError("invalid owned native container identity")
        native = common.inspect(container)
        host = native["HostConfig"]
        if (native["Config"].get("Labels", {}).get(label) != run_id or host["NetworkMode"] != "none" or
                not host["ReadonlyRootfs"] or host["Privileged"] or host["CapDrop"] != ["ALL"] or
                any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings", "PidMode", "UTSMode", "UsernsMode", "Tmpfs")) or
                host.get("IpcMode") != "private" or host["SecurityOpt"] != ["no-new-privileges:true"] or
                len(native["Mounts"]) != 2 or any(m["Type"] != "bind" for m in native["Mounts"]) or
                {(m["Source"], m["Destination"], m["RW"]) for m in native["Mounts"]} !=
                {(str(scratch), "/work", True), (str(scratch / "data"), "/alertmanager", True)}):
            raise RuntimeError("native restore isolation contract changed")
        capture = common.CapturedContainer(container)
        pid = str(common.inspect(container)["State"]["Pid"])
        network = ["nsenter", "--target", pid, "--net", "--"]
        links = json.loads(common.command(network + ["ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command(network + ["ip", family, "-j", "route", "show", "table", "all"]).stdout)
                      for family in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command(network + ["ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("restore namespace can route to production")
        while request(pid, "/-/ready", check=False).returncode:
            if not common.inspect(container)["State"]["Running"]:
                raise RuntimeError("native restore exited before readiness")
            time.sleep(1)
        status = json.loads(request(pid, "/api/v2/status").stdout)
        if status["versionInfo"]["version"] != "0.32.1" or json.loads(request(pid, "/api/v2/silences").stdout) != []:
            raise RuntimeError("native version or restored silence state differs")
        if json.loads(request(pid, "/api/v2/alerts").stdout) != []:
            raise RuntimeError("isolated restore unexpectedly has active alerts")
        common.docker("stop", "--time=30", container)
        stopped = common.inspect(container)["State"]
        if stopped["Running"] or stopped["ExitCode"] != 0 or stopped["OOMKilled"]:
            raise RuntimeError("native shutdown did not complete successfully")
        logs = capture.output()
        diagnostic = shared.log_diagnostic(logs.stdout + logs.stderr)
        result["native_log_diagnostic"] = diagnostic
        if diagnostic["findings"]:
            raise RuntimeError("native restore emitted error or repair messages")
        original = records(payloads["nflog"])
        restored = records((scratch / "data/nflog").read_bytes())
        if original != restored or (scratch / "data/silences").read_bytes() != b"":
            raise RuntimeError("native snapshot roundtrip changed persisted state")
        result.update(accepted=True, native_version="0.32.1", nflog=original, silences=0,
                      native_roundtrip_equal=True, network_none=True, empty_receiver_no_alerts=True)
    except Exception as error:
        result.update(failure_class=type(error).__name__, failure_reason=str(error))
    finally:
        try:
            if container:
                if common.inspect(container)["Config"].get("Labels", {}).get(label) != run_id:
                    raise RuntimeError("owned native container identity changed during cleanup")
                common.docker("rm", "-f", "--volumes", container)
            shutil.rmtree(scratch)
            removed = False
            if image_id and image_id not in previous and not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
                removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
                if not removed:
                    raise RuntimeError("new owned native restore image remains")
            verify_point(point, expected)
            result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_image_removed": removed,
                                 "owned_container_absent": not common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip(),
                                 "protected_original_unchanged": True}
        finally:
            if capture is not None:
                capture.close()
    return result
