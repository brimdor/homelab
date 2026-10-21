#!/usr/bin/env python3
"""Qualify K3s HA upgrades and snapshot rollback in a caller-owned disposable VM."""

import argparse
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import urllib.request

import yaml

import cilium_l2_qualification as l2
import cilium_qualification as cq
from cilium_cli_build import CLI_VERSION


BASELINE = "v1.33.6+k3s1"
BINARIES = {
    "v1.33.13+k3s2": "cf6afb3944f9ecf120fa2837b542479018c08f9ea1d1d181d4a68445e7717a8d",
    "v1.34.12+k3s1": "67e3e242ba23480634caecc18939feff3a558756b340e4ef964552d748b0271e",
    "v1.35.9+k3s1": "6176dd12c512e177af998e6035920f6283c5fdbd5adfdff85c103a7fdf2a00b5",
    "v1.36.5+k3s1": "135e34cb9e8a1cfae3cb55577789e93501efe7edc080a8b2630458a85b07721e",
}
SUFFIXES = ("-server-0", "-server-1", "-server-2", "-agent-0", "-agent-1")
CILIUM = "1.20.3"
SERVER_FLAGS = ("--flannel-backend=none", "--disable-network-policy", "--disable-kube-proxy",
                "--disable-helm-controller", "--disable=traefik", "--disable=servicelb",
                "--disable=local-storage", "--disable=metrics-server", "--secrets-encryption")
MARKER = "qualification-k3s-snapshot"
DATA = "/var/lib/rancher/k3s"
ECHO_IMAGE = "quay.io/cilium/json-mock:v1.4.1@sha256:6a66df90808a39c02e7a9d58af7bf0e54d8f8b7d4bc528f48c891969a7049195"
ECHO_ENV = [{"name": "PORT", "value": "8080"}, {"name": "NAMED_PORT", "value": "http-8080"}]
CONNECTION_REFUSED = rb"connection refused|The connection to the server 127\.0\.0\.1:6443 was refused - did you specify the right host or port\?"


class CommandFailure(RuntimeError):
    def __init__(self, number, code, stderr):
        super().__init__("qualification command " + str(number) + " exited " + str(code))
        self.number = number
        self.code = code
        self.stderr = stderr


def startup_pending(stderr):
    if {"access-refused", "trust-refused"}.intersection(failure_classes(stderr)):
        return False
    return read_transport_pending(stderr) or stderr.startswith(b"Error from server (InternalError):")


def failure_classes(stderr):
    patterns = {
        "access-refused": rb"(?i)forbidden|unauthorized|permission denied|access.?denied|\b40[13]\b",
        "trust-refused": rb"(?i)x509|certificate|private key|client-key|error loading config|invalid configuration",
        "connection-refused": CONNECTION_REFUSED,
        "connection-reset": rb"connection reset by peer",
        "connection-eof": rb"Unable to connect to the server: EOF|unexpected EOF",
        "connection-goaway": rb"server sent GOAWAY.*ErrCode=NO_ERROR",
        "transport-timeout": rb"TLS handshake timeout|net/http: request canceled|i/o timeout|context deadline exceeded",
        "probe-timeout": rb"(?m)^(?:TimeoutError|socket\.timeout): timed out$",
        "probe-connection-refused": rb"(?m)^ConnectionRefusedError:",
        "probe-connection-reset": rb"(?m)^ConnectionResetError:",
        "probe-url-error": rb"(?m)^urllib\.error\.URLError:",
        "api-unavailable": rb"ServiceUnavailable|server is currently unable to handle",
        "api-notready": rb"readyz check failed|^Error from server \(InternalError\):",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, stderr)] or ["unclassified"]


def read_transport_pending(stderr):
    classes = set(failure_classes(stderr))
    allowed = {"connection-refused", "connection-reset", "connection-eof", "connection-goaway", "transport-timeout", "api-unavailable"}
    return bool(classes) and classes <= allowed


def minor(version):
    match = re.fullmatch(r"v1\.(\d+)\.\d+\+k3s\d+", version)
    if not match:
        raise RuntimeError("invalid pinned K3s version")
    return int(match[1])


def require_transition(previous, target):
    versions = (BASELINE, *BINARIES)
    if previous not in versions or target not in BINARIES or versions.index(target) != versions.index(previous) + 1:
        raise RuntimeError("only the pinned consecutive forward transition is allowed")


def require_nodes(config, name, namespace, nodes, versions, uids=None):
    cq.require_endpoint(config, name)
    uid = namespace["metadata"]["uid"]
    expected = {"k3d-" + name + suffix for suffix in SUFFIXES}
    items = nodes["items"]
    if not uid or uid == cq.PRODUCTION_UID or len(items) != 5 or set(versions) != expected or {n["metadata"]["name"] for n in items} != expected:
        raise RuntimeError("isolated HA cluster must contain the exact five owned nodes")
    for node in items:
        meta = node["metadata"]
        if (not meta.get("uid") or meta.get("deletionTimestamp") or
                node["status"]["nodeInfo"]["kubeletVersion"] != versions[meta["name"]] or
                (uids is not None and meta["uid"] != uids.get(meta["name"]))):
            raise RuntimeError("isolated HA node UID or exact version changed")
    return uid


