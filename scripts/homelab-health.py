#!/usr/bin/env python3
"""Read-only, bounded CORE evidence collection. Exit 0 is NOT whole-homelab GREEN.

Usage: python3 scripts/homelab-health.py [--repo DIR] [--json]
       python3 scripts/homelab-health.py --fixture FILE --json
       python3 scripts/homelab-health.py --expected-revision FULL_COMMIT_SHA --json

Live mode requires the canonical checkout on macOS, origin below, branch master,
metal/kubeconfig.yaml targeting the verified VIP, and already-installed PyYAML or
ansible-inventory. Dirty local desired state is reported, not rejected. Nothing is
installed. No SSH, remote Git operations, logs, secrets, or mutation commands run.
Each child has a 20-second deadline and 32 MiB stdout limit; collection has a
240-second deadline starting before Git/inventory prerequisites. All children and
kubectl requests share its remaining budget; requests also cap at 15 seconds. No
scratch files are written. Evidence is sequential, not an atomic cluster snapshot.

Offline fixture contract (synthetic/non-secret JSON only):
{
  "schema_version": 1,
  "repository": {"path": "/synthetic/homelab",
                 "origin": "git@git.eaglepass.io:ops/homelab.git", "branch": "master",
                 "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "dirty": false},
  "inventory": {"metal": {"children": ["masters", "workers"]},
                "masters": {"hosts": ["charmander"]},
                "workers": {"hosts": ["pikachu"]}, "_meta": {"hostvars": {}}},
  "charts": ["system/argocd", "system/monitoring-system",
             "platform/external-secrets", "apps/example"],
  "sources": {"kubeconfig": {"clusters": [{"cluster": {"server": "https://10.0.20.50:6443"}}]},
              "version": {"clientVersion": {"major": "1", "minor": "34"},
                          "serverVersion": {"major": "1", "minor": "34"}},
              "nodes": {"kind": "NodeList", "items": []},
              "pods": {"kind": "PodList", "items": []},
              "deployments": {"kind": "DeploymentList", "items": []},
              "statefulsets": {"kind": "StatefulSetList", "items": []},
              "daemonsets": {"kind": "DaemonSetList", "items": []},
              "jobs": {"kind": "JobList", "items": []},
              "applications": {"kind": "ApplicationList", "items": []},
              "certificates": {"kind": "CertificateList", "items": []},
              "pvcs": {"kind": "PersistentVolumeClaimList", "items": []},
              "warnings": {"kind": "EventList", "items": []},
              "ceph": {"status": "HEALTH_OK"}}
}
The empty lists above intentionally produce missing-node/application findings;
they illustrate the format, not a passing fixture. Populate real-shaped Kubernetes
objects for a passing synthetic scenario. Generic kind List is also accepted.
ceph may instead be exact text HEALTH_OK/HEALTH_WARN/
HEALTH_ERR (surrounding whitespace allowed). An optional source {"error": true}
simulates a failed read. --inventory FILE replaces ONLY fixture inventory with
Ansible JSON, never live inventory. Fixtures execute no subprocesses or APIs and
cannot prove repository identity, freshness, or live health. See the sibling
unittest file for a complete synthetic fixture builder.

Output allowlists condition statuses/reasons, counts, ownership, node scope, and
timestamps. Messages, annotations, logs, environment, secret data, unexpected
repository URLs, and command stdout/stderr are never emitted verbatim. Exit 1
means findings; exit 2 means missing/invalid evidence or a gate/read failure.
"""

import argparse
import datetime
import importlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time


CANONICAL = Path("/Users/chris/Documents/Github/homelab")
ORIGIN = "git@git.eaglepass.io:ops/homelab.git"
ARGO_REPO = "http://gitea-http.gitea:3000/ops/homelab"
ARGO_SERVER = "https://kubernetes.default.svc"
VIP = "https://10.0.20.50:6443"
MAX_BYTES = 32 * 1024 * 1024
SAFE_TOKENS = frozenset({
    "True", "False", "Unknown", "Ready", "MemoryPressure", "DiskPressure", "PIDPressure",
    "NetworkUnavailable", "PodScheduled", "Initialized", "ContainersReady", "PodReadyToStartContainers",
    "DisruptionTarget", "Complete", "Failed", "FailureTarget", "SuccessCriteriaMet", "Suspended",
    "Available", "Progressing", "ReplicaFailure", "Issuing", "Resizing", "FileSystemResizePending",
    "Pending", "Running", "Succeeded", "Bound", "Lost", "Released", "Synced", "OutOfSync",
    "Healthy", "Degraded", "Missing", "Terminating", "Error",
    "Node", "Pod", "Job", "CronJob", "ReplicaSet", "Deployment", "StatefulSet", "DaemonSet",
    "Application", "Certificate", "PersistentVolumeClaim", "Event", "ClusterPolicy",
    "Completed", "OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
    "ContainerCreating", "PodInitializing", "CreateContainerConfigError", "CreateContainerError",
    "RunContainerError", "ContainerCannotRun", "InvalidImageName", "ErrImageNeverPull",
    "FailedMount", "FailedAttachVolume", "FailedScheduling", "BackOff", "Unhealthy", "Evicted",
    "Preempted", "NodeNotReady", "NodeLost", "Unschedulable", "DeadlineExceeded", "BackoffLimitExceeded",
    "MinimumReplicasAvailable", "MinimumReplicasUnavailable", "NewReplicaSetAvailable", "JobComplete",
})
RESOURCES = {
    "nodes": ("nodes", "Node", False),
    "pods": ("pods", "Pod", True),
    "deployments": ("deployments.apps", "Deployment", True),
    "statefulsets": ("statefulsets.apps", "StatefulSet", True),
    "daemonsets": ("daemonsets.apps", "DaemonSet", True),
    "jobs": ("jobs.batch", "Job", True),
    "applications": ("applications.argoproj.io", "Application", False),
    "certificates": ("certificates.cert-manager.io", "Certificate", True),
    "pvcs": ("persistentvolumeclaims", "PersistentVolumeClaim", True),
    "warnings": ("events", "Event", True),
}
UNTESTED = [
    "application behavior and migrations", "network, DNS and public TLS behavior",
    "host security, hardware and updates", "storage data integrity and backups",
    "external dependencies including NAS", "whole-homelab ALL GREEN completion",
]


