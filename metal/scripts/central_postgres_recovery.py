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
import tempfile
import time

import etcd_recovery as common
import mariadb_recovery as protected
import maintenance_k3s_contract as k3s


SOURCE_UID = "1c5b0e1c-2b0d-499e-8bd2-afe68313ba28"
PVC_UID = "2b7b4f6f-d198-4bb1-adc0-65467a8840a6"
PV_UID = "e83c623f-adf2-45ab-92b0-b568c37540f3"
SYSTEM_ID = "7702033148198322214"
IMAGE = "docker.io/brimdor/postgres@sha256:cf396ec97def9e03769e1736e7f1224b989bb664ead28e49dc28815e5c25988e"
SOURCE_CONTAINER = "218b0fb30daefaf042b2e42b3f6e20cd3e063850e60c026565c266924f7dd865"



CAPTURE_VERSION = common.VERSION
RESTORE_VERSION = common.VERSION


def configure_profile(profile):
    """Bind a fresh Pod to the original protected database and approved K3s bridge."""
    global SOURCE_UID, SOURCE_CONTAINER, CAPTURE_VERSION, RESTORE_VERSION
    fixed = {
        "format": 1, "node": "totodile",
        "node_uid": "83e0e536-e94a-45a1-8dfb-1cedac1e9bd7",
        "pvc_uid": PVC_UID, "pv_uid": PV_UID,
        "system_identifier": SYSTEM_ID, "image": IMAGE,
    }
    if (not isinstance(profile, dict) or
            set(profile) != set(fixed) | {"pod_uid", "container_id", "source_version", "receiver_version"} or
            type(profile["format"]) is not int or
            any(profile[key] != value for key, value in fixed.items()) or
            not k3s.reviewed(profile["source_version"], profile["receiver_version"]) or
            not isinstance(profile["pod_uid"], str) or
            not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", profile["pod_uid"]) or
            not isinstance(profile["container_id"], str) or
            not re.fullmatch(r"[0-9a-f]{64}", profile["container_id"])):
        raise RuntimeError("unreviewed protected PostgreSQL bridge profile")
    SOURCE_UID, SOURCE_CONTAINER = profile["pod_uid"], profile["container_id"]
    CAPTURE_VERSION, RESTORE_VERSION = profile["source_version"], profile["receiver_version"]


def source_runtime(value):
    """Reject a changed native container before reading its namespace files."""
    status = value["status"]
    if (status["id"] != SOURCE_CONTAINER or status["state"] != "CONTAINER_RUNNING" or
            status["imageRef"] != IMAGE or
            status["labels"].get("io.kubernetes.pod.uid") != SOURCE_UID or
            status["labels"].get("io.kubernetes.pod.namespace") != "postgres" or
            status["labels"].get("io.kubernetes.container.name") != "main" or
            type(value["info"].get("pid")) is not int or value["info"]["pid"] <= 0):
        raise RuntimeError("native PostgreSQL capture source changed")
    return value["info"]["pid"]


def capture_local(run_id):
    """Materialize a verified backup before transporting bytes over the network."""
    common.require_host("totodile", CAPTURE_VERSION)
    common.private_root()
    run_id = common.run_identifier(run_id)
    point = common.ROOT / ("central-postgres-source-" + run_id)
    point.mkdir(mode=0o700)

    def runtime():
        return source_runtime(json.loads(common.command(
            ["/usr/local/bin/k3s", "crictl", "inspect", SOURCE_CONTAINER]).stdout))

    pid = runtime()
    temporary = "/tmp/maintenance103-postgres-" + run_id
    script = ("umask 077; mkdir -m 0700 -- \"$1\"; "
              "export PGUSER=\"$POSTGRES_USER\" PGPASSWORD=\"$POSTGRES_PASSWORD\" "
              "PGHOST=127.0.0.1 PGPORT=5432; "
              "pg_basebackup --no-password --pgdata=- --format=tar "
              "--wal-method=fetch --checkpoint=fast --manifest-checksums=SHA256 > \"$1/base.tar\"")
    common.command(["/usr/local/bin/k3s", "crictl", "exec", SOURCE_CONTAINER,
                    "/bin/bash", "-ceu", script, "maintenance103-capture", temporary])
    if runtime() != pid:
        raise RuntimeError("capture source process changed; original files preserved")
    directory = Path("/proc") / str(pid) / "root" / temporary.lstrip("/")
    metadata = directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or
            stat.S_IMODE(metadata.st_mode) != 0o700):
        raise RuntimeError("native backup directory protection changed")
    source = directory / "base.tar"
    record, original = common.source_record("base.tar", source)
    with source.open("rb") as incoming, (point / "base.tar").open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        shutil.copyfileobj(incoming, output)
        output.flush()
        os.fsync(output.fileno())
    if (common.source_record("base.tar", source) != (record, original) or runtime() != pid or
            protected.file_digest(point / "base.tar") !=
            {"sha256": record["sha256"], "bytes": record["size"]}):
        raise RuntimeError("materialized backup changed; originals preserved")
    result = {"point": str(point), "archive": protected.file_digest(point / "base.tar"),
              "identity": archive_identity(point / "base.tar"), "source_uid": SOURCE_UID}
    protected.write_json(point / "complete.json", result)
    shutil.rmtree(directory)
    result["container_temporary_absent"] = not directory.exists()
    return result


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
    common.require_host("pikachu", RESTORE_VERSION)
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


