#!/usr/bin/env python3
"""Capture a quiesced query contract, then copy its stopped writer's exact PVC."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import urllib.request

import recovery


POINT = "pre-upgrade-offline-20261019"
NODES = {"charmander", "squirtle", "bulbasaur", "pikachu", "cyndaquil", "totodile", "growlithe"}
BUFFER_URL = 'url = "http://loki-cutover-buffer:3100/loki/api/v1/push"'
OLD_URL = 'url = "http://loki:3100/loki/api/v1/push"'
BASE = "http://loki.loki:3100"
BUFFER_POD_UID = "0cd16b6d-d876-463b-a424-0b5a1c422480"
BUFFER_CLAIM_UID = "8dbcfbed-2bf7-4d47-bc5a-94c64fd4c2f3"


def api(path):
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(account / "ca.crt"))
    return recovery.get_json("https://kubernetes.default.svc" + path, {
        "Authorization": "Bearer " + (account / "token").read_text().strip(),
    }, context)


def require_buffered(uid, pvc_uid, offline=False):
    claim = api("/api/v1/namespaces/loki/persistentvolumeclaims/loki-data")
    ds = api("/apis/apps/v1/namespaces/loki/daemonsets/loki-promtail")
    config = api("/api/v1/namespaces/loki/configmaps/loki-alloy")["data"]["config.alloy"]
    pods = api("/api/v1/namespaces/loki/pods")["items"]
    buffer_claim = api("/api/v1/namespaces/loki/persistentvolumeclaims/loki-cutover-buffer")
    buffer_pods = [p for p in pods if p["metadata"]["uid"] == BUFFER_POD_UID]
    checksum = hashlib.sha256(config.encode()).hexdigest()
    collectors = [p for p in pods if p["metadata"].get("labels", {}).get(
        "app.kubernetes.io/name") == "promtail"]
    status = ds["status"]
    if not (
        claim["metadata"]["uid"] == pvc_uid and
        not claim["metadata"].get("deletionTimestamp") and
        claim["status"]["phase"] == "Bound" and
        buffer_claim["metadata"]["uid"] == BUFFER_CLAIM_UID and
        not buffer_claim["metadata"].get("deletionTimestamp") and
        buffer_claim["status"]["phase"] == "Bound" and
        len(buffer_pods) == 1 and
        not buffer_pods[0]["metadata"].get("deletionTimestamp") and
        buffer_pods[0]["status"].get("containerStatuses") and
        all(s.get("ready") for s in buffer_pods[0]["status"]["containerStatuses"]) and
        config.count(BUFFER_URL) == 1 and OLD_URL not in config and
        status["observedGeneration"] == ds["metadata"]["generation"] and
        all(status.get(k) == 7 for k in (
            "desiredNumberScheduled", "currentNumberScheduled", "numberReady",
            "updatedNumberScheduled")) and
        ds["spec"]["template"]["metadata"]["annotations"]["checksum/alloy-config"] == checksum and
        len(collectors) == 7 and {p["spec"]["nodeName"] for p in collectors} == NODES and
        all(not p["metadata"].get("deletionTimestamp") and
            p["metadata"].get("annotations", {}).get("checksum/alloy-config") == checksum and
            any(o.get("uid") == ds["metadata"]["uid"] for o in p["metadata"].get("ownerReferences", [])) and
            p["status"].get("containerStatuses") and
            all(s.get("ready") for s in p["status"]["containerStatuses"]) for p in collectors)
    ):
        raise RuntimeError("claim identity or fully rolled buffered collection changed")
    source = [p for p in pods if p["metadata"]["name"] == "loki-0"]
    if not offline:
        if not (len(source) == 1 and source[0]["metadata"]["uid"] == uid and
                not source[0]["metadata"].get("deletionTimestamp") and
                source[0]["spec"]["nodeName"] == "pikachu" and
                any(v.get("persistentVolumeClaim", {}).get("claimName") == "loki-data"
                    for v in source[0]["spec"]["volumes"])):
            raise RuntimeError("old production Pod identity changed")
        return
    controller = api("/apis/apps/v1/namespaces/loki/statefulsets/loki")
    if not (not source and controller["spec"]["replicas"] == 0 and
            controller["status"].get("observedGeneration") == controller["metadata"]["generation"] and
            controller["status"].get("replicas", 0) == 0):
        raise RuntimeError("old production writer has not stopped")
    own_uid = os.environ.get("POD_UID")
    consumers = [p for p in pods if any(v.get("persistentVolumeClaim", {}).get(
        "claimName") == "loki-data" for v in p["spec"].get("volumes", []))]
    if not (own_uid and len(consumers) == 1 and consumers[0]["metadata"]["uid"] == own_uid and
            consumers[0]["spec"]["nodeName"] == "pikachu" and
            len(consumers[0]["spec"]["containers"]) == 1 and
            consumers[0]["spec"]["containers"][0]["name"] == "backup" and
            [v["name"] for v in consumers[0]["spec"]["volumes"] if
             v.get("persistentVolumeClaim", {}).get("claimName") == "loki-data"] == ["source"] and
            [m for m in consumers[0]["spec"]["containers"][0].get("volumeMounts", []) if
             m["name"] == "source"] == [{"name": "source", "mountPath": "/source", "readOnly": True}]):
        raise RuntimeError("source has another consumer or backup mount is not read-only")


def metrics():
    with urllib.request.urlopen(BASE + "/metrics", timeout=30) as response:
        lines = response.read().decode().splitlines()
    chunks = [float(s.split()[-1]) for s in lines if s.startswith("loki_ingester_memory_chunks ")]
    received = [float(s.split()[-1]) for s in lines if s.startswith((
        "loki_distributor_lines_received_total{", "loki_distributor_lines_received_total "))]
    if len(chunks) != 1 or not received:
        raise RuntimeError("missing flush or ingestion counter evidence")
    return chunks[0], sum(received)


def flush_old():
    request = urllib.request.Request(BASE + "/flush", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 204:
            raise RuntimeError("old production flush failed")
    for _ in range(120):
        chunks, received = metrics()
        if chunks == 0:
            time.sleep(5)
            if metrics() == (0, received):
                return received
            raise RuntimeError("old production still receives writes")
        time.sleep(5)
    raise RuntimeError("old production did not finish flushing")


def write_verified(path, value):
    with path.open("x") as output:
        json.dump(value, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    for parent in (path.parent, path.parent.parent):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def capture(uid, pvc_uid, root=None):
    root = root or Path("/recovery") / POINT
    require_buffered(uid, pvc_uid)
    received = flush_old()
    timestamp = int(time.time())
    proof = recovery.query_proof(BASE, timestamp)
    require_buffered(uid, pvc_uid)
    if metrics() != (0, received):
        raise RuntimeError("old production changed while capturing query proof")
    root.mkdir(mode=0o700)
    value = {"source_pod_uid": uid, "source_pvc_uid": pvc_uid,
             "timestamp": timestamp, "queries": proof, "received_counter": received}
    write_verified(root / "capture.json", value)
    print(json.dumps({"query_contract_captured": True, **value}), flush=True)


def copy_store(uid, pvc_uid, root=None, source=None):
    root = root or Path("/recovery") / POINT
    source = source or Path("/source")
    value = json.loads((root / "capture.json").read_text())
    if value["source_pod_uid"] != uid or value["source_pvc_uid"] != pvc_uid:
        raise RuntimeError("captured source identity differs")
    require_buffered(uid, pvc_uid, offline=True)
    expected = recovery.inventory(source)
    recovery.copy_verified(source, root / "source", expected)
    if recovery.inventory(source) != expected:
        raise RuntimeError("stopped source changed during copy")
    require_buffered(uid, pvc_uid, offline=True)
    result = {**value, "manifest": expected, "manifest_sha256": recovery.digest(expected)}
    write_verified(root / "verified.json", result)
    print(json.dumps({"offline_backup_verified": True, "source_pod_uid": uid,
                      "source_pvc_uid": pvc_uid, "files": len(expected),
                      "bytes": sum(x["size"] for x in expected),
                      "manifest_sha256": result["manifest_sha256"],
                      "timestamp": value["timestamp"], "queries": value["queries"]}), flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["capture", "copy"])
    parser.add_argument("--source-uid", required=True)
    parser.add_argument("--source-pvc-uid", required=True)
    args = parser.parse_args()
    if args.mode == "capture":
        capture(args.source_uid, args.source_pvc_uid)
    else:
        copy_store(args.source_uid, args.source_pvc_uid)