class EvidenceError(Exception):
    """Only fixed, non-secret diagnostic strings may be raised here."""


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def require(test, detail):
    if not test:
        raise EvidenceError(detail)


def mapping(value):
    require(isinstance(value, dict), "Invalid object schema; expected a JSON object.")
    return value


def sequence(value):
    require(isinstance(value, list), "Invalid object schema; expected a JSON array.")
    return value


def integer(value):
    require(type(value) is int and value >= 0, "Invalid non-negative integer schema.")
    return value


def name(value):
    require(isinstance(value, str) and len(value) <= 253 and
            re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value),
            "Invalid or missing resource/group name.")
    return value


def token(value):
    # Kubernetes reasons are identifiers; never forward arbitrary diagnostic text.
    if isinstance(value, str) and value in SAFE_TOKENS:
        return value
    return None if value is None else "[redacted]"


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value),
            "Expected a full lowercase commit SHA (40 or 64 hexadecimal characters).")
    return value


def command(argv, deadline=None):
    """Bound memory/time without temporary raw evidence files or raw diagnostics."""
    limit = min(time.monotonic() + 20, deadline if deadline is not None else float("inf"))
    require(time.monotonic() < limit, "Collection deadline exceeded.")
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        raise EvidenceError("Required command unavailable or could not start.") from None
    chunks = []
    size = 0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = limit - time.monotonic()
                require(remaining > 0, "Command timeout; evidence unavailable.")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    require(size <= MAX_BYTES, "Command output bound exceeded; evidence unavailable.")
                    chunks.append(chunk)
        try:
            remaining = limit - time.monotonic()
            require(remaining > 0, "Command timeout; evidence unavailable.")
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise EvidenceError("Command timeout; evidence unavailable.") from None
        require(code == 0, "Command failed; raw stdout/stderr suppressed.")
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            raise EvidenceError("Command returned invalid UTF-8 evidence.") from None
    finally:
        try:
            # Stop only our child group, including credential-plugin descendants.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                raise EvidenceError("Child cleanup timeout; evidence unavailable.") from None
        finally:
            process.stdout.close()


def decode(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise EvidenceError("Invalid JSON evidence; raw output suppressed.") from None


def read_json(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "Fixture exceeds the 32 MiB input bound.")
        return decode(raw)
    except OSError:
        raise EvidenceError("Cannot read fixture/inventory JSON file.") from None


def inventory_nodes(inventory):
    """Read either safe-loaded Ansible YAML or canonical ansible-inventory JSON."""
    inventory = mapping(inventory)

    def hosts(group, seen):
        if isinstance(group, str):
            require(group not in seen, "Inventory contains a group cycle.")
            seen = seen | {group}
            group = mapping(inventory.get(group))
        group = mapping(group)
        members = group.get("hosts", {})
        require(isinstance(members, (dict, list)), "Invalid inventory hosts schema.")
        result = {name(host) for host in members}
        children = group.get("children", {})
        require(isinstance(children, (dict, list)), "Invalid inventory children schema.")
        for child in children:
            result.update(hosts(children[child] if isinstance(children, dict) else child, seen))
        return result

    metal = mapping(inventory.get("metal"))
    children = metal.get("children")
    require(isinstance(children, (dict, list)), "Inventory must contain metal children.")
    result = set()
    for group in ("masters", "workers"):
        require(group in children, "Inventory must contain active masters and workers groups.")
        members = hosts(children[group] if isinstance(children, dict) else group, {"metal"})
        require(bool(members), "Active inventory group is empty.")
        require(not result.intersection(members), "Inventory node occurs in multiple active groups.")
        result.update(members)
    # Include any other active metal children/hosts, not only today's two groups.
    return sorted(hosts("metal", set()))


def load_inventory(repo, deadline):
    require(time.monotonic() < deadline, "Collection deadline exceeded.")
    path = repo / "metal/inventories/prod.yml"
    require(path.is_file() and not path.is_symlink(), "Canonical production inventory missing or symlinked.")
    try:
        yaml = importlib.import_module("yaml")
    except ModuleNotFoundError:
        require(shutil.which("ansible-inventory") is not None,
                "Inventory unavailable: use an existing Python with PyYAML or installed ansible-inventory; "
                "nothing is installed. For offline evaluation, supply --fixture JSON.")
        return inventory_nodes(decode(command(["ansible-inventory", "-i", str(path), "--list"], deadline))), "ansible-inventory"
    try:
        with path.open() as stream:
            inventory = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError):
        raise EvidenceError("Could not safely parse the canonical production inventory.") from None
    return inventory_nodes(inventory), "PyYAML"