def restore_copy(run_id, manifest_sha256, role):
    """Verify and start only a disposable copy, retaining the protected original."""
    manifest = verify(run_id, manifest_sha256)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", role):
        raise RuntimeError("unreviewed recovery role identifier")
    point = point_path(run_id)
    if shutil.disk_usage(common.ROOT).free <= manifest["backup"]["identity"]["payload_bytes"]:
        raise RuntimeError("insufficient actual capacity for the recovery copy")
    scratch = Path(tempfile.mkdtemp(prefix="central-postgres-copy-", dir=common.ROOT))
    data = scratch / "data"
    data.mkdir(mode=0o700)
    identity = None
    before_images = set(common.docker("image", "ls", "--no-trunc", "-q").stdout.decode().splitlines())
    image_id = None
    result = {"accepted_restore": False}
    label = "io.eaglepass.central-postgres-recovery=" + run_id
    try:
        with tarfile.open(point / "base.tar", "r:") as archive:
            archive.extractall(data, filter="data")
        for parent, directories, files in os.walk(data):
            os.chown(parent, 999, 999)
            for name in directories + files:
                os.chown(Path(parent) / name, 999, 999, follow_symlinks=False)
        os.chmod(data, 0o700)
        common.docker("pull", IMAGE)
        image_id = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]["Id"]
        identity = common.docker("create", "--label", label, "--user", "999:999", "--network", "none",
                                 "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                                 "--tmpfs", "/tmp:rw,mode=1777,size=268435456",
                                 "-v", str(data) + ":/var/lib/postgresql/data:Z",
                                 "--entrypoint", "/bin/bash", IMAGE, "-ceu", "exec sleep infinity").stdout.decode().strip()
        common.docker("start", identity)

        def isolated():
            value = common.inspect(identity)
            mounts = [m for m in value["Mounts"] if m["Type"] == "bind"]
            if (value["Config"]["User"] != "999:999" or
                    value["Config"]["Labels"].get("io.eaglepass.central-postgres-recovery") != run_id or
                    value["HostConfig"]["NetworkMode"] != "none" or
                    not value["HostConfig"]["ReadonlyRootfs"] or
                    set(value["HostConfig"].get("CapDrop") or []) != {"ALL"} or
                    "no-new-privileges" not in (value["HostConfig"].get("SecurityOpt") or []) or
                    len(mounts) != 1 or mounts[0]["Source"] != str(data) or
                    mounts[0]["Destination"] != "/var/lib/postgresql/data" or
                    any(m["Type"] == "volume" for m in value["Mounts"])):
                raise RuntimeError("physical recovery copy isolation changed")

        def execute(*arguments):
            isolated()
            return common.docker("exec", "--user", "999:999", identity, *arguments).stdout

        execute("pg_verifybackup", "--exit-on-error", "/var/lib/postgresql/data")
        execute("pg_ctl", "-D", "/var/lib/postgresql/data", "-l", "/tmp/postgres.log", "-w", "-t", "60",
                "-o", "-c listen_addresses= -c unix_socket_directories=/tmp -c unix_socket_permissions=0700 "
                "-c shared_buffers=32MB -c max_connections=10 -c autovacuum=off", "start")
        query = ("SELECT json_build_object('version',current_setting('server_version_num'),"
                 "'system_identifier',(SELECT system_identifier::text FROM pg_control_system()),"
                 "'in_recovery',pg_is_in_recovery(),"
                 "'databases',(SELECT count(*) FROM pg_database WHERE NOT datistemplate),"
                 "'roles',(SELECT count(*) FROM pg_roles))")
        observed = json.loads(execute("psql", "-X", "-w", "-h", "/tmp", "-U", role, "-d", "postgres",
                                      "-Atq", "-v", "ON_ERROR_STOP=1", "-c", query))
        if observed != {"version": "170005", "system_identifier": SYSTEM_ID,
                        "in_recovery": False, "databases": 6, "roles": 20}:
            raise RuntimeError("physical recovery copy database identity differs")
        execute("pg_ctl", "-D", "/var/lib/postgresql/data", "-w", "-m", "fast", "stop")
        execute("test", "!", "-e", "/var/lib/postgresql/data/postmaster.pid")
        verify(run_id, manifest_sha256)
        result.update(accepted_restore=True, physical_manifest_verified=True,
                      native_database=observed, clean_shutdown=True, original_unchanged=True,
                      network_none=True, ordinary_copied_authentication=True)
    finally:
        if identity:
            common.docker("rm", "-f", identity)
        shutil.rmtree(scratch)
        image_removed = False
        if image_id and image_id not in before_images:
            if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
                image_removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_unused_image_removed": image_removed,
                             "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip()}
        if not result["cleanup"]["scratch_absent"] or not result["cleanup"]["owned_containers_absent"]:
            raise RuntimeError("physical recovery copy cleanup is incomplete")
        protected.write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result
