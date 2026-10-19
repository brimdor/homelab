#!/usr/bin/env python3
"""Retire the exact orphaned NGINX ServiceMonitor from maintenance #103; read-only by default."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "git@git.eaglepass.io:ops/homelab.git"
NS, NAME = "ingress-nginx", "ingress-nginx-controller"
UID = "d9d21fc9-4402-407b-984f-d476194ad1df"
ENDPOINT = "/apis/monitoring.coreos.com/v1/namespaces/" + NS + "/servicemonitors/" + NAME
SELECTOR = {"app.kubernetes.io/component": "controller", "app.kubernetes.io/instance": NS,
            "app.kubernetes.io/name": NS}
SCOPED = ["scripts/retire-nginx-monitor.py", "scripts/test_retire_nginx_monitor.py",
          "system/ingress-nginx", "specs/ingress-successor.html"]


class Refusal(RuntimeError):
    """Only constant, sanitized messages leave the executor."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def run(args, data=None):
    p = subprocess.run(args, input=data, text=True, capture_output=True, cwd=ROOT, timeout=60)
    require(p.returncode == 0, "Command failed or write outcome unknown; stop without retry")
    return p.stdout


def source_gate(apply):
    def git(*args):
        return run(["git", *args]).strip()
    require(ROOT == Path("/Users/chris/Documents/Github/homelab") and
            git("rev-parse", "--show-toplevel") == str(ROOT), "Canonical checkout required")
    require(git("branch", "--show-current") == "master" and
            git("remote", "get-url", "origin") == ORIGIN, "Canonical Gitea master required")
    head = git("rev-parse", "HEAD")
    require(git("ls-remote", "origin", "refs/heads/master") == head + "\trefs/heads/master",
            "HEAD is not pushed canonical master")
    if apply:
        require(not git("status", "--porcelain", "--untracked-files=all", "--", *SCOPED), "Scoped source is dirty")
        for name in SCOPED[:2]:
            require(git("ls-files", "--error-unmatch", name) == name and
                    not (ROOT / name).is_symlink(), "Executor/tests must be tracked regular files")
    return head


def object_gate(obj):
    m = obj["metadata"]
    require(obj["kind"] == "ServiceMonitor" and obj["apiVersion"] == "monitoring.coreos.com/v1" and
            m.get("name") == NAME and m.get("namespace") == NS and m.get("uid") == UID and
            m.get("resourceVersion"), "Retired monitor identity changed")
    require(not any(m.get(k) for k in ("ownerReferences", "finalizers", "deletionTimestamp")) and
            not m.get("annotations", {}).get("argocd.argoproj.io/tracking-id"), "Retired monitor ownership changed")
    require(obj["spec"] == {"endpoints": [{"interval": "30s", "port": "metrics"}],
            "namespaceSelector": {"matchNames": [NS]}, "selector": {"matchLabels": SELECTOR}},
            "Retired monitor specification changed")


def delete_request(obj):
    object_gate(obj)
    return ENDPOINT, {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground",
                      "preconditions": {"uid": UID, "resourceVersion": obj["metadata"]["resourceVersion"]}}


def snapshot(get, head):
    app = get("applications.argoproj.io", NS, "argocd")
    require(app["spec"]["source"] == {"repoURL": "http://gitea-http.gitea:3000/ops/homelab",
            "path": "system/ingress-nginx", "targetRevision": "master", "helm": {"skipCrds": True}},
            "Ingress source changed")
    status = app["status"]
    require(status["sync"]["revision"] == head and status["sync"]["status"] == "Synced" and
            status["health"]["status"] == "Healthy" and
            status.get("operationState", {}).get("phase") not in ("Running", "Terminating"),
            "Ingress reconciliation is not healthy at current master")
    require(not any(x["kind"] == "ServiceMonitor" and x["name"] == NAME
                    for x in status["resources"]), "Retired monitor is still desired by Argo")
    services = get("services", None, NS)["items"]
    require(not any(all(x["metadata"].get("labels", {}).get(k) == v for k, v in SELECTOR.items()) and
                    any(p["name"] == "metrics" for p in x["spec"]["ports"]) for x in services),
            "Retired scrape selector has an active metrics Service")
    require(get("deployments.apps", NAME, NS) is None, "Old NGINX controller still exists")
    protected = [get("servicemonitors.monitoring.coreos.com", "ingress-traefik", NS),
                 get("services", "ingress-traefik-metrics", NS), get("services", NAME, NS)]
    require(all(protected) and protected[2]["metadata"]["uid"] == "c6304c6a-977c-4137-9e67-9d555b077dff",
            "Replacement monitoring/public Service missing or changed")
    deploy = get("deployments.apps", "ingress-traefik", NS)
    require(deploy and deploy["status"].get("readyReplicas") == deploy["spec"].get("replicas") == 2 and
            deploy["status"].get("availableReplicas") == 2, "Replacement controller not ready")
    return [(x["metadata"]["uid"], x["spec"]) for x in protected]


def execute(get, delete, gate, apply=False):
    head = gate(apply)
    protected = snapshot(get, head)
    obj = get("servicemonitors.monitoring.coreos.com", NAME, NS)
    if obj is None:
        return {"head": head, "already_absent": True}
    object_gate(obj)
    require(gate(apply) == head and snapshot(get, head) == protected, "Source or protected resources changed")
    current = get("servicemonitors.monitoring.coreos.com", NAME, NS)
    require(current == obj, "Retired monitor changed before action")
    if apply:
        path, options = delete_request(current)
        delete(path, options)
        require(get("servicemonitors.monitoring.coreos.com", NAME, NS) is None, "Deletion not yet confirmed; do not retry")
        require(snapshot(get, head) == protected, "Protected resources changed after deletion")
    return {"head": head, "uid": UID, "applied": apply, "protected_objects": len(protected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        cache = Path(os.environ.get("KUBECACHEDIR", ""))
        require(cache.is_absolute() and cache.is_dir(), "Existing process-local KUBECACHEDIR required")
        base = ["kubectl", "--kubeconfig", str(ROOT / "metal/kubeconfig.yaml"),
                "--cache-dir=" + str(cache), "--request-timeout=30s"]
        config = json.loads(run(base + ["config", "view", "--minify", "-o", "json"]))
        require(len(config["clusters"]) == 1, "Ambiguous Kubernetes target")
        cluster = config["clusters"][0]["cluster"]
        require(cluster.get("server") == "https://10.0.20.50:6443" and
                (cluster.get("certificate-authority-data") or cluster.get("certificate-authority")) and
                not any(cluster.get(k) for k in ("insecure-skip-tls-verify", "proxy-url", "tls-server-name")),
                "Kubernetes TLS identity changed")
        versions = json.loads(run(base + ["version", "-o", "json"]))
        client, server = versions["clientVersion"], versions["serverVersion"]
        require(client["major"] == server["major"] == "1" and
                abs(int(client["minor"]) - int(server["minor"])) <= 1, "Unsupported kubectl/server skew")
        def get(resource, name, namespace):
            command = base + ["get", resource] + ([name, "--ignore-not-found"] if name else [])
            text = run(command + ["-n", namespace, "-o", "json"])
            return json.loads(text) if text.strip() else None
        def delete(path, options):
            require(path == ENDPOINT, "Delete outside exact target forbidden")
            run(base + ["delete", "--raw", path, "-f", "-"], json.dumps(options))
        print(json.dumps(execute(get, delete, source_gate, args.apply), sort_keys=True))
        return 0
    except (Refusal, KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("BLOCKED: " + (str(exc) if isinstance(exc, Refusal) else "Evidence failed; no automatic retry"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