def chart_paths(paths):
    result = {}
    for value in sequence(paths):
        require(isinstance(value, str), "Invalid expected chart path schema.")
        parts = value.split("/")
        require(len(parts) == 2 and parts[0] in ("system", "platform", "apps") and
                parts[1] != "archived", "Expected charts must be active direct children, never archived paths.")
        app = name(parts[1])
        require(app not in result, "Duplicate application name across active charts.")
        result[app] = value
    require(bool(result), "No active expected charts found.")
    return dict(sorted(result.items()))


def discover_charts(repo):
    paths = []
    for layer in ("system", "platform", "apps"):
        root = repo / layer
        require(root.is_dir() and not root.is_symlink(), "Active chart root missing or symlinked.")
        for child in sorted(root.iterdir()):
            require(not child.is_symlink(), "Symlink in active chart discovery; refusing ambiguous desired state.")
            chart = child / "Chart.yaml"
            require(not chart.is_symlink(), "Symlinked Chart.yaml, including dangling links, is not owned desired state.")
            if child.is_dir() and chart.exists():
                require(chart.is_file() and not chart.is_symlink(), "Chart.yaml is not a regular owned file.")
                paths.append(f"{layer}/{child.name}")
    # monitoring-system and external-secrets are active via the separate CRD ApplicationSet.
    return chart_paths(paths)


def repository_metadata(repo, deadline):
    repo = repo.expanduser().resolve()
    if sys.platform == "darwin":
        require(repo == CANONICAL, "macOS requires /Users/chris/Documents/Github/homelab.")
    git = ["git", "--no-optional-locks", "-C", str(repo)]
    top = command(git + ["rev-parse", "--show-toplevel"], deadline).strip()
    require(Path(top).resolve() == repo, "Repository path is not the checkout root.")
    require(command(git + ["remote", "get-url", "origin"], deadline).strip() == ORIGIN,
            "Repository origin must be git@git.eaglepass.io:ops/homelab.git; unexpected URL suppressed.")
    require(command(git + ["symbolic-ref", "--short", "HEAD"], deadline).strip() == "master",
            "Repository source branch must be master.")
    require((repo / "system/argocd/Chart.yaml").is_file(), "Repository identity marker missing.")
    revision = sha(command(git + ["rev-parse", "HEAD"], deadline).strip())
    dirty = command(git + ["status", "--porcelain", "--untracked-files=normal"], deadline).splitlines()
    return repo, {"path": str(repo), "origin": ORIGIN, "branch": "master", "revision": revision,
                  "dirty": bool(dirty), "changed_entries": len(dirty), "identity": "local_git_verified",
                  "expected_state": "local_worktree_not_necessarily_deployed"}


def verify_kubeconfig(data):
    clusters = sequence(mapping(data).get("clusters"))
    require(len(clusters) == 1, "Minified kubeconfig must identify exactly one cluster.")
    cluster = mapping(mapping(clusters[0]).get("cluster"))
    require(cluster.get("server") == VIP, "Repo kubeconfig does not target https://10.0.20.50:6443.")
    require(cluster.get("insecure-skip-tls-verify", False) is False and not cluster.get("proxy-url"),
            "VIP verification requires TLS verification and no kubeconfig proxy override.")
    return {"server": VIP, "tls_verified_configuration": True}


def versions(data):
    data = mapping(data)
    result = {}
    for key in ("clientVersion", "serverVersion"):
        item = mapping(data.get(key))
        major, minor = item.get("major"), item.get("minor")
        require(isinstance(major, str) and re.fullmatch(r"[0-9]+", major) and
                isinstance(minor, str) and re.fullmatch(r"[0-9]+\+?", minor),
                "Invalid or missing kubectl client/server version evidence.")
        result[key] = {"major": int(major), "minor": int(minor.rstrip("+"))}
    client, server = result.values()
    result["compatible"] = (client["major"] == server["major"] and
                            abs(client["minor"] - server["minor"]) <= 1)
    return result


def collect_live(repo, deadline):
    config = repo / "metal/kubeconfig.yaml"
    require(config.is_file() and not config.is_symlink(), "Explicit repo metal/kubeconfig.yaml missing or symlinked.")
    base = ["kubectl", "--kubeconfig", str(config)]

    def read(args):
        timeout_ms = min(15000, int((deadline - time.monotonic()) * 1000))
        require(timeout_ms > 0, "Collection deadline exceeded.")
        return command(base + [f"--request-timeout={timeout_ms}ms"] + args, deadline)

    sources = {"kubeconfig": decode(read(["config", "view", "--minify", "-o", "json"]))}
    verify_kubeconfig(sources["kubeconfig"])
    base += ["--server=" + VIP]
    sources["version"] = decode(read(["version", "-o", "json"]))
    require(versions(sources["version"])["compatible"],
            "kubectl client must be within +/-1 minor of verified server; collection stopped.")
    receipts = {}
    for key, (resource, _, namespaced) in RESOURCES.items():
        args = ["get", resource, "-o", "json", "--chunk-size=200"]
        if key == "applications":
            args += ["-n", "argocd"]
        elif namespaced:
            args += ["-A"]
        if key == "warnings":
            args += ["--field-selector=type=Warning"]
        try:
            sources[key] = decode(read(args))
            receipts[key] = {"captured_at": timestamp(), "read": "ok"}
        except EvidenceError as error:
            sources[key] = {"error": str(error)}
            receipts[key] = {"captured_at": timestamp(), "read": "error", "detail": str(error)}
    try:
        text = read(["exec", "-n", "rook-ceph", "deploy/rook-ceph-tools", "--",
                     "ceph", "health", "-f", "json"])
        sources["ceph"] = decode(text) if text.lstrip().startswith("{") else text.strip()
        receipts["ceph"] = {"captured_at": timestamp(), "read": "ok"}
    except EvidenceError as error:
        sources["ceph"] = {"error": str(error)}
        receipts["ceph"] = {"captured_at": timestamp(), "read": "error", "detail": str(error)}
    return sources, receipts


