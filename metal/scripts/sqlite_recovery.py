#!/usr/bin/env python3
"""Protect native online SQLite snapshots; restore only off-master without networking."""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import etcd_recovery as common
import mariadb_recovery as protected

SOURCES = {
    "second-brain": {
        "pod_uid": "52fc3f42-1813-4a05-a424-468e30f8af4c", "container": "second-brain",
        "pvc": "second-brain", "pvc_uid": "e6710211-dfb7-4a1d-ba2c-e1fba53cf6c6",
        "pv_uid": "24b5eb91-847e-463a-b0cc-affc90fe0b96", "database": "/app/data/second-brain.sqlite",
        "image": "registry.eaglepass.io/second-brain@sha256:112b7db8fd2bffb9174797797b2980d4218974dd33085f302134257608c8e1c3",
        "key": {"secret": "second-brain-secrets", "field": "APP_SECRETS_MASTER_KEY_B64",
                "uid": "f9c6ab53-c3b3-4f2e-a8c8-8333f4622631"}},
    "podwave": {
        "pod_uid": "dedfbbae-f4c2-422f-8c23-61d5c805b769", "container": "main",
        "pvc": "podwave-data", "pvc_uid": "768b3cd1-5bb9-4ac6-b3f8-407d055d89cb",
        "pv_uid": "9e5a8b79-92a3-49cb-8fd5-c3b85da25d08", "database": "/app/data/podwave.db",
        "image": "registry.eaglepass.io/podwave@sha256:6168b0fd487c4ed796590e9a4295102efad3412a712594bc33828f0c0c41321e"},
}
LABEL = "io.eaglepass.sqlite-recovery"


def program():
    return globals().get("NODE_PROGRAM") or Path(__file__).with_suffix(".cjs").read_text()


def kube(*args):
    return json.loads(common.command([os.environ.get("KUBECTL", "kubectl"), *args, "-o=json"]).stdout)


def source_identity(namespace):
    expected = SOURCES[namespace]
    if kube("get", "namespace", "kube-system")["metadata"]["uid"] != common.CLUSTER_UID:
        raise RuntimeError("wrong cluster")
    pods = kube("get", "pods", "-n", namespace)["items"]
    pods = [p for p in pods if p["metadata"]["uid"] == expected["pod_uid"] and not p["metadata"].get("deletionTimestamp")]
    if len(pods) != 1:
        raise RuntimeError("reviewed source Pod changed")
    pod = pods[0]
    container = next(c for c in pod["spec"]["containers"] if c["name"] == expected["container"])
    status = next(c for c in pod["status"]["containerStatuses"] if c["name"] == expected["container"])
    image = status["imageID"]
    if not status["ready"] or image.split("@")[-1] != expected["image"].split("@")[-1]:
        raise RuntimeError("reviewed ready source image changed")
    claim = kube("get", "pvc", expected["pvc"], "-n", namespace)
    pv = kube("get", "pv", claim["spec"]["volumeName"])
    mount = [m for m in container["volumeMounts"] if m["mountPath"] == "/app/data"]
    volumes = {v["name"]: v for v in pod["spec"]["volumes"]}
    if (claim["metadata"]["uid"] != expected["pvc_uid"] or pv["metadata"]["uid"] != expected["pv_uid"] or
            claim["status"]["phase"] != "Bound" or claim["spec"]["storageClassName"] != "standard-rwo" or
            pv["spec"].get("csi", {}).get("driver") != "rook-ceph.rbd.csi.ceph.com" or
            pv["spec"]["claimRef"]["uid"] != expected["pvc_uid"] or len(mount) != 1 or
            volumes[mount[0]["name"]].get("persistentVolumeClaim", {}).get("claimName") != expected["pvc"] or
            any(o["metadata"].get("deletionTimestamp") for o in (claim, pv))):
        raise RuntimeError("reviewed source Ceph ownership changed")
    return {"namespace": namespace, "pod": pod["metadata"]["name"], "pod_uid": expected["pod_uid"],
            "pvc_uid": expected["pvc_uid"], "pv_uid": expected["pv_uid"], "image": expected["image"],
            "database": expected["database"], "container": expected["container"], "node": pod["spec"]["nodeName"]}


