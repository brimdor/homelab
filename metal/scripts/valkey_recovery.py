#!/usr/bin/env python3
"""Protect each live Valkey shard and exercise disconnected exact-image recovery."""

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

import etcd_recovery as common
import mariadb_recovery as protected


IMAGE = "docker.io/bitnamilegacy/valkey-cluster@sha256:32869e769b7e554219f2ae527b85f4a4739574750beac63b895f5d09fc38f53b"
OWNER = "756a4a5c-e05b-49be-8c27-3bca8de95d88"
LABEL = "io.eaglepass.valkey-recovery"
MASTERS = {"0": "4cefe0b4-6768-4036-9d04-3a1b6bbed826",
           "3": "00498d79-7c81-4c17-b951-9572226932a0",
           "5": "fbf9684d-8e82-499b-adc6-3f47ceadb638"}
CLAIMS = {"0": ("70f147a6-e69d-483e-a4b9-0c732f82bbde", "6fb8c623-327b-4cd9-9958-093671d5d19b"),
          "3": ("33bc20df-0539-4f53-90b3-b58379a02d3a", "29a388c9-f3a5-4c15-a429-159b620db71c"),
          "5": ("b1d74ac6-cc32-42df-902b-73df1b903eed", "0a1273dc-e91e-462c-8bbf-3f46bacfdddd")}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def info(value):
    return dict(line.split(":", 1) for line in value.decode().splitlines()
                if line and not line.startswith("#") and ":" in line)


def topology(value):
    nodes = []
    for line in value.decode().splitlines():
        fields = line.split()
        if len(fields) < 8 or not re.fullmatch(r"[a-f0-9]{40}", fields[0]):
            raise RuntimeError("invalid cluster node evidence")
        flags = set(fields[2].split(",")) - {"myself"}
        if flags not in ({"master"}, {"slave"}) or fields[7] != "connected":
            raise RuntimeError("cluster has an unhealthy or unreviewed node role")
        if any(not re.fullmatch(r"\d+(?:-\d+)?", slot) for slot in fields[8:]):
            raise RuntimeError("cluster has migrating or unreviewed slots")
        nodes.append([fields[0], sorted(flags), fields[3], fields[8:]])
    if len(nodes) != 6 or len({n[0] for n in nodes}) != 6 or sum(n[1] == ["master"] for n in nodes) != 3:
        raise RuntimeError("cluster membership changed")
    masters = {n[0] for n in nodes if n[1] == ["master"]}
    if any(sum(n[2] == master for n in nodes if n[1] == ["slave"]) != 1 for master in masters):
        raise RuntimeError("cluster replica ownership changed")
    slots = []
    for node in nodes:
        if node[1] != ["master"]:
            continue
        for entry in node[3]:
            edges = [int(v) for v in entry.split("-")]
            left, right = edges[0], edges[-1]
            if not 0 <= left <= right < 16384:
                raise RuntimeError("invalid cluster slot range")
            slots.extend(range(left, right + 1))
    if len(slots) != 16384 or len(set(slots)) != 16384:
        raise RuntimeError("cluster slot coverage is incomplete or overlapping")
    return digest(common.canonical(sorted(nodes)))


def remote(mode, run_id, *extra):
    modules = ("etcd_recovery", "mariadb_recovery")
    code = "import base64,sys,types; "
    for name in modules:
        encoded = base64.b64encode(Path(__file__).with_name(name + ".py").read_bytes()).decode()
        code += ("m=types.ModuleType(" + repr(name) + "); sys.modules[" + repr(name) +
                 "]=m; exec(base64.b64decode(" + repr(encoded) + "),m.__dict__); ")
    encoded = base64.b64encode(Path(__file__).read_bytes()).decode()
    code += "exec(base64.b64decode(" + repr(encoded) + "))"
    return [*common.SSH[:-1], "-o", "ControlMaster=no", common.SSH[-1],
            shlex.join(["python3", "-B", "-c", code, mode, "--run-id", run_id, *extra])]