def objects(data, kind):
    data = mapping(data)
    require(data.get("kind") in (kind + "List", "List"), "Invalid Kubernetes list kind; tables are not evidence.")
    seen = set()
    result = []
    for item in sequence(data.get("items")):
        item = mapping(item)
        require(item.get("kind") == kind, "Invalid Kubernetes item kind.")
        metadata = mapping(item.get("metadata"))
        if kind == "Node":
            require(metadata.get("namespace") is None, "Node evidence must be cluster-scoped.")
        identity = (metadata.get("namespace"), name(metadata.get("name")))
        if kind != "Node":
            name(metadata.get("namespace"))
        require(identity not in seen, "Duplicate resource in collected evidence.")
        seen.add(identity)
        mapping(item.get("status", {}))
        result.append(item)
    return result


def conditions(status):
    result = []
    seen = set()
    for item in sequence(status.get("conditions", [])):
        item = mapping(item)
        kind, value = item.get("type"), item.get("status")
        require(isinstance(kind, str) and bool(kind) and kind not in seen and
                value in ("True", "False", "Unknown"), "Invalid or duplicate condition schema.")
        seen.add(kind)
        result.append({"type": token(kind), "status": value, "reason": token(item.get("reason")),
                       "observed_generation": integer(item["observedGeneration"]) if "observedGeneration" in item else None})
    return result


def condition_value(items, kind):
    return next((item["status"] for item in items if item["type"] == kind), "Unknown")


def reference(item):
    metadata = item["metadata"]
    owners = []
    for owner in sequence(metadata.get("ownerReferences", [])):
        owner = mapping(owner)
        owners.append({"kind": token(owner.get("kind")), "name": name(owner.get("name")),
                       "uid": "[redacted]" if owner.get("uid") is not None else None})
    return {"kind": item["kind"], "namespace": metadata.get("namespace"),
            "name": metadata["name"], "owners": owners}


def container_evidence(spec, status, field):
    declared = sequence(spec.get(field, []))
    if field == "containers":
        require(bool(declared), "Pod must declare containers.")
    status_field = "containerStatuses" if field == "containers" else "initContainerStatuses"
    observed = {}
    for item in sequence(status.get(status_field, [])):
        item = mapping(item)
        key = name(item.get("name"))
        require(key not in observed, "Duplicate container status.")
        observed[key] = item
    result = []
    seen = set()
    for declared_item in declared:
        declared_item = mapping(declared_item)
        key = name(declared_item.get("name"))
        require(key not in seen, "Duplicate declared container.")
        seen.add(key)
        item = observed.get(key, {})
        ready = item.get("ready", False)
        require(type(ready) is bool, "Invalid container readiness schema.")
        state = mapping(item.get("state", {}))
        require(len(state) <= 1 and all(k in ("running", "waiting", "terminated") for k in state),
                "Invalid container state schema.")
        state_name = next(iter(state), "unknown")
        details = mapping(state.get(state_name, {}))
        exit_code = details.get("exitCode") if state_name == "terminated" else None
        if state_name == "terminated":
            require(type(exit_code) is int, "Terminated container requires an integer exit code.")
        result.append({"name": key, "ready": ready, "state": state_name,
                       "reason": token(details.get("reason")), "exit_code": exit_code,
                       "restart_count": integer(item.get("restartCount", 0)),
                       "sidecar_init": declared_item.get("restartPolicy") == "Always"})
    require(not set(observed).difference(seen), "Status names do not match declared containers.")
    return result


def job_evidence(item):
    spec, status = mapping(item.get("spec")), mapping(item.get("status", {}))
    result = reference(item)
    result.update({"conditions": conditions(status), "active": integer(status.get("active", 0)),
                   "failed": integer(status.get("failed", 0)), "succeeded": integer(status.get("succeeded", 0)),
                   "completions": integer(spec.get("completions") if spec.get("completions") is not None else 1),
                   "suspended": spec.get("suspend", False)})
    require(type(result["suspended"]) is bool, "Invalid Job suspend schema.")
    result["terminal_failed"] = any(condition_value(result["conditions"], kind) == "True"
                                    for kind in ("Failed", "FailureTarget"))
    # The API terminal condition accounts for successPolicy and Job completion rules.
    result["complete"] = condition_value(result["conditions"], "Complete") == "True" and not result["terminal_failed"]
    return result


