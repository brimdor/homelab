#!/usr/bin/env python3
"""Qualify a network-isolated k3s recovery environment without production data."""

import argparse
import hashlib
import ipaddress
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


IMAGE = "docker.io/rancher/k3s@sha256:d7119ab9e0054692a86a8eda454f2d3370dafc1c3a96b3ace5c5599f0c1e9f15"
VERSION = "v1.33.6+k3s1"
CLUSTER_UID = "7ff226e0-565a-4610-8a3e-97e7e87355a3"
ROOT = Path("/var/lib/homelab-recovery/maintenance-103")
IMAGE_VOLUMES = {"/var/lib/rancher/k3s": "data", "/var/lib/cni": "cni",
                 "/var/lib/kubelet": "kubelet", "/var/log": "logs"}
SSH = ["ssh", "-i", str(Path.home() / ".ssh/homelab"), "-o", "IdentitiesOnly=yes",
       "-o", "UserKnownHostsFile=" + str(Path.home() / ".ssh/homelab_known_hosts"),
       "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=15", "root@10.0.20.14"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def source_record(name, path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_size <= 0):
            raise RuntimeError("recovery source is not a protected nonempty regular file")
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1048576), b""):
            digest.update(chunk)
        after = os.fstat(source.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after):
            raise RuntimeError("recovery source changed while hashing")
    return {"name": name, "size": before.st_size, "sha256": digest.hexdigest()}, identity(before)


def send_bundle(output, paths, metadata, confirm_source):
    if set(paths) != {"snapshot", "token", "encryption-config.json"}:
        raise RuntimeError("recovery source file contract changed")
    records = {name: source_record(name, path) for name, path in sorted(paths.items())}
    header = {"format": 1, "metadata": metadata, "files": [record for record, _ in records.values()]}
    encoded = canonical(header)
    output.write(encoded + b"\n")
    for name, path in sorted(paths.items()):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            digest = hashlib.sha256()
            length = 0
            for chunk in iter(lambda: source.read(1048576), b""):
                output.write(chunk)
                digest.update(chunk)
                length += len(chunk)
        if length != records[name][0]["size"] or digest.hexdigest() != records[name][0]["sha256"]:
            raise RuntimeError("recovery source changed during streaming")
    if any(source_record(name, path) != records[name] for name, path in sorted(paths.items())) or not confirm_source():
        raise RuntimeError("source identity or recovery material changed before commit")
    output.write(canonical({"commit": hashlib.sha256(encoded).hexdigest()}) + b"\n")
    output.flush()


def read_frame(source):
    line = source.readline(65537)
    if not line.endswith(b"\n") or len(line) > 65536:
        raise RuntimeError("incomplete or oversized recovery frame")
    try:
        frame = json.loads(line)
    except (ValueError, UnicodeError):
        raise RuntimeError("invalid recovery frame") from None
    if not isinstance(frame, dict):
        raise RuntimeError("invalid recovery frame type")
    return frame


