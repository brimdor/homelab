#!/usr/bin/env python3
"""Audit a persisted receiver and transfer only query-proven missing originals."""

import argparse
from collections import defaultdict
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import cold_recovery


SOURCE = "http://loki-cutover-buffer.loki:3100"
TARGET = "http://loki.loki:3100"
SELECTOR = '{job=~".+"}'
SPAN = 120 * 10**9
CLAIM_UID = "656cee92-dc36-4fc8-8742-b691c670cf77"
IMAGE_DIGEST = "sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193"
FROZEN_SOURCE_SHA256 = "41d4f77e26147287092c6936e7ffd7d247657aebdc4f08a1ef886b53fece95fa"
SOURCE_AUDIT_SHA256 = "9ce2339207236861dd9bf0d93e599b089145922d9ac7057c673224ff47c6ab97"


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def fingerprint(row):
    labels, timestamp, line = row
    value = [sorted(labels.items()), str(timestamp), line]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def query(base, start, end, limit=5000, direction="forward", selector=SELECTOR):
    # Loki's HTTP end is exclusive; internal windows include both endpoints.
    parameters = {"query": selector, "start": str(start), "end": str(end + 1),
                  "limit": str(limit), "direction": direction}
    value = get_json(base + "/loki/api/v1/query_range?" + urllib.parse.urlencode(parameters))
    if (value.get("status") != "success" or value.get("data", {}).get("resultType") != "streams" or
            not isinstance(value.get("data", {}).get("result"), list)):
        raise RuntimeError("buffer comparison query failed")
    rows = []
    for stream in value["data"]["result"]:
        labels = stream["stream"]
        if not labels or not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
            raise RuntimeError("invalid original stream labels")
        for timestamp, line in stream["values"]:
            if not (isinstance(timestamp, str) and timestamp.isdigit() and
                    start <= int(timestamp) <= end and isinstance(line, str)):
                raise RuntimeError("invalid or out-of-window original record")
            rows.append((labels, int(timestamp), line))
    return sorted(rows, key=lambda row: (row[1], fingerprint(row)))


def windows(base, start, end, limit=5000):
    if end < start:
        raise RuntimeError("invalid query interval")
    if end - start > SPAN:
        middle = (start + end) // 2
        yield from windows(base, start, middle, limit)
        yield from windows(base, middle + 1, end, limit)
        return
    rows = query(base, start, end, limit)
    split = len(rows) >= limit
    if not split:
        # Merged query pages can underfill before all originals are returned.
        # Opposite traversal exposed this in two frozen production intervals.
        reverse = query(base, start, end, limit, direction="backward")
        split = len(reverse) >= limit or {fingerprint(r) for r in rows} != {fingerprint(r) for r in reverse}
    if split:
        if start == end:
            raise RuntimeError("cannot prove complete query at one timestamp")
        middle = (start + end) // 2
        yield from windows(base, start, middle, limit)
        yield from windows(base, middle + 1, end, limit)
    else:
        yield start, end, rows


def observed(base, start, end):
    return {fingerprint(row) for _, _, rows in windows(base, start, end) for row in rows}


def source_accounting():
    # Received counts parsed attempts, including whole batches rejected with 429.
    # Never discount other refusal classes or infer that a rejected batch retried.
    with urllib.request.urlopen(SOURCE + "/metrics", timeout=30) as response:
        lines = response.read().decode().splitlines()
    received = []
    rejected = 0
    for line in lines:
        if not line.startswith(("loki_distributor_lines_received_total ",
                                "loki_distributor_lines_received_total{",
                                "loki_discarded_samples_total ", "loki_discarded_samples_total{")):
            continue
        value = float(line.split()[-1])
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise RuntimeError("invalid source ingestion counter")
        if line.startswith("loki_distributor_lines_received_total"):
            received.append(int(value))
        else:
            reason = re.search(r'(?:\{|,)reason="([^"]+)"(?:,|\})', line)
            if value and (not reason or reason[1] != "rate_limited"):
                raise RuntimeError("source has unqualified rejected records")
            rejected += int(value)
    total = sum(received)
    if not received or total <= rejected:
        raise RuntimeError("missing or inconsistent source ingestion accounting")
    return {"received_attempts": total, "rate_limited_attempts": rejected,
            "accepted_records": total - rejected}