def cuda_completion_proven(item, row, daemonsets):
    """One exact successful validator shape and its current healthy policy-owned DaemonSet."""
    spec = item["spec"]
    metadata = item["metadata"]
    if (row["namespace"] == "gpu-operator" and row["name"].startswith("nvidia-cuda-validator-") and
            mapping(metadata.get("labels", {})).get("app") == "nvidia-cuda-validator" and
            spec.get("serviceAccountName") == "nvidia-operator-validator" and
            spec.get("restartPolicy") == "OnFailure" and row["node_in_active_inventory"] and
            not metadata.get("deletionTimestamp") and
            [c["name"] for c in row["containers"]] == ["nvidia-cuda-validator"] and
            [c["name"] for c in row["init_containers"]] == ["cuda-validation"] and
            not row["init_containers"][0]["sidecar_init"] and
            all(c["state"] == "terminated" and c["exit_code"] == 0
                for c in row["containers"] + row["init_containers"])):
        validators = [ds for ds in daemonsets if
                      ds["metadata"].get("namespace") == "gpu-operator" and
                      ds["metadata"]["name"] == "nvidia-operator-validator"]
        owners = metadata.get("ownerReferences", [])
        if len(validators) == 1 and len(owners) == 1:
            parent = validators[0]["metadata"]
            parent_status = mapping(validators[0].get("status", {}))
            parent_owners = sequence(parent.get("ownerReferences", []))
            desired = integer(parent_status.get("desiredNumberScheduled"))
            return (not parent.get("deletionTimestamp") and len(parent_owners) == 1 and
                all(mapping(o).get("apiVersion") == "nvidia.com/v1" and
                    o.get("kind") == "ClusterPolicy" and o.get("name") == "cluster-policy"
                    for o in owners + parent_owners) and
                isinstance(owners[0].get("uid"), str) and bool(owners[0]["uid"]) and
                owners[0]["uid"] == parent_owners[0].get("uid") and
                integer(parent_status.get("observedGeneration", 0)) >= integer(parent.get("generation")) and
                desired > 0 and all(integer(parent_status.get(field, 0)) == desired for field in
                    ("currentNumberScheduled", "updatedNumberScheduled", "numberReady", "numberAvailable")) and
                integer(parent_status.get("numberMisscheduled", 0)) == 0 and
                integer(parent_status.get("numberUnavailable", 0)) == 0)
    return False


def expected_application_namespace(app, charts):
    if app not in charts:
        return None
    # system/argocd/values.yaml explicitly keeps this legacy release in kube-system.
    # Keep this exact contract usable with ansible-inventory and JSON fixtures, without PyYAML.
    if app == "nfs-client-provisioner" and charts[app] == "system/nfs-client-provisioner":
        return "kube-system"
    return app


def destination_matches_expected(destination, namespace):
    destination = mapping(destination)
    return (namespace is not None and destination.get("namespace") == namespace and
            (destination.get("name") == "in-cluster" or destination.get("server") == ARGO_SERVER) and
            destination.get("name") in (None, "", "in-cluster") and
            destination.get("server") in (None, "", ARGO_SERVER))


def node_dependencies(spec):
    """Positive node references, not a claim that affinity alternatives cannot run."""
    result = set()
    if spec.get("nodeName"):
        result.add(name(spec["nodeName"]))
    selector = mapping(spec.get("nodeSelector", {}))
    if "kubernetes.io/hostname" in selector:
        result.add(name(selector["kubernetes.io/hostname"]))
    affinity = mapping(mapping(spec.get("affinity", {})).get("nodeAffinity", {}))
    required = mapping(affinity.get("requiredDuringSchedulingIgnoredDuringExecution", {}))
    terms = list(sequence(required.get("nodeSelectorTerms", [])))
    for preferred in sequence(affinity.get("preferredDuringSchedulingIgnoredDuringExecution", [])):
        terms.append(mapping(preferred).get("preference", {}))
    for term in terms:
        term = mapping(term)
        for field, key in (("matchExpressions", "kubernetes.io/hostname"), ("matchFields", "metadata.name")):
            for expression in sequence(term.get(field, [])):
                expression = mapping(expression)
                if expression.get("key") == key and expression.get("operator") == "In":
                    result.update(name(value) for value in sequence(expression.get("values", [])))
    return sorted(result)