def point_path(run_id):
    common.require_host("pikachu")
    common.private_root()
    path = common.ROOT / ("valkey-" + common.run_identifier(run_id))
    if path.is_symlink():
        raise RuntimeError("recovery point is a symlink")
    return path


def receive(run_id, shard):
    point = point_path(run_id)
    if shard == "0":
        point.mkdir(mode=0o700)
        descriptor = os.open(point.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    meta = point.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o700:
        raise RuntimeError("recovery point is not protected")
    path = point / ("shard-" + shard + ".rdb")
    with path.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        header = sys.stdin.buffer.read(9)
        if not re.fullmatch(rb"REDIS\d{4}", header):
            raise RuntimeError("invalid snapshot header; protected partial retained")
        output.write(header)
        for block in iter(lambda: sys.stdin.buffer.read(1048576), b""):
            if shutil.disk_usage(point).free < len(block):
                raise RuntimeError("recovery destination is full; protected partial retained")
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    return protected.file_digest(path)


def source_snapshot():
    kubectl = [os.environ.get("KUBECTL", "kubectl")]
    def get(*arguments):
        return json.loads(common.command([*kubectl, "get", *arguments, "-o=json"]).stdout)
    if get("namespace", "kube-system")["metadata"]["uid"] != common.CLUSTER_UID:
        raise RuntimeError("wrong source cluster")
    pods = [p for p in get("pods", "-n=gitea")["items"] if any(
        o.get("uid") == OWNER and o.get("kind") == "StatefulSet"
        for o in p["metadata"].get("ownerReferences", []))]
    if len(pods) != 6 or any(p["metadata"].get("deletionTimestamp") or not p["status"].get("containerStatuses") or not all(
            s["ready"] and s["restartCount"] == 0 for s in p["status"].get("containerStatuses", [])) for p in pods):
        raise RuntimeError("six stable ready Valkey Pods are required")
    result = {}
    for shard, uid in MASTERS.items():
        pod = next((p for p in pods if p["metadata"]["uid"] == uid), None)
        if pod is None or pod["metadata"]["name"] != "gitea-valkey-cluster-" + shard:
            raise RuntimeError("reviewed source master changed")
        container = pod["spec"]["containers"]
        statuses = pod["status"]["containerStatuses"]
        if len(container) != 1 or len(statuses) != 1 or statuses[0]["imageID"] != IMAGE:
            raise RuntimeError("reviewed source image changed")
        mounts = [m for m in container[0]["volumeMounts"] if m["mountPath"] == "/bitnami/valkey/data"]
        if len(mounts) != 1:
            raise RuntimeError("source data mount changed")
        volume = next(v for v in pod["spec"]["volumes"] if v["name"] == mounts[0]["name"])
        claim = get("pvc", volume["persistentVolumeClaim"]["claimName"], "-n=gitea")
        pv = get("pv", claim["spec"]["volumeName"])
        if (claim["status"]["phase"] != "Bound" or claim["spec"]["storageClassName"] != "standard-rwo" or
                (claim["metadata"]["uid"], pv["metadata"]["uid"]) != CLAIMS[shard] or
                pv["spec"].get("csi", {}).get("driver") != "rook-ceph.rbd.csi.ceph.com"):
            raise RuntimeError("source is not the reviewed Ceph data")
        def cli(*arguments):
            return common.command([*kubectl, "exec", "-n=gitea", pod["metadata"]["name"], "--",
                                   "valkey-cli", "--raw", *arguments]).stdout
        replication, cluster = info(cli("INFO", "replication")), info(cli("CLUSTER", "INFO"))
        memory, persistence = info(cli("INFO", "memory")), info(cli("INFO", "persistence"))
        if (replication.get("role") != "master" or replication.get("connected_slaves") != "1" or
                cluster.get("cluster_state") != "ok" or cluster.get("cluster_slots_assigned") != "16384" or
                cluster.get("cluster_slots_fail") != "0" or persistence.get("rdb_last_bgsave_status") != "ok" or
                persistence.get("rdb_bgsave_in_progress") != "0" or
                int(memory["used_memory"]) >= 128 * 1024**2 or cli("MODULE", "LIST").strip()):
            raise RuntimeError("source master lacks healthy snapshot prerequisites")
        if info(cli("INFO", "server")).get("valkey_version") != "8.1.3":
            raise RuntimeError("source executable version changed")
        result[shard] = {"pod_uid": uid, "pvc_uid": claim["metadata"]["uid"], "pv_uid": pv["metadata"]["uid"],
                         "topology_sha256": topology(cli("CLUSTER", "NODES"))}
    if len({v["topology_sha256"] for v in result.values()}) != 1:
        raise RuntimeError("source masters disagree on topology")
    return result


def backup(run_id):
    before = source_snapshot()
    shards = {}
    for shard in MASTERS:
        producer = receiver = None
        try:
            producer = subprocess.Popen([os.environ.get("KUBECTL", "kubectl"), "exec", "-n=gitea",
                                         "gitea-valkey-cluster-" + shard, "--", "valkey-cli", "--rdb", "-"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            receiver = subprocess.Popen(remote("internal-receive", run_id, "--shard", shard), stdin=producer.stdout,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            producer.stdout.close()
            data, _ = receiver.communicate()
            producer.communicate()
            if producer.returncode or receiver.returncode:
                raise RuntimeError("snapshot transfer failed; protected partial point retained")
            shards[shard] = {**before[shard], **json.loads(data)}
        finally:
            for process in (receiver, producer):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    if source_snapshot() != before:
        raise RuntimeError("source identity or slot topology changed during snapshots")
    manifest = {"format": 1, "cluster_uid": common.CLUSTER_UID, "owner_uid": OWNER, "image": IMAGE,
                "shards": shards, "cross_shard_atomic": False, "source_quiesced": False}
    return json.loads(common.command(remote("internal-finalize", run_id, "--manifest", json.dumps(manifest))).stdout)


def finalize(run_id, manifest):
    point = point_path(run_id)
    require_manifest(manifest)
    for shard, value in manifest["shards"].items():
        if protected.file_digest(point / ("shard-" + shard + ".rdb")) != {key: value[key] for key in ("bytes", "sha256")}:
            raise RuntimeError("snapshot bytes changed")
    protected.write_json(point / "verified.json", manifest)
    return {"point": str(point), "manifest_sha256": digest(common.canonical(manifest)),
            "shards": {k: {n: v[n] for n in ("bytes", "sha256")} for k, v in manifest["shards"].items()},
            "cross_shard_atomic": False}


def require_manifest(manifest):
    if (manifest.get("format") != 1 or manifest.get("cluster_uid") != common.CLUSTER_UID or manifest.get("owner_uid") != OWNER or
            manifest.get("image") != IMAGE or set(manifest.get("shards", {})) != set(MASTERS) or
            manifest.get("cross_shard_atomic") is not False or manifest.get("source_quiesced") is not False):
        raise RuntimeError("snapshot manifest contract changed")
    for shard, value in manifest["shards"].items():
        if (value.get("pod_uid") != MASTERS[shard] or type(value.get("bytes")) is not int or value["bytes"] <= 9 or
                (value.get("pvc_uid"), value.get("pv_uid")) != CLAIMS[shard] or
                not re.fullmatch(r"[a-f0-9]{64}", value.get("sha256", "")) or
                not re.fullmatch(r"[a-f0-9]{64}", value.get("topology_sha256", "")) or any(
                    not re.fullmatch(r"[a-f0-9-]{36}", value.get(key, "")) for key in ("pvc_uid", "pv_uid"))):
            raise RuntimeError("snapshot provenance changed")
    if len({v["topology_sha256"] for v in manifest["shards"].values()}) != 1:
        raise RuntimeError("snapshot topology changed")


def require_isolation(container, scratch, run_id, mount):
    host = container["HostConfig"]
    if (mount not in ("/bitnami/valkey", "/bitnami/valkey/data") or
            container["Config"].get("Labels", {}).get(LABEL) != run_id or
            container["Config"].get("User") != "1001:1001" or any(host.get(k) != v for k, v in {
                "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"],
                "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": ""}.items()) or
            any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings")) or
            host.get("SecurityOpt") != ["no-new-privileges:true"] or
            host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev"}):
        raise RuntimeError("Valkey restore isolation changed")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("Source") != str(scratch / "data") or
            mounts[0].get("Destination") != mount or mounts[0].get("RW") is not True):
        raise RuntimeError("Valkey restore mount ownership changed")


def checked_keys(result):
    if result.returncode or b"Checksum OK" not in result.stdout:
        raise RuntimeError("RDB checksum validation failed")
    values = re.findall(rb"(?m)\b([0-9]+) keys read\s*$", result.stdout)
    if len(values) != 1:
        raise RuntimeError("RDB key inventory is missing")
    return int(values[0])


def load_counts(persistence, keyspace, expected):
    loaded = int(persistence["rdb_last_load_keys_loaded"])
    expired = int(persistence["rdb_last_load_keys_expired"])
    current = sum(int(re.search(r'(?:^|,)keys=(\d+)(?:,|$)', value)[1]) for value in keyspace.values())
    if min(loaded, expired, current) < 0 or loaded + expired != expected or current > loaded:
        raise RuntimeError("loaded and expired keys do not account for the protected RDB")
    return {"checked_keys": expected, "loaded_keys": loaded, "expired_at_load": expired,
            "current_keys": current, "expired_after_load": loaded - current}


def image_mount(image):
    volumes = set(image["Config"].get("Volumes") or {})
    if (image.get("Os") != "linux" or image.get("Architecture") != "amd64" or
            IMAGE not in {protected.canonical_reference(r) for r in image.get("RepoDigests", [])} or
            volumes not in (set(), {"/bitnami/valkey"}, {"/bitnami/valkey/data"})):
        raise RuntimeError("reviewed Valkey image or volumes changed")
    return next(iter(volumes)) if volumes else "/bitnami/valkey/data"


def restore(run_id, expected_manifest):
    point = point_path(run_id)
    protected.protected_file(point / "verified.json")
    raw = (point / "verified.json").read_bytes()
    manifest = json.loads(raw)
    require_manifest(manifest)
    if digest(raw) != expected_manifest or manifest.get("image") != IMAGE or set(manifest["shards"]) != set(MASTERS):
        raise RuntimeError("protected recovery manifest changed")
    def interrupted(_number, _frame):
        raise InterruptedError("Valkey restore interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    if common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip():
        raise RuntimeError("an owned Valkey drill is already active; leave it alone")
    before_images = set(common.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + "-restore-", dir=common.ROOT))
    identity = image_id = None
    result = {"accepted": False, "run_id": run_id, "shards": {}, "cross_shard_atomic": False}
    try:
        scratch.chmod(0o700)
        data = scratch / "data"
        data.mkdir(mode=0o700)
        os.chown(data, 1001, 1001)
        common.docker("pull", IMAGE)
        image = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        mount = image_mount(image)
        identity = common.docker("create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=1001:1001",
                                 "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=128",
                                 "--cpus=1", "--memory=384m", "--label=" + LABEL + "=" + run_id,
                                 "--mount=type=bind,source=" + str(data) + ",target=" + mount,
                                 "--tmpfs=/tmp:rw,nosuid,nodev", "--entrypoint=/bin/sh", IMAGE,
                                 "-c", "exec sleep 2147483647").stdout.decode().strip()
        require_isolation(common.inspect(identity), scratch, run_id, mount)
        common.docker("start", identity)
        state = common.inspect(identity)
        require_isolation(state, scratch, run_id, mount)
        namespace = ["nsenter", "--target", str(state["State"]["Pid"]), "--net", "--"]
        links = json.loads(common.command([*namespace, "ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command([*namespace, "ip", f, "-j", "route", "show", "table", "all"]).stdout)
                      for f in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command([*namespace, "ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("restore can route to production")
        version = common.docker("exec", identity, "valkey-server", "--version").stdout
        if not re.search(rb"\bv=8\.1\.3\b", version):
            raise RuntimeError("restore executable version changed")
        for shard, evidence in manifest["shards"].items():
            source = point / ("shard-" + shard + ".rdb")
            expected = {k: evidence[k] for k in ("bytes", "sha256")}
            if protected.file_digest(source) != expected:
                raise RuntimeError("protected snapshot bytes changed")
            target = data / "dump.rdb"
            shutil.copyfile(source, target)
            target.chmod(0o600)
            os.chown(target, 1001, 1001)
            count = checked_keys(common.docker("exec", identity, "valkey-check-rdb", mount + "/dump.rdb", check=False))
            common.docker("exec", "-d", identity, "valkey-server", "--port=0", "--cluster-enabled=no",
                          "--dir=" + mount, "--dbfilename=dump.rdb", "--unixsocket=/tmp/recovery.sock",
                          "--unixsocketperm=700",
                          "--pidfile=/tmp/recovery.pid", "--appendonly=no", "--save", "", "--logfile=/tmp/recovery.log")
            def cli(*args, check=True):
                return common.docker("exec", identity, "valkey-cli", "--raw", "-s", "/tmp/recovery.sock", *args, check=check)
            for _ in range(120):
                if cli("PING", check=False).stdout.strip() == b"PONG":
                    break
                time.sleep(1)
            else:
                raise RuntimeError("isolated Valkey did not become ready")
            if common.docker("exec", identity, "stat", "-c", "%a:%u:%g:%F", "/tmp/recovery.sock").stdout.strip() != b"700:1001:1001:socket":
                raise RuntimeError("restore socket ownership or permissions changed")
            counts = load_counts(info(cli("INFO", "persistence").stdout), info(cli("INFO", "keyspace").stdout), count)
            if info(cli("INFO", "cluster").stdout).get("cluster_enabled") != "0":
                raise RuntimeError("isolated restore is unexpectedly clustered")
            require_isolation(common.inspect(identity), scratch, run_id, mount)
            cli("SHUTDOWN", "NOSAVE")
            for _ in range(30):
                if common.docker("exec", identity, "test", "!", "-e", "/tmp/recovery.pid", check=False).returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("restored Valkey did not stop cleanly")
            if protected.file_digest(source) != expected or digest(target.read_bytes()) != expected["sha256"]:
                raise RuntimeError("original or restored RDB changed")
            target.unlink()
            result["shards"][shard] = {**counts, "checksum_valid": True, "protected_hash_unchanged": True,
                                       "clean_shutdown": True, "owner_only_socket": True}
        result.update(accepted=True, version="8.1.3", image=IMAGE, manifest_sha256=expected_manifest,
                      production_network_unroutable=True)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if identity:
            require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker("rm", "-f", identity)
        shutil.rmtree(scratch)
        removed = False
        if image_id and image_id not in before_images:
            if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
                removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
                if not removed:
                    raise RuntimeError("owned Valkey image remains")
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_image_removed": removed,
                             "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip()}
    protected.write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result


def main():
    def interrupted(_number, _frame):
        raise InterruptedError("Valkey recovery interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "restore", "internal-receive", "internal-finalize", "internal-restore"))
    parser.add_argument("--run-id", type=common.run_identifier, required=True)
    parser.add_argument("--shard", choices=sorted(MASTERS))
    parser.add_argument("--manifest")
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == "backup":
        result = backup(args.run_id)
    elif args.mode == "restore":
        response = common.command(remote("internal-restore", args.run_id, "--manifest", args.manifest), check=False)
        result = json.loads(response.stdout)
        if response.returncode and result.get("accepted"):
            raise RuntimeError("remote exit contradicts the restore receipt")
    elif args.mode == "internal-receive":
        result = receive(args.run_id, args.shard)
    elif args.mode == "internal-finalize":
        result = finalize(args.run_id, json.loads(args.manifest))
    else:
        result = restore(args.run_id, args.manifest)
    print(json.dumps(result), flush=True)
    return 0 if result.get("accepted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
