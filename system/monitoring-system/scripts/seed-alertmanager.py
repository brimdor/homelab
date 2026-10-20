#!/usr/bin/env python3
"""Seed only a verified fresh native Alertmanager point into its empty claim."""

import hashlib
import json
import os
from pathlib import Path
import shutil

import seed_common


NAMES = {"nflog", "silences"}
IMAGE = "quay.io/prometheus/alertmanager@sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286"
SOURCE_UID = "318d7270-40b8-4b7d-a2d5-da168801b4e3"


def protected_source(source, expected):
    if any(p.is_symlink() for p in (source, *source.parents)):
        raise RuntimeError("protected source ancestry changed")
    files = seed_common.inventory(source)
    if set(files) != NAMES | {"verified.json"} or files["verified.json"]["bytes"] > 1048576:
        raise RuntimeError("protected source file set changed")
    encoded = (source / "verified.json").read_bytes()
    if hashlib.sha256(encoded).hexdigest() != expected:
        raise RuntimeError("protected source manifest changed")
    value = json.loads(encoded)
    if (value.get("format") != 1 or value.get("kind") != "alertmanager-native-persisted-snapshots" or
            value.get("image") != IMAGE or value.get("pod_uid") != SOURCE_UID or
            value.get("current_persisted_ram_proven") is not True or set(value.get("files", {})) != NAMES):
        raise RuntimeError("protected source is not the accepted fresh native point")
    records = {n: {k: value["files"][n][k] for k in ("bytes", "sha256")} for n in NAMES}
    if any(files[n] != records[n] or not 0 <= files[n]["bytes"] <= 32 * 1024 * 1024 for n in NAMES):
        raise RuntimeError("protected native file hash or size changed")
    return encoded, records


def seed(source, target, expected, guard, owner=(1000, 2000)):
    encoded, records = protected_source(source, expected)
    if not target.is_dir() or any(p.is_symlink() for p in (target, *target.parents)):
        raise RuntimeError("retained target ancestry changed")
    guard()
    if any(p.name != "lost+found" or p.is_symlink() or not p.is_dir() or any(p.iterdir())
           for p in target.iterdir()):
        raise RuntimeError("retained target is not empty")
    destination = target / "alertmanager-db"
    destination.mkdir(mode=0o700)
    inode = destination.stat().st_ino
    accepted = False
    try:
        for name in sorted(NAMES):
            with (source / name).open("rb") as original, (destination / name).open("xb") as output:
                shutil.copyfileobj(original, output, length=1024 * 1024)
                output.flush()
                os.fchmod(output.fileno(), 0o640)
                os.fchown(output.fileno(), *owner)
                os.fsync(output.fileno())
        os.chmod(destination, 0o770)
        os.chown(destination, *owner)
        if seed_common.inventory(destination) != records or protected_source(source, expected)[0] != encoded:
            raise RuntimeError("retained copy or protected original changed")
        guard()
        for directory in (destination, target):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        accepted = True
        return {"accepted": True, "manifest_sha256": expected, "files": 2,
                "bytes": sum(r["bytes"] for r in records.values()), "sub_path": "alertmanager-db",
                "owner_uid": owner[0], "owner_gid": owner[1], "original_unchanged": True}
    finally:
        if not accepted:
            guard()
            if destination.is_symlink() or destination.stat().st_ino != inode:
                raise RuntimeError("owned partial identity changed; preserved")
            shutil.rmtree(destination)


if __name__ == "__main__":
    os.umask(0o077)
    print(json.dumps(seed(Path("/source"), Path("/target"), os.environ["MANIFEST_SHA256"],
                          seed_common.cluster_guard)), flush=True)