def query_count(base, start, end, allow_empty=False):
    # An independent full-range aggregate must agree with enumeration and counters.
    upper = end + 10**9 if allow_empty else end
    duration = (upper - start) // 10**9 + 2
    parameters = {"query": "sum(count_over_time(" + SELECTOR + "[" + str(duration) + "s]))",
                  "time": str(upper)}
    value = get_json(base + "/loki/api/v1/query?" + urllib.parse.urlencode(parameters))
    data = value.get("data", {})
    result = data.get("result", [])
    if (value.get("status") != "success" or data.get("resultType") != "vector" or
            not isinstance(data.get("result"), list)):
        raise RuntimeError("missing independent query count")
    if allow_empty and result == []:
        return 0
    if len(result) != 1:
        raise RuntimeError("missing independent source query count")
    count = float(result[0]["value"][1])
    if not math.isfinite(count) or count < 0 or (not allow_empty and count == 0) or not count.is_integer():
        raise RuntimeError("invalid independent source query count")
    return int(count)


def source_query_count(start, end):
    return query_count(SOURCE, start, end)


def prove_missing(rows, start, end):
    # A zero aggregate over a superset interval independently proves absence.
    if query_count(TARGET, start, end, allow_empty=True) == 0:
        return rows, {"target_empty_aggregate": True, "targeted_presence_probes": 0, "already_present": 0}
    missing = []
    for row in rows:
        labels, timestamp, _ = row
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in labels):
            raise RuntimeError("invalid exact stream selector labels")
        selector = "{" + ",".join(key + "=" + json.dumps(value) for key, value in sorted(labels.items())) + "}"
        expected = fingerprint(row)
        source = query(SOURCE, timestamp, timestamp, selector=selector)
        forward = query(TARGET, timestamp, timestamp, selector=selector)
        backward = query(TARGET, timestamp, timestamp, direction="backward", selector=selector)
        if (expected not in {fingerprint(r) for r in source} or
                max(len(source), len(forward), len(backward)) >= 5000 or
                {fingerprint(r) for r in forward} != {fingerprint(r) for r in backward}):
            raise RuntimeError("exact stream/timestamp presence is unproven; no replay of this window")
        if expected not in {fingerprint(r) for r in forward}:
            missing.append(row)
    return missing, {"target_empty_aggregate": False, "targeted_presence_probes": 3 * len(rows),
                     "already_present": len(rows) - len(missing)}


