#!/usr/bin/env python3
"""Qualify adjacent Cilium transitions in a fresh, explicitly isolated Docker VM."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
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
}
K3S = "docker.io/rancher/k3s:v1.33.6-k3s1@sha256:d7119ab9e0054692a86a8eda454f2d3370dafc1c3a96b3ace5c5599f0c1e9f15"
TESTS = ("no-policies", "all-ingress-deny", "all-egress-deny", "client-egress-l7")
PRODUCTION_UID = "7ff226e0-565a-4610-8a3e-97e7e87355a3"


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


def require_cluster(config, name, namespace, nodes):
    context = "k3d-" + name
    if config.get("current-context") != context or len(config.get("clusters", [])) != 1:
        raise RuntimeError("unexpected isolated kubeconfig context")
    server = urlparse(config["clusters"][0]["cluster"]["server"])
    if server.scheme != "https" or server.hostname != "127.0.0.1" or not server.port:
        raise RuntimeError("isolated Kubernetes API must bind IPv4 loopback")
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
        if not private:
            (self.work / (str(self.count) + ".log.gz")).write_bytes(gzip.compress(stdout + stderr))
        if child.returncode:
            raise RuntimeError("qualification command " + str(self.count) + " exited " + str(child.returncode))
        return stdout

    def kubectl(self, *args, json_output=True, data=None):
        command = [self.args.kubectl, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                   "--request-timeout=30s", *args]
        raw = self.command(command + (["-o", "json"] if json_output else []), data=data)
        return json.loads(raw) if json_output else raw

    def helm(self, *args):
        return self.command(["helm", "--kubeconfig", self.env["KUBECONFIG"], "--kube-context", self.context, *args])

    def identity(self):
        config = yaml.safe_load(Path(self.env["KUBECONFIG"]).read_text())
        uid = require_cluster(config, self.args.name, self.kubectl("get", "namespace", "kube-system"),
                              self.kubectl("get", "nodes"))
        if self.cluster_uid is not None and uid != self.cluster_uid:
            raise RuntimeError("isolated cluster UID changed")
        self.cluster_uid = uid

    def create(self):
        name = self.command(["docker", "info", "--format", "{{.Name}}"], private=True).decode().strip()
        if name != self.args.docker_server or self.command(["docker", "ps", "-aq"], private=True).strip():
            raise RuntimeError("Docker daemon is not the expected empty owned VM")
        self.creation_started = True
        self.command([self.args.k3d, "cluster", "create", self.args.name, "--servers=1", "--agents=2",
                      "--image=" + K3S, "--api-port=127.0.0.1:0", "--subnet=172.31.240.0/24",
                      "--kubeconfig-update-default=false", "--kubeconfig-switch-context=false",
                      "--k3s-arg=--flannel-backend=none@server:*", "--k3s-arg=--disable-network-policy@server:*",
                      "--k3s-arg=--disable-kube-proxy@server:*;@agent:*",
                      "--k3s-arg=--disable=traefik@server:*", "--k3s-arg=--disable=servicelb@server:*",
                      "--k3s-arg=--disable=local-storage@server:*", "--k3s-arg=--disable=metrics-server@server:*"])
        raw = self.command([self.args.k3d, "kubeconfig", "get", self.args.name], private=True)
        path = Path(self.env["KUBECONFIG"])
        with path.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        self.identity()
        values = {"operator": {"replicas": 1}, "kubeProxyReplacement": True,
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

    def validate(self, version, phase):
        self.identity()
        print(json.dumps({"phase": phase, "version": version}), flush=True)
        self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                      "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        pods = self.kubectl("get", "pods", "-n", "kube-system", "-l", "k8s-app=cilium")["items"]
        if len(pods) != 3 or any(not all(c["ready"] for c in p["status"]["containerStatuses"]) for p in pods):
            raise RuntimeError("expected three ready Cilium agents")
        for pod in pods:
            raw = self.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--",
                               "cilium-dbg", "version", json_output=False)
            if not re.search(rb"\b" + re.escape(version.encode()) + rb"\b", raw):
                raise RuntimeError("native agent version differs from selected stage")
        path = self.work / (phase + ".xml")
        self.command([self.args.cilium, "--kubeconfig", self.env["KUBECONFIG"], "--context", self.context,
                      "connectivity", "test", "--test=^(" + "|".join(TESTS) + ")$", "--ip-families=ipv4",
                      "--flow-validation=strict", "--hubble=true", "--collect-sysdump-on-failure=false",
                      "--junit-file=" + str(path)])
        results = require_results(path)
        self.stages.append({"phase": phase, "version": version, "cluster_uid": self.cluster_uid,
                            "agent_uids": [p["metadata"]["uid"] for p in pods], **results})
        (self.work / "progress.json").write_text(json.dumps(self.stages, indent=2))

    def run(self):
        self.create()
        self.install("1.15.1")
        self.validate("1.15.1", "baseline")
        self.install("1.15.19")
        self.validate("1.15.19", "patched-baseline")
        previous = "1.15.19"
        for version in ("1.16.19", "1.17.18", "1.18.15"):
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
                "production_change": False, "production_hardware_kernel_gpu_l2_unqualified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("name", "docker-host", "docker-server", "k3d", "cilium", "kubectl"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    qualification = Qualification(args)
    def interrupted(_number, _frame):
        raise InterruptedError("isolated qualification interrupted")
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
