#!/usr/bin/env python3
"""Preserve a quiesced Loki store and prove an isolated restored query set."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inventory(root):
    result = []
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError("source contains a symlink or special file")
        for name in files:
            path = Path(parent) / name
            with path.open("rb") as source:
                checksum = hashlib.file_digest(source, "sha256").hexdigest()
            result.append({
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": checksum,
            })
    if not result:
        raise RuntimeError("empty source is not a recovery point")
    return sorted(result, key=lambda item: item["path"])


def copy_verified(source, destination, expected, owner=None):
    if destination.exists():
        raise RuntimeError("refusing to overwrite an existing destination")
    destination.mkdir(mode=0o700)
    for item in expected:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("invalid manifest path")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as output, (source / relative).open("rb") as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        target.chmod(0o600)
    if inventory(destination) != expected:
        raise RuntimeError("copied store does not match its manifest")
    if owner is not None:
        for parent, dirs, files in os.walk(destination):
            os.chown(parent, owner, owner)
            for name in files:
                os.chown(Path(parent) / name, owner, owner)
    for parent, _, _ in os.walk(destination, topdown=False):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def get_json(url, headers=None, context=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, context=context, timeout=60) as response:
        return json.load(response)


def require_quiesced(uid, pvc_uid=None):
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    token = (account / "token").read_text().strip()
    headers = {"Authorization": "Bearer " + token}
    context = ssl.create_default_context(cafile=str(account / "ca.crt"))
    base = "https://kubernetes.default.svc"

    def get(path):
        return get_json(base + path, headers, context)

    pod = get("/api/v1/namespaces/loki/pods/loki-0")
    ds = get("/apis/apps/v1/namespaces/loki/daemonsets/loki-promtail")
    pods = get("/api/v1/namespaces/loki/pods?labelSelector=" +
               urllib.parse.quote("app.kubernetes.io/name=promtail"))
    valid = (
        pod["metadata"]["uid"] == uid and
        not pod["metadata"].get("deletionTimestamp") and
        pod["spec"]["nodeName"] == ("pikachu" if pvc_uid else "totodile") and
        any(v["name"] == "storage" and (
            v.get("persistentVolumeClaim", {}).get("claimName") == "loki-data" if pvc_uid else
            "emptyDir" in v) for v in pod["spec"]["volumes"]) and
        ds["status"]["observedGeneration"] == ds["metadata"]["generation"] and
        ds["status"]["desiredNumberScheduled"] == 0 and
        ds["status"]["currentNumberScheduled"] == 0 and
        not pods["items"]
    )
    if not valid:
        raise RuntimeError("source identity or collector quiescence changed")
    if pvc_uid:
        claim = get("/api/v1/namespaces/loki/persistentvolumeclaims/loki-data")
        if (claim["metadata"]["uid"] != pvc_uid or claim["metadata"].get("deletionTimestamp") or
                claim["status"]["phase"] != "Bound"):
            raise RuntimeError("source claim identity changed")


def query_proof(base, timestamp):
    window = {"start": str(timestamp - 7 * 86400), "end": str(timestamp)}
    namespaces = get_json(base + "/loki/api/v1/label/namespace/values?" +
                          urllib.parse.urlencode(window))
    if namespaces["status"] != "success" or not namespaces["data"]:
        raise RuntimeError("missing namespace census")
    queries = [("counts/" + namespace, "query", {
        "query": 'count_over_time({job=~".+",namespace=' + json.dumps(namespace) + '}[168h])',
        "time": str(timestamp),
    }) for namespace in sorted(namespaces["data"])]
    queries.append(("historical", "query_range", {
        "query": '{job=~".+"}', **window, "limit": "100", "direction": "forward",
    }))
    proof = {}
    for name, endpoint, parameters in queries:
        value = get_json(base + "/loki/api/v1/" + endpoint + "?" +
                         urllib.parse.urlencode(parameters))
        if value["status"] != "success" or not value["data"]["result"]:
            raise RuntimeError("empty or failed recovery query")
        result = []
        for stream in value["data"]["result"]:
            if name.startswith("counts/"):
                result.append([sorted(stream["metric"].items()), stream["value"][1]])
            else:
                for ts, line in stream["values"]:
                    result.append([sorted(stream["stream"].items()), ts,
                                   hashlib.sha256(line.encode()).hexdigest()])
        proof[name] = {"rows": len(result), "sha256": digest(sorted(result))}
    return proof


def backup(uid, point="pre-pvc-20261019", pvc_uid=None):
    require_quiesced(uid, pvc_uid)
    base = "http://loki.loki:3100"
    request = urllib.request.Request(base + "/flush", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 204:
            raise RuntimeError("flush request failed")
    # A flush acknowledgement only enqueues work. Wait for retained chunks to drain.
    for _ in range(120):
        with urllib.request.urlopen(base + "/metrics", timeout=30) as response:
            metrics = response.read().decode()
        values = [float(line.split()[-1]) for line in metrics.splitlines()
                  if line.startswith("loki_ingester_memory_chunks ")]
        if values == [0.0]:
            break
        time.sleep(5)
    else:
        raise RuntimeError("ingester did not finish flushing; source preserved")
    require_quiesced(uid, pvc_uid)
    timestamp = int(time.time())
    proof = query_proof(base, timestamp)
    source = Path("/source")
    expected = inventory(source)
    destination = Path("/recovery") / point
    destination.mkdir(mode=0o700)
    copy_verified(source, destination / "source", expected)
    if inventory(source) != expected:
        raise RuntimeError("source changed during copy; candidate is not verified")
    require_quiesced(uid, pvc_uid)
    result = {"source_pod_uid": uid, "source_pvc_uid": pvc_uid,
              "timestamp": timestamp, "manifest": expected,
              "manifest_sha256": digest(expected), "queries": proof}
    with (destination / "verified.json").open("x") as output:
        json.dump(result, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    for directory in [destination, destination.parent]:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    print(json.dumps({"backup_verified": True, "source_pod_uid": uid,
                      "source_pvc_uid": pvc_uid, "timestamp": timestamp, "files": len(expected),
                      "bytes": sum(item["size"] for item in expected),
                      "manifest_sha256": digest(expected), "queries": proof}), flush=True)


def recovery_point(point="pre-pvc-20261019"):
    root = Path("/recovery") / point
    value = json.loads((root / "verified.json").read_text())
    if digest(value["manifest"]) != value["manifest_sha256"]:
        raise RuntimeError("recovery manifest changed")
    if inventory(root / "source") != value["manifest"]:
        raise RuntimeError("recovery store changed")
    return root, value


def prepare(point="pre-pvc-20261019", subdirectory=""):
    root, value = recovery_point(point)
    target = Path("/target") / subdirectory
    if subdirectory:
        target.mkdir(mode=0o700)
        os.chown(target, 10001, 10001)
    if any(p.name != "lost+found" or not p.is_dir() or list(p.iterdir())
           for p in target.iterdir()):
        raise RuntimeError("target is not an empty fresh claim")
    # The captured volume contains one Loki tree. Preserve its path under /data.
    if any(Path(item["path"]).parts[0] != "loki" for item in value["manifest"]):
        raise RuntimeError("unexpected source volume layout")
    subtree = [{**item, "path": str(Path(item["path"]).relative_to("loki"))}
               for item in value["manifest"]]
    copy_verified(root / "source/loki", target / "loki", subtree, owner=10001)
    print(json.dumps({"restored_files": len(subtree), "source_manifest": value["manifest_sha256"]}), flush=True)


def verify(service=False, candidate=False, point="pre-pvc-20261019", read_only=False):
    root, value = recovery_point(point)
    base = "http://loki.loki:3100" if service else "http://127.0.0.1:3100"
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + "/ready", timeout=5) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.HTTPError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError("isolated restored Loki did not become ready")
    candidate_identity = {}
    if candidate:
        build = get_json(base + "/loki/api/v1/status/buildinfo")
        if build["version"] != "3.7.8":
            raise RuntimeError("unexpected isolated candidate version")
        candidate_identity = {
            "version": build["version"],
            "config_sha256": hashlib.sha256(Path("/scripts/candidate.yaml").read_bytes()).hexdigest(),
        }
    proof = query_proof(base, value["timestamp"])
    if proof != value["queries"]:
        raise RuntimeError("restored query results differ")
    result = {"restored_queries_identical": True, "queries": proof,
              "source_manifest_sha256": value["manifest_sha256"],
              "timestamp": value["timestamp"], "service": service, **candidate_identity}
    if not service and not candidate and not read_only:
        with (root / "restore-proof.json").open("x") as output:
            json.dump(result, output, sort_keys=True)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["backup", "prepare", "verify", "verify-service", "verify-candidate", "verify-readonly"])
    parser.add_argument("--source-uid")
    parser.add_argument("--source-pvc-uid")
    parser.add_argument("--point", choices=["pre-pvc-20261019", "pre-upgrade-20261019", "pre-upgrade-offline-20261019"], default="pre-pvc-20261019")
    parser.add_argument("--target-subdirectory", choices=["", "pre-upgrade-20261019-old", "pre-upgrade-20261019-new", "pre-upgrade-offline-20261019-old", "pre-upgrade-offline-20261019-new"], default="")
    args = parser.parse_args()
    if args.mode == "backup":
        if args.point == "pre-upgrade-offline-20261019":
            parser.error("use the guarded cold_recovery workflow for an offline point")
        if not args.source_uid:
            parser.error("backup requires the exact source Pod UID")
        if (args.point == "pre-upgrade-20261019") != bool(args.source_pvc_uid):
            parser.error("the fresh PVC recovery point requires its exact claim UID")
        backup(args.source_uid, args.point, args.source_pvc_uid)
    elif args.mode == "prepare":
        prepare(args.point, args.target_subdirectory)
    else:
        verify(service=args.mode == "verify-service", candidate=args.mode == "verify-candidate",
               point=args.point, read_only=args.mode == "verify-readonly")
