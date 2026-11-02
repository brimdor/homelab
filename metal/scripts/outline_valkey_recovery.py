#!/usr/bin/env python3
"""Capture Outline's volatile Valkey into protected storage and prove isolated recovery."""

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
import subprocess
import sys
import tempfile
import time
import zlib

import etcd_recovery as common
import mariadb_recovery as protected
import valkey_recovery as valkey


IMAGE = "docker.io/valkey/valkey@sha256:bf09d58e96d6b4524a15396b65b242bbe18beebbcc15a04d8ee75ddac62fae0b"
POD = "outline-5bdfb8cb84-2scgm"
POD_UID = "73ee1edb-f7d5-43d5-8c56-7bf996eff32c"
CONTAINER = "7a7ec3fe6bf6677e90bcf7c66660cbae70d7b1d260c2d542899839d93e67ff3b"
LABEL = "io.eaglepass.outline-valkey-recovery-103"
MAX_SNAPSHOT = 128 * 1024**2
MODULES_SHA256 = "4df4afbb43d9173b3a3de17573d90ed785a5769cf27aa090e943bb95eaa25673"
PROFILE = "original"
SOURCE_NODE = "bulbasaur"
RECEIVER = "pikachu"
MAIN = None
PROFILES = {
    "original": {"pod": POD, "uid": POD_UID, "container": CONTAINER,
                 "node": SOURCE_NODE, "receiver": RECEIVER, "main": None},
    "growlithe-20261102": {
        "pod": "outline-5bdfb8cb84-7zjf4", "uid": "62b73e44-1a31-4251-be50-eefed281a231",
        "container": "5756fd780ffa4cbb72de9bdc266db688450a1caaa8045e403ca5978a2eeac637",
        "node": "growlithe", "receiver": "cyndaquil",
        "main": {
            "containerID": "containerd://a5c3307a9fd5ed577b0821670c89eb60e91555297a52c1358582757ac30d956c",
            "imageID": "docker.io/outlinewiki/outline@sha256:f670705964cfb5521aea45b6e78dc2eaf1fd20dec265f17bd75497938d1f3461",
        },
    },
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def configure_profile(name):
    global PROFILE, POD, POD_UID, CONTAINER, SOURCE_NODE, RECEIVER, MAIN
    require(name in PROFILES, "unreviewed Outline recovery profile")
    selected = PROFILES[name]
    PROFILE = name
    POD, POD_UID, CONTAINER = (selected[k] for k in ("pod", "uid", "container"))
    SOURCE_NODE, RECEIVER, MAIN = (selected[k] for k in ("node", "receiver", "main"))


def source():
    client = [os.environ.get("KUBECTL", "kubectl")]
    def get(*args):
        return json.loads(common.command([*client, "get", *args, "-o=json"]).stdout)
    require(get("namespace", "kube-system")["metadata"]["uid"] == common.CLUSTER_UID, "wrong source cluster")
    pod = get("pod", POD, "-n=outline")
    statuses = {c["name"]: c for c in pod["status"].get("containerStatuses", [])}
    require(pod["metadata"]["uid"] == POD_UID and not pod["metadata"].get("deletionTimestamp") and
            pod["spec"]["nodeName"] == SOURCE_NODE and set(statuses) == {"main", "redis"} and
            all(c["ready"] and c["restartCount"] == 0 and c.get("state", {}).get("running") for c in statuses.values()),
            "reviewed Outline source is not unchanged and ready")
    redis = next(c for c in pod["spec"]["containers"] if c["name"] == "redis")
    require(not redis.get("volumeMounts") and statuses["redis"]["imageID"] == IMAGE and
            statuses["redis"]["containerID"] == "containerd://" + CONTAINER, "volatile source binding changed")
    require(MAIN is None or {k: statuses["main"][k] for k in MAIN} == MAIN,
            "reviewed application runtime changed")
    owners = [o for o in pod["metadata"].get("ownerReferences", []) if o.get("controller")]
    require(len(owners) == 1 and owners[0]["kind"] == "ReplicaSet", "source controller changed")
    replica = get("replicaset", owners[0]["name"], "-n=outline")
    require(replica["metadata"]["uid"] == owners[0]["uid"], "source ReplicaSet identity changed")
    owners = [o for o in replica["metadata"].get("ownerReferences", []) if o.get("controller")]
    require(len(owners) == 1 and owners[0]["kind"] == "Deployment" and owners[0]["name"] == "outline",
            "source Deployment ownership changed")
    deployment = get("deployment", "outline", "-n=outline")
    require(deployment["metadata"]["uid"] == owners[0]["uid"] and deployment["spec"].get("replicas") == 1 and
            deployment["status"].get("observedGeneration") == deployment["metadata"]["generation"] and
            all(deployment["status"].get(k) == 1 for k in ("replicas", "readyReplicas", "updatedReplicas", "availableReplicas")),
            "source Deployment is not stable")
    def cli(*args):
        return common.command([*client, "exec", "-n=outline", POD, "-c=redis", "--", "valkey-cli", "--raw", *args]).stdout
    persistence = valkey.info(cli("INFO", "persistence"))
    require(valkey.info(cli("INFO", "server")).get("valkey_version") == "9.1.3" and
            valkey.info(cli("INFO", "replication")).get("role") == "master" and
            valkey.info(cli("INFO", "cluster")).get("cluster_enabled") == "0" and
            persistence.get("loading") == "0" and persistence.get("aof_enabled") == "0" and
            persistence.get("rdb_bgsave_in_progress") == "0" and persistence.get("rdb_last_bgsave_status") == "ok" and
            int(valkey.info(cli("INFO", "memory"))["used_memory"]) < MAX_SNAPSHOT // 2,
            "standalone snapshot prerequisites failed")
    modules = common.command([*client, "exec", "-n=outline", POD, "-c=redis", "--",
                              "valkey-cli", "--json", "MODULE", "LIST"]).stdout
    require(hashlib.sha256(modules).hexdigest() == MODULES_SHA256, "reviewed built-in Lua module profile changed")
    return {"pod_uid": POD_UID, "deployment_uid": deployment["metadata"]["uid"],
            "module_list_sha256": MODULES_SHA256,
            "containers": {n: {k: c[k] for k in ("containerID", "imageID")} for n, c in statuses.items()}}


def remote(mode, run_id, *extra):
    code = "import base64,sys,types,zlib; "
    for name in ("etcd_recovery", "mariadb_recovery", "valkey_recovery"):
        raw = base64.b64encode(zlib.compress(Path(__file__).with_name(name + ".py").read_bytes())).decode()
        code += "m=types.ModuleType(" + repr(name) + ");sys.modules[" + repr(name) + "]=m;exec(zlib.decompress(base64.b64decode(" + repr(raw) + ")),m.__dict__);"
    raw = base64.b64encode(zlib.compress(Path(__file__).read_bytes())).decode()
    code += "exec(zlib.decompress(base64.b64decode(" + repr(raw) + ")))"
    profile = ["--profile", PROFILE] if PROFILE != "original" else []
    ssh = [*common.SSH[:-1], "root@" + common.RECEIVERS[RECEIVER]["address"]]
    return [*ssh, shlex.join(["python3", "-B", "-c", code, mode, "--run-id", run_id, *profile, *extra])]


def point_path(run_id):
    common.require_host(RECEIVER, "v1.36.5+k3s1")
    expected = common.RECEIVERS[RECEIVER]
    require(Path("/etc/machine-id").read_text().strip() == expected["machine"] and
            common.command(["findmnt", "-n", "-o", "UUID", "/"]).stdout.decode().strip() == expected["root_uuid"] and
            common.command(["getenforce"]).stdout.strip() == b"Enforcing", "receiver identity or SELinux changed")
    require(not any(p.is_symlink() for p in (common.ROOT, *common.ROOT.parents)), "recovery ancestry contains symlink")
    common.private_root()
    point = common.ROOT / ("outline-valkey-" + common.run_identifier(run_id))
    require(not point.is_symlink(), "recovery point contains symlink")
    return point


def receiver_preflight(run_id):
    point = point_path(run_id)
    require(not point.exists(), "recovery point already exists; inspect original outcome")
    common.require_capacity(point.parent, MAX_SNAPSHOT, copies=3)
    return {"receiver": RECEIVER, "point": str(point), "capacity_verified": True}


def require_header(header):
    require(header in (b"VALKEY080", b"REDIS0011"), "unsupported RDB header; partial point retained")


def receive(run_id):
    point = point_path(run_id)
    common.require_capacity(point.parent, MAX_SNAPSHOT, copies=3)
    point.mkdir(mode=0o700)
    descriptor = os.open(point.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path = point / "dump.rdb"
    with path.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        header = sys.stdin.buffer.read(9)
        require_header(header)
        output.write(header)
        size = len(header)
        for block in iter(lambda: sys.stdin.buffer.read(1048576), b""):
            size += len(block)
            require(size <= MAX_SNAPSHOT, "snapshot exceeds reviewed bound; partial point retained")
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    return protected.file_digest(path)


def require_manifest(manifest):
    require(set(manifest) == {"format", "cluster_uid", "image", "source", "snapshot", "source_quiesced"} and
            type(manifest["format"]) is int and manifest["format"] == 1 and manifest["cluster_uid"] == common.CLUSTER_UID and
            manifest["image"] == IMAGE and manifest["source_quiesced"] is False, "manifest contract changed")
    identity, snapshot = manifest["source"], manifest["snapshot"]
    require(set(identity) == {"pod_uid", "deployment_uid", "containers", "module_list_sha256"} and
            identity["pod_uid"] == POD_UID and identity["module_list_sha256"] == MODULES_SHA256 and
            re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identity["deployment_uid"]) and
            set(identity["containers"]) == {"main", "redis"} and
            identity["containers"]["redis"] == {"containerID": "containerd://" + CONTAINER, "imageID": IMAGE},
            "source provenance changed")
    require(MAIN is None or identity["containers"]["main"] == MAIN, "application provenance changed")
    for c in identity["containers"].values():
        require(set(c) == {"containerID", "imageID"} and re.fullmatch(r"containerd://[0-9a-f]{64}", c["containerID"]) and
                re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}", c["imageID"]), "container provenance changed")
    require(set(snapshot) == {"bytes", "sha256"} and type(snapshot["bytes"]) is int and
            9 < snapshot["bytes"] <= MAX_SNAPSHOT and re.fullmatch(r"[0-9a-f]{64}", snapshot["sha256"]),
            "snapshot provenance changed")


def finalize(run_id, manifest):
    point = point_path(run_id)
    require_manifest(manifest)
    require({p.name for p in point.iterdir()} == {"dump.rdb"} and
            protected.file_digest(point / "dump.rdb") == manifest["snapshot"], "snapshot changed before durable acceptance")
    protected.write_json(point / "verified.json", manifest)
    return {"point": str(point), "manifest_sha256": hashlib.sha256(common.canonical(manifest)).hexdigest(),
            "snapshot": manifest["snapshot"], "source_quiesced": False}


def backup(run_id):
    before = source()
    producer = receiver = None
    try:
        common.command(remote("internal-preflight", run_id))
        require(source() == before, "source changed during receiver preflight")
        producer = subprocess.Popen([os.environ.get("KUBECTL", "kubectl"), "exec", "-n=outline", POD,
                                     "-c=redis", "--", "valkey-cli", "--rdb", "-"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receiver = subprocess.Popen(remote("internal-receive", run_id), stdin=producer.stdout,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        data, _ = receiver.communicate()
        producer.communicate()
        require(producer.returncode == 0 and receiver.returncode == 0, "snapshot transfer failed; protected partial retained")
        require(source() == before, "source changed during snapshot; partial point retained")
        manifest = {"format": 1, "cluster_uid": common.CLUSTER_UID, "image": IMAGE, "source": before,
                    "snapshot": json.loads(data), "source_quiesced": False}
        require_manifest(manifest)
        return json.loads(common.command(remote("internal-finalize", run_id, "--manifest", json.dumps(manifest))).stdout)
    finally:
        for process in (receiver, producer):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def isolation(container, scratch, run_id):
    host = container["HostConfig"]
    require(container["Config"]["Image"] == IMAGE and container["Config"]["User"] == "1001:1001" and
            container["Config"]["Labels"].get(LABEL) == run_id and
            all(host.get(k) == v for k, v in {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": "",
                "SecurityOpt": ["no-new-privileges:true"], "PidsLimit": 64, "Memory": 134217728,
                "NanoCpus": 500000000, "LogConfig": {"Type": "none", "Config": {}},
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,uid=1001,gid=1001,mode=0700,size=16777216"}}.items()) and
            not any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings")), "restore isolation changed")
    mounts = container["Mounts"]
    require(len(mounts) == 1 and mounts[0]["Type"] == "bind" and mounts[0]["Source"] == str(scratch / "data") and
            mounts[0]["Destination"] == "/data" and mounts[0]["RW"] is True and mounts[0]["Mode"] == "rw,Z",
            "restore mount ownership changed")


def verify_point(point, expected_manifest):
    meta = point.lstat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o700,
            "recovery point ownership changed")
    path = point / "verified.json"
    meta = protected.protected_file(path)
    require(meta.st_size <= 65536 and meta.st_nlink == 1, "manifest file contract changed")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_manifest, "protected manifest changed")
    manifest = json.loads(raw)
    require_manifest(manifest)
    require(protected.protected_file(point / "dump.rdb").st_nlink == 1 and
            protected.file_digest(point / "dump.rdb") == manifest["snapshot"], "protected snapshot changed")
    return manifest


def restore(run_id, expected_manifest):
    point = point_path(run_id)
    manifest = verify_point(point, expected_manifest)
    require(not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip(), "owned drill already active")
    before_images = set(common.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())
    common.require_capacity(common.ROOT, manifest["snapshot"]["bytes"], copies=3)
    scratch = Path(tempfile.mkdtemp(prefix="outline-valkey-restore-", dir=common.ROOT))
    identity = image_id = None
    result = {"accepted": False, "manifest_sha256": expected_manifest, "source_quiesced": False}
    try:
        data = scratch / "data"
        data.mkdir(mode=0o700)
        os.chown(data, 1001, 1001)
        copied = data / "dump.rdb"
        shutil.copyfile(point / "dump.rdb", copied)
        copied.chmod(0o600)
        os.chown(copied, 1001, 1001)
        common.docker("pull", IMAGE)
        image = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        require(image["Os"] == "linux" and image["Architecture"] == "amd64" and
                IMAGE in {protected.canonical_reference(r) for r in image["RepoDigests"]} and
                set(image["Config"].get("Volumes") or {}) <= {"/data"}, "restore image contract changed")
        identity = common.docker("create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=1001:1001",
            "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=64", "--memory=128m", "--cpus=0.5",
            "--label=" + LABEL + "=" + run_id, "-v", str(data) + ":/data:rw,Z",
            "--tmpfs=/tmp:rw,nosuid,nodev,uid=1001,gid=1001,mode=0700,size=16777216", "--entrypoint=/bin/sh",
            IMAGE, "-c", "exec sleep 2147483647").stdout.decode().strip()
        isolation(common.inspect(identity), scratch, run_id)
        common.docker("start", identity)
        container = common.inspect(identity)
        isolation(container, scratch, run_id)
        process_label = container["ProcessLabel"]
        require(re.fullmatch(r"[^:]+:[^:]+:container_t:s0:c\d+,c\d+", process_label), "private process label missing")
        for path in (data, copied):
            label = common.command(["stat", "-c", "%C", str(path)]).stdout.decode().strip()
            require(label.split(":", 3)[2:] == ["container_file_t", process_label.split(":", 3)[3]],
                    "private scratch SELinux label changed")
        namespace = ["nsenter", "--target", str(container["State"]["Pid"]), "--net", "--"]
        links = json.loads(common.command([*namespace, "ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command([*namespace, "ip", f, "-j", "route", "show", "table", "all"]).stdout)
                      for f in ("-4", "-6")), [])
        common.require_network(links, routes)
        require(common.command([*namespace, "ip", "route", "get", "10.0.20.50"], check=False).returncode != 0,
                "restore has a production route")
        version = common.docker("exec", identity, "valkey-server", "--version").stdout
        require(re.search(rb"\bv=9\.1\.3\b", version), "restore version changed")
        count = valkey.checked_keys(common.docker("exec", identity, "valkey-check-rdb", "/data/dump.rdb", check=False))
        common.docker("exec", identity, "valkey-server", "--daemonize", "yes", "--port", "0", "--cluster-enabled", "no",
            "--dir", "/data", "--dbfilename", "dump.rdb", "--unixsocket", "/tmp/recovery.sock", "--unixsocketperm", "700",
            "--pidfile", "/tmp/recovery.pid", "--appendonly", "no", "--save", "", "--logfile", "/tmp/recovery.log")
        def cli(*args, check=True):
            return common.docker("exec", identity, "valkey-cli", "--raw", "-s", "/tmp/recovery.sock", *args, check=check)
        deadline = time.monotonic() + 120
        while cli("PING", check=False).stdout.strip() != b"PONG":
            require(time.monotonic() < deadline, "isolated Valkey startup failed")
            time.sleep(1)
        require(common.docker("exec", identity, "stat", "-c", "%a:%u:%g:%F", "/tmp/recovery.sock").stdout.strip() ==
                b"700:1001:1001:socket", "restore socket permissions changed")
        counts = valkey.load_counts(valkey.info(cli("INFO", "persistence").stdout), valkey.info(cli("INFO", "keyspace").stdout), count)
        require(valkey.info(cli("INFO", "cluster").stdout).get("cluster_enabled") == "0", "restore is clustered")
        modules = common.docker("exec", identity, "valkey-cli", "--json", "-s", "/tmp/recovery.sock", "MODULE", "LIST").stdout
        require(hashlib.sha256(modules).hexdigest() == MODULES_SHA256, "restored built-in Lua profile changed")
        cli("SHUTDOWN", "NOSAVE")
        require(common.docker("exec", identity, "test", "!", "-e", "/tmp/recovery.pid", check=False).returncode == 0,
                "restored Valkey did not stop cleanly")
        require(hashlib.sha256(copied.read_bytes()).hexdigest() == manifest["snapshot"]["sha256"] and
                verify_point(point, expected_manifest) == manifest, "snapshot changed during restore")
        result.update(accepted=True, version="9.1.3", image=IMAGE, counts=counts, checksum_valid=True,
                      protected_hash_unchanged=True, clean_shutdown=True, production_network_unroutable=True)
    finally:
        if identity:
            isolation(common.inspect(identity), scratch, run_id)
            common.docker("rm", "-f", identity)
            require(common.docker("inspect", identity, check=False).returncode != 0, "owned container remains")
        shutil.rmtree(scratch)
        removed = False
        if image_id and image_id not in before_images and not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
            common.docker("image", "rm", IMAGE)
            removed = common.docker("image", "inspect", IMAGE, check=False).returncode != 0
            require(removed, "new unused image remains")
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_unused_image_removed": removed,
                             "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip()}
    protected.write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result


def main():
    def interrupted(_number, _frame):
        raise InterruptedError("Outline Valkey recovery interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backup", "restore", "internal-preflight", "internal-receive", "internal-finalize", "internal-restore"))
    parser.add_argument("--run-id", type=common.run_identifier, required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="original")
    args = parser.parse_args()
    configure_profile(args.profile)
    os.umask(0o077)
    if args.mode == "backup":
        result = backup(args.run_id)
    elif args.mode == "restore":
        result = json.loads(common.command(remote("internal-restore", args.run_id, "--manifest", args.manifest)).stdout)
    elif args.mode == "internal-receive":
        result = receive(args.run_id)
    elif args.mode == "internal-finalize":
        result = finalize(args.run_id, json.loads(args.manifest))
    elif args.mode == "internal-preflight":
        result = receiver_preflight(args.run_id)
    else:
        result = restore(args.run_id, args.manifest)
    print(json.dumps(result), flush=True)
    return 0 if result.get("accepted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