def container_identity(container, name, fixture):
    volumes = [m for m in container["Mounts"] if m["Destination"] == DATA]
    if (container["Name"] != "/" + name or not container.get("Id") or
            container["Config"]["Labels"].get("k3d.cluster") != fixture or
            len(volumes) != 1 or volumes[0]["Type"] != "volume" or not volumes[0].get("Name") or
            not volumes[0].get("RW")):
        raise RuntimeError("owned synthetic container or datastore volume identity changed")
    # Preserve configuration, including private synthetic environment, by digest only.
    configuration = {key: container[key] for key in ("Config", "HostConfig")}
    configuration["Mounts"] = sorted(container["Mounts"], key=lambda mount: mount["Destination"])
    return {"id": container["Id"], "volume": volumes[0]["Name"],
            "configuration_sha256": hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest(),
            "component_sha256": {key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
                                 for key, value in configuration.items()}}


def snapshot_path(path, prefix):
    if not re.fullmatch(r"qualification-\d+", prefix) or not re.fullmatch(re.escape(DATA + "/server/db/snapshots/" + prefix + "-") + r"[a-z0-9-]+", path):
        raise RuntimeError("snapshot is outside the exact owned synthetic snapshot contract")
    return path


def require_separate_datastores(containers):
    if (len(containers) != 5 or len({c["id"] for c in containers.values()}) != 5 or
            len({c["volume"] for c in containers.values()}) != 5):
        raise RuntimeError("five distinct owned containers and datastore volumes required")


