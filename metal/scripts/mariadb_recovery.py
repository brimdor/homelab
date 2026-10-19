#!/usr/bin/env python3
"""Protect Ceph database dumps off-master; restore only in an isolated container."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

import etcd_recovery as common


NAMESPACES = {"backlog", "jovo"}
ROOT = common.ROOT
LABEL = "io.eaglepass.mariadb-recovery"
DUMP = ["mariadb-dump", "--all-databases", "--single-transaction", "--quick",
        "--routines", "--events", "--triggers", "--hex-blob", "--order-by-primary",
        "--skip-comments", "--skip-dump-date", "--skip-lock-tables", "-uroot"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pull_reference(image):
    # Both endpoints are declared in metal/roles/k3s/templates/registries.yaml.j2.
    # Docker uses the existing TLS endpoint; never weaken its daemon TLS policy.
    if image.startswith("10.0.20.11:32309/"):
        return "registry.eaglepass.io/" + image.split("/", 1)[1]
    return image


def canonical_reference(reference):
    repository, separator, checksum = reference.partition("@")
    if "/" not in repository:
        repository = "docker.io/library/" + repository
    elif not any(c in repository.split("/", 1)[0] for c in (".", ":")):
        repository = "docker.io/" + repository
    return repository + separator + checksum


def require_image(image, reference):
    if (canonical_reference(reference) not in {canonical_reference(r) for r in image.get("RepoDigests", [])} or
            image.get("Os") != "linux" or image.get("Architecture") not in ("amd64", "arm64") or
            set(image["Config"].get("Volumes") or {}) != {"/var/lib/mysql"}):
        raise RuntimeError("reviewed MariaDB image volume, digest or architecture changed")
    if image["Architecture"] == "arm64":
        # Reuse the already-installed handler; never install/register host emulation.
        handler = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64").read_text()
        if not {"enabled", "interpreter /usr/bin/qemu-aarch64-static", "flags: F"}.issubset(handler.splitlines()):
            raise RuntimeError("existing reviewed ARM64 emulation is unavailable")
        return {"architecture": "arm64", "existing_binfmt_sha256": digest(handler.encode())}
    return {"architecture": "amd64"}


def remote(mode, run_id, *extra):
    sources = {name: base64.b64encode(Path(__file__).with_name(name + ".py").read_bytes()).decode()
               for name in ("etcd_recovery", "mariadb_recovery")}
    code = ("import base64,sys,types; m=types.ModuleType('etcd_recovery'); "
            "sys.modules['etcd_recovery']=m; exec(base64.b64decode(" + repr(sources["etcd_recovery"]) +
            "),m.__dict__); exec(base64.b64decode(" + repr(sources["mariadb_recovery"]) + "))")
    return [*common.SSH, shlex.join(["python3", "-c", code, mode, "--run-id", run_id, *extra])]


def protected_file(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError("recovery path contains a symlink")
    meta = path.stat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o600:
        raise RuntimeError("recovery file is not protected")
    return meta


def file_digest(path):
    before = protected_file(path)
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1048576), b""):
            value.update(chunk)
    after = protected_file(path)
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError("recovery file changed while hashing")
    return {"bytes": before.st_size, "sha256": value.hexdigest()}


def write_json(path, value):
    with path.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(common.canonical(value))
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def point_path(run_id):
    common.require_host("pikachu")
    common.private_root()
    return ROOT / ("mariadb-" + common.run_identifier(run_id))


def receive(run_id):
    point = point_path(run_id)
    point.mkdir(mode=0o700)
    value = hashlib.sha256()
    size = 0
    with (point / "cluster.sql").open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        for chunk in iter(lambda: sys.stdin.buffer.read(1048576), b""):
            if shutil.disk_usage(point).free < len(chunk):
                raise RuntimeError("recovery destination is full; protected partial retained")
            output.write(chunk)
            value.update(chunk)
            size += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    if not size:
        raise RuntimeError("empty database export; protected partial retained")
    return {"bytes": size, "sha256": value.hexdigest()}


def finalize(run_id, manifest):
    point = point_path(run_id)
    if (manifest.get("namespace") not in NAMESPACES or
            manifest.get("cluster_uid") != common.CLUSTER_UID or
            not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", manifest.get("image", "")) or
            manifest.get("before") != manifest.get("after") or
            file_digest(point / "cluster.sql") != manifest.get("dump")):
        raise RuntimeError("export identity, stable schema/grants or dump hash changed")
    write_json(point / "verified.json", manifest)
    return {"point": str(point), "manifest_sha256": digest(common.canonical(manifest)), **manifest["dump"]}


def source_client(namespace, pod, *arguments):
    return [os.environ.get("KUBECTL", "kubectl"), "exec", "-n", namespace, pod,
            "-c", "database", "--", "sh", "-c",
            'set -eu; MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; export MYSQL_PWD; exec ' + shlex.join(arguments)]


def source_metadata(namespace, pod):
    def query(sql):
        return common.command(source_client(namespace, pod, "mariadb", "-uroot", "-BN", "-e", sql)).stdout
    version = query("SELECT VERSION()").decode().strip()
    engines = query("SELECT ENGINE,COUNT(*) FROM information_schema.TABLES WHERE TABLE_TYPE='BASE TABLE' "
                    "AND TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys') "
                    "GROUP BY ENGINE ORDER BY ENGINE").decode().splitlines()
    if not version.startswith("10.11.") or not engines or any(not row.startswith("InnoDB\t") for row in engines):
        raise RuntimeError("reviewed MariaDB version or transactional application engine changed")
    schema = common.command(source_client(namespace, pod, *DUMP, "--no-data")).stdout
    grants = query("SELECT Host,User,Priv FROM mysql.global_priv ORDER BY Host,User")
    return {"version": version, "engines": engines, "schema_sha256": digest(schema), "grants_sha256": digest(grants)}


def backup(namespace, expected_uid, run_id):
    if namespace not in NAMESPACES:
        raise RuntimeError("unreviewed database namespace")
    client = [os.environ.get("KUBECTL", "kubectl")]
    def get(*args):
        return json.loads(common.command([*client, "get", *args, "-o=json"]).stdout)
    if get("namespace", "kube-system")["metadata"]["uid"] != common.CLUSTER_UID:
        raise RuntimeError("wrong source cluster")
    pods = [p for p in get("pods", "-n", namespace)["items"] if p["metadata"]["uid"] == expected_uid]
    if len(pods) != 1 or pods[0]["metadata"].get("deletionTimestamp"):
        raise RuntimeError("reviewed database Pod changed")
    pod = pods[0]
    container = next(c for c in pod["spec"]["containers"] if c["name"] == "database")
    mounts = [m for m in container["volumeMounts"] if m["mountPath"] == "/var/lib/mysql"]
    if len(mounts) != 1:
        raise RuntimeError("database mount contract changed")
    volume = next(v for v in pod["spec"]["volumes"] if v["name"] == mounts[0]["name"])
    claim = get("pvc", volume["persistentVolumeClaim"]["claimName"], "-n", namespace)
    pv = get("pv", claim["spec"]["volumeName"])
    status = next(c for c in pod["status"]["containerStatuses"] if c["name"] == "database")
    image = status["imageID"]
    if (not status["ready"] or claim["status"]["phase"] != "Bound" or
            claim["spec"]["storageClassName"] != "standard-rwo" or
            pv["spec"].get("csi", {}).get("driver") != "rook-ceph.rbd.csi.ceph.com"):
        raise RuntimeError("database readiness or reviewed Ceph ownership changed")
    before = source_metadata(namespace, pod["metadata"]["name"])
    producer = subprocess.Popen(source_client(namespace, pod["metadata"]["name"], *DUMP),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    receiver = None
    try:
        receiver = subprocess.Popen(remote("internal-receive", run_id), stdin=producer.stdout,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        result, _ = receiver.communicate()
        _, errors = producer.communicate()
        if receiver.returncode or producer.returncode or errors:
            raise RuntimeError("database stream failed or warned; protected partial point retained")
    finally:
        for process in (receiver, producer):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    current = get("pod", pod["metadata"]["name"], "-n", namespace)
    if current["metadata"]["uid"] != expected_uid or current["metadata"].get("deletionTimestamp"):
        raise RuntimeError("source Pod changed during export")
    manifest = {"namespace": namespace, "cluster_uid": common.CLUSTER_UID, "pod_uid": expected_uid,
                "pvc_uid": claim["metadata"]["uid"], "pv_uid": pv["metadata"]["uid"], "image": image,
                "before": before, "after": source_metadata(namespace, pod["metadata"]["name"]),
                "dump": json.loads(result), "consistent_application_snapshot": True,
                "mysql_nontransactional_limit": "Schema/grants stable before/after; system tables are not an InnoDB snapshot"}
    return json.loads(common.command(remote("internal-finalize", run_id, "--manifest", json.dumps(manifest))).stdout)


def require_isolation(container, scratch, run_id):
    host = container["HostConfig"]
    if (container["Config"].get("Labels", {}).get(LABEL) != run_id or container["Config"].get("User") != "999:999" or
            any(host.get(k) != v for k, v in {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": ""}.items()) or
            any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings")) or
            host.get("SecurityOpt") != ["no-new-privileges:true"] or
            host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev"}):
        raise RuntimeError("database restore isolation changed")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("Source") != str(scratch / "data") or
            mounts[0].get("Destination") != "/var/lib/mysql" or mounts[0].get("RW") is not True):
        raise RuntimeError("database restore mount ownership changed")


def restore(run_id, expected_manifest):
    point = point_path(run_id)
    marker = common.source_record("verified.json", point / "verified.json")[0]
    if marker["sha256"] != expected_manifest:
        raise RuntimeError("reviewed database recovery manifest changed")
    manifest = json.loads((point / "verified.json").read_bytes())
    if file_digest(point / "cluster.sql") != manifest["dump"]:
        raise RuntimeError("database recovery bytes changed")
    if common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip():
        raise RuntimeError("another owned database restore exists")
    def interrupted(_number, _frame):
        raise InterruptedError("database restore interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    before_images = set(common.docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix="mariadb-restore-", dir=ROOT))
    identity = image_id = None
    result = {"accepted": False, "run_id": run_id, "namespace": manifest["namespace"], "stage": "image-pull"}
    try:
        (scratch / "data").mkdir(mode=0o700)
        os.chown(scratch / "data", 999, 999)
        reference = pull_reference(manifest["image"])
        common.docker("pull", reference)
        image = json.loads(common.docker("image", "inspect", reference).stdout)[0]
        image_id = image["Id"]
        result["image_runtime"] = require_image(image, reference)
        result["stage"] = "container-isolation"
        identity = common.docker("create", "--platform=linux/" + image["Architecture"],
                                 "--network=none", "--read-only", "--cap-drop=ALL", "--user=999:999",
                                 "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=256",
                                 "--cpus=1", "--memory=1g", "--label=" + LABEL + "=" + run_id,
                                 "--mount=type=bind,source=" + str(scratch / "data") + ",target=/var/lib/mysql",
                                 "--tmpfs=/tmp:rw,nosuid,nodev", "--entrypoint=/bin/sh", reference,
                                 "-c", "exec sleep 2147483647").stdout.decode().strip()
        require_isolation(common.inspect(identity), scratch, run_id)
        common.docker("start", identity)
        state = common.inspect(identity)
        require_isolation(state, scratch, run_id)
        network = ["nsenter", "--target", str(state["State"]["Pid"]), "--net", "--"]
        links = json.loads(common.command([*network, "ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command([*network, "ip", family, "-j", "route", "show", "table", "all"]).stdout)
                      for family in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command([*network, "ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("restore can route to the production API")
        header = common.docker("exec", identity, "head", "-c", "20", "/usr/sbin/mariadbd").stdout
        expected_machine = 183 if image["Architecture"] == "arm64" else 62
        if header[:6] != b"\x7fELF\x02\x01" or struct.unpack("<H", header[18:20])[0] != expected_machine:
            raise RuntimeError("database executable differs from the reviewed image architecture")
        version = common.docker("exec", identity, "mariadbd", "--version").stdout.decode()
        found = re.search(r"\bVer (\d+\.\d+\.\d+)\b", version)
        if not found or found[1] != manifest["before"]["version"].split("-", 1)[0]:
            raise RuntimeError("isolated database executable version changed")
        result["stage"] = "fresh-initialization"
        common.docker("exec", identity, "mariadb-install-db", "--datadir=/var/lib/mysql",
                      "--auth-root-authentication-method=normal", "--skip-test-db")
        server = ["mariadbd", "--datadir=/var/lib/mysql", "--socket=/tmp/recovery.sock", "--pid-file=/tmp/recovery.pid",
                  "--skip-networking", "--skip-grant-tables", "--event-scheduler=OFF", "--log-error=/tmp/recovery.log"]
        common.docker("exec", "-d", identity, *server)
        client = ["docker", "exec", "-i", identity, "mariadb", "--socket=/tmp/recovery.sock", "-uroot", "-BN"]
        for _ in range(120):
            if common.command([*client, "-e", "SELECT 1"], check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated database did not become ready")
        result["stage"] = "logical-import"
        with (point / "cluster.sql").open("rb") as source:
            restored = subprocess.run(client, stdin=source, capture_output=True)
        if restored.returncode or restored.stdout or restored.stderr:
            raise RuntimeError("isolated database import failed or warned")
        result["stage"] = "schema-grants-data-check"
        schema = common.command(["docker", "exec", identity, *DUMP, "--socket=/tmp/recovery.sock", "--no-data"]).stdout
        grants = common.command([*client, "-e", "SELECT Host,User,Priv FROM mysql.global_priv ORDER BY Host,User"]).stdout
        if digest(schema) != manifest["before"]["schema_sha256"] or digest(grants) != manifest["before"]["grants_sha256"]:
            raise RuntimeError("restored schema or account grants differ")
        dump = common.command(["docker", "exec", identity, *DUMP, "--socket=/tmp/recovery.sock"]).stdout
        if digest(dump) != manifest["dump"]["sha256"]:
            raise RuntimeError("restored normalized logical data differs from the recovery stream")
        rows = common.command([*client, "-e", "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA NOT IN "
                              "('mysql','information_schema','performance_schema','sys')"]).stdout.decode().strip()
        common.docker("exec", identity, "mariadb-check", "--socket=/tmp/recovery.sock", "-uroot", "--all-databases")
        require_isolation(common.inspect(identity), scratch, run_id)
        if file_digest(point / "cluster.sql") != manifest["dump"]:
            raise RuntimeError("original recovery bytes changed during restore")
        result.update(accepted=True, table_count=int(rows), schema_and_grants_match=True, normalized_data_matches=True,
                      production_network_unroutable=True, image=manifest["image"], fetched_reference=reference,
                      manifest_sha256=expected_manifest, stage="accepted")
    except Exception as error:
        result["error"] = str(error)
    finally:
        if identity:
            require_isolation(common.inspect(identity), scratch, run_id)
            common.docker("rm", "-f", identity)
        shutil.rmtree(scratch)
        if image_id and image_id not in before_images:
            if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
        result["cleanup"] = {"scratch_absent": not scratch.exists(),
                             "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip()}
    write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "restore", "internal-receive", "internal-finalize", "internal-restore"))
    parser.add_argument("--run-id", type=common.run_identifier, required=True)
    parser.add_argument("--namespace", choices=sorted(NAMESPACES))
    parser.add_argument("--pod-uid")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == "backup":
        result = backup(args.namespace, args.pod_uid, args.run_id)
    elif args.mode == "restore":
        response = common.command(remote("internal-restore", args.run_id, "--manifest", args.manifest), check=False)
        result = json.loads(response.stdout)
        if response.returncode and result.get("accepted"):
            raise RuntimeError("remote exit status contradicts its restore receipt")
    elif args.mode == "internal-receive":
        result = receive(args.run_id)
    elif args.mode == "internal-finalize":
        result = finalize(args.run_id, json.loads(args.manifest))
    else:
        result = restore(args.run_id, args.manifest)
    print(json.dumps(result), flush=True)
    return 0 if result.get("accepted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
