#!/usr/bin/env python3
"""Enroll public SSH host keys through the repository's authenticated Kubernetes API."""

import argparse
import base64
import binascii
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import yaml


ROOT = Path(__file__).resolve().parents[2]
SERVER = "https://10.0.20.50:6443"
NAME = "homelab-ssh-trust"
LABEL = {"app.kubernetes.io/managed-by": "homelab-metal-ssh-trust"}
CONTRACT = "repo-inventory/node-exporter-readonly-host-public-keys/gitea-data-rsa/v1"
NODE_LABEL = "app.kubernetes.io/name=prometheus-node-exporter"
GITEA_LABEL = "app.kubernetes.io/name=gitea"
ALGORITHMS = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
              "ecdsa-sha2-nistp521", "ssh-rsa")
PUBLIC_FILES = tuple("/host/root/etc/ssh/ssh_host_" + kind + "_key.pub"
                     for kind in ("ed25519", "ecdsa", "rsa"))
NODE_COMMAND = ("/host/root/usr/lib64/ld-linux-x86-64.so.2", "--library-path",
                "/host/root/usr/lib64", "/host/root/usr/bin/cat", *PUBLIC_FILES)
HOST = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
IDENTITY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class Refusal(Exception):
    """A missing or inconsistent trust prerequisite; never include command output."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identity(value):
    require(isinstance(value, str) and IDENTITY.fullmatch(value), "Invalid source identity")
    return value


def validate_inventory(hosts):
    require(isinstance(hosts, dict) and hosts, "Empty or invalid active inventory")
    addresses = set()
    for name, address in hosts.items():
        require(isinstance(name, str) and len(name) <= 63 and HOST.fullmatch(name)
                and name not in ("chikorita", "git.eaglepass.io"), "Invalid inventory hostname")
        try:
            ip = ipaddress.IPv4Address(address)
        except (ipaddress.AddressValueError, TypeError):
            raise Refusal("Invalid inventory IPv4 address") from None
        require(str(ip) == address and ip in ipaddress.IPv4Network("10.0.20.0/24")
                and address not in ("10.0.20.0", "10.0.20.50", "10.0.20.255")
                and address not in addresses, "Duplicate or unexpected inventory address")
        addresses.add(address)
    return dict(sorted(hosts.items()))


def inventory(path=None):
    try:
        document = yaml.safe_load((path or ROOT / "metal/inventories/prod.yml").read_text())
        groups = document["metal"]["children"]
        hosts = {}
        for group in ("masters", "workers"):
            members = groups[group]["hosts"]
            require(isinstance(members, dict) and members, "Missing inventory group")
            for name, values in members.items():
                if name == "chikorita":
                    continue
                require(name not in hosts, "Duplicate inventory hostname")
                hosts[name] = values["ansible_host"]
        return validate_inventory(hosts)
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        raise Refusal("Cannot parse production inventory with PyYAML") from None


def parse_key(line):
    require(isinstance(line, str) and 0 < len(line) <= 16384
            and all(32 <= ord(char) <= 126 for char in line), "Invalid public key text")
    fields = line.split()
    require(len(fields) >= 2 and fields[0] in ALGORITHMS, "Unexpected SSH key algorithm")
    algorithm, encoded = fields[:2]
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise Refusal("Invalid public key base64") from None
    require(base64.b64encode(blob).decode() == encoded, "Noncanonical public key base64")
    offset = 0

    def string():
        nonlocal offset
        require(offset + 4 <= len(blob), "Truncated SSH key blob")
        length = struct.unpack_from(">I", blob, offset)[0]
        offset += 4
        require(offset + length <= len(blob), "Truncated SSH key field")
        value = blob[offset:offset + length]
        offset += length
        return value

    require(string() == algorithm.encode(), "SSH wire algorithm does not match public key")
    if algorithm == "ssh-ed25519":
        require(len(string()) == 32, "Invalid Ed25519 public key")
    elif algorithm == "ssh-rsa":
        exponent, modulus = string(), string()
        for number in (exponent, modulus):
            require(number and not number[0] & 128 and any(number)
                    and not (len(number) > 1 and number[0] == 0 and not number[1] & 128),
                    "Invalid RSA public integer")
        require(int.from_bytes(exponent, "big") >= 3 and int.from_bytes(exponent, "big") % 2
                and int.from_bytes(modulus, "big") % 2, "Invalid RSA public key")
    else:
        curve = algorithm.removeprefix("ecdsa-sha2-")
        require(string() == curve.encode(), "ECDSA curve does not match algorithm")
        point = string()
        require(len(point) == {"nistp256": 65, "nistp384": 97, "nistp521": 133}[curve]
                and point[0] == 4, "Invalid ECDSA public point")
    require(offset == len(blob), "Trailing data in SSH key blob")
    return {"algorithm": algorithm, "key": encoded}


def parse_keys(text, node=True):
    keys = [parse_key(line) for line in text.splitlines()]
    kinds = [key["algorithm"] for key in keys]
    if node:
        require(len(keys) == 3 and kinds[0] == "ssh-ed25519"
                and kinds[1].startswith("ecdsa-sha2-") and kinds[2] == "ssh-rsa",
                "Node must supply all three expected public host keys in order")
    else:
        require(kinds == ["ssh-rsa"], "Gitea must supply exactly its RSA public host key")
    return keys


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(
        base64.b64decode(key["key"], validate=True)).digest()).decode().rstrip("=")


class API:
    def __init__(self):
        self.base = ["kubectl", "--kubeconfig", str(ROOT / "metal/kubeconfig.yaml")]
        self.changed = False

    def run(self, args, payload=None, local=False):
        command = self.base + ([] if local else ["--server", SERVER, "--request-timeout=20s"]) + list(args)
        try:
            result = subprocess.run(command, input=payload, text=True, capture_output=True,
                                    check=False, cwd=ROOT, timeout=60)
        except subprocess.TimeoutExpired:
            raise Refusal("kubectl request timed out; inspect the trust pointer before retrying a write") from None
        except (OSError, UnicodeError):
            raise Refusal("kubectl unavailable or returned invalid text") from None
        require(result.returncode == 0, "kubectl failed; command diagnostics withheld")
        return result.stdout

    def json(self, args, payload=None, local=False):
        try:
            return json.loads(self.run(args, payload, local))
        except ValueError:
            raise Refusal("kubectl returned invalid JSON") from None

    def establish(self):
        require(not any(os.environ.get(key) for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")),
            "Proxy environment overrides are not allowed for SSH trust enrollment")
        config = self.json(["config", "view", "--minify", "-o", "json"], local=True)
        clusters = config.get("clusters", [])
        require(len(clusters) == 1, "Expected one minified kubeconfig cluster")
        cluster = clusters[0]["cluster"]
        require(cluster.get("server") == SERVER and not cluster.get("insecure-skip-tls-verify")
                and not cluster.get("proxy-url") and not cluster.get("tls-server-name")
                and (cluster.get("certificate-authority") or cluster.get("certificate-authority-data")),
                "Kubeconfig must verify the exact API VIP using its configured CA, without overrides")
        versions = self.json(["version", "-o", "json"])
        try:
            client, server = [tuple(int(re.fullmatch(r"v?(\d+)\.(\d+)\.\d+.*", versions[key][
                "gitVersion"]).group(index)) for index in (1, 2))
                for key in ("clientVersion", "serverVersion")]
        except (KeyError, TypeError, AttributeError, ValueError):
            raise Refusal("Cannot establish kubectl/server versions") from None
        require(client[0] == server[0] and abs(client[1] - server[1]) <= 1,
                "kubectl/server must be within one minor version")
        return self.cluster_uid()

    def cluster_uid(self):
        namespace = self.json(["get", "namespace", "kube-system", "-o", "json"])
        require(namespace["metadata"]["name"] == "kube-system"
                and not namespace["metadata"].get("deletionTimestamp"), "Invalid kube-system namespace")
        return identity(namespace["metadata"]["uid"])

    def get_cm(self, name=NAME):
        text = self.run(["get", "configmap", name, "-n", "kube-system", "--ignore-not-found", "-o", "json"])
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            raise Refusal("Invalid ConfigMap JSON") from None


def pod_source(pod, namespace, container, node=None):
    metadata, spec, status = pod["metadata"], pod["spec"], pod["status"]
    label = "prometheus-node-exporter" if container == "node-exporter" else "gitea"
    require(metadata["namespace"] == namespace and not metadata.get("deletionTimestamp")
            and metadata.get("labels", {}).get("app.kubernetes.io/name") == label
            and status.get("phase") == "Running"
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", [])), "Source pod is not ready or correctly labeled")
    containers = [c for c in spec.get("containers", []) if c.get("name") == container]
    statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == container]
    require(len(containers) == len(statuses) == 1 and statuses[0].get("ready") is True
            and "running" in statuses[0].get("state", {})
            and (node is None or spec.get("nodeName") == node), "Source container/node mismatch")
    mounts = containers[0].get("volumeMounts", [])
    mount_path = "/host/root" if node else "/data"
    mounts_at_path = [m for m in mounts if m.get("mountPath") == mount_path]
    require(len(mounts_at_path) == 1, "Expected exact source volume mount")
    mount = mounts_at_path[0]
    require(not mount.get("subPath") and not mount.get("subPathExpr")
            and not any(m.get("mountPath", "").startswith(mount_path + "/") for m in mounts),
            "Source mount is shadowed or uses a subpath")
    volumes = [v for v in spec.get("volumes", []) if v.get("name") == mount.get("name")]
    require(len(volumes) == 1, "Source volume is missing or ambiguous")
    if node:
        require(mount.get("readOnly") is True and volumes[0].get("hostPath", {}).get("path") == "/",
                "Node source must mount hostPath / readOnly at /host/root")
    else:
        require(bool(volumes[0].get("persistentVolumeClaim", {}).get("claimName")),
                "Gitea /data must use its persistent volume")
    return {"namespace": namespace, "name": identity(metadata["name"]),
            "uid": identity(metadata["uid"]), "node": identity(spec["nodeName"]),
            "container": container}


def collect(api, hosts):
    nodes = api.json(["get", "nodes", "-o", "json"])["items"]
    live = {node["metadata"]["name"]: node for node in nodes
            if node["metadata"]["name"] != "chikorita"}
    require(len(live) == len([n for n in nodes if n["metadata"]["name"] != "chikorita"])
            and set(live) == set(hosts), "API node membership does not match active inventory")
    for name, address in hosts.items():
        node = live[name]
        require(not node["metadata"].get("deletionTimestamp")
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in node["status"].get("conditions", []))
                and [a["address"] for a in node["status"].get("addresses", [])
                     if a.get("type") == "InternalIP"] == [address], "Node readiness/IP mismatch")
    pods = api.json(["get", "pods", "-n", "monitoring-system", "-l", NODE_LABEL, "-o", "json"])["items"]
    entries = {}
    for name in hosts:
        candidates = [pod for pod in pods if pod["spec"].get("nodeName") == name]
        require(len(candidates) == 1, "Expected exactly one node-exporter pod per active node")
        source = pod_source(candidates[0], "monitoring-system", "node-exporter", name)
        source["node_uid"] = identity(live[name]["metadata"]["uid"])
        text = api.run(["exec", "-n", source["namespace"], source["name"], "-c", "node-exporter",
                        "--", *NODE_COMMAND])
        entries[name] = {"source": source, "keys": parse_keys(text)}
    pods = api.json(["get", "pods", "-n", "gitea", "-l", GITEA_LABEL, "-o", "json"])["items"]
    require(len(pods) == 1, "Expected exactly one Gitea pod")
    source = pod_source(pods[0], "gitea", "gitea")
    require(source["node"] in hosts, "Gitea source runs outside active inventory")
    source["node_uid"] = identity(live[source["node"]]["metadata"]["uid"])
    text = api.run(["exec", "-n", "gitea", source["name"], "-c", "gitea", "--",
                    "cat", "/data/ssh/gitea.rsa.pub"])
    entries["git.eaglepass.io"] = {"source": source, "keys": parse_keys(text, node=False)}
    snapshot = {"inventory": hosts, "entries": entries}
    validate_snapshot(snapshot)
    recheck_sources(api, snapshot)
    return snapshot


def validate_snapshot(snapshot):
    hosts = validate_inventory(snapshot["inventory"])
    entries = snapshot["entries"]
    require(set(snapshot) == {"inventory", "entries"} and set(entries) == set(hosts) | {"git.eaglepass.io"},
            "Incomplete SSH trust snapshot")
    seen_keys = set()
    for name, entry in entries.items():
        require(set(entry) == {"source", "keys"}, "Unexpected snapshot fields")
        source = entry["source"]
        require(set(source) == {"namespace", "name", "uid", "node", "container", "node_uid"},
                "Incomplete source identity")
        for value in source.values():
            identity(value)
        node = name != "git.eaglepass.io"
        require(source["namespace"] == ("monitoring-system" if node else "gitea")
                and source["container"] == ("node-exporter" if node else "gitea")
                and (source["node"] == name if node else source["node"] in hosts),
                "Stored source identity mismatch")
        require(all(set(key) == {"algorithm", "key"} for key in entry["keys"]), "Invalid stored key fields")
        parsed = parse_keys("\n".join(key["algorithm"] + " " + key["key"] for key in entry["keys"]), node)
        require(parsed == entry["keys"], "Invalid stored public keys")
        for key in parsed:
            pair = (key["algorithm"], key["key"])
            require(pair not in seen_keys, "Different hosts share an SSH host key; investigate before enrollment")
            seen_keys.add(pair)


def recheck_sources(api, snapshot):
    for name, entry in snapshot["entries"].items():
        source = entry["source"]
        pod = api.json(["get", "pod", source["name"], "-n", source["namespace"], "-o", "json"])
        current = pod_source(pod, source["namespace"], source["container"],
                             name if name != "git.eaglepass.io" else None)
        require(current == {key: value for key, value in source.items() if key != "node_uid"},
                "Source pod changed during collection/approval; rerun enrollment")
        node = api.json(["get", "node", source["node"], "-o", "json"])
        require(node["metadata"]["uid"] == source["node_uid"]
                and not node["metadata"].get("deletionTimestamp")
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in node["status"].get("conditions", []))
                and [a["address"] for a in node["status"].get("addresses", [])
                     if a.get("type") == "InternalIP"] == [snapshot["inventory"][source["node"]]],
                "Source node changed during collection/approval")
        command = NODE_COMMAND if name != "git.eaglepass.io" else ("cat", "/data/ssh/gitea.rsa.pub")
        current_keys = parse_keys(api.run(["exec", "-n", source["namespace"], source["name"],
                                          "-c", source["container"], "--", *command]),
                                  node=name != "git.eaglepass.io")
        require(current_keys == entry["keys"], "Public keys changed during collection/approval; rerun enrollment")


def batch_digest(uid, snapshot):
    return hashlib.sha256(canonical({"server": SERVER, "cluster_uid": uid,
                                    "source_contract": CONTRACT, "snapshot": snapshot}).encode()).hexdigest()


def known_hosts(snapshot):
    lines = []
    for name, entry in sorted(snapshot["entries"].items()):
        aliases = name + "," + snapshot["inventory"][name] if name in snapshot["inventory"] else name
        for key in entry["keys"]:
            lines.append(aliases + " " + key["algorithm"] + " " + key["key"])
    return "\n".join(lines) + "\n"


def show(uid, snapshot, previous=None):
    print("HOSTNAME/IP                         ALGORITHM                  FINGERPRINT")
    old = previous["entries"] if previous else {}
    for name, entry in sorted(snapshot["entries"].items()):
        alias = name + "/" + snapshot["inventory"][name] if name in snapshot["inventory"] else name
        for key in entry["keys"]:
            changed = " CHANGED" if previous and key not in old.get(name, {}).get("keys", []) else ""
            print(f"{alias:35} {key['algorithm']:26} {fingerprint(key)}{changed}")
    if previous:
        for name, entry in sorted(old.items()):
            for key in entry["keys"]:
                if key not in snapshot["entries"].get(name, {}).get("keys", []):
                    print(f"REMOVED {name} {key['algorithm']} {fingerprint(key)}")
    print(f"API: {SERVER}\nkube-system UID: {uid}\nBatch SHA256: {batch_digest(uid, snapshot)}")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_time(value):
    require(isinstance(value, str), "Invalid approval time")
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
                "Approval time must be UTC")
    except ValueError:
        raise Refusal("Invalid approval time") from None


def bundle(uid, snapshot, previous=None, automatic=False):
    digest = batch_digest(uid, snapshot)
    now = timestamp()
    method = "automatic" if automatic else "manual"
    approval = {"method": method, "time": now}
    root_approval = previous["source_approval"] if automatic and previous and previous["cluster_uid"] == uid else {
        "method": method, "time": now, "batch_digest": digest}
    record = {"version": 1, "server": SERVER, "cluster_uid": uid, "source_contract": CONTRACT,
              "source_approval": root_approval, "approval": approval,
              "batch_digest": digest, "snapshot": snapshot}
    return {"known_hosts": known_hosts(snapshot), "record.json": canonical(record)}


def validate_cm(cm, uid, name=NAME):
    require(isinstance(cm, dict) and cm.get("apiVersion") == "v1" and cm.get("kind") == "ConfigMap",
            "Missing SSH trust ConfigMap; publish it through manual enrollment or automated provisioning")
    metadata = cm["metadata"]
    require(metadata["name"] == name and metadata["namespace"] == "kube-system"
            and all(metadata.get("labels", {}).get(key) == value for key, value in LABEL.items())
            and not metadata.get("deletionTimestamp") and not cm.get("binaryData"),
            "ConfigMap identity/ownership mismatch")
    identity(metadata["uid"])
    identity(metadata["resourceVersion"])
    require(set(cm["data"]) == {"known_hosts", "record.json"}, "Unexpected trust ConfigMap data")
    try:
        record = json.loads(cm["data"]["record.json"])
    except (ValueError, TypeError):
        raise Refusal("Invalid trust record JSON") from None
    require(set(record) == {"version", "server", "cluster_uid", "source_contract", "source_approval",
                            "approval", "batch_digest", "snapshot"}
            and record["version"] == 1 and record["server"] == SERVER
            and record["cluster_uid"] == uid and record["source_contract"] == CONTRACT,
            "Trust record cluster/source contract mismatch; collect the current authenticated source before publication")
    validate_snapshot(record["snapshot"])
    root, approval = record["source_approval"], record["approval"]
    require(set(root) == {"method", "time", "batch_digest"} and root["method"] in ("manual", "automatic")
            and isinstance(root["batch_digest"], str) and DIGEST.fullmatch(root["batch_digest"])
            and set(approval) == {"method", "time"} and approval["method"] in ("manual", "automatic"),
            "No valid source authorization record")
    validate_time(root["time"])
    validate_time(approval["time"])
    require(record["batch_digest"] == batch_digest(uid, record["snapshot"])
            and cm["data"]["known_hosts"] == known_hosts(record["snapshot"]),
            "Trust record batch/bundle mismatch")
    if approval["method"] == "manual":
        require(root["method"] == "manual" and root["batch_digest"] == record["batch_digest"]
                and root["time"] == approval["time"],
                "Manual approval does not match exact batch")
    return record


def write_cm(api, manifest, replacing=False):
    written = api.json(["replace" if replacing else "create", "-f", "-", "-o", "json"], canonical(manifest))
    api.changed = True
    name = manifest["metadata"]["name"]
    readback = api.get_cm(name)
    require(written == readback and readback is not None
            and readback.get("data") == manifest["data"]
            and readback.get("immutable", False) == manifest.get("immutable", False),
            "ConfigMap exact GET readback failed; local trust not installed")
    return readback


def manifest(name, data, immutable=False):
    result = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {
        "name": name, "namespace": "kube-system", "labels": LABEL.copy()}, "data": data}
    if immutable:
        result["immutable"] = True
    return result


def publish(api, uid, snapshot, data, old):
    require(inventory() == snapshot["inventory"], "Inventory changed during approval; rerun enrollment")
    require(api.cluster_uid() == uid, "kube-system UID changed; publication refused")
    recheck_sources(api, snapshot)
    require(api.get_cm() == old, "Trust ConfigMap changed during approval; rerun enrollment")
    if old is not None and old["data"] == data:
        require(api.cluster_uid() == uid, "kube-system UID changed; local trust not installed")
        return False
    if old is not None:
        require(not old.get("immutable"), "Trust pointer must not be immutable")
        # Archive the complete prior approval, not just its keys. Never overwrite audit history.
        archive_name = NAME + "-" + hashlib.sha256(canonical(old["data"]).encode()).hexdigest()[:16]
        archive = api.get_cm(archive_name)
        if archive is None:
            archive = write_cm(api, manifest(archive_name, old["data"], immutable=True))
        require(archive.get("immutable") is True and archive.get("data") == old["data"],
                "Prior trust archive collision or mismatch")
        validate_cm(archive, old_uid(old), archive_name)
        # Archive creation can take time. Recheck the exact pointer and sources immediately before CAS.
        require(api.cluster_uid() == uid, "kube-system UID changed before publication")
        recheck_sources(api, snapshot)
        require(api.get_cm() == old, "Trust ConfigMap changed before publication")
    desired = copy.deepcopy(old) if old is not None else manifest(NAME, data)
    desired["data"] = data
    desired["metadata"].pop("managedFields", None)
    result = write_cm(api, desired, replacing=old is not None)
    validate_cm(result, uid)
    require(api.cluster_uid() == uid, "kube-system UID changed after publication; local trust not installed")
    return True


def old_uid(cm):
    try:
        return identity(json.loads(cm["data"]["record.json"])["cluster_uid"])
    except (KeyError, ValueError, TypeError):
        raise Refusal("Invalid existing trust record") from None


@contextmanager
def local_lock(path):
    path = path.expanduser().absolute()
    require(not any(parent.is_symlink() for parent in (path, *path.parents)),
            "Refusing symlink trust destination ancestry")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = path.with_name("." + path.name + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "Unsafe local trust lock")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def install(path, text):
    def stamp(info):
        # Reads may change atime; only identity, content, and permission changes invalidate installation.
        return None if info is None else (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                                         info.st_mtime_ns, info.st_ctime_ns)

    path = path.expanduser().absolute()
    require(not any(parent.is_symlink() for parent in (path, *path.parents)),
            "Refusing symlink trust destination ancestry")
    before = path.lstat() if path.exists() else None
    require(before is None or stat.S_ISREG(before.st_mode), "Trust destination must be a regular file")
    if before:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as handle:
            require(stamp(os.fstat(handle.fileno())) == stamp(before), "Trust destination changed during read")
            if handle.read() == text and stat.S_IMODE(before.st_mode) == 0o600:
                return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".homelab-known-hosts-", delete=False) as handle:
            temporary = handle.name
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        require(not path.is_symlink() and stamp(path.lstat() if path.exists() else None) == stamp(before),
                "Trust destination changed before atomic install")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            os.unlink(temporary)
    return True


def approve(digest):
    print("Trust source: the authenticated Kubernetes cluster, including future public-key rotations.")
    print("No unverified network scans. Approval covers this exact batch and this ongoing source contract.")
    try:
        answer = input(f"Type APPROVE {digest}: ")
    except EOFError:
        raise Refusal("No approval received; nothing written") from None
    require(answer == "APPROVE " + digest, "Exact batch approval rejected; nothing written")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preview", action="store_true", help="show complete batch without writing")
    modes.add_argument("--automatic", action="store_true", help="publish authenticated host identities without prompting")
    modes.add_argument("--read", "--install", dest="read", action="store_true", help="install stored approval without collection")
    parser.add_argument("--known-hosts", type=Path, default=Path.home() / ".ssh/homelab_known_hosts")
    args = parser.parse_args(argv)
    api = None
    try:
        hosts = inventory()
        api = API()
        uid = api.establish()
        if args.read:
            cm = api.get_cm()
            record = validate_cm(cm, uid)
            require(record["snapshot"]["inventory"] == hosts, "Stored inventory differs; enroll current inventory first")
            with local_lock(args.known_hosts):
                require(api.get_cm() == cm and api.cluster_uid() == uid, "Stored trust changed during read")
                changed = install(args.known_hosts, cm["data"]["known_hosts"])
        else:
            old = api.get_cm() if not args.preview else None
            previous = None
            if old is not None:
                # Preserve the predecessor's audit record even when provisioning replaces the cluster.
                previous = validate_cm(old, old_uid(old))
            snapshot = collect(api, hosts)
            require(api.cluster_uid() == uid, "kube-system UID changed during collection")
            show(uid, snapshot, previous["snapshot"] if previous else None)
            if args.preview:
                return 0
            if not args.automatic:
                approve(batch_digest(uid, snapshot))
            data = bundle(uid, snapshot, previous, automatic=args.automatic)
            if args.automatic and previous is not None and previous["cluster_uid"] == uid and previous["snapshot"] == snapshot:
                data = old["data"]
            with local_lock(args.known_hosts):
                changed = publish(api, uid, snapshot, data, old) or api.changed
                current = api.get_cm()
                require(current is not None and current.get("data") == data
                        and api.cluster_uid() == uid, "Stored trust changed before local install")
                changed = install(args.known_hosts, data["known_hosts"]) or changed
        print("SSH_TRUST_CHANGED=" + ("1" if changed else "0"))
        return 0
    except (Refusal, OSError, KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        if api is not None and api.changed:
            print("SSH_TRUST_CHANGED=1")
        print("SSH trust refused: " + (str(error) if isinstance(error, Refusal)
                                      else "invalid/inaccessible trust input; diagnostics withheld"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if api is not None and api.changed:
            print("SSH_TRUST_CHANGED=1")
        print("SSH trust interrupted; inspect the stored pointer before retrying", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
