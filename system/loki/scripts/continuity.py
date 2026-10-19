#!/usr/bin/env python3
"""Preserve a scoped rotated CRI file and recover only query-proven missing logs."""

import argparse
import calendar
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import urllib.parse
import urllib.request


def timestamp(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise RuntimeError("invalid CRI timestamp")
    seconds = calendar.timegm(datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").timetuple())
    return seconds * 10**9 + int((match[2] or "").ljust(9, "0"))


def records(path, start, end):
    result = []
    with path.open() as source:
        for line in source:
            fields = line.removesuffix("\n").split(" ", 3)
            if len(fields) != 4:
                raise RuntimeError("invalid CRI record")
            date, stream, flag, content = fields
            when = timestamp(date)
            if flag != "F" or stream not in ("stdout", "stderr"):
                raise RuntimeError("partial CRI records require the native merge pipeline")
            if start <= when <= end:
                result.append((when, stream, content))
    if not result:
        raise RuntimeError("empty recovery interval")
    return result


def checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_log(original, target, compressed):
    reader = gzip.GzipFile(fileobj=original) if compressed else original
    try:
        shutil.copyfileobj(reader, target)
    finally:
        if compressed:
            reader.close()


def existing(base, labels, start, end):
    selector = "{" + ",".join(k + "=" + json.dumps(v) for k, v in sorted(labels.items())) + "}"
    parameters = {"query": selector, "start": str(start), "end": str(end),
                  "limit": "5000", "direction": "forward"}
    with urllib.request.urlopen(base + "/loki/api/v1/query_range?" +
                                urllib.parse.urlencode(parameters), timeout=60) as response:
        value = json.load(response)
    if value["status"] != "success":
        raise RuntimeError("recovery comparison query failed")
    rows = [(int(ts), hashlib.sha256(line.encode()).hexdigest())
            for stream in value["data"]["result"] for ts, line in stream["values"]]
    if len(rows) >= 5000:
        if start == end:
            raise RuntimeError("cannot prove complete query at one timestamp")
        middle = (start + end) // 2
        return existing(base, labels, start, middle) | existing(base, labels, middle + 1, end)
    return set(rows)


def recover(config, apply):
    os.umask(0o077)
    root = Path("/recovery") / config["name"]
    archived = root / "source.log"
    manifest = root / "manifest.json"
    if not manifest.exists():
        source = Path("/source") / config["file"]
        if source.is_symlink() or not source.is_file() or source.stat().st_ino != config["inode"]:
            raise RuntimeError("rotated source identity changed")
        root.mkdir(mode=0o700)
        before = source.stat()
        with source.open("rb") as original, archived.open("xb") as target:
            copy_log(original, target, source.suffix == ".gz")
            target.flush()
            os.fsync(target.fileno())
            after = os.fstat(original.fileno())
        if (before.st_ino, before.st_size, before.st_mtime_ns) != \
                (after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError("rotated source changed during preservation")
        if archived.stat().st_size != config["uncompressed_bytes"]:
            raise RuntimeError("preserved log size differs from observed rotated source")
        value = {"config": config, "sha256": checksum(archived), "size": archived.stat().st_size}
        with manifest.open("x") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        for directory in (root, root.parent):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    value = json.loads(manifest.read_text())
    if value["config"] != config or value["sha256"] != checksum(archived):
        raise RuntimeError("protected rotation archive changed")
    start, end = config["start"], config["end"]
    source = records(archived, start, end)
    base = "http://loki.loki:3100"
    observed = existing(base, config["labels"], start, end)
    missing = [row for row in source if
               (row[0], hashlib.sha256(row[2].encode()).hexdigest()) not in observed]
    if apply:
        for offset in range(0, len(missing), 250):
            streams = defaultdict(list)
            for when, stream, content in missing[offset:offset + 250]:
                streams[stream].append([str(when), content])
            body = {"streams": [{"stream": {**config["labels"], "stream": stream},
                                 "values": sorted(rows, key=lambda row: int(row[0]))}
                                for stream, rows in streams.items()]}
            request = urllib.request.Request(base + "/loki/api/v1/push",
                                             data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 204:
                    raise RuntimeError("log recovery push failed")
        final = existing(base, config["labels"], start, end)
        if any((row[0], hashlib.sha256(row[2].encode()).hexdigest()) not in final for row in source):
            raise RuntimeError("recovered records not visible in service queries")
    print(json.dumps({"archive_sha256": value["sha256"], "archive_bytes": value["size"],
                      "source_records": len(source), "missing_before": len(missing),
                      "applied": apply, "all_source_records_visible": apply or not missing,
                      "start": start, "end": end}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    recover(json.loads(Path("/scripts/continuity.json").read_text()), args.apply)
