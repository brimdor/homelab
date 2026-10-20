#!/usr/bin/env python3
"""Qualify adjacent Cilium transitions in a fresh, explicitly isolated Docker VM."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import time
import urllib.request
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import yaml


CHARTS = {
    "1.15.1": "f5e9ba3b7a98fb1d391ff98b3af0bb711f61aa2d585b24554c1b2946fe5d5ea1",
    "1.15.19": "fd1c33af55d62c0954fe302d603295cf6aead24b715e92ee75b7be06c5a8b591",
    "1.16.19": "91672864f438a2a45fbfac65b0f8b42a8dd76e9e712cabe602311c34f290f7a3",
    "1.17.18": "6a9a929a4bfa7a7cbb1fbb429514dde61fdf70622aac3adfd0bed8a4b09e34e9",
    "1.18.15": "8991506b1620a8c1751b66338ebd7d5e51413917736f2e1c9b957fc548eab127",
    "1.19.9": "b54b1bae91bd87bcf9f19672e7f23304156697596332e6c64a53b62143b2b251",
    "1.20.3": "0805a5273118c436c9772bb9566d87ec558d8b25cc2ce5dc32918ecdd36f2c7c",
}
K3S = "docker.io/rancher/k3s:v1.33.6-k3s1@sha256:d7119ab9e0054692a86a8eda454f2d3370dafc1c3a96b3ace5c5599f0c1e9f15"
TESTS = ("no-policies", "all-ingress-deny", "all-egress-deny", "client-egress-l7")
TEST_FILTER = "^(" + "|".join(TESTS) + ")/"
PRODUCTION_UID = "7ff226e0-565a-4610-8a3e-97e7e87355a3"


def inherited_resolver(text):
    match = re.search(r"(?m)^# ExtServers: \[host\(([0-9.]+)\)\]$", text)
    if not match:
        raise RuntimeError("owned Docker node has no single inherited IPv4 resolver")
    address = ipaddress.ip_address(match[1])
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
        raise RuntimeError("owned Docker resolver is outside the reviewed private upstream contract")
    return str(address)


def require_root(root, name, docker_host):
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise RuntimeError("qualification root must be an absolute nonsymlink directory")
    meta = root.stat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
        raise RuntimeError("qualification root must be private and owned")
    if root.is_relative_to(Path.cwd()) or Path.cwd().is_relative_to(root):
        raise RuntimeError("qualification root overlaps the source checkout")
    if not re.fullmatch(r"qualification-[a-z0-9]{8}", name):
        raise RuntimeError("qualification name must have a unique explicit prefix")
    if not docker_host.startswith("unix://"):
        raise RuntimeError("qualification requires a private local Docker socket")
    socket = Path(docker_host.removeprefix("unix://"))
    if not socket.resolve().is_relative_to(root) or not stat.S_ISSOCK(socket.stat().st_mode):
        raise RuntimeError("Docker socket is outside the owned qualification root")


def require_endpoint(config, name):
    context = "k3d-" + name
    if config.get("current-context") != context or len(config.get("clusters", [])) != 1:
        raise RuntimeError("unexpected isolated kubeconfig context")
    server = urlparse(config["clusters"][0]["cluster"]["server"])
    if server.scheme != "https" or server.hostname != "127.0.0.1" or not server.port:
        raise RuntimeError("isolated Kubernetes API must bind IPv4 loopback")


def require_cluster(config, name, namespace, nodes):
    require_endpoint(config, name)
    uid = namespace["metadata"]["uid"]
    expected = {"k3d-" + name + suffix for suffix in ("-server-0", "-agent-0", "-agent-1")}
    if not uid or uid == PRODUCTION_UID or {n["metadata"]["name"] for n in nodes["items"]} != expected:
        raise RuntimeError("isolated cluster identity does not match the owned three nodes")
    if any(n["status"]["nodeInfo"]["kubeletVersion"] != "v1.33.6+k3s1" for n in nodes["items"]):
        raise RuntimeError("isolated Kubernetes version changed")
    return uid


def require_results(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(list(c.iter("failure")) or list(c.iter("error")) for c in cases):
        raise RuntimeError("connectivity suite failed or produced no cases")
    executed = [c for c in cases if c.find("skipped") is None]
    names = [c.get("classname", "") + "/" + c.get("name", "") for c in executed]
    if any(not any(test in name for name in names) for test in TESTS):
        raise RuntimeError("a required connectivity scenario was skipped or missing")
    return {"executed_cases": len(executed), "skipped_cases": len(cases) - len(executed), "required_tests": list(TESTS)}


class Qualification:
    def __init__(self, args):
        require_root(args.work_dir, args.name, args.docker_host)
        self.args = args
        self.work = args.work_dir / "qualification"
        self.work.mkdir(mode=0o700)
        self.env = {**os.environ, "DOCKER_HOST": args.docker_host, "KUBECONFIG": str(self.work / "kubeconfig")}
        self.context = "k3d-" + args.name
        self.cluster_uid = None
        self.stages = []
        self.count = 0
        self.creation_started = False
        self.resolver = None

    def command(self, command, *, data=None, private=False):
        self.count += 1
        child = subprocess.Popen(command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
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
                stream.close()
        if not private:
            (self.work / (str(self.count) + ".log.gz")).write_bytes(gzip.compress(stdout + stderr))
        if child.returncode:
            raise RuntimeError("qualification command " + str(self.count) + " exited " + str(child.returncode))
        return stdout

    def kubectl(self, *args, json_output=True, data=None):
        command = [self.args.kubectl, "--cache-dir", str(self.work / "cache/kubectl"), "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                   "--request-timeout=30s", *args]
        raw = self.command(command + (["-o", "json"] if json_output else []), data=data)
        return json.loads(raw) if json_output else raw

    def helm(self, *args):
        return self.command(["helm", "--kubeconfig", self.env["KUBECONFIG"], "--kube-context", self.context, *args])

    def identity(self):
        config = yaml.safe_load(Path(self.env["KUBECONFIG"]).read_text())
        require_endpoint(config, self.args.name)
        uid = require_cluster(config, self.args.name, self.kubectl("get", "namespace", "kube-system"),
                              self.kubectl("get", "nodes"))
        if self.cluster_uid is not None and uid != self.cluster_uid:
            raise RuntimeError("isolated cluster UID changed")
        self.cluster_uid = uid

    def create(self):
        name = self.command(["docker", "info", "--format", "{{.Name}}"], private=True).decode().strip()
        if name != self.args.docker_server or self.command(["docker", "ps", "-aq"], private=True).strip():
            raise RuntimeError("Docker daemon is not the expected empty owned VM")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            api_port = listener.getsockname()[1]
        self.creation_started = True
        self.command([self.args.k3d, "cluster", "create", self.args.name, "--servers=1", "--agents=2",
                      "--image=" + K3S, "--api-port=127.0.0.1:" + str(api_port), "--subnet=172.31.240.0/24",
                      "--kubeconfig-update-default=false", "--kubeconfig-switch-context=false",
                      "--k3s-arg=--flannel-backend=none@server:*", "--k3s-arg=--disable-network-policy@server:*",
                      "--k3s-arg=--disable-kube-proxy@server:*",
                      "--k3s-arg=--disable=traefik@server:*", "--k3s-arg=--disable=servicelb@server:*",
                      "--k3s-arg=--disable=local-storage@server:*", "--k3s-arg=--disable=metrics-server@server:*"])
        raw = self.command([self.args.k3d, "kubeconfig", "get", self.args.name], private=True)
        path = Path(self.env["KUBECONFIG"])
        with path.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        self.identity()
        for suffix in ("-server-0", "-agent-0", "-agent-1"):
            self.command(["docker", "exec", "k3d-" + self.args.name + suffix,
                          "test", "-d", "/sys/fs/cgroup/kubepods"])
        resolvers = set()
        for suffix in ("-server-0", "-agent-0", "-agent-1"):
            node = "k3d-" + self.args.name + suffix
            resolver = inherited_resolver(self.command(["docker", "exec", node, "cat", "/etc/resolv.conf"]).decode())
            self.command(["docker", "exec", node, "nslookup", "example.com.", resolver])
            resolvers.add(resolver)
        if len(resolvers) != 1:
            raise RuntimeError("owned nodes disagree on their inherited DNS upstream")
        self.resolver = resolvers.pop()
        self.identity()
        config = self.kubectl("get", "configmap", "coredns", "-n", "kube-system")
        corefile = config["data"]["Corefile"]
        if corefile.count("forward . /etc/resolv.conf") != 1:
            raise RuntimeError("unexpected synthetic CoreDNS forwarding contract")
        # k3d's gateway-DNAT resolver timed out from Cilium pods; retain its actual inherited upstream.
        patch = [{"op": "test", "path": "/data/Corefile", "value": corefile},
                 {"op": "replace", "path": "/data/Corefile", "value": corefile.replace(
                     "forward . /etc/resolv.conf", "forward . " + self.resolver)}]
        self.kubectl("patch", "configmap", "coredns", "-n", "kube-system", "--type=json", "-p", json.dumps(patch))
        values = {"operator": {"replicas": 1}, "kubeProxyReplacement": True,
                  # Nested container automount selected the agent's empty subtree instead of the node's workloads.
                  "cgroup": {"autoMount": {"enabled": False}, "hostRoot": "/sys/fs/cgroup"},
                  "l2announcements": {"enabled": True}, "k8sServiceHost": "127.0.0.1", "k8sServicePort": 6444,
                  "upgradeCompatibility": "1.15", "hubble": {"relay": {"enabled": True}, "ui": {"enabled": True}}}
        (self.work / "values.yaml").write_text(yaml.safe_dump(values))

    def install(self, version):
        self.identity()
        path = self.work / ("cilium-" + version + ".tgz")
        if not path.exists():
            with urllib.request.urlopen("https://helm.cilium.io/" + path.name, timeout=60) as response:
                raw = response.read()
            if hashlib.sha256(raw).hexdigest() != CHARTS[version]:
                raise RuntimeError("official Cilium chart digest mismatch")
            path.write_bytes(raw)
        self.helm("upgrade", "--install", "cilium", str(path), "--namespace", "kube-system", "--reset-values",
                  "--values", str(self.work / "values.yaml"))

    @contextmanager
    def hubble_forward(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        path = self.work / "hubble-forward.log"
        with path.open("wb") as output:
            child = subprocess.Popen([self.args.kubectl, "--cache-dir", str(self.work / "cache/kubectl"),
                                      "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                                      "--request-timeout=30s", "-n", "kube-system", "port-forward",
                                      "service/hubble-relay", str(port) + ":80", "--address=127.0.0.1"],
                                     env=self.env, stdin=subprocess.DEVNULL, stdout=output,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                while b"Forwarding from 127.0.0.1:" + str(port).encode() + b" ->" not in path.read_bytes():
                    if child.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("owned Hubble port-forward did not bind")
                    time.sleep(0.1)
                if child.poll() is not None:
                    raise RuntimeError("owned Hubble port-forward exited")
                yield "127.0.0.1:" + str(port)
                if child.poll() is not None:
                    raise RuntimeError("owned Hubble port-forward exited during validation")
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                (self.work / "hubble-forward.log.gz").write_bytes(gzip.compress(path.read_bytes()))
                path.unlink()

    def validate(self, version, phase):
        self.identity()
        print(json.dumps({"phase": phase, "version": version}), flush=True)
        self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                      "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        pods = self.kubectl("get", "pods", "-n", "kube-system", "-l", "k8s-app=cilium")["items"]
        if len(pods) != 3 or any(not all(c["ready"] for c in p["status"]["containerStatuses"]) for p in pods):
            raise RuntimeError("expected three ready Cilium agents")
        for pod in pods:
            self.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--",
                         "test", "-d", "/sys/fs/cgroup/kubepods", json_output=False)
            raw = self.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--",
                               "cilium-dbg", "version", json_output=False)
            if not re.search(rb"\b" + re.escape(version.encode()) + rb"\b", raw):
                raise RuntimeError("native agent version differs from selected stage")
        path = self.work / (phase + ".xml")
        with self.hubble_forward() as address:
            self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                          "connectivity", "test", "--test=" + TEST_FILTER, "--ip-families=ipv4",
                          "--flow-validation=strict", "--hubble=true", "--hubble-server=" + address,
                          "--collect-sysdump-on-failure=false", "--junit-file=" + str(path)])
        results = require_results(path)
        self.stages.append({"phase": phase, "version": version, "cluster_uid": self.cluster_uid,
                            "agent_uids": [p["metadata"]["uid"] for p in pods], **results})
        (self.work / "progress.json").write_text(json.dumps(self.stages, indent=2))

    def dns_preflight(self):
        self.identity()
        self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                      "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        # Deploy only the official fixture; zero selected cases provide no connectivity acceptance.
        with self.hubble_forward() as address:
            self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                          "connectivity", "test", "--test=^$", "--ip-families=ipv4",
                          "--flow-validation=strict", "--hubble=true", "--hubble-server=" + address,
                          "--collect-sysdump-on-failure=false"])
        pods = self.kubectl("get", "pods", "-n", "cilium-test-1")["items"]
        clients = [p for p in pods if p["metadata"]["name"].startswith("client")]
        if len(clients) != 3 or any(not all(c["ready"] for c in p["status"]["containerStatuses"]) for p in clients):
            raise RuntimeError("expected three ready synthetic DNS clients")
        for pod in clients:
            for resolver in ([], [self.resolver]):
                raw = self.kubectl("exec", "-n", "cilium-test-1", pod["metadata"]["name"],
                                   "-c", pod["spec"]["containers"][0]["name"], "--",
                                   "nslookup", "one.one.one.one.", *resolver, json_output=False)
                if not all(re.search(rb"(?m)^Address:\s+" + re.escape(ip) + rb"\s*$", raw)
                           for ip in (b"1.1.1.1", b"1.0.0.1")):
                    raise RuntimeError("synthetic pod-origin external DNS prerequisite failed")
        (self.work / "dns-preflight.json").write_text(json.dumps({
            "client_uids": [p["metadata"]["uid"] for p in clients], "inherited_upstream": self.resolver,
            "core_dns_and_direct_upstream_passed": True, "connectivity_acceptance": False}, indent=2))

    def run(self):
        self.create()
        self.install("1.15.1")
        self.dns_preflight()
        self.validate("1.15.1", "baseline")
        self.install("1.15.19")
        self.validate("1.15.19", "patched-baseline")
        previous = "1.15.19"
        for version in ("1.16.19", "1.17.18", "1.18.15", "1.19.9", "1.20.3"):
            history = json.loads(self.helm("history", "cilium", "-n", "kube-system", "-o", "json"))
            revision = next(x["revision"] for x in history if x["status"] == "deployed")
            self.install(version)
            self.validate(version, "upgrade-" + version)
            self.helm("rollback", "cilium", str(revision), "-n", "kube-system")
            self.validate(previous, "rollback-" + previous)
            self.install(version)
            self.validate(version, "return-" + version)
            previous = version
        return {"connectivity_stages_accepted": True, "stages": self.stages,
                "production_change": False, "test_dns_inherited_upstream": self.resolver,
                "production_hardware_kernel_gpu_l2_unqualified": True}


def interrupted(_number, _frame):
    raise RuntimeError("isolated qualification interrupted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("name", "docker-host", "docker-server", "k3d", "cilium", "kubectl"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    qualification = Qualification(args)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    try:
        result = qualification.run()
        (qualification.work / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        # The caller owns the isolated VM, its images and final scratch cleanup.
        if qualification.creation_started:
            qualification.command([args.k3d, "cluster", "delete", args.name])
            if qualification.command(["docker", "ps", "-aq"], private=True).strip():
                raise RuntimeError("owned qualification VM still has containers")


if __name__ == "__main__":
    main()