def evaluate(sources, expected_nodes, charts, expected_revision=None):
    sources = mapping(sources)
    evidence, findings, errors, parsed = {}, [], [], {}

    def finding(source, item, code, details=None):
        findings.append({"source": source, "namespace": item.get("namespace"), "name": item.get("name"),
                         "code": code, "details": details or {}})

    def source_data(key):
        require(key in sources, "Required snapshot source missing.")
        data = sources[key]
        require(not (isinstance(data, dict) and "error" in data), "Source read failed; raw diagnostics suppressed.")
        return data

    for key, (_, kind, _) in RESOURCES.items():
        try:
            parsed[key] = objects(source_data(key), kind)
        except EvidenceError as error:
            errors.append({"source": key, "detail": str(error)})
    for key in ("kubeconfig", "version", "ceph"):
        try:
            data = source_data(key)
            if key == "kubeconfig":
                evidence[key] = verify_kubeconfig(data)
            elif key == "version":
                evidence[key] = versions(data)
                if not evidence[key]["compatible"]:
                    finding(key, {}, "client_server_version_skew", evidence[key])
            else:
                health = data.strip() if isinstance(data, str) else mapping(data).get("status")
                require(health in ("HEALTH_OK", "HEALTH_WARN", "HEALTH_ERR"), "Invalid or missing Ceph health status.")
                evidence[key] = {"status": health}
                if health != "HEALTH_OK":
                    finding(key, {}, "ceph_not_health_ok", {"status": health})
        except EvidenceError as error:
            errors.append({"source": key, "detail": str(error)})

    jobs = {}
    for key in RESOURCES:
        if key not in parsed:
            continue
        evidence[key] = []
        try:
            if key == "jobs":
                continue  # Job findings are emitted below; Pod eligibility uses the same projection.
            if key == "pods":
                for item in parsed.get("jobs", []):
                    job = job_evidence(item)
                    jobs[(job["namespace"], job["name"])] = (item, job)
            for item in parsed[key]:
                spec, status = mapping(item.get("spec", {})), item.get("status", {})
                row = reference(item)
                if key == "nodes":
                    row.update({"expected": row["name"] in expected_nodes, "conditions": conditions(status),
                                "unschedulable": spec.get("unschedulable", False)})
                    require(type(row["unschedulable"]) is bool, "Invalid node scheduling schema.")
                    row["scope"] = "active_inventory" if row["expected"] else "retired_or_unknown_status_only"
                    if row["expected"]:
                        for kind, wanted in (("Ready", "True"), ("MemoryPressure", "False"),
                                             ("DiskPressure", "False"), ("PIDPressure", "False")):
                            observed = condition_value(row["conditions"], kind)
                            if observed != wanted:
                                finding(key, row, "node_condition", {"type": kind, "expected": wanted, "observed": observed})
                        if row["unschedulable"]:
                            finding(key, row, "node_unschedulable")
                elif key == "pods":
                    row.update({"node": name(spec["nodeName"]) if spec.get("nodeName") else None,
                                "phase": token(status.get("phase")), "conditions": conditions(status),
                                "containers": container_evidence(spec, status, "containers"),
                                "init_containers": container_evidence(spec, status, "initContainers")})
                    row["node_in_active_inventory"] = row["node"] in expected_nodes
                    completed_job_pod = False
                    if row["node"] and not row["node_in_active_inventory"] and row["phase"] not in ("Succeeded", "Failed"):
                        finding(key, row, "pod_node_outside_active_inventory")
                    if row["phase"] == "Running":
                        if condition_value(row["conditions"], "Ready") != "True":
                            finding(key, row, "pod_not_ready")
                        if any(not c["ready"] or c["state"] != "running" for c in row["containers"]):
                            finding(key, row, "containers_not_ready")
                    elif row["phase"] == "Succeeded":
                        eligible = False
                        for owner in item["metadata"].get("ownerReferences", []):
                            owned = jobs.get((row["namespace"], owner["name"]))
                            if owner.get("kind") == "Job" and owned:
                                original, job = owned
                                owner_healthy = job["complete"] or (job["active"] > 0 and not job["terminal_failed"])
                                eligible = eligible or (isinstance(owner.get("uid"), str) and bool(owner["uid"]) and
                                                        owner["uid"] == original["metadata"].get("uid") and owner_healthy and
                                                        spec.get("restartPolicy") in ("Never", "OnFailure"))
                        completed_job_pod = eligible and all(c["state"] == "terminated" and c["exit_code"] == 0
                                                            for c in row["containers"])
                        completed_cuda_pod = False
                        completed_cuda_pod = cuda_completion_proven(item, row, parsed.get("daemonsets", []))
                        if not completed_job_pod and not completed_cuda_pod:
                            finding(key, row, "pod_completion_not_proven")
                    else:
                        finding(key, row, "pod_phase_unhealthy", {"phase": row["phase"]})
                    for container in row["init_containers"]:
                        if container["sidecar_init"] and row["phase"] == "Running":
                            ok = container["state"] == "running" and container["ready"]
                        elif container["sidecar_init"] and completed_job_pod:
                            ok = container["state"] == "terminated"
                        else:
                            ok = container["state"] == "terminated" and container["exit_code"] == 0
                        if not ok:
                            finding(key, row, "init_container_not_successful", {"container": container["name"]})
                    if item["metadata"].get("deletionTimestamp"):
                        finding(key, row, "pod_terminating")
                elif key in ("deployments", "statefulsets", "daemonsets"):
                    template = mapping(mapping(spec.get("template", {})).get("spec", {}))
                    row["node_dependencies_outside_active_inventory"] = [
                        node for node in node_dependencies(template) if node not in expected_nodes]
                    if row["node_dependencies_outside_active_inventory"]:
                        finding(key, row, "controller_node_dependency_outside_active_inventory",
                                {"nodes": row["node_dependencies_outside_active_inventory"]})
                    row.update({"generation": integer(item["metadata"].get("generation")),
                                "observed_generation": integer(status.get("observedGeneration", 0)),
                                "conditions": conditions(status)})
                    if row["observed_generation"] < row["generation"]:
                        finding(key, row, "controller_generation_stale")
                    if key == "daemonsets":
                        row["desired"] = integer(status.get("desiredNumberScheduled"))
                        fields = ("currentNumberScheduled", "updatedNumberScheduled", "numberReady", "numberAvailable")
                        row["counts"] = {field: integer(status.get(field, 0)) for field in fields}
                        row["misscheduled"] = integer(status.get("numberMisscheduled", 0))
                        row["unavailable"] = integer(status.get("numberUnavailable", 0))
                        if any(count != row["desired"] for count in row["counts"].values()) or row["misscheduled"] or row["unavailable"]:
                            finding(key, row, "daemonset_not_available")
                    else:
                        row["desired"] = integer(spec.get("replicas", 1))
                        fields = ("replicas", "readyReplicas", "updatedReplicas")
                        if key == "deployments":
                            fields += ("availableReplicas",)
                        row["counts"] = {field: integer(status.get(field, 0)) for field in fields}
                        if any(count != row["desired"] for count in row["counts"].values()):
                            finding(key, row, "controller_replicas_unavailable")
                    if condition_value(row["conditions"], "ReplicaFailure") == "True" or condition_value(row["conditions"], "Progressing") == "False":
                        finding(key, row, "controller_failure_condition")
                    if row["desired"] and any(c["type"] == "Available" and c["status"] != "True" for c in row["conditions"]):
                        finding(key, row, "controller_not_available_condition")
                elif key == "applications":
                    source = mapping(spec.get("source", {}))
                    expected_namespace = expected_application_namespace(row["name"], charts)
                    sync, health = mapping(status.get("sync", {})), mapping(status.get("health", {}))
                    row.update({"sync": token(sync.get("status")), "health": token(health.get("status")),
                                "expected_path": charts.get(row["name"]),
                                "source_path": source.get("path") if source.get("path") == charts.get(row["name"]) else "[unexpected/redacted]",
                                "source_repo": ARGO_REPO if source.get("repoURL") == ARGO_REPO else "[unexpected/redacted]",
                                "target_revision": "master" if source.get("targetRevision") == "master" else "[unexpected/redacted]",
                                "observed_revision": sync.get("revision") if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(sync.get("revision"))) else None})
                    if row["name"] not in charts:
                        finding(key, row, "unexpected_application")
                    if row["namespace"] != "argocd":
                        finding(key, row, "application_namespace_mismatch")
                    row["destination_matches_expected"] = destination_matches_expected(spec.get("destination", {}),
                                                                                        expected_namespace)
                    if not row["destination_matches_expected"]:
                        finding(key, row, "application_destination_mismatch")
                    if (source.get("path") != charts.get(row["name"]) or source.get("repoURL") != ARGO_REPO or
                            source.get("targetRevision") != "master" or spec.get("sources")):
                        finding(key, row, "application_source_mismatch")
                    compared = mapping(sync.get("comparedTo", {}))
                    if mapping(compared.get("source", {})) != source:
                        finding(key, row, "application_comparison_source_mismatch")
                    row["comparison_destination_matches_expected"] = destination_matches_expected(
                        compared.get("destination", {}), expected_namespace)
                    if not row["comparison_destination_matches_expected"]:
                        finding(key, row, "application_comparison_destination_mismatch")
                    if row["sync"] != "Synced" or row["health"] != "Healthy":
                        finding(key, row, "application_not_synced_healthy")
                    app_conditions = sequence(status.get("conditions", []))
                    row["conditions"] = [{"type": token(mapping(c).get("type"))} for c in app_conditions]
                    if app_conditions:
                        finding(key, row, "application_conditions_present")
                    operation = mapping(status.get("operationState", {}))
                    row["operation_phase"] = token(operation.get("phase"))
                    # ApplyOutOfSyncOnly may leave historical operation metadata older than sync.revision.
                    last_operation = mapping(operation.get("syncResult", {})).get("revision")
                    row["last_operation_revision"] = last_operation if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(last_operation)) else None
                    if operation and operation.get("phase") != "Succeeded":
                        finding(key, row, "application_operation_not_succeeded")
                    if expected_revision and row["observed_revision"] != expected_revision:
                        finding(key, row, "expected_revision_not_observed", {"expected_revision": expected_revision})
                elif key == "certificates":
                    row["conditions"] = conditions(status)
                    if condition_value(row["conditions"], "Ready") != "True":
                        finding(key, row, "certificate_not_ready")
                    generation = integer(item["metadata"].get("generation"))
                    ready = next((c for c in row["conditions"] if c["type"] == "Ready"), {})
                    if ready.get("observed_generation") is None or ready["observed_generation"] < generation:
                        finding(key, row, "certificate_generation_not_observed")
                elif key == "pvcs":
                    row.update({"phase": token(status.get("phase")), "conditions": conditions(status)})
                    if row["phase"] != "Bound":
                        finding(key, row, "pvc_not_bound")
                elif key == "warnings":
                    if item.get("type") != "Warning":
                        continue
                    involved = mapping(item.get("involvedObject", {}))
                    series = mapping(item.get("series", {}))
                    row.update({"reason": token(item.get("reason")), "count": integer(item.get("count", series.get("count", 1))),
                                "object": {"kind": token(involved.get("kind")), "name": name(involved.get("name")),
                                           "namespace": name(involved["namespace"]) if involved.get("namespace") else None},
                                "first_timestamp": safe_timestamp(item.get("firstTimestamp")),
                                "last_timestamp": safe_timestamp(item.get("lastTimestamp")),
                                "event_time": safe_timestamp(item.get("eventTime")),
                                "last_observed_time": safe_timestamp(series.get("lastObservedTime")),
                                "message": "[redacted]"})
                    finding(key, row, "warning_event", {"reason": row["reason"], "count": row["count"]})
                evidence[key].append(row)
        except EvidenceError as error:
            errors.append({"source": key, "detail": str(error)})

    if "jobs" in parsed:
        try:
            for item in parsed["jobs"]:
                row = job_evidence(item)
                evidence["jobs"].append(row)
                if row["terminal_failed"]:
                    finding("jobs", row, "job_failed_including_retained")
                if condition_value(row["conditions"], "Complete") == "True" and not row["complete"]:
                    finding("jobs", row, "job_completion_inconsistent")
                elif not row["complete"] and not row["active"] and not row["suspended"]:
                    finding("jobs", row, "job_incomplete_without_active_work")
        except EvidenceError as error:
            errors.append({"source": "jobs", "detail": str(error)})
    if "nodes" in parsed:
        present = {item["metadata"]["name"] for item in parsed["nodes"]}
        for missing in sorted(set(expected_nodes) - present):
            finding("nodes", {"name": missing}, "expected_node_missing")
    if "applications" in parsed:
        present = {item["metadata"]["name"] for item in parsed["applications"]}
        for missing in sorted(set(charts) - present):
            finding("applications", {"name": missing, "namespace": "argocd"}, "expected_application_missing",
                    {"expected_path": charts[missing]})
    return evidence, findings, errors


