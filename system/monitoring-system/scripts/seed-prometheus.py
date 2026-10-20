#!/usr/bin/env python3
"""Seed an empty retained claim from the exact verified maintenance point."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import stat
import urllib.request


MANIFEST_SHA256 = "b9d2bedfa37e07b9eb3d5736337294e465c53b5cb44a9af5521a7f5d4e4e1a58"
SOURCE_UID = "8c8708ed-dd73-4a5e-baee-9431663553f2"
IMAGE = "quay.io/prometheus/prometheus@sha256:f39df5334dee301b885f77e0ff1159f5d8a43bf9db518f885544594799a1e3c2"


def inventory(root):
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("seed tree root is unsafe")
    result = {}
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise RuntimeError("seed tree contains a symlink or special file")
        for name in names:
            path = Path(parent) / name
            with path.open("rb") as source:
                result[str(path.relative_to(root))] = {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.file_digest(source, "sha256").hexdigest(),
                }
    return result


def seed(source, target, guard, owner=(1000, 2000), expected=MANIFEST_SHA256):
    for root in (source, target):
        if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
            raise RuntimeError("seed root or ancestry is unsafe")
    metadata = source / "verified.json"
    if metadata.is_symlink() or not metadata.is_file():
        raise RuntimeError("protected manifest is unsafe")
    encoded = metadata.read_bytes()
    if len(encoded) > 1048576 or hashlib.sha256(encoded).hexdigest() != expected:
        raise RuntimeError("protected manifest changed")
    manifest = json.loads(encoded)
    if (manifest.get("format") != 1 or manifest.get("source", {}).get("pod_uid") != SOURCE_UID or
            manifest["source"].get("image") != IMAGE or not manifest.get("files")):
        raise RuntimeError("protected source identity changed")
    for name in manifest["files"]:
        path = PurePosixPath(name)
        if not path.parts or path.is_absolute() or str(path) != name or any(p in (".", "..") for p in path.parts):
            raise RuntimeError("unsafe protected path")
    records = manifest["files"]
    if inventory(source / "data") != records:
        raise RuntimeError("protected source files changed")
    guard()
    entries = list(target.iterdir())
    if any(p.name != "lost+found" or p.is_symlink() or not p.is_dir() or any(p.iterdir()) for p in entries):
        raise RuntimeError("retained claim is not empty")
    destination = target / "prometheus-db"
    destination.mkdir(mode=0o700)
    identity = destination.stat().st_ino
    accepted = False
    try:
        for name in sorted(records):
            path = destination / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (source / "data" / name).open("rb") as original, path.open("xb") as output:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fchmod(output.fileno(), 0o640)
                os.fchown(output.fileno(), *owner)
                os.fsync(output.fileno())
        for parent, _, _ in os.walk(destination, topdown=False):
            os.chmod(parent, 0o770)
            os.chown(parent, *owner)
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if inventory(destination) != records or inventory(source / "data") != records:
            raise RuntimeError("seed or protected original hash changed")
        if (source / "verified.json").read_bytes() != encoded:
            raise RuntimeError("protected manifest changed during seed")
        guard()
        descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        accepted = True
        return {"accepted": True, "manifest_sha256": expected, "files": len(records),
                "bytes": sum(r["bytes"] for r in records.values()), "sub_path": "prometheus-db",
                "owner_uid": owner[0], "owner_gid": owner[1], "original_unchanged": True}
    finally:
        if not accepted:
            # Preserve the candidate if identity or another consumer changed.
            guard()
            if destination.is_symlink() or destination.stat().st_ino != identity:
                raise RuntimeError("owned seed directory changed; preserved")
            shutil.rmtree(destination)


def validate_storage(claim, volume, pods, env):
    claim_name = env["CLAIM_NAME"]
    if (claim["metadata"]["uid"] != env["CLAIM_UID"] or
            claim["metadata"].get("deletionTimestamp") or claim["status"]["phase"] != "Bound" or
            claim["spec"]["volumeName"] != env["PV_NAME"] or
            claim["spec"]["storageClassName"] != "standard-rwo" or
            claim["spec"]["accessModes"] != ["ReadWriteOnce"] or
            volume["metadata"]["uid"] != env["PV_UID"] or
            volume["metadata"].get("deletionTimestamp") or
            volume["spec"]["claimRef"]["uid"] != env["CLAIM_UID"]):
        raise RuntimeError("retained storage identity changed")
    for pod in pods:
        if pod["metadata"]["uid"] == env["POD_UID"] or pod["status"].get("phase") in ("Succeeded", "Failed"):
            continue
        if any(v.get("persistentVolumeClaim", {}).get("claimName") == claim_name
               for v in pod["spec"].get("volumes", [])):
            raise RuntimeError("another retained claim consumer exists")


def cluster_guard():
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    token = (account / "token").read_text().strip()
    context = ssl.create_default_context(cafile=str(account / "ca.crt"))

    def get(path):
        request = urllib.request.Request("https://" + os.environ["KUBERNETES_SERVICE_HOST"] + path,
                                         headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            return json.load(response)

    validate_storage(
        get("/api/v1/namespaces/monitoring-system/persistentvolumeclaims/" + os.environ["CLAIM_NAME"]),
        get("/api/v1/persistentvolumes/" + os.environ["PV_NAME"]),
        get("/api/v1/namespaces/monitoring-system/pods")["items"], os.environ)


if __name__ == "__main__":
    os.umask(0o077)
    print(json.dumps(seed(Path("/source"), Path("/target"), cluster_guard)), flush=True)