def receive_bundle(source, destination):
    header = read_frame(source)
    metadata = header.get("metadata")
    files = header.get("files")
    if (set(header) != {"format", "metadata", "files"} or type(header["format"]) is not int or
            header["format"] != 1 or not isinstance(metadata, dict) or
            metadata.get("version") != VERSION or metadata.get("cluster_uid") != CLUSTER_UID or
            not isinstance(files, list) or len(files) != 3 or
            any(not isinstance(record, dict) or set(record) != {"name", "size", "sha256"} or
                type(record["size"]) is not int or record["size"] <= 0 or
                not isinstance(record["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
                for record in files) or {record["name"] for record in files} !=
            {"snapshot", "token", "encryption-config.json"}):
        raise RuntimeError("recovery manifest identity or file contract changed")
    if any(path.is_symlink() for path in (destination.parent, *destination.parent.parents)):
        raise RuntimeError("recovery destination ancestry contains a symlink")
    if sum(record["size"] for record in files) > shutil.disk_usage(destination.parent).free:
        raise RuntimeError("insufficient actual capacity for the recovery point")
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    for record in files:
        digest = hashlib.sha256()
        remaining = record["size"]
        with (destination / record["name"]).open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            while remaining:
                chunk = source.read(min(1048576, remaining))
                if not chunk:
                    raise RuntimeError("recovery stream truncated before file completion")
                remaining -= len(chunk)
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != record["sha256"]:
            raise RuntimeError("recovery file hash mismatch")
    expected = {"commit": hashlib.sha256(canonical(header)).hexdigest()}
    if read_frame(source) != expected or source.read(1):
        raise RuntimeError("recovery stream has no valid final commit")
    with (destination / "verified.json").open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(canonical(header))
        output.flush()
        os.fsync(output.fileno())
    for parent in (destination, destination.parent):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return header


def run_identifier(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,79}", value):
        raise ValueError("invalid recovery run identifier")
    return value


def require_isolation(container, scratch, run_id):
    labels = container["Config"].get("Labels", {})
    host = container["HostConfig"]
    expected = {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "",
                "UsernsMode": "", "Tmpfs": {"/run": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev",
                                               "/etc/rancher": "rw,nosuid,nodev"}}
    if (labels.get("io.eaglepass.maintenance") != "103" or
            labels.get("io.eaglepass.recovery-run") != run_id or
            any(host.get(k) != v for k, v in expected.items()) or
            any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings")) or
            host.get("SecurityOpt") != ["no-new-privileges:true"]):
        raise RuntimeError("container isolation contract changed")
    expected_mounts = {(str(scratch), "/work", True)} | {
        (str(scratch / name), path, True) for path, name in IMAGE_VOLUMES.items()}
    mounts = container.get("Mounts", [])
    if (len(mounts) != len(expected_mounts) or any(m.get("Type") != "bind" for m in mounts) or
            {(m.get("Source"), m.get("Destination"), m.get("RW")) for m in mounts} != expected_mounts):
        raise RuntimeError("container has an unowned or unexpected mount")


def require_network(links, routes):
    if not links or {link["ifname"] for link in links} != {"lo"}:
        raise RuntimeError("isolated namespace has an external interface")
    for route in routes:
        destination = route.get("dst", "default")
        try:
            network = ipaddress.ip_network(destination, strict=False)
        except ValueError:
            raise RuntimeError("isolated namespace has an external route") from None
        if route.get("dev") != "lo" or not network.is_loopback or route.get("gateway"):
            raise RuntimeError("isolated namespace has an external route")


def command(arguments, check=True):
    result = subprocess.run(arguments, capture_output=True)
    if check and result.returncode:
        # k3s logs can contain join tokens; never include subprocess output in an error.
        raise RuntimeError("recovery subprocess failed: " + arguments[0] + ":" + str(result.returncode))
    return result


def docker(*arguments, check=True):
    return command(["docker", *arguments], check=check)


def inspect(container_id):
    return json.loads(docker("inspect", container_id).stdout)[0]


def private_root():
    for path in (ROOT.parent, ROOT):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RuntimeError("recovery root is not a protected owned directory")


def require_host(name):
    if os.geteuid() != 0 or command(["hostname"]).stdout.strip().decode() != name:
        raise RuntimeError("recovery operation is on the wrong host or identity")
    version = command(["/usr/local/bin/k3s", "--version"]).stdout.decode().splitlines()[0].split()
    if version[:3] != ["k3s", "version", VERSION]:
        raise RuntimeError("installed recovery version changed")


def source_identity():
    client = ["/usr/local/bin/kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml", "--request-timeout=30s"]
    namespaces = json.loads(command([*client, "get", "namespaces", "-o=json"]).stdout)["items"]
    nodes = json.loads(command([*client, "get", "nodes", "-o=json"]).stdout)["items"]
    secret = json.loads(command([*client, "get", "secret", "secrets", "-n=backlog", "-o=json"]).stdout)
    namespace_uids = {item["metadata"]["name"]: item["metadata"]["uid"] for item in namespaces}
    node_uids = {item["metadata"]["name"]: item["metadata"]["uid"] for item in nodes}
    if (namespace_uids.get("kube-system") != CLUSTER_UID or set(node_uids) != {
            "charmander", "squirtle", "bulbasaur", "pikachu", "cyndaquil", "totodile", "growlithe", "arcanine", "sprigatito"} or
            secret["metadata"]["uid"] != "d2322fd9-358d-483e-b0aa-9f89c06ce197" or not secret.get("data")):
        raise RuntimeError("live source cluster or protected Secret identity changed")
    return {"version": VERSION, "source_host": "charmander", "cluster_uid": CLUSTER_UID,
            "namespaces": namespace_uids, "nodes": node_uids,
            "protected_secret": {"namespace": "backlog", "name": "secrets", "uid": secret["metadata"]["uid"],
                                 "key_count": len(secret["data"]), "data_sha256": hashlib.sha256(canonical(secret["data"])).hexdigest()}}


def produce_point(run_id):
    require_host("charmander")
    before = source_identity()
    encryption = command(["/usr/local/bin/k3s", "secrets-encrypt", "status"]).stdout.decode()
    if not re.search(r"(?m)^Encryption Status:\s+Enabled\s*$", encryption):
        raise RuntimeError("source encryption is not proven enabled")
    snapshots = Path("/var/lib/rancher/k3s/server/db/snapshots")
    prefix = "maintenance-103-" + run_id
    if list(snapshots.glob(prefix + "*")):
        raise RuntimeError("refusing to repeat an existing named recovery point")
    command(["/usr/local/bin/k3s", "etcd-snapshot", "save", "--name=" + prefix])
    matches = list(snapshots.glob(prefix + "*"))
    if len(matches) != 1 or source_identity() != before:
        raise RuntimeError("snapshot or source identity is not stable")
    paths = {"snapshot": matches[0], "token": Path("/var/lib/rancher/k3s/server/token"),
             "encryption-config.json": Path("/var/lib/rancher/k3s/server/cred/encryption-config.json")}
    before.update(snapshot_name=matches[0].name, snapshot_mtime_ns=matches[0].stat().st_mtime_ns,
                  source_encryption_enabled=True)
    stable = {key: value for key, value in before.items() if key not in (
        "snapshot_name", "snapshot_mtime_ns", "source_encryption_enabled")}
    send_bundle(sys.stdout.buffer, paths, before, lambda: source_identity() == stable)


def preserve_point(run_id):
    require_host("pikachu")
    private_root()
    point = ROOT / run_id
    manifest = receive_bundle(sys.stdin.buffer, point)
    return {"accepted": True, "phase": "protected-copy", "run_id": run_id, "point": str(point),
            "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(), **manifest}


def remote_command(source, phase, run_id):
    return "python3 -B -c " + shlex.quote(source) + " " + phase + " --run-id " + shlex.quote(run_id)


def copy_point(run_id, source):
    sender = receiver = None
    try:
        sender = subprocess.Popen([*SSH[:-1], "root@10.0.20.11", remote_command(source, "internal-send", run_id)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        receiver = subprocess.Popen([*SSH, remote_command(source, "internal-receive", run_id)],
                                    stdin=sender.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sender.stdout.close()
        output, _ = receiver.communicate()
        source_exit = sender.wait()
        if source_exit or receiver.returncode:
            raise RuntimeError("recovery copy incomplete; protected partial point retained; source exit " +
                               str(source_exit) + ", receiver exit " + str(receiver.returncode))
        receipt = json.loads(output)
        if receipt.get("accepted") is not True or receipt.get("run_id") != run_id:
            raise RuntimeError("recovery receiver returned an invalid receipt")
        return receipt
    finally:
        for process in (receiver, sender):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def qualify(run_id):
    if os.geteuid() != 0 or command(["hostname"]).stdout.strip() != b"pikachu":
        raise RuntimeError("qualification must run on the exact authorized off-master host")
    if VERSION.encode() not in command(["/usr/local/bin/k3s", "--version"]).stdout:
        raise RuntimeError("installed k3s version changed")
    private_root()
    def interrupted(_number, _frame):
        raise InterruptedError("recovery qualification interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    scratch = Path(tempfile.mkdtemp(prefix=run_id + "-qualify-", dir=ROOT))
    scratch.chmod(0o700)
    for name in IMAGE_VOLUMES.values():
        (scratch / name).mkdir(mode=0o700)
    before_images = set(docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
    container_id = image_id = None
    receipt = {"run_id": run_id, "phase": "synthetic-qualification", "accepted": False}
    try:
        docker("pull", IMAGE)
        image = json.loads(docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        if (image.get("Architecture") != "amd64" or image.get("Os") != "linux" or
                set(image["Config"].get("Volumes") or {}) != set(IMAGE_VOLUMES)):
            raise RuntimeError("official image architecture or volume contract changed")
        arguments = ["create", "--network=none", "--read-only", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=256",
                     "--cpus=2", "--memory=2g", "--label=io.eaglepass.maintenance=103",
                     "--label=io.eaglepass.recovery-run=" + run_id,
                     "--mount=type=bind,source=" + str(scratch) + ",target=/work",
                     "--tmpfs=/run:rw,nosuid,nodev", "--tmpfs=/tmp:rw,nosuid,nodev",
                     "--tmpfs=/etc/rancher:rw,nosuid,nodev",
                     "--entrypoint=/bin/sh"]
        arguments += ["--mount=type=bind,source=" + str(scratch / name) + ",target=" + path
                      for path, name in IMAGE_VOLUMES.items()]
        arguments += [IMAGE, "-c", "exec sleep 2147483647"]
        container_id = docker(*arguments).stdout.decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise RuntimeError("Docker returned an invalid owned container identity")
        require_isolation(inspect(container_id), scratch, run_id)
        docker("start", container_id)
        state = inspect(container_id)
        require_isolation(state, scratch, run_id)
        pid = str(state["State"]["Pid"])
        namespace = ["nsenter", "--target", pid, "--net", "--"]
        links = json.loads(command(namespace + ["ip", "-j", "address"]).stdout)
        routes = []
        for family in ("-4", "-6"):
            routes += json.loads(command(namespace + ["ip", family, "-j", "route", "show", "table", "all"]).stdout)
        require_network(links, routes)
        if command(namespace + ["ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("isolated namespace can route to the production API")
        if VERSION.encode() not in docker("exec", container_id, "/bin/k3s", "--version").stdout:
            raise RuntimeError("container k3s version changed")
        server = ["/bin/k3s", "server", "--config=/dev/null", "--data-dir=/var/lib/rancher/k3s",
                  "--write-kubeconfig=/work/kubeconfig", "--disable-agent", "--cluster-init",
                  "--node-name=maintenance-103-qualify", "--node-ip=127.0.0.1", "--advertise-address=127.0.0.1",
                  "--bind-address=127.0.0.1", "--https-listen-port=16443", "--secrets-encryption",
                  "--etcd-disable-snapshots", "--disable=traefik,servicelb,local-storage,metrics-server,coredns",
                  "--disable-helm-controller", "--disable-network-policy", "--disable-kube-proxy", "--flannel-backend=none"]
        script = "umask 077; " + shlex.join(server) + " > /work/server.log 2>&1; echo $? > /work/server.exit"
        docker("exec", "-d", container_id, "/bin/sh", "-c", script)
        client = ["exec", container_id, "/bin/kubectl", "--kubeconfig=/work/kubeconfig", "--request-timeout=5s"]
        while True:
            if (scratch / "server.exit").exists():
                receipt["server_exit"] = (scratch / "server.exit").read_text().strip()
                raise RuntimeError("synthetic k3s exited before readiness")
            if not inspect(container_id)["State"]["Running"]:
                raise RuntimeError("owned qualification container stopped before readiness")
            result = docker(*client, "get", "--raw=/readyz", check=False)
            if result.returncode == 0 and result.stdout.strip() == b"ok":
                break
            time.sleep(5)
        namespace = json.loads(docker(*client, "get", "namespace", "kube-system", "-o=json").stdout)
        nodes = json.loads(docker(*client, "get", "nodes", "-o=json").stdout)
        if namespace["metadata"]["uid"] == "7ff226e0-565a-4610-8a3e-97e7e87355a3" or nodes["items"]:
            raise RuntimeError("synthetic identity or agentless contract failed")
        receipt.update(accepted=True, image_id=image_id, image_digest=IMAGE, version=VERSION,
                       only_loopback=True, production_api_unroutable=True,
                       synthetic_namespace_uid=namespace["metadata"]["uid"], synthetic_nodes=0)
    except Exception as error:
        receipt["error"] = str(error)
    finally:
        if container_id:
            current = inspect(container_id)
            labels = current["Config"].get("Labels", {})
            if (current["Id"] != container_id or labels.get("io.eaglepass.maintenance") != "103" or
                    labels.get("io.eaglepass.recovery-run") != run_id):
                raise RuntimeError("owned recovery container identity changed before cleanup")
            docker("rm", "--force", "--volumes", container_id)
            if docker("inspect", container_id, check=False).returncode == 0:
                raise RuntimeError("owned recovery container cleanup failed")
        shutil.rmtree(scratch)
        if image_id and image_id not in before_images:
            consumers = docker("ps", "--all", "--quiet", "--filter=ancestor=" + image_id).stdout.strip()
            if not consumers:
                docker("image", "rm", IMAGE)
        receipt["cleanup"] = {"container_absent": True, "scratch_absent": not scratch.exists()}
    return receipt


def cancel_qualification(run_id):
    identities = docker("ps", "--all", "--quiet", "--no-trunc",
                        "--filter=label=io.eaglepass.maintenance=103",
                        "--filter=label=io.eaglepass.recovery-run=" + run_id).stdout.decode().split()
    if len(identities) != 1 or not re.fullmatch(r"[a-f0-9]{64}", identities[0]):
        raise RuntimeError("cannot identify exactly one owned qualification container")
    current = inspect(identities[0])
    labels = current["Config"].get("Labels", {})
    work = [m for m in current["Mounts"] if m.get("Destination") == "/work" and m.get("Type") == "bind"]
    if (current["Id"] != identities[0] or labels.get("io.eaglepass.maintenance") != "103" or
            labels.get("io.eaglepass.recovery-run") != run_id or len(work) != 1 or
            Path(work[0]["Source"]).resolve().parent != ROOT or
            not Path(work[0]["Source"]).name.startswith(run_id + "-qualify-")):
        raise RuntimeError("qualification ownership changed before cancellation")
    # The tracked qualification parent owns removal and its finally cleanup receipt.
    docker("kill", "--signal=KILL", identities[0])
    if inspect(identities[0])["State"]["Running"]:
        raise RuntimeError("owned qualification container did not stop")
    return {"accepted": True, "phase": "cancellation-request", "run_id": run_id, "container_id": identities[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["qualify", "internal-qualify", "cancel-qualify", "internal-cancel-qualify",
                                         "copy", "internal-send", "internal-receive"])
    parser.add_argument("--run-id", required=True, type=run_identifier)
    args = parser.parse_args()
    if args.phase == "internal-qualify":
        receipt = qualify(args.run_id)
    elif args.phase == "internal-cancel-qualify":
        receipt = cancel_qualification(args.run_id)
    elif args.phase == "internal-send":
        produce_point(args.run_id)
        return 0
    elif args.phase == "internal-receive":
        receipt = preserve_point(args.run_id)
    elif args.phase == "copy":
        receipt = copy_point(args.run_id, Path(__file__).read_text())
    else:
        source = Path(__file__).read_text()
        remote = "python3 -B -c " + shlex.quote(source) + " internal-" + args.phase + " --run-id " + shlex.quote(args.run_id)
        result = command([*SSH, remote], check=False)
        try:
            receipt = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise RuntimeError("remote qualification returned no valid receipt; exit " + str(result.returncode)) from None
        if (result.returncode == 0) != (receipt.get("accepted") is True):
            raise RuntimeError("remote qualification exit disagrees with its receipt")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