def safe_timestamp(value):
    if value is None:
        return None
    require(isinstance(value, str), "Invalid timestamp schema.")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError("Invalid timestamp schema.") from None
    require(parsed.tzinfo is not None, "Timestamp must have a timezone.")
    return parsed.isoformat()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EvidenceError("Invalid CLI arguments; use --help for the supported contract.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    report = {"timestamp": timestamp(), "scope": "CORE", "core_status": "ERROR", "core_passed": False,
              "exit_code": 2, "all_layers_verified": False, "untested": UNTESTED,
              "evidence": {}, "findings": [], "errors": [], "collection": {"atomic": False}}
    try:
        parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
        parser.add_argument("--repo", default=os.environ.get("REPO_ROOT") or str(CANONICAL))
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--fixture", metavar="FILE")
        parser.add_argument("--inventory", metavar="FILE", help="Ansible JSON override, fixtures only")
        parser.add_argument("--expected-revision", help="Full immutable commit SHA required in the current compared sync revision; last operation revision is informational")
        parser.add_argument("--verbose", action="store_true", help="Compatibility flag; all structured evidence is always included")
        args = parser.parse_args(argv)
        expected_revision = sha(args.expected_revision) if args.expected_revision is not None else None
        require(not args.inventory or args.fixture, "--inventory is permitted only with --fixture; live inventory cannot be overridden.")
        if args.fixture:
            report["mode"] = "fixture"
            fixture = mapping(read_json(args.fixture))
            require(type(fixture.get("schema_version")) is int and fixture["schema_version"] == 1, "Unsupported fixture schema_version.")
            metadata = mapping(fixture.get("repository"))
            require(metadata.get("origin") == ORIGIN and metadata.get("branch") == "master",
                    "Fixture repository must model canonical origin and master source branch.")
            require(type(metadata.get("dirty")) is bool, "Fixture repository dirty must be boolean.")
            report["repository"] = {"origin": ORIGIN, "branch": "master", "revision": sha(metadata.get("revision")),
                                    "dirty": metadata["dirty"], "identity": "synthetic_unverified",
                                    "expected_state": "fixture_not_live"}
            nodes = inventory_nodes(read_json(args.inventory) if args.inventory else fixture.get("inventory"))
            charts = chart_paths(fixture.get("charts"))
            sources = mapping(fixture.get("sources"))
            report["collection"].update({"inventory_reader": "fixture_JSON", "sources": "synthetic_unverified"})
        else:
            report["mode"] = "live"
            deadline = time.monotonic() + 240
            repo, metadata = repository_metadata(Path(args.repo), deadline)
            report["repository"] = metadata
            nodes, reader = load_inventory(repo, deadline)
            charts = discover_charts(repo)
            sources, receipts = collect_live(repo, deadline)
            report["collection"].update({"inventory_reader": reader, "sources": receipts})
        report["expected"] = {"nodes": nodes, "applications": charts, "revision": expected_revision}
        evidence, findings, errors = evaluate(sources, nodes, charts, expected_revision)
        report.update({"evidence": evidence, "findings": findings, "errors": errors})
        report["exit_code"] = 2 if errors else 1 if findings else 0
        report["core_status"] = "ERROR" if errors else "RED" if findings else "PASS"
        report["core_passed"] = report["exit_code"] == 0
    except EvidenceError as error:
        report["errors"].append({"source": "gate", "detail": str(error)})
    except (Exception, KeyboardInterrupt):
        report["errors"].append({"source": "gate", "detail": "Collector error or invalid evidence; raw diagnostics suppressed. Diagnose with offline fixtures."})
    report["collection"]["finished_at"] = timestamp()
    if "--json" in argv:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"CORE {report['core_status']} [{report['timestamp']}] exit={report['exit_code']}")
        print("CORE evidence only. Application behavior, network, host security, storage/backups and ALL GREEN are untested.")
        for item in report["errors"]:
            print(f"ERROR {item['source']}: {item['detail']}")
        for item in report["findings"]:
            print(f"FINDING {item['source']} {item.get('namespace') or '-'}/{item.get('name') or '-'}: {item['code']}")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