def remote(mode, run_id, namespace, manifest_hash=""):
    code = "import base64,sys,types; "
    for name in ("etcd_recovery", "mariadb_recovery", "sqlite_recovery"):
        encoded = base64.b64encode(Path(__file__).with_name(name + ".py").read_bytes()).decode()
        code += "m=types.ModuleType(" + repr(name) + ");sys.modules[" + repr(name) + "]=m;"
        if name == "sqlite_recovery":
            code += "m.NODE_PROGRAM=base64.b64decode(" + repr(base64.b64encode(program().encode()).decode()) + ").decode();"
        code += "exec(base64.b64decode(" + repr(encoded) + "),m.__dict__);"
    code += "m.internal(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4])"
    encoded = base64.b64encode(zlib.compress(code.encode())).decode()
    compressed = "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(encoded) + ")))"
    return [*common.SSH[:-1], "-o", "ControlMaster=no", common.SSH[-1],
            shlex.join(["python3", "-B", "-c", compressed, mode, run_id, namespace, manifest_hash])]


def point_path(run_id):
    common.require_host("pikachu")
    common.private_root()
    return common.ROOT / ("sqlite-" + common.run_identifier(run_id))


def receive_database(source, destination):
    line = source.readline(65537)
    if not line.endswith(b"\n") or len(line) > 65536:
        raise RuntimeError("invalid SQLite header frame")
    header = json.loads(line)
    if (set(header) != {"format", "bytes", "sha256", "snapshot"} or type(header["format"]) is not int or header["format"] != 1 or
            type(header["bytes"]) is not int or header["bytes"] <= 0 or
            not re.fullmatch(r"[a-f0-9]{64}", header["sha256"]) or
            not isinstance(header["snapshot"], dict)):
        raise RuntimeError("invalid SQLite snapshot contract")
    snapshot = header["snapshot"]
    if (set(snapshot) != {"tables", "rows", "schema_sha256", "data_sha256", "metadata_sha256", "sqlite_version"} or
            type(snapshot.get("tables")) is not int or snapshot["tables"] <= 0 or
            type(snapshot.get("rows")) is not int or snapshot["rows"] < 0 or
            any(not isinstance(snapshot.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot[k])
                for k in ("schema_sha256", "data_sha256", "metadata_sha256")) or
            not isinstance(snapshot.get("sqlite_version"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", snapshot["sqlite_version"])):
        raise RuntimeError("invalid complete SQLite state fingerprint")
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise RuntimeError("SQLite recovery destination is a symlink")
    if header["bytes"] > shutil.disk_usage(destination.parent).free:
        raise RuntimeError("insufficient actual recovery capacity")
    digest = hashlib.sha256(); remaining = header["bytes"]
    with destination.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        while remaining:
            block = source.read(min(1048576, remaining))
            if not block:
                raise RuntimeError("truncated SQLite snapshot")
            output.write(block); digest.update(block); remaining -= len(block)
        output.flush(); os.fsync(output.fileno())
    if digest.hexdigest() != header["sha256"]:
        raise RuntimeError("SQLite snapshot checksum mismatch")
    if common.read_frame(source) != {"commit": hashlib.sha256(line[:-1]).hexdigest()} or source.read(1):
        raise RuntimeError("SQLite snapshot final commit missing")
    return header


def declared_key(namespace, identity):
    key = SOURCES[namespace].get("key")
    if not key:
        return None
    secret = kube("get", "secret", key["secret"], "-n", namespace)
    if secret["metadata"]["uid"] != key["uid"]:
        raise RuntimeError("declared encryption-key Secret identity changed")
    data = base64.b64decode(secret["data"][key["field"]], validate=True)
    if not data:
        raise RuntimeError("empty declared encryption key")
    script = "process.stdout.write(require('node:crypto').createHash('sha256').update(process.env[process.argv[1]]||'').digest('hex'))"
    actual = common.command([os.environ.get("KUBECTL", "kubectl"), "exec", "-n", namespace,
        identity["pod"], "-c", SOURCES[namespace]["container"], "--", "node", "-e", script, key["field"]]).stdout.strip()
    if not hmac.compare_digest(actual, hashlib.sha256(data).hexdigest().encode()):
        raise RuntimeError("declared encryption key differs from the running application")
    return data


def backup(namespace, run_id):
    identity = source_identity(namespace); expected = SOURCES[namespace]
    key_material = declared_key(namespace, identity)
    producer = receiver = None
    try:
        producer = subprocess.Popen([os.environ.get("KUBECTL", "kubectl"), "exec", "-i", "-n", namespace,
            identity["pod"], "-c", expected["container"], "--", "node", "--disable-warning=ExperimentalWarning",
            "-e", program(), "capture", expected["database"], "/app/data"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receiver = subprocess.Popen(remote("receive", run_id, namespace), stdin=producer.stdout,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close(); output, error = receiver.communicate(); _, native_error = producer.communicate()
        if producer.returncode or receiver.returncode or error or native_error:
            raise RuntimeError("SQLite capture incomplete; protected partial retained; no automatic retry")
        transfer = json.loads(output)
    finally:
        for process in (receiver, producer):
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
    if source_identity(namespace) != identity:
        raise RuntimeError("SQLite source identity changed during capture")
    key = expected.get("key")
    key_record = None
    if key:
        data = declared_key(namespace, identity)
        if not hmac.compare_digest(data, key_material):
            raise RuntimeError("source encryption key changed during SQLite snapshot")
        response = subprocess.run(remote("key", run_id, namespace), input=data, capture_output=True)
        if response.returncode or response.stderr:
            raise RuntimeError("protected encryption key preservation failed")
        key_record = json.loads(response.stdout)
        if key_record != {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}:
            raise RuntimeError("protected encryption key readback mismatch")
    manifest = {"format": 1, "cluster_uid": common.CLUSTER_UID, "source": identity,
                "capture": transfer, "encryption_key": {**key, **key_record} if key else None,
                "created_at_ns": time.time_ns()}
    response = subprocess.run(remote("finalize", run_id, namespace), input=common.canonical(manifest), capture_output=True)
    if response.returncode or response.stderr:
        raise RuntimeError("SQLite protected manifest was not finalized")
    return json.loads(response.stdout)


def restore(point, manifest, manifest_hash, run_id):
    before_images = set(common.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())
    if common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip():
        raise RuntimeError("an owned SQLite restore is active")
    original = protected.file_digest(point / "database.sqlite")
    if original != {k: manifest["capture"][k] for k in ("bytes", "sha256")}:
        raise RuntimeError("protected SQLite bytes changed")
    scratch = Path(tempfile.mkdtemp(prefix=run_id + "-restore-", dir=common.ROOT)); scratch.chmod(0o700)
    identity = image_id = None; result = {"accepted": False, "manifest_sha256": manifest_hash}
    try:
        image_ref = manifest["source"]["image"]
        common.docker("pull", image_ref)
        image = json.loads(common.docker("image", "inspect", image_ref).stdout)[0]; image_id = image["Id"]
        if (image.get("Architecture") != "amd64" or image.get("Os") != "linux" or image["Config"].get("Volumes") or
                image_ref not in image.get("RepoDigests", [])):
            raise RuntimeError("reviewed native application image contract changed")
        identity = common.docker("create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=0:0",
            "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=128", "--cpus=1", "--memory=1g",
            "--label=" + LABEL + "=" + run_id,
            "--mount=type=bind,source=" + str(scratch) + ",target=/work",
            "--mount=type=bind,source=" + str(point / "database.sqlite") + ",target=/original/database.sqlite,readonly",
            "--tmpfs=/tmp:rw,nosuid,nodev", "--entrypoint=node", image_ref, "--disable-warning=ExperimentalWarning",
            "-e", "setInterval(()=>{},2147483647)").stdout.decode().strip()
        container = common.inspect(identity); host = container["HostConfig"]
        if (host["NetworkMode"] != "none" or not host["ReadonlyRootfs"] or host["Privileged"] or
                host["CapDrop"] != ["ALL"] or host.get("CapAdd") or host.get("Devices") or host.get("DeviceRequests") or
                host.get("PortBindings") or host["SecurityOpt"] != ["no-new-privileges:true"] or
                host["PidMode"] or host["IpcMode"] != "private" or
                len(container["Mounts"]) != 2 or
                {(m["Source"], m["Destination"], m["RW"]) for m in container["Mounts"]} !=
                {(str(scratch), "/work", True), (str(point / "database.sqlite"), "/original/database.sqlite", False)}):
            raise RuntimeError("SQLite restore isolation changed")
        # No application entrypoint, credentials, host networking or writable recovery mount.
        common.docker("start", identity)
        state = common.inspect(identity)["State"]
        net = ["nsenter", "--target", str(state["Pid"]), "--net", "--"]
        links = json.loads(common.command([*net, "ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command([*net, "ip", family, "-j", "route", "show", "table", "all"]).stdout) for family in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command([*net, "ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("SQLite restore can route to production")
        response = common.docker("exec", identity, "node", "--disable-warning=ExperimentalWarning", "-e", program(),
                                 "restore", "/original/database.sqlite", "/work", json.dumps(manifest["capture"]["snapshot"]), check=False)
        if response.returncode or response.stderr:
            raise RuntimeError("isolated native SQLite restore failed")
        result.update(json.loads(response.stdout)); assert result["accepted"]
        result.update(namespace=manifest["source"]["namespace"], image=image_ref,
                      network_none=True, application_not_started=True, original_read_only=True)
    finally:
        if identity:
            current = common.inspect(identity)
            if current["Id"] != identity or current["Config"].get("Labels", {}).get(LABEL) != run_id:
                raise RuntimeError("owned SQLite container identity changed")
            common.docker("rm", "-f", "--volumes", identity)
        shutil.rmtree(scratch)
        removed = False
        if image_id and image_id not in before_images and not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
            common.docker("image", "rm", image_id); removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
            if not removed: raise RuntimeError("new SQLite test image remains")
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip(), "new_image_removed": removed}
        if protected.file_digest(point / "database.sqlite") != original:
            raise RuntimeError("original SQLite recovery material changed")
        if manifest["encryption_key"] and protected.file_digest(point / "app-secrets-master-key.b64") != {k: manifest["encryption_key"][k] for k in ("bytes", "sha256")}:
            raise RuntimeError("original SQLite recovery key changed")
        if protected.file_digest(point / "verified.json")["sha256"] != manifest_hash:
            raise RuntimeError("original SQLite manifest changed")
        result["protected_hashes_unchanged"] = True
    protected.write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result


def internal(mode, run_id, namespace, manifest_hash=""):
    def interrupted(_number, _frame):
        raise InterruptedError("SQLite recovery interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    point = point_path(run_id)
    if mode == "receive":
        point.mkdir(mode=0o700); result = receive_database(sys.stdin.buffer, point / "database.sqlite")
        protected.write_json(point / "capture.json", result)
    elif mode == "key":
        key = SOURCES[namespace].get("key")
        if not key: raise RuntimeError("namespace has no reviewed encryption key")
        data = sys.stdin.buffer.read(65537)
        if not data or len(data) > 65536: raise RuntimeError("invalid encryption key size")
        with (point / "app-secrets-master-key.b64").open("xb") as output:
            os.fchmod(output.fileno(), 0o600); output.write(data); output.flush(); os.fsync(output.fileno())
        result = protected.file_digest(point / "app-secrets-master-key.b64")
    elif mode == "finalize":
        manifest = json.load(sys.stdin)
        if manifest["source"]["namespace"] != namespace or manifest["source"]["pod_uid"] != SOURCES[namespace]["pod_uid"]:
            raise RuntimeError("protected namespace or source identity differs")
        if protected.file_digest(point / "database.sqlite") != {k: manifest["capture"][k] for k in ("bytes", "sha256")}:
            raise RuntimeError("protected snapshot bytes differ")
        if manifest["encryption_key"] and protected.file_digest(point / "app-secrets-master-key.b64") != {k: manifest["encryption_key"][k] for k in ("bytes", "sha256")}:
            raise RuntimeError("protected encryption key differs")
        protected.write_json(point / "verified.json", manifest)
        result = {"point": str(point), "manifest_sha256": protected.file_digest(point / "verified.json")["sha256"], "namespace": namespace}
    else:
        assert mode == "restore"
        protected.protected_file(point / "verified.json"); raw = (point / "verified.json").read_bytes(); manifest = json.loads(raw)
        if (not re.fullmatch(r"[a-f0-9]{64}", manifest_hash) or hashlib.sha256(raw).hexdigest() != manifest_hash or
                manifest["cluster_uid"] != common.CLUSTER_UID or manifest["source"]["namespace"] != namespace or
                manifest["source"]["pod_uid"] != SOURCES[namespace]["pod_uid"] or
                manifest["source"]["image"] != SOURCES[namespace]["image"]):
            raise RuntimeError("exact protected restore manifest differs")
        if manifest["encryption_key"] and protected.file_digest(point / "app-secrets-master-key.b64") != {k: manifest["encryption_key"][k] for k in ("bytes", "sha256")}:
            raise RuntimeError("protected recovery key changed")
        result = restore(point, manifest, hashlib.sha256(raw).hexdigest(), run_id)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backup", "restore")); parser.add_argument("--namespace", choices=sorted(SOURCES), required=True)
    parser.add_argument("--run-id", type=common.run_identifier, required=True); parser.add_argument("--manifest"); args = parser.parse_args(); os.umask(0o077)
    if args.mode == "restore" and not re.fullmatch(r"[a-f0-9]{64}", args.manifest or ""):
        parser.error("restore requires exact manifest hash")
    result = backup(args.namespace, args.run_id) if args.mode == "backup" else json.loads(common.command(remote("restore", args.run_id, args.namespace, args.manifest)).stdout)
    print(json.dumps(result), flush=True)
    return 0 if result.get("accepted", True) else 1

if __name__ == "__main__":
    raise SystemExit(main())