class Qualification(cq.Qualification):
    def __init__(self, args):
        resolver = ipaddress.ip_address(args.resolver)
        if resolver.version != 4 or not resolver.is_private or resolver.is_loopback or resolver.is_unspecified:
            raise RuntimeError("resolver must be the verified private VM upstream")
        if args.guest_resolver_file != "/tmp/" + args.name + "/resolv.conf":
            raise RuntimeError("resolver file must belong to this exact disposable guest fixture")
        super().__init__(args)
        self.resolver = str(resolver)
        self.versions = {"k3d-" + args.name + suffix: BASELINE for suffix in SUFFIXES}
        self.node_uids = None
        self.containers = {}
        self.binary_paths = {}
        self.transitions = []
        self.snapshots = []
        self.l2 = l2.L2Qualification(self)
        self.helpers = set()
        self.read_retries = []

    def command(self, command, *, data=None, private=True, merge_stderr=False):
        # Synthetic kubeconfigs/tokens/restore output never enter persistent command logs.
        self.count += 1
        child = subprocess.Popen(command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = child.communicate(data)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        stderr = stderr or b""
        if not private:
            (self.work / (str(self.count) + ".log.gz")).write_bytes(gzip.compress(stdout + stderr))
        if child.returncode:
            if merge_stderr:
                stderr = stdout
            (self.work / "last-command-failure.json").write_text(json.dumps({
                "number": self.count, "classes": failure_classes(stderr), "stderr_bytes": len(stderr),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest()}, indent=2))
            raise CommandFailure(self.count, child.returncode, stderr)
        return stdout

    def kubectl(self, *args, json_output=True, data=None):
        deadline = time.monotonic() + 120
        while True:
            try:
                return super().kubectl(*args, json_output=json_output, data=data)
            except CommandFailure as error:
                if not args or args[0] != "get" or not read_transport_pending(error.stderr) or time.monotonic() >= deadline:
                    raise
                self.read_retries.append({"command_number": self.count, "classes": failure_classes(error.stderr),
                                          "stderr_sha256": hashlib.sha256(error.stderr).hexdigest()})
                self.persist()
                time.sleep(2)

    def wait_api(self, node):
        deadline = time.monotonic() + 600
        while True:
            self.inspect(node)
            try:
                # This exact synthetic health endpoint contains no configuration or credential dump.
                raw = self.command(["docker", "exec", node, "/bin/kubectl", "get", "--raw=/readyz?verbose", "--request-timeout=10s"], private=False)
                if b"[+]etcd ok" in raw and b"readyz check passed" in raw:
                    return
                raise RuntimeError("native server returned incomplete API/etcd readiness")
            except CommandFailure as error:
                if not startup_pending(error.stderr) or time.monotonic() >= deadline:
                    raise
            time.sleep(1)

    def dns_preflight(self):
        try:
            return super().dns_preflight()
        except CommandFailure as error:
            self.record_fixture_failure(error)
            raise

    def record_fixture_failure(self, error):
        # Later diagnostic reads may fail too; retain the triggering failure separately.
        if isinstance(error, CommandFailure):
            primary = {"number": error.number, "exit_code": error.code, "classes": failure_classes(error.stderr),
                       "stderr_bytes": len(error.stderr), "stderr_sha256": hashlib.sha256(error.stderr).hexdigest()}
        else:
            primary = {"type": type(error).__name__, "classes": ["acceptance-refused"],
                       "message_sha256": hashlib.sha256(str(error).encode()).hexdigest()}
        (self.work / "fixture-primary-failure.json").write_text(json.dumps(primary, indent=2))
        if {"access-refused", "trust-refused"}.intersection(primary["classes"]):
            return
        try:
            self.fixture_failure_status()
        except (CommandFailure, RuntimeError, KeyError, ValueError) as diagnostic_error:
            (self.work / "fixture-diagnostic-error.json").write_text(json.dumps({
                "type": type(diagnostic_error).__name__, "original_failure_preserved": True,
                "classes": failure_classes(diagnostic_error.stderr) if isinstance(diagnostic_error, CommandFailure) else []}))

    def fixture_failure_status(self):
        # Inspect only this guarded synthetic cluster; never persist Pod messages, env or termination text.
        self.identity()
        if self.l2.service_uid is not None:
            lease = self.l2.get_lease()
            l2.validate_lease(lease, self.l2.nodes)
            (self.work / "fixture-l2-lease.json").write_text(json.dumps({"uid": lease["metadata"]["uid"], **{
                key: lease["spec"][key] for key in ("holderIdentity", "leaseTransitions", "renewTime")}}, indent=2))
        nodes = []
        for node in self.containers:
            item = self.inspect(node)
            nodes.append({"name": node, "id": item["Id"], "restarts": item["RestartCount"],
                          "state": {key: item["State"][key] for key in
                                    ("Running", "Status", "OOMKilled", "ExitCode", "StartedAt", "FinishedAt")}})
            (self.work / "fixture-node-failure-status.json").write_text(json.dumps(nodes, indent=2))
        pods = self.kubectl("get", "pods", "-A")["items"]
        statuses = []
        for pod in pods:
            item = {"name": pod["metadata"]["name"], "namespace": pod["metadata"]["namespace"], "uid": pod["metadata"]["uid"],
                    "phase": pod["status"]["phase"], "node": pod["spec"].get("nodeName"),
                    "images": {c["name"]: c["image"] for c in pod["spec"]["containers"]}, "containers": []}
            for container in pod["status"].get("containerStatuses", []):
                terminated = container.get("lastState", {}).get("terminated", {})
                item["containers"].append({"name": container["name"], "ready": container["ready"],
                    "restarts": container["restartCount"], "state": sorted(container.get("state", {})),
                    "last_exit_code": terminated.get("exitCode"), "last_signal": terminated.get("signal"),
                    "last_reason": terminated.get("reason")})
                spec = next(c for c in pod["spec"]["containers"] if c["name"] == container["name"])
                if (item["namespace"] == "cilium-test-1" and container["restartCount"] and
                        container["name"] in ("echo-same-node", "echo-other-node") and
                        spec["image"] == ECHO_IMAGE and spec.get("env") == ECHO_ENV and not spec.get("envFrom") and
                        all(m.get("readOnly") and m["name"].startswith("kube-api-access-")
                            for m in spec.get("volumeMounts", []))):
                    # Only the pinned public HTTP fixture, without application data/config, may persist its error log.
                    raw = self.kubectl("logs", "-n", "cilium-test-1", item["name"], "-c", container["name"],
                                       "--previous", "--tail=80", json_output=False)
                    (self.work / ("synthetic-" + container["name"] + "-error.log.gz")).write_bytes(gzip.compress(raw))
            statuses.append(item)
        (self.work / "fixture-failure-status.json").write_text(json.dumps(statuses, indent=2))

    def select_client(self, version):
        self.args.kubectl = self.args.kubectl35 if minor(version) >= 35 else self.args.kubectl34
        data = json.loads(self.command([self.args.kubectl, "version", "--client", "-o", "json"]))
        client_minor = int(data["clientVersion"]["minor"].rstrip("+"))
        if any(abs(client_minor - minor(v)) > 1 for v in self.versions.values()):
            raise RuntimeError("kubectl client exceeds the live server/node version skew")

    def inspect(self, node, *, stopped=False):
        if node not in self.versions:
            raise RuntimeError("container is outside the exact five-node fixture")
        item = json.loads(self.command(["docker", "inspect", node]))[0]
        identity = container_identity(item, node, self.args.name)
        if self.containers and identity != self.containers.get(node):
            (self.work / "container-identity-mismatch.json").write_text(json.dumps({
                "node": node, "expected": self.containers.get(node), "actual": identity}, indent=2))
            raise RuntimeError("synthetic container identity or configuration changed")
        if stopped and (item["State"]["Running"] or item["State"]["Status"] != "exited"):
            raise RuntimeError("synthetic node must be fully stopped before datastore mutation")
        return item

    def identity(self):
        config = yaml.safe_load(Path(self.env["KUBECONFIG"]).read_text())
        nodes = self.kubectl("get", "nodes")
        uid = require_nodes(config, self.args.name, self.kubectl("get", "namespace", "kube-system"),
                            nodes, self.versions, self.node_uids)
        if self.cluster_uid is not None and uid != self.cluster_uid:
            raise RuntimeError("isolated cluster UID changed")
        self.cluster_uid = uid
        self.node_uids = {n["metadata"]["name"]: n["metadata"]["uid"] for n in nodes["items"]}

    def ready(self):
        self.kubectl("wait", "node", "--all", "--for=condition=Ready", "--timeout=600s", json_output=False)
        self.identity()
        for node in self.kubectl("get", "nodes")["items"]:
            conditions = {c["type"]: c["status"] for c in node["status"]["conditions"]}
            if conditions.get("Ready") != "True" or any(conditions.get(k) != "False" for k in ("MemoryPressure", "DiskPressure", "PIDPressure")):
                raise RuntimeError("synthetic node is not Ready without pressure")

    def bind_cpus(self):
        if self.command(["docker", "info", "--format", "{{.NCPU}}"]).strip() != b"8":
            raise RuntimeError("the declared synthetic CPU affinity requires an eight-CPU guest")
        bindings = {}
        for suffix, cpus in zip(SUFFIXES, ("0-1", "2-3", "4-5", "6", "7")):
            node = "k3d-" + self.args.name + suffix
            item = self.inspect(node)
            if item["HostConfig"]["CpusetCpus"] != "":
                raise RuntimeError("synthetic node already has unexpected CPU affinity")
            self.command(["docker", "update", "--cpuset-cpus=" + cpus, item["Id"]])
            item["HostConfig"]["CpusetCpus"] = cpus
            expected = container_identity(item, node, self.args.name)
            actual = container_identity(self.inspect(node), node, self.args.name)
            if actual != expected:
                raise RuntimeError("synthetic CPU binding changed undeclared container configuration")
            bindings[node] = {"cpus": cpus, **actual}
        (self.work / "guest-cpu-affinity.json").write_text(json.dumps(bindings, indent=2))

    def create(self):
        print(json.dumps({"phase": "create-owned-ha-cluster", "servers": 3, "agents": 2}), flush=True)
        daemon = self.command(["docker", "info", "--format", "{{.Name}}"]).decode().strip()
        if daemon != self.args.docker_server or self.command(["docker", "ps", "-aq"]).strip():
            raise RuntimeError("Docker daemon is not the expected empty owned VM")
        # Nested nodes share the guest kernel's per-user inotify instance limit.
        raw = self.command(["docker", "run", "--rm", "--name", self.args.name + "-kernel-capacity",
                            "--network=none", "--log-driver=none", "--privileged", "--entrypoint=/bin/sh", cq.K3S,
                            "-ec", "before=$(cat /proc/sys/fs/inotify/max_user_instances); "
                            "if test \"$before\" -lt 512; then sysctl -w fs.inotify.max_user_instances=512 >/dev/null; fi; "
                            "after=$(cat /proc/sys/fs/inotify/max_user_instances); printf '%s\\n%s\\n' \"$before\" \"$after\""])
        before, after = map(int, raw.split())
        if after != max(before, 512):
            raise RuntimeError("private guest inotify capacity was not established")
        (self.work / "guest-inotify-capacity.json").write_text(json.dumps({
            "before": before, "after": after, "production_change": False}))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        flags = ["--k3s-arg=" + flag + "@server:*" for flag in SERVER_FLAGS]
        for role in ("server:*", "agent:*"):
            flags.append("--k3s-arg=--resolv-conf=" + self.args.guest_resolver_file + "@" + role)
        self.creation_started = True
        self.command([self.args.k3d, "cluster", "create", self.args.name, "--servers=3", "--agents=2",
                      "--env=GOMAXPROCS=2@server:*", "--env=GOMAXPROCS=1@agent:*",
                      "--image=" + cq.K3S, "--api-port=127.0.0.1:" + str(port), "--subnet=" + l2.NETWORK,
                      "--volume=" + self.args.guest_resolver_file + ":/etc/qualification-resolv.conf:ro@all",
                      "--kubeconfig-update-default=false", "--kubeconfig-switch-context=false",
                      *[f.replace(self.args.guest_resolver_file, "/etc/qualification-resolv.conf") for f in flags]])
        self.bind_cpus()
        path = Path(self.env["KUBECONFIG"])
        with path.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(self.command([self.args.k3d, "kubeconfig", "get", self.args.name]))
        self.select_client(BASELINE)
        self.identity()
        self.containers = {node: container_identity(json.loads(self.command(["docker", "inspect", node]))[0], node, self.args.name)
                           for node in self.versions}
        require_separate_datastores(self.containers)
        for node in self.versions:
            item = self.inspect(node)
            concurrency = "2" if "-server-" in node else "1"
            if [value for value in item["Config"]["Env"] if value.startswith("GOMAXPROCS=")] != ["GOMAXPROCS=" + concurrency]:
                raise RuntimeError("synthetic node Go concurrency differs from its declared role")
            self.command(["docker", "exec", node, "test", "-d", "/sys/fs/cgroup/kubepods"])
            inherited = cq.inherited_resolver(self.command(["docker", "exec", node, "cat", "/etc/resolv.conf"]).decode())
            if inherited != self.resolver or self.command(["docker", "exec", node, "cat", "/etc/qualification-resolv.conf"]) != ("nameserver " + self.resolver + "\n").encode():
                raise RuntimeError("node resolver differs from the proven guest upstream")
            self.command(["docker", "exec", node, "nslookup", "example.com.", self.resolver])
        (self.work / "values.yaml").write_text(yaml.safe_dump({
            "operator": {"replicas": 1}, "kubeProxyReplacement": True,
            "cgroup": {"autoMount": {"enabled": False}, "hostRoot": "/sys/fs/cgroup"},
            "devices": ["eth0"], "l2announcements": {"enabled": True},
            "k8sServiceHost": "127.0.0.1", "k8sServicePort": 6444,
            "hubble": {"relay": {"enabled": True}, "ui": {"enabled": True}}}))
        baseline = self.work / "k3s-baseline"
        self.command(["docker", "cp", "-L", next(iter(self.versions)) + ":/bin/k3s", str(baseline)])
        baseline.chmod(0o700)
        self.binary_paths[BASELINE] = (baseline, hashlib.sha256(baseline.read_bytes()).hexdigest())
        for node in self.versions:
            if self.command(["docker", "exec", node, "sha256sum", "/bin/k3s"]).decode().split()[0] != self.binary_paths[BASELINE][1]:
                raise RuntimeError("baseline node binaries disagree")
        # Qualify the actual node-local operator path before longer CNI acceptance.
        for node in self.versions:
            if "-server-" in node:
                self.wait_api(node)

    def prepare_l2(self):
        network = json.loads(self.command(["docker", "network", "inspect", "k3d-" + self.args.name]))[0]
        allocated = {str(ipaddress.ip_interface(c["IPv4Address"]).ip) for c in network["Containers"].values()}
        if [c["Subnet"] for c in network["IPAM"]["Config"]] != [l2.NETWORK] or "172.31.240.10" in allocated or any(ipaddress.ip_address(x) in ipaddress.ip_network(l2.CIDR) for x in allocated):
            raise RuntimeError("synthetic caller/VIP collides with bridge allocation")
        self.l2_network_id = network["Id"]
        for node in self.versions:
            item = self.inspect(node)
            self.l2.nodes[node] = item["NetworkSettings"]["Networks"]["k3d-" + self.args.name]["MacAddress"].lower()
            self.kubectl("label", "node", node, l2.LABEL + "=true", "--overwrite", json_output=False)
        manifest = l2.manifest()
        manifest["items"][1]["spec"]["blocks"] = manifest["items"][1]["spec"].pop("cidrs")
        self.kubectl("apply", "-f", "-", data=json.dumps(manifest).encode(), json_output=False)
        self.l2.pool_uid = self.l2.get_pool()["metadata"]["uid"]
        self.l2.service_uid = self.l2.get_service()["metadata"]["uid"]
        l2.await_value(self.l2.get_service, l2.allocated_vip, "synthetic L2 allocation")
        self.kubectl("rollout", "status", "deployment/" + l2.NAME, "-n", l2.NAMESPACE, "--timeout=300s", json_output=False)
        self.command(["docker", "run", "--detach", "--name", self.l2.client, "--network", "k3d-" + self.args.name,
                      "--ip=172.31.240.10", "--cap-drop=ALL", "--cap-add=NET_RAW", "--read-only",
                      "--security-opt=no-new-privileges", "--log-driver=none", "--entrypoint=python3", l2.IMAGE,
                      "-B", "-c", "import signal;signal.pause()"])

    def cilium_ready(self):
        self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                      "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        pods = self.kubectl("get", "pods", "-n", "kube-system", "-l", "k8s-app=cilium")["items"]
        if len(pods) != 5 or any(not p["status"].get("containerStatuses") or not all(c["ready"] for c in p["status"]["containerStatuses"]) for p in pods):
            raise RuntimeError("five ready native Cilium agents required")
        return pods

    def app_probe(self):
        try:
            self.cilium_ready()
            self.kubectl("rollout", "status", "deployment/" + l2.NAME, "-n", l2.NAMESPACE, "--timeout=300s", json_output=False)
            lease = self.l2.get_lease()
            return self.l2_probe(lease)
        except RuntimeError as error:
            self.record_fixture_failure(error)
            raise

    def l2_probe(self, lease):
        l2.validate_lease(lease, self.l2.nodes)
        holder = lease["spec"]["holderIdentity"]
        item = self.inspect(holder)
        networks = item["NetworkSettings"]["Networks"]
        network = networks.get("k3d-" + self.args.name, {})
        mac = network.get("MacAddress")
        if (not item["State"]["Running"] or set(networks) != {"k3d-" + self.args.name} or
                network.get("NetworkID") != self.l2_network_id or
                not re.fullmatch(r"[a-f0-9]{64}", network.get("EndpointID", "")) or
                not isinstance(mac, str) or not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac) or
                mac == "00:00:00:00:00:00"):
            raise RuntimeError("owned L2 holder network identity is incomplete or changed")
        native = self.command(["docker", "exec", item["Id"], "cat", "/sys/class/net/eth0/address"]).decode().strip()
        if native != mac:
            raise RuntimeError("owned L2 holder Docker and native interface MAC disagree")
        # Docker may recreate the endpoint/MAC while preserving the same stopped container.
        self.l2.nodes[holder] = mac
        (self.work / ("l2-node-network-" + str(self.count) + ".json")).write_text(json.dumps({
            "holder": holder, "container_id": item["Id"], "network_id": self.l2_network_id,
            "endpoint_id": network["EndpointID"], "mac": mac, "native_mac_verified": True}, indent=2))
        return self.l2.external(lease)

    def checkpoint(self, version, phase):
        self.ready()
        print(json.dumps({"phase": phase, "k3s": version, "cilium": CILIUM}), flush=True)
        pods = self.cilium_ready()
        for pod in pods:
            self.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--", "test", "-d", "/sys/fs/cgroup/kubepods", json_output=False)
            raw = self.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--", "cilium-dbg", "version", json_output=False)
            if not re.search(rb"\b" + re.escape(CILIUM.encode()) + rb"\b", raw):
                raise RuntimeError("native Cilium version differs from fixed qualification version")
        self.dns_preflight()
        path = self.work / (phase + ".xml")
        with self.hubble_forward() as address:
            try:
                self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                              "connectivity", "test", "--test=" + cq.TEST_FILTER, "--ip-families=ipv4",
                              "--flow-validation=strict", "--hubble=true", "--hubble-server=" + address,
                              "--collect-sysdump-on-failure=false", "--junit-file=" + str(path)], private=False)
            except CommandFailure as error:
                self.record_fixture_failure(error)
                raise
        result = cq.require_results(path)
        l2.validate_pool(self.l2.get_pool(), self.l2.pool_uid, migrated=True)
        l2.validate_service(self.l2.get_service(), self.l2.service_uid)
        first = self.l2.get_lease()
        before = self.app_probe()
        holder = first["spec"]["holderIdentity"]
        self.kubectl("label", "node", holder, l2.LABEL + "=false", "--overwrite", json_output=False)
        try:
            second = l2.await_value(self.l2.get_lease, lambda item: item["spec"].get("holderIdentity") in self.l2.nodes and item["spec"]["holderIdentity"] != holder and item["spec"].get("leaseTransitions", 0) > first["spec"]["leaseTransitions"], "synthetic L2 lease transfer")
            l2.validate_lease(second, self.l2.nodes, previous=first)
            after = self.l2_probe(second)
        finally:
            self.kubectl("label", "node", holder, l2.LABEL + "=true", "--overwrite", json_output=False)
        self.stages.append({"phase": phase, "k3s": version, "cilium": CILIUM, "cluster_uid": self.cluster_uid,
                            "node_uids": self.node_uids, "pool_uid": self.l2.pool_uid, "service_uid": self.l2.service_uid,
                            "node_runtime": {n["metadata"]["name"]: {key: n["status"]["nodeInfo"][key] for key in
                                ("containerRuntimeVersion", "kernelVersion", "osImage", "architecture", "kubeletVersion")}
                                for n in self.kubectl("get", "nodes")["items"]},
                            "lease_uid": second["metadata"]["uid"], "before": before, "after": after, **result})
        self.persist()
        print(json.dumps({"accepted_phase": phase, "executed_cases": result["executed_cases"]}), flush=True)

    def persist(self):
        (self.work / "progress.json").write_text(json.dumps({"stages": self.stages, "transitions": self.transitions,
            "snapshots": self.snapshots, "containers": self.containers, "read_retries": self.read_retries, "production_change": False}, indent=2))

    def binary(self, version):
        if version not in self.binary_paths:
            path = self.work / (version + "-k3s-arm64")
            with urllib.request.urlopen("https://github.com/k3s-io/k3s/releases/download/" + version + "/k3s-arm64", timeout=120) as response:
                raw = response.read()
            if hashlib.sha256(raw).hexdigest() != BINARIES[version]:
                raise RuntimeError("official K3s binary checksum mismatch")
            path.write_bytes(raw)
            path.chmod(0o700)
            self.binary_paths[version] = (path, BINARIES[version])
        return self.binary_paths[version]

    def replace_binary(self, node, version, *, stopped=False):
        item = self.inspect(node, stopped=stopped)
        path, digest = self.binary(version)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("owned binary changed after verification")
        destination = "/bin/k3s" if stopped else "/bin/k3s.next"
        self.command(["docker", "cp", str(path), item["Id"] + ":" + destination])
        if not stopped:
            self.command(["docker", "exec", item["Id"], "sh", "-ec", "test \"$(sha256sum /bin/k3s.next | cut -d ' ' -f 1)\" = \"$1\"; chmod 755 /bin/k3s.next; mv /bin/k3s.next /bin/k3s", "qualification", digest])

    def snapshot(self, previous, target):
        self.identity()
        server = next(iter(self.versions))
        self.inspect(server)
        prefix = "qualification-" + str(len(self.snapshots))
        marker = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": MARKER, "namespace": "default"}, "data": {"value": prefix}}
        self.kubectl("apply", "-f", "-", data=json.dumps(marker).encode(), json_output=False)
        before = self.kubectl("get", "configmap", MARKER)
        self.command(["docker", "exec", server, "test", "-s", DATA + "/server/token"])
        self.command(["docker", "exec", server, "/bin/k3s", "etcd-snapshot", "save", "--name=" + prefix])
        paths = self.command(["docker", "exec", server, "find", DATA + "/server/db/snapshots", "-maxdepth", "1", "-type", "f", "-name", prefix + "-*"]).decode().splitlines()
        if len(paths) != 1:
            raise RuntimeError("exactly one owned on-demand snapshot required")
        path = snapshot_path(paths[0], prefix)
        digest = self.command(["docker", "exec", server, "sha256sum", path]).decode().split()[0]
        size = int(self.command(["docker", "exec", server, "stat", "-c", "%s", path]))
        if size <= 0 or not re.fullmatch("[a-f0-9]{64}", digest):
            raise RuntimeError("snapshot size/digest evidence missing")
        marker["data"]["value"] = prefix + "-after-snapshot"
        self.kubectl("apply", "-f", "-", data=json.dumps(marker).encode(), json_output=False)
        result = {"previous": previous, "target": target, "prefix": prefix, "path": path, "sha256": digest, "bytes": size,
                  "marker_uid": before["metadata"]["uid"], "marker_data": before["data"]}
        self.snapshots.append(result)
        self.persist()
        return result

    def forward(self, previous, target, phase):
        require_transition(previous, target)
        print(json.dumps({"phase": phase, "previous": previous, "target": target}), flush=True)
        self.binary(target)
        self.select_client(target)
        for node in self.versions:
            self.ready()
            self.replace_binary(node, target)
            item = self.inspect(node)
            self.command(["docker", "stop", "--time=30", item["Id"]])
            self.inspect(node, stopped=True)
            surviving = []
            quorum_write = None
            if "-server-" in node:
                for peer in [n for n in self.versions if "-server-" in n and n != node]:
                    self.inspect(peer)
                    self.wait_api(peer)
                    raw = self.command(["docker", "exec", peer, "/bin/kubectl", "get", "--raw=/readyz?verbose"])
                    if b"[+]etcd ok" not in raw or b"readyz check passed" not in raw:
                        raise RuntimeError("surviving server API/etcd readiness failed")
                    surviving.append(peer)
                write = json.loads(self.command(["docker", "exec", surviving[0], "/bin/kubectl", "patch", "configmap", MARKER,
                    "--type=merge", "-p", json.dumps({"data": {"quorum": phase + ":" + node}}), "-o", "json"]))
                if write["data"].get("quorum") != phase + ":" + node:
                    raise RuntimeError("surviving etcd quorum did not accept the synthetic write")
                quorum_write = {"uid": write["metadata"]["uid"], "resource_version": write["metadata"]["resourceVersion"]}
            self.command(["docker", "start", item["Id"]])
            if "-server-" in node:
                self.wait_api(node)
            self.versions[node] = target
            l2.await_value(lambda: self.kubectl("get", "node", node), lambda n: n["status"]["nodeInfo"]["kubeletVersion"] == target and any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"]), "upgraded exact node version and readiness", seconds=600)
            self.ready()
            raw = self.command(["docker", "exec", node, "/bin/k3s", "--version"])
            if target.encode() not in raw or self.command(["docker", "exec", node, "sha256sum", "/bin/k3s"]).decode().split()[0] != self.binary(target)[1]:
                raise RuntimeError("running native binary version/digest mismatch")
            probe = self.app_probe()
            self.transitions.append({"phase": phase, "node": node, "target": target, "surviving_ready_apis": surviving,
                                     "quorum_write": quorum_write, "binary_sha256": self.binary(target)[1], "application": probe})
            self.persist()
            print(json.dumps({"upgraded_node": node, "target": target, "surviving_ready_apis": len(surviving)}), flush=True)
        self.checkpoint(target, phase)

    def helper(self, node, command, *, version=None, restore=False):
        for name in self.versions:
            self.inspect(name, stopped=True)
        name = self.args.name + "-helper"
        if self.helpers:
            raise RuntimeError("a previous synthetic datastore helper remains")
        network = "k3d-" + self.args.name if restore else "none"
        args = ["docker", "create", "--name", name, "--hostname", node, "--network", network,
                "--log-driver=none", "--volumes-from", self.containers[node]["id"],
                "--entrypoint", "/bin/k3s" if restore else "/bin/sh"]
        if restore:
            args.append("--privileged")
        helper_id = self.command([*args, cq.K3S, *command]).decode().strip()
        self.helpers.add(helper_id)
        try:
            if version is not None:
                path, _ = self.binary(version)
                self.command(["docker", "cp", str(path), helper_id + ":/bin/k3s"])
            actual = json.loads(self.command(["docker", "inspect", helper_id]))[0]
            volume = [m for m in actual["Mounts"] if m["Destination"] == DATA]
            if len(volume) != 1 or volume[0].get("Name") != self.containers[node]["volume"] or actual["HostConfig"]["LogConfig"]["Type"] != "none" or actual.get("LogPath"):
                raise RuntimeError("synthetic helper datastore/logging identity changed")
            raw = self.command(["docker", "start", "--attach", helper_id], merge_stderr=True)
            finished = json.loads(self.command(["docker", "inspect", helper_id]))[0]
            if finished["State"]["Running"] or finished["State"]["ExitCode"] != 0:
                raise RuntimeError("synthetic datastore helper failed")
            if restore and b"Managed etcd cluster membership has been reset" not in raw:
                raise RuntimeError("native matching-version datastore restore did not report success")
        finally:
            self.command(["docker", "rm", "--force", helper_id])
            self.helpers.remove(helper_id)

    def rollback(self, snapshot):
        previous = snapshot["previous"]
        print(json.dumps({"phase": "matching-version-snapshot-restore", "target": previous}), flush=True)
        self.ready()
        server = next(iter(self.versions))
        path = snapshot_path(snapshot["path"], snapshot["prefix"])
        digest = self.command(["docker", "exec", server, "sha256sum", path]).decode().split()[0]
        if digest != snapshot["sha256"]:
            raise RuntimeError("snapshot changed before restoration")
        self.kubectl("drain", *self.versions, "--ignore-daemonsets", "--delete-emptydir-data", "--timeout=600s", json_output=False)
        for node in self.versions:
            item = self.inspect(node)
            self.command(["docker", "stop", "--time=30", item["Id"]])
        for node in self.versions:
            self.replace_binary(node, previous, stopped=True)
        self.helper(server, ["server", "--node-name=" + server, *SERVER_FLAGS, "--cluster-reset",
                            "--cluster-reset-restore-path=" + path, "--token-file=" + DATA + "/server/token"], version=previous, restore=True)
        for peer in [n for n in self.versions if "-server-" in n and n != server]:
            self.helper(peer, ["-ec", "test -d " + DATA + "/server/db; rm -rf " + DATA + "/server/db; test ! -e " + DATA + "/server/db"])
        self.versions = dict.fromkeys(self.versions, previous)
        self.select_client(previous)
        for node in self.versions:
            item = self.inspect(node, stopped=True)
            self.command(["docker", "start", item["Id"]])
            if "-server-" in node:
                self.wait_api(node)
            if self.command(["docker", "exec", node, "sha256sum", "/bin/k3s"]).decode().split()[0] != self.binary(previous)[1]:
                raise RuntimeError("restored native binary digest mismatch")
        l2.await_value(lambda: self.kubectl("get", "configmap", MARKER), lambda m: m["data"] == snapshot["marker_data"] and m["metadata"]["uid"] == snapshot["marker_uid"], "restored pre-snapshot marker UID and exact data", seconds=600)
        self.ready()
        if any(n["spec"].get("unschedulable") for n in self.kubectl("get", "nodes")["items"]):
            raise RuntimeError("snapshot did not restore the uncordoned node state")
        snapshot["matching_version_restore_accepted"] = True
        self.checkpoint(previous, "rollback-" + snapshot["target"])

    def require_cli(self):
        raw = self.command([self.args.cilium, "version", "--client"])
        if not re.search(rb"(?m)^cilium-cli: " + re.escape(CLI_VERSION.encode()) + rb"(?:\s|$)", raw):
            raise RuntimeError("the HA fixture requires its pinned maintained Cilium CLI")

    def run(self):
        self.require_cli()
        self.create()
        self.install(CILIUM)
        self.dns_preflight()
        self.ready()
        self.prepare_l2()
        self.checkpoint(BASELINE, "baseline")
        previous = BASELINE
        for version in BINARIES:
            snapshot = self.snapshot(previous, version)
            self.forward(previous, version, "upgrade-" + version)
            self.rollback(snapshot)
            self.forward(previous, version, "return-" + version)
            previous = version
        if len(self.stages) != 13 or len(self.transitions) != 40 or not all(s.get("matching_version_restore_accepted") for s in self.snapshots):
            raise RuntimeError("K3s upgrade/restore qualification is incomplete")
        return {"k3s_ha_qualification_accepted": True, "stages": self.stages, "transitions": self.transitions,
                "snapshots": self.snapshots, "read_retries": self.read_retries, "production_change": False, "production_host_security_hardware_unqualified": True}

    def cleanup(self):
        for helper_id in list(self.helpers):
            self.command(["docker", "rm", "--force", helper_id])
            self.helpers.remove(helper_id)
        found = self.command(["docker", "ps", "-aq", "--filter", "name=^/" + self.l2.client + "$"]).strip()
        if found:
            self.command(["docker", "rm", "--force", self.l2.client])
        if self.creation_started:
            self.command([self.args.k3d, "cluster", "delete", self.args.name])
            if self.command(["docker", "ps", "-aq"]).strip():
                raise RuntimeError("owned qualification VM still has containers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("name", "docker-host", "docker-server", "k3d", "cilium", "kubectl34", "kubectl35", "resolver", "guest-resolver-file"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    args.kubectl = args.kubectl34
    qualification = Qualification(args)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cq.interrupted)
    try:
        result = qualification.run()
        (qualification.work / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == "__main__":
    main()