def push(rows):
    streams = defaultdict(list)
    for labels, timestamp, line in rows:
        streams[json.dumps(labels, sort_keys=True)].append([str(timestamp), line])
    body = {"streams": [{"stream": json.loads(labels), "values": sorted(values, key=lambda x: int(x[0]))}
                        for labels, values in streams.items()]}
    encoded = json.dumps(body).encode()
    # Keep the entire replay below the receiver's 3 MiB/s per-stream limit.
    time.sleep(len(encoded) / 1048576)
    request = urllib.request.Request(TARGET + "/loki/api/v1/push", data=encoded,
                                     method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 204:
                raise RuntimeError("non-204 push response")
    except urllib.error.HTTPError as error:
        # Response bodies may contain original log lines; retain only known classes.
        body = error.read(4096)
        category = "too_far_behind" if b"too far behind" in body else "unclassified"
        raise RuntimeError("push outcome uncertain; HTTP " + str(error.code) + "; " + category +
                           "; rerun the comparison audit before recovery") from None
    except Exception:
        raise RuntimeError("push outcome uncertain; rerun the comparison audit before recovery") from None


def confirm_visible(expected, start, end, originals=None):
    # A successful push is not query proof; retry reads only, never the write.
    for attempt in range(10):
        after = observed(TARGET, start, end)
        if expected.issubset(after):
            return
        if originals is not None:
            candidates = [row for row in originals if fingerprint(row) not in after]
            missing, _ = prove_missing(candidates, start, end)
            if not missing:
                return
        if attempt < 9:
            time.sleep(2)
    raise RuntimeError("transferred originals are not all query-visible; interval " +
                       str(start) + ":" + str(end) + "; missing " + str(len(expected - after)))


def require_unsharded():
    with urllib.request.urlopen(TARGET + "/config", timeout=30) as response:
        config = response.read().decode()
    limits = re.search(r"(?ms)^limits_config:\n(.*?)(?=^\S|\Z)", config)
    if not limits or not re.search(
            r"(?m)^  shard_streams:\n    enabled: false\n    time_sharding_enabled: false$", limits[1]):
        raise RuntimeError("receiver may transform original labels through stream sharding")


def source_windows(start, end, audit=None):
    if audit is None:
        yield from windows(SOURCE, start, end)
        return
    if start != audit["start"] or end < audit["end"]:
        raise RuntimeError("canonical source audit range changed")
    for window in audit["windows"]:
        left, right = window["start"], window["end"]
        rows = query(SOURCE, left, right)
        if window.get("bidirectional"):
            rows += query(SOURCE, left, right, direction="backward")
        unique = {fingerprint(row) for row in rows}
        checksum = hashlib.sha256("\n".join(sorted(unique)).encode()).hexdigest()
        if len(unique) != window["source_distinct_records"] or checksum != window["source_sha256"]:
            raise RuntimeError("canonical source window no longer matches its preserved audit")
        yield left, right, rows
    if end > audit["end"]:
        yield from windows(SOURCE, audit["end"] + 1, end)


def preserved_source_audit(root):
    data = (root / "final-1.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_AUDIT_SHA256:
        raise RuntimeError("preserved canonical source audit changed")
    audit = json.loads(data)
    if not (audit["complete_source_quiescence"] and not audit["applied"] and
            audit["source_uid"] == cold_recovery.BUFFER_POD_UID and
            audit["source_distinct_records"] == audit["source_received_counter"] and
            sum(w["source_distinct_records"] for w in audit["windows"]) == audit["source_distinct_records"]):
        raise RuntimeError("canonical source audit does not prove complete originals")
    return audit


def frozen_source_audit(original, accounting, path=Path("/scripts/source-final-windows.json")):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != FROZEN_SOURCE_SHA256:
        raise RuntimeError("frozen source proof changed")
    audit = json.loads(data)
    if not (audit["format"] == 1 and audit["source_uid"] == cold_recovery.BUFFER_POD_UID and
            audit["claim_uid"] == cold_recovery.BUFFER_CLAIM_UID and
            audit["original_anchor_sha256"] == SOURCE_AUDIT_SHA256 and
            audit["start"] == original["start"] and audit["end"] >= original["end"] and
            audit["source_accepted_records"] == accounting["accepted_records"] and
            audit["source_received_attempts"] == accounting["received_attempts"] and
            audit["source_rate_limited_attempts"] == accounting["rate_limited_attempts"]):
        raise RuntimeError("frozen source identity or accounting changed")
    if not audit["windows"] or audit["windows"][0]["start"] != audit["start"]:
        raise RuntimeError("frozen source first interval changed")
    left = audit["start"]
    total = 0
    for window in audit["windows"]:
        if not (window["start"] >= left and window["end"] >= window["start"] and
                type(window["source_distinct_records"]) is int and window["source_distinct_records"] >= 0 and
                re.fullmatch(r"[a-f0-9]{64}", window["source_sha256"]) and
                type(window["bidirectional"]) is bool and window["refinement_factor"] == 1):
            raise RuntimeError("frozen source windows are invalid or overlapping")
        total += window["source_distinct_records"]
        left = window["end"] + 1
    if left != audit["end"] + 1 or total != accounting["accepted_records"]:
        raise RuntimeError("frozen source windows do not cover accepted originals")
    prefix = audit["windows"][:len(original["windows"])]
    if any({key: w[key] for key in ("start", "end", "source_distinct_records", "source_sha256")} !=
           {key: old[key] for key in ("start", "end", "source_distinct_records", "source_sha256")} or
           w["bidirectional"] for w, old in zip(prefix, original["windows"])) or len(prefix) != len(original["windows"]):
        raise RuntimeError("frozen source proof changed preserved anchor windows")
    return audit


def transfer(start, end, apply=False, source_audit=None):
    manifest = []
    total = missing_total = 0
    for left, right, rows in source_windows(start, end, source_audit):
        unique = {fingerprint(row): row for row in rows}
        if not unique:
            continue
        before = observed(TARGET, left, right)
        missing = sorted((row for key, row in unique.items() if key not in before), key=lambda row: row[1])
        evidence = {}
        if apply:
            missing, evidence = prove_missing(missing, left, right) if missing else ([], {})
            for index in range(0, len(missing), 250):
                push(missing[index:index + 250])
            confirm_visible(set(unique), left, right, list(unique.values()))
        total += len(unique)
        missing_total += len(missing)
        manifest.append({"start": left, "end": right, "source_distinct_records": len(unique),
                         "source_sha256": hashlib.sha256("\n".join(sorted(unique)).encode()).hexdigest(),
                         "missing_before": len(missing), **evidence})
    if not total:
        raise RuntimeError("empty buffer is not transfer evidence")
    return {"source_distinct_records": total, "missing_before": missing_total, "applied": apply,
            "all_source_records_visible": apply or missing_total == 0, "windows": manifest,
            "start": start, "end": end}


def require_stage(target_uid, phase):
    api = cold_recovery.api
    claim = api("/api/v1/namespaces/loki/persistentvolumeclaims/loki-data")
    source_claim = api("/api/v1/namespaces/loki/persistentvolumeclaims/loki-cutover-buffer")
    ds = api("/apis/apps/v1/namespaces/loki/daemonsets/loki-promtail")
    config = api("/api/v1/namespaces/loki/configmaps/loki-alloy")["data"]["config.alloy"]
    pods = api("/api/v1/namespaces/loki/pods")["items"]
    if not (claim["metadata"]["uid"] == CLAIM_UID and source_claim["metadata"]["uid"] ==
            cold_recovery.BUFFER_CLAIM_UID and all(not p["metadata"].get("deletionTimestamp") and
            p["status"]["phase"] == "Bound" for p in (claim, source_claim))):
        raise RuntimeError("transfer storage identity changed")
    expected_url = cold_recovery.BUFFER_URL if phase == "bulk" else cold_recovery.OLD_URL
    other_url = cold_recovery.OLD_URL if phase == "bulk" else cold_recovery.BUFFER_URL
    checksum = hashlib.sha256(config.encode()).hexdigest()
    collectors = [p for p in pods if p["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "promtail"]
    if not (config.count(expected_url) == 1 and other_url not in config and
            ds["status"]["observedGeneration"] == ds["metadata"]["generation"] and
            all(ds["status"].get(k) == 7 for k in ("desiredNumberScheduled", "currentNumberScheduled",
                                                  "numberReady", "updatedNumberScheduled")) and
            ds["spec"]["template"]["metadata"]["annotations"]["checksum/alloy-config"] == checksum and
            len(collectors) == 7 and {p["spec"]["nodeName"] for p in collectors} == cold_recovery.NODES and
            all(not p["metadata"].get("deletionTimestamp") and
                p["metadata"].get("annotations", {}).get("checksum/alloy-config") == checksum and
                any(o.get("uid") == ds["metadata"]["uid"] for o in p["metadata"].get("ownerReferences", [])) and
                p["status"].get("containerStatuses") and all(s["ready"] for s in p["status"]["containerStatuses"])
                for p in collectors)):
        raise RuntimeError("collector route is not fully rolled for this transfer phase")
    for uid, service, selector, pvc in (
        (cold_recovery.BUFFER_POD_UID, "loki-cutover-buffer", {"app.kubernetes.io/name": "loki-cutover-buffer"}, "loki-cutover-buffer"),
        (target_uid, "loki", {"app.kubernetes.io/name": "loki", "app.kubernetes.io/instance": "loki",
                             "app.kubernetes.io/component": "single-binary"}, "loki-data"),
    ):
        matches = [p for p in pods if all(p["metadata"].get("labels", {}).get(k) == v for k, v in selector.items())]
        consumers = [p["metadata"]["uid"] for p in pods if p["status"].get("phase") not in
                     ("Succeeded", "Failed") and any(v.get("persistentVolumeClaim", {}).get(
                         "claimName") == pvc for v in p["spec"].get("volumes", []))]
        if not (len(matches) == 1 and matches[0]["metadata"]["uid"] == uid and
                consumers == [uid] and
                not matches[0]["metadata"].get("deletionTimestamp") and
                any(v.get("persistentVolumeClaim", {}).get("claimName") == pvc for v in matches[0]["spec"]["volumes"]) and
                matches[0]["status"].get("containerStatuses") and all(s["ready"] and s.get("imageID", "").endswith(
                    "@" + IMAGE_DIGEST) for s in matches[0]["status"]["containerStatuses"]) and
                api("/api/v1/namespaces/loki/services/" + service)["spec"]["selector"] == selector):
            raise RuntimeError("receiver Pod, Service, image or claim identity changed")
    return source_claim


def run(target_uid, phase, attempt, apply):
    root = Path("/recovery/cutover-transfer")
    root.mkdir(mode=0o700, exist_ok=True)
    receipt = root / (phase + "-" + str(attempt) + ".json")
    if receipt.exists():
        raise RuntimeError("transfer attempt already has a preserved receipt")
    source_claim = require_stage(target_uid, phase)
    if apply:
        require_unsharded()
    for base in (SOURCE, TARGET):
        if get_json(base + "/loki/api/v1/status/buildinfo")["version"] != "3.7.8":
            raise RuntimeError("unexpected transfer server version")
    received = cold_recovery.flush_old(SOURCE) if phase == "final" else None
    accounting = source_accounting() if phase == "final" else None
    if accounting and accounting["received_attempts"] != received:
        raise RuntimeError("quiescent source accounting changed after flush")
    created = datetime.datetime.fromisoformat(source_claim["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
    # Verified 3.7.8 receiver limits: maximum accepted age 1w, future grace 10m.
    lower = int(created.timestamp()) * 10**9 - 7 * 86400 * 10**9
    upper = time.time_ns() + 600 * 10**9
    first = query(SOURCE, lower, upper, limit=1)
    if not first:
        raise RuntimeError("persisted receiver unexpectedly has no originals")
    source_audit = preserved_source_audit(root) if phase == "final" else None
    if source_audit:
        source_audit = frozen_source_audit(source_audit, accounting)
    result = transfer(first[0][1], upper, apply, source_audit)
    require_stage(target_uid, phase)
    if phase == "final" and cold_recovery.metrics(SOURCE) != (0, received):
        raise RuntimeError("quiescent source changed during final transfer")
    if phase == "final":
        count = source_query_count(first[0][1], upper)
        if source_accounting() != accounting:
            raise RuntimeError("quiescent source rejection accounting changed")
        if result["source_distinct_records"] != accounting["accepted_records"] or count != accounting["accepted_records"]:
            raise RuntimeError("source enumeration does not account for every accepted original; enumerated=" +
                               str(result["source_distinct_records"]) + "; aggregate=" + str(count) +
                               "; accepted=" + str(accounting["accepted_records"]))
        result.update(enumeration_complete=True, frozen_source_sha256=FROZEN_SOURCE_SHA256,
                      source_accepted_records=count, source_query_count=count,
                      source_rate_limited_attempts=accounting["rate_limited_attempts"])
    result.update(phase=phase, attempt=attempt, target_uid=target_uid,
                  source_uid=cold_recovery.BUFFER_POD_UID,
                  complete_source_quiescence=phase == "final", source_received_counter=received,
                  canonical_source_audit_sha256=SOURCE_AUDIT_SHA256 if source_audit else None)
    cold_recovery.write_verified(receipt, result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["bulk", "final"], required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--target-uid", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.attempt < 1:
        parser.error("attempt must be positive")
    run(args.target_uid, args.phase, args.attempt, args.apply)
