#!/usr/bin/env python3
"""Copy a proven frozen receiver for a credential-free, store-only audit sidecar."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import cold_recovery
import recovery


CONFIG_SHA = "a9d241c7a09e2439153244a25e5719024b7caae68d197c03de2a3c2a2821ad29"
PYTHON = "docker.io/library/python:3.13.9-alpine3.22@sha256:e5fa639e49b85986c4481e28faa2564b45aa8021413f31026c3856e5911618b1"
LOKI = "docker.io/grafana/loki:3.7.8@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193"
READER_ARGS = ["-config.file=/etc/loki/loki.yaml", "-ingester.wal-enabled=false", "-log.level=error",
               "-querier.query-timeout=3m", "-server.http-write-timeout=4m", "-target=querier,compactor",
               "-querier.query-store-only=true", "-common.compactor-grpc-address=127.0.0.1:9095"]


def require_consumer(pods):
    source = [p for p in pods if p["metadata"]["uid"] == cold_recovery.BUFFER_POD_UID]
    if (len(source) != 1 or source[0]["metadata"].get("annotations", {}).get("checksum/config") != CONFIG_SHA or
            source[0]["spec"].get("nodeName") != "totodile" or
            not source[0]["status"].get("containerStatuses") or any(
                not s.get("ready") or s.get("restartCount") != 0 or s.get("containerID") !=
                "containerd://6b449c1357b0ccf232ec9cd784739a2c773dd929c7231a45759925d011bcae12"
                for s in source[0]["status"]["containerStatuses"])):
        raise RuntimeError("original frozen process or configuration changed")
    own = [p for p in pods if p["metadata"]["uid"] == os.environ.get("POD_UID")]
    if len(own) != 1:
        raise RuntimeError("frozen-copy audit Pod identity missing")
    pod = own[0]
    meta, spec = pod["metadata"], pod["spec"]
    owners = meta.get("ownerReferences", [])
    init = {c["name"]: c for c in spec.get("initContainers", [])}
    main = spec.get("containers", [])
    volumes = [v for v in spec.get("volumes", []) if v.get("persistentVolumeClaim", {}).get("claimName") == "loki-cutover-buffer"]
    if (meta.get("deletionTimestamp") or len(owners) != 1 or not owners[0].get("uid") or
            owners[0].get("kind") != "Job" or not re.fullmatch(r"loki-buffer-continuation-audit-20261019-[0-9]+", owners[0].get("name", "")) or
            spec.get("nodeName") != "totodile" or spec.get("serviceAccountName") != "loki-store-recovery" or
            spec.get("automountServiceAccountToken") is not False or len(main) != 1 or
            main[0]["name"] != "transfer" or main[0]["image"] != PYTHON or "--apply" in main[0].get("args", []) or
            "--phase=continuation" not in main[0].get("args", []) or
            set(init) != {"copy-frozen-source", "frozen-query-reader"} or
            init["copy-frozen-source"]["image"] != PYTHON or
            init["copy-frozen-source"].get("command") != ["python3", "-B", "/scripts/frozen_query_copy.py"] or
            init["frozen-query-reader"]["image"] != LOKI or
            init["frozen-query-reader"].get("restartPolicy") != "Always" or
            init["frozen-query-reader"].get("args") != READER_ARGS or
            len(volumes) != 1 or volumes[0].get("name") != "frozen-source" or
            volumes[0]["persistentVolumeClaim"].get("readOnly") is not True):
        raise RuntimeError("frozen-copy consumer is not the exact read-only audit")
    for container in [*main, *init.values()]:
        mounts = [m for m in container.get("volumeMounts", []) if m["name"] == "frozen-source"]
        expected = [] if container["name"] == "frozen-query-reader" else [
            {"name": "frozen-source", "mountPath": "/frozen-original", "readOnly": True}]
        if mounts != expected or (container["name"] == "frozen-query-reader" and any(
                m["name"] in ("api-access", "recovery") for m in container.get("volumeMounts", []))):
            raise RuntimeError("source mount or reader credential isolation changed")
    return meta["uid"]


def require_copy(accounting):
    proof = json.loads(Path("/frozen-copy/source-proof.json").read_bytes())
    manifest = recovery.inventory(Path("/frozen-original"))
    if (proof.get("source_uid") != cold_recovery.BUFFER_POD_UID or
            proof.get("claim_uid") != cold_recovery.BUFFER_CLAIM_UID or proof.get("config_sha256") != CONFIG_SHA or
            proof.get("source_accounting") != accounting or
            proof.get("manifest_sha256") != recovery.digest(manifest) or
            proof.get("files") != len(manifest) or proof.get("bytes") != sum(x["size"] for x in manifest)):
        raise RuntimeError("original frozen source differs from its verified query copy")
    return proof


def prepare(target_uid):
    import buffer_transfer
    buffer_transfer.require_stage(target_uid, "continuation", preparing_copy=True)
    accounting = buffer_transfer.source_accounting()
    if (accounting["received_attempts"], accounting["rate_limited_attempts"], accounting["accepted_records"]) != (7373410, 5249, 7368160):
        raise RuntimeError("frozen source accounting changed")
    if cold_recovery.metrics(buffer_transfer.SOURCE) != (0, 7373410):
        raise RuntimeError("source has live memory or changed received counter")
    if hashlib.sha256(Path("/scripts/buffer-loki.yaml").read_bytes()).hexdigest() != CONFIG_SHA:
        raise RuntimeError("frozen reader configuration differs from the qualified source")
    source, work = Path("/frozen-original"), Path("/frozen-copy")
    before = recovery.inventory(source)
    if sum(x["size"] for x in before) > shutil.disk_usage(work).free:
        raise RuntimeError("insufficient actual query-copy capacity")
    recovery.copy_verified(source, work / "data", before, owner=10001)
    buffer_transfer.require_stage(target_uid, "continuation", preparing_copy=True)
    if (recovery.inventory(source) != before or buffer_transfer.source_accounting() != accounting or
            cold_recovery.metrics(buffer_transfer.SOURCE) != (0, 7373410)):
        raise RuntimeError("source changed during verified copy")
    proof = {"source_uid": cold_recovery.BUFFER_POD_UID, "claim_uid": cold_recovery.BUFFER_CLAIM_UID,
             "source_accounting": accounting, "config_sha256": CONFIG_SHA,
             "manifest_sha256": recovery.digest(before), "files": len(before), "bytes": sum(x["size"] for x in before)}
    cold_recovery.write_verified(work / "source-proof.json", proof)
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-uid", required=True)
    prepare(parser.parse_args().target_uid)
