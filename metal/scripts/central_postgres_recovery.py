#!/usr/bin/env python3
"""Protect the shared PostgreSQL physical backup before fixing its shadowed mount."""

import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tarfile

import etcd_recovery as common
import mariadb_recovery as protected


SOURCE_UID = "1c5b0e1c-2b0d-499e-8bd2-afe68313ba28"
PVC_UID = "2b7b4f6f-d198-4bb1-adc0-65467a8840a6"
PV_UID = "e83c623f-adf2-45ab-92b0-b568c37540f3"
SYSTEM_ID = "7702033148198322214"
IMAGE = "docker.io/brimdor/postgres@sha256:cf396ec97def9e03769e1736e7f1224b989bb664ead28e49dc28815e5c25988e"


def archive_identity(path, system_id=SYSTEM_ID):
    """Inspect backup bytes without extracting data or returning private records."""
    required = {"PG_VERSION", "global/pg_control", "backup_label", "backup_manifest"}
    found = set()
    names = set()
    files = payload = wal = 0
    with tarfile.open(path, "r:") as archive:
        for entry in archive:
            name = entry.name.removeprefix("./").rstrip("/")
            parts = PurePosixPath(name)
            if (not name or parts.is_absolute() or ".." in parts.parts or
                    name in names or not (entry.isfile() or entry.isdir())):
                raise RuntimeError("unsafe or duplicate physical backup member")
            names.add(name)
            if not entry.isfile():
                continue
            files += 1
            payload += entry.size
            if re.fullmatch(r"pg_wal/[0-9A-F]{24}", name):
                wal += 1
            if name in required:
                found.add(name)
                source = archive.extractfile(entry)
                if name == "PG_VERSION" and source.read(16) != b"17\n":
                    raise RuntimeError("physical backup PostgreSQL major changed")
                if name == "global/pg_control":
                    raw = source.read(8)
                    if len(raw) != 8 or str(struct.unpack("<Q", raw)[0]) != system_id:
                        raise RuntimeError("physical backup system identifier changed")
                if name == "backup_manifest":
                    manifest = json.load(source)
                    if (manifest.get("PostgreSQL-Backup-Manifest-Version") != 2 or
                            str(manifest.get("System-Identifier")) != system_id or
                            not manifest.get("Files") or not manifest.get("WAL-Ranges")):
                        raise RuntimeError("physical backup manifest is incomplete")
    if found != required or not files or not payload or not wal:
        raise RuntimeError("physical backup is incomplete")
    return {"system_identifier": system_id, "files": files, "payload_bytes": payload, "wal_files": wal}


def point_path(run_id, create=False):
    common.require_host("pikachu")
    common.private_root()
    point = common.ROOT / ("central-postgres-" + common.run_identifier(run_id))
    if create:
        point.mkdir(mode=0o700)
    metadata = point.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or
            stat.S_IMODE(metadata.st_mode) != 0o700 or
            any(p.is_symlink() for p in (point, *point.parents))):
        raise RuntimeError("shared PostgreSQL recovery point is not protected")
    return point


def receive(source, run_id):
    point = point_path(run_id, create=True)
    archive = point / "base.tar"
    with archive.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        for block in iter(lambda: source.read(1048576), b""):
            if shutil.disk_usage(point).free < len(block):
                raise RuntimeError("protected backup destination is full; partial preserved")
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    result = {"archive": protected.file_digest(archive), "identity": archive_identity(archive)}
    protected.write_json(point / "received.json", result)
    return result


def accept(run_id, received, metadata):
    point = point_path(run_id)
    if (set(metadata) != {"pod_uid", "pvc_uid", "pv_uid", "system_identifier", "image", "source_unchanged"} or
            metadata != {"pod_uid": SOURCE_UID, "pvc_uid": PVC_UID, "pv_uid": PV_UID,
                         "system_identifier": SYSTEM_ID, "image": IMAGE, "source_unchanged": True}):
        raise RuntimeError("shared PostgreSQL capture source changed")
    if (received != json.loads((point / "received.json").read_bytes()) or
            protected.file_digest(point / "base.tar") != received["archive"] or
            archive_identity(point / "base.tar") != received["identity"]):
        raise RuntimeError("received physical backup changed")
    manifest = {"format": 1, "source": metadata, "backup": received}
    protected.write_json(point / "complete.json", manifest)
    marker = protected.file_digest(point / "complete.json")
    return {"point": str(point), "manifest": marker, "backup": received, "accepted_capture": True}


def verify(run_id, manifest_sha256):
    point = point_path(run_id)
    if protected.file_digest(point / "complete.json")["sha256"] != manifest_sha256:
        raise RuntimeError("shared PostgreSQL manifest changed")
    manifest = json.loads((point / "complete.json").read_bytes())
    if (manifest.get("format") != 1 or manifest["source"]["system_identifier"] != SYSTEM_ID or
            protected.file_digest(point / "base.tar") != manifest["backup"]["archive"] or
            archive_identity(point / "base.tar") != manifest["backup"]["identity"]):
        raise RuntimeError("shared PostgreSQL backup changed")
    return manifest
