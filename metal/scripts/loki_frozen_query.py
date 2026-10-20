#!/usr/bin/env python3
"""Compare frozen Loki query plans on a protected remote copy, never on live data."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse

import etcd_recovery as common
import prometheus_recovery as shared
import recovery


POD = "0cd16b6d-d876-463b-a424-0b5a1c422480"
CONTAINER = "6b449c1357b0ccf232ec9cd784739a2c773dd929c7231a45759925d011bcae12"
IMAGE = "docker.io/grafana/loki@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193"
CLAIM = "8dbcfbed-2bf7-4d47-bc5a-94c64fd4c2f3"
HANDLE = "0001-0009-rook-ceph-0000000000000001-035bc9cc-25a4-49a2-bff4-228628836ab5"
CONFIG_SHA = "a9d241c7a09e2439153244a25e5719024b7caae68d197c03de2a3c2a2821ad29"
ROOT = Path("/var/lib/homelab-recovery/maintenance-103")
POINT = ROOT / "loki-buffer-frozen-query-20261020"
DATA = Path("/var/lib/kubelet/pods") / POD / "volumes/kubernetes.io~csi" / ("pvc-" + CLAIM) / "mount"
LABEL = "io.eaglepass.loki-frozen-query-103"
START = 1792425257955388935
RANGES = {"prefix": (1792465477456599213, 7090404), "full": (1792470820200149129, 7368160)}
MODES = [
    ("ingester-store-entire-range", ["-ingester.query-store-max-look-back-period=-1ns"]),
    ("standalone-store-only", ["-target=querier", "-querier.query-store-only=true"]),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError("owned diagnostic command failed: " + args[0])
    return result.stdout


def source_identity():
    common.require_host("totodile")
    runtime = json.loads(command(["/usr/local/bin/crictl", "inspect", CONTAINER]))
    status = runtime["status"]
    labels = status["labels"]
    if (status["state"] != "CONTAINER_RUNNING" or status["imageRef"] != IMAGE or
            labels.get("io.kubernetes.pod.uid") != POD or
            labels.get("io.kubernetes.pod.namespace") != "loki" or
            labels.get("io.kubernetes.container.name") != "loki"):
        raise RuntimeError("frozen source runtime identity changed")
    process = shared.process_identity(runtime["info"]["pid"])
    root = Path("/proc") / str(process["pid"])
    metadata = DATA.parent / "vol_data.json"
    if any(p.is_symlink() for p in (DATA, *DATA.parents)):
        raise RuntimeError("source ancestry contains a symlink")
    volume = json.loads(metadata.read_bytes())
    a, b = DATA.stat(), (root / "root/var/loki").stat()
    if (volume["driverName"] != "rook-ceph.rbd.csi.ceph.com" or volume["volumeHandle"] != HANDLE or
            (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino) or a.st_dev == Path("/").stat().st_dev or
            process["exe"] != "/usr/bin/loki" or POD.replace("-", "_") not in process["cgroup"]):
        raise RuntimeError("source CSI mount or native process changed")
    config = (root / "root/etc/loki/loki.yaml").read_bytes()
    if sha(config) != CONFIG_SHA:
        raise RuntimeError("source configuration changed")
    return {"process": process, "device": a.st_dev, "inode": a.st_ino,
            "csi_metadata_sha256": sha(metadata.read_bytes())}, config


def source_counters(pid):
    code = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:3100/metrics',timeout=30).read().decode())"
    text = command(["nsenter", "--target", str(pid), "--net", "--", "python3", "-B", "-c", code]).decode()
    names = ("loki_ingester_memory_chunks", "loki_distributor_lines_received_total", "loki_discarded_samples_total")
    values = {line.split()[0]: float(line.split()[1]) for line in text.splitlines()
              if line.startswith(tuple(n + suffix for n in names for suffix in (" ", "{")))}
    refusals = {}
    for name, value in values.items():
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise RuntimeError("invalid source counter")
        if name.startswith("loki_discarded_samples_total") and value:
            reason = re.search(r'(?:\{|,)reason="([^"]+)"(?:,|\})', name)
            if not reason:
                raise RuntimeError("unidentified source refusal")
            refusals[reason[1]] = refusals.get(reason[1], 0) + value
    if (values.get("loki_ingester_memory_chunks") != 0 or
            sum(v for k, v in values.items() if k.startswith("loki_distributor_lines_received_total")) != 7373410 or
            refusals != {"rate_limited": 5249, "line_too_long": 1}):
        raise RuntimeError("source is not the exact quiescent buffer")
    return values


def capture():
    identity, config = source_identity()
    counters = source_counters(identity["process"]["pid"])
    if not ROOT.is_dir() or ROOT.is_symlink() or POINT.exists():
        raise RuntimeError("protected parent absent or point already exists; no overwrite")
    before = recovery.inventory(DATA)
    if sum(item["size"] for item in before) > shutil.disk_usage(ROOT).free:
        raise RuntimeError("insufficient actual protected capacity")
    POINT.mkdir(mode=0o700)
    recovery.copy_verified(DATA, POINT / "source", before)
    if (recovery.inventory(DATA) != before or source_identity() != (identity, config) or
            source_counters(identity["process"]["pid"]) != counters):
        raise RuntimeError("source changed during capture; incomplete point is not accepted")
    for name, data in {"loki.yaml": config, "verified.json": json.dumps({
            "source": identity, "counters": counters, "manifest": before,
            "manifest_sha256": recovery.digest(before), "config_sha256": CONFIG_SHA,
            "source_pod_uid": POD, "claim_uid": CLAIM, "captured_at": time.time(),
    }, sort_keys=True).encode()}.items():
        with (POINT / name).open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    fsync_directory(POINT)
    fsync_directory(ROOT)
    value = verify_point()
    print(json.dumps({"captured": True, "manifest_sha256": value["manifest_sha256"],
                      "files": len(before), "bytes": sum(x["size"] for x in before),
                      "same_live_identity_and_counters": True}), flush=True)


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_point():
    if (any(p.is_symlink() for p in (POINT, *POINT.parents)) or POINT.stat().st_mode & 0o777 != 0o700 or
            POINT.stat().st_uid != os.geteuid() or
            {p.name for p in POINT.iterdir()} != {"source", "verified.json", "loki.yaml"}):
        raise RuntimeError("protected point identity changed")
    value = json.loads((POINT / "verified.json").read_bytes())
    if (value["source_pod_uid"] != POD or value["claim_uid"] != CLAIM or
            sha((POINT / "loki.yaml").read_bytes()) != CONFIG_SHA or
            recovery.digest(value["manifest"]) != value["manifest_sha256"] or
            recovery.inventory(POINT / "source") != value["manifest"]):
        raise RuntimeError("protected point content differs")
    return value


def query_path(end):
    duration = (end - START) // 10**9 + 2
    return "/loki/api/v1/query?" + urllib.parse.urlencode({
        "query": 'sum(count_over_time({job=~".+"}[' + str(duration) + "s]))", "time": str(end),
    })


def summarize(value):
    data = value.get("data", {})
    rows = data.get("result", [])
    if value.get("status") != "success" or data.get("resultType") != "vector" or len(rows) != 1:
        raise RuntimeError("missing isolated count evidence")
    raw = rows[0]["value"][1]
    if not isinstance(raw, str) or not raw.isdecimal():
        raise RuntimeError("invalid isolated exact integer count")
    stats = data["stats"]
    return {"count": int(raw), "splits": stats["summary"]["splits"], "shards": stats["summary"]["shards"],
            "querier_chunks": stats["querier"]["store"]["totalChunksRef"],
            "ingester_chunks": stats["ingester"]["store"]["totalChunksRef"]}


def diagnose():
    common.require_host("totodile")
    identity, config = source_identity()
    counters = source_counters(identity["process"]["pid"])
    point = verify_point()
    docker = lambda *a: command(["docker", "--host", "unix:///var/run/docker.sock", *a])
    if docker("ps", "-aq", "--filter", "label=" + LABEL).strip():
        raise RuntimeError("an owned diagnostic already exists")
    images_before = set(docker("image", "ls", "-q", "--no-trunc").decode().split())
    image_id = None
    results = []
    try:
        docker("pull", IMAGE)
        image = json.loads(docker("image", "inspect", IMAGE))[0]
        image_id = image["Id"]
        if image["Os"] != "linux" or image["Architecture"] != "amd64" or image["Config"].get("Volumes"):
            raise RuntimeError("isolated native image contract differs")
        for mode, flags in MODES:
            scratch = Path(tempfile.mkdtemp(prefix="loki-frozen-query-", dir=ROOT))
            scratch.chmod(0o700)
            container = None
            try:
                recovery.copy_verified(POINT / "source", scratch / "data", point["manifest"])
                (scratch / "loki.yaml").write_bytes(config)
                container = docker("create", "--network=none", "--read-only", "--user=0:0", "--cap-drop=ALL",
                                   "--security-opt=no-new-privileges:true", "--pids-limit=128", "--cpus=1", "--memory=1g",
                                   "--label=" + LABEL, "--mount=type=bind,source=" + str(scratch / "data") + ",target=/var/loki",
                                   "--mount=type=bind,source=" + str(scratch / "loki.yaml") + ",target=/etc/loki/loki.yaml,readonly",
                                   IMAGE, "-config.file=/etc/loki/loki.yaml", "-ingester.wal-enabled=false", "-log.level=error",
                                   "-querier.query-timeout=3m", "-server.http-write-timeout=4m", *flags).decode().strip()
                docker("start", container)
                state = json.loads(docker("inspect", container))[0]
                if state["HostConfig"]["NetworkMode"] != "none" or not state["HostConfig"]["ReadonlyRootfs"]:
                    raise RuntimeError("isolated network or root filesystem contract differs")
                ns = ["nsenter", "--target", str(state["State"]["Pid"]), "--net", "--"]
                if subprocess.run(ns + ["ip", "route", "get", "10.0.20.50"], capture_output=True).returncode == 0:
                    raise RuntimeError("diagnostic can reach the cluster")

                def http(path):
                    code = "import sys,urllib.request;sys.stdout.buffer.write(urllib.request.urlopen('http://127.0.0.1:3100'+sys.argv[1],timeout=210).read())"
                    return command(ns + ["python3", "-B", "-c", code, path])

                for _ in range(90):
                    try:
                        if http("/ready").strip() == b"ready":
                            break
                    except RuntimeError:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError("isolated query runtime did not become ready")
                runtime_config = http("/config").decode()
                for field, expected in (("query_store_only", "true" if mode == "standalone-store-only" else "false"),
                                        ("query_store_max_look_back_period", "0s" if mode == "standalone-store-only" else "-1ns")):
                    if not re.search(r"(?m)^  " + field + ": " + re.escape(expected) + r"$", runtime_config):
                        raise RuntimeError("isolated query cutoff configuration differs")
                print(json.dumps({"mode": mode, "runtime_cutoff_configuration_verified": True}), flush=True)
                for round_number in range(3):
                    for name, (end, expected) in RANGES.items():
                        result = summarize(json.loads(http(query_path(end))))
                        if result["ingester_chunks" if mode == "standalone-store-only" else "querier_chunks"] != 0:
                            raise RuntimeError("isolated query used an unexpected store path")
                        result.update(mode=mode, round=round_number, range=name, expected=expected,
                                      matches=result["count"] == expected)
                        results.append(result)
                        print(json.dumps(result), flush=True)
            finally:
                if container:
                    own = json.loads(docker("inspect", container))[0]
                    if own["Id"] != container or LABEL not in own["Config"]["Labels"]:
                        raise RuntimeError("owned cleanup identity differs")
                    docker("rm", "-f", container)
                shutil.rmtree(scratch)
                if scratch.exists():
                    raise RuntimeError("owned diagnostic scratch remains")
    finally:
        if image_id and image_id not in images_before and not docker("ps", "-aq", "--filter", "ancestor=" + image_id).strip():
            docker("image", "rm", image_id)
        if docker("ps", "-aq", "--filter", "label=" + LABEL).strip():
            raise RuntimeError("owned diagnostic container remains")
        if (verify_point() != point or source_identity() != (identity, config) or
                source_counters(identity["process"]["pid"]) != counters):
            raise RuntimeError("protected point or original source changed during diagnostics")
        print(json.dumps({"cleanup": True, "source_unchanged": True, "protected_point_unchanged": True,
                          "queries_completed": len(results), "production_record_posts": 0}), flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["capture", "diagnose"])
    action = parser.parse_args().mode
    capture() if action == "capture" else diagnose()
