#!/usr/bin/env python3
"""Qualify a network-isolated k3s recovery environment without production data."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time


IMAGE = "docker.io/rancher/k3s@sha256:d7119ab9e0054692a86a8eda454f2d3370dafc1c3a96b3ace5c5599f0c1e9f15"
VERSION = "v1.33.6+k3s1"
ROOT = Path("/var/lib/homelab-recovery/maintenance-103")
IMAGE_VOLUMES = {"/var/lib/rancher/k3s": "data", "/var/lib/cni": "cni",
                 "/var/lib/kubelet": "kubelet", "/var/log": "logs"}
SSH = ["ssh", "-i", str(Path.home() / ".ssh/homelab"), "-o", "IdentitiesOnly=yes",
       "-o", "UserKnownHostsFile=" + str(Path.home() / ".ssh/homelab_known_hosts"),
       "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=15", "root@10.0.20.14"]


def run_identifier(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,79}", value):
        raise ValueError("invalid recovery run identifier")
    return value


def require_isolation(container, scratch, run_id):
    labels = container["Config"].get("Labels", {})
    host = container["HostConfig"]
    expected = {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "",
                "UsernsMode": "", "Tmpfs": {"/run": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev"}}
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


def qualify(run_id):
    if os.geteuid() != 0 or command(["hostname"]).stdout.strip() != b"pikachu":
        raise RuntimeError("qualification must run on the exact authorized off-master host")
    if VERSION.encode() not in command(["/usr/local/bin/k3s", "--version"]).stdout:
        raise RuntimeError("installed k3s version changed")
    private_root()
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
        client = ["exec", container_id, "/bin/k3s", "kubectl", "--kubeconfig=/work/kubeconfig", "--request-timeout=5s"]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["qualify", "internal-qualify"])
    parser.add_argument("--run-id", required=True, type=run_identifier)
    args = parser.parse_args()
    if args.phase == "internal-qualify":
        receipt = qualify(args.run_id)
    else:
        source = Path(__file__).read_text()
        remote = "python3 -B -c " + shlex.quote(source) + " internal-qualify --run-id " + shlex.quote(args.run_id)
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
