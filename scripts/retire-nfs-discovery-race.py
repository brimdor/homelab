#!/usr/bin/env python3
"""One-time maintenance #103 cleanup. Default: read-only; --apply requires pushed master.

Remove the temporary quiescence template through Git first. Configure the Argo CD
CLI for this cluster; its manifests command must return the exact HEAD revision.
Never remove finalizers, retry a DELETE, delete storage, or uninstall the Helm release.
An incomplete/changed inventory stops execution, including after a partial cleanup.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import fnmatch
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode

import yaml


ROOT = Path("/Users/chris/Documents/Github/homelab")
ORIGIN = "git@git.eaglepass.io:ops/homelab.git"
REPO = "http://gitea-http.gitea:3000/ops/homelab"
NS = "nfs-client-provisioner"
NAME = "nfs-client-provisioner-nfs-subdir-external-provisioner"
ROLE = "leader-locking-" + NAME
LOCK = "cluster.local-" + NAME
RBAC = "rbac.authorization.k8s.io/v1"
NS_UID = "717f700b-a93a-426a-af64-efe87e0be7ae"
ORIGINAL_UID = "5e60b9b6-b2c7-422e-89ee-9e7899b1e1c5"
# Observed 2026-10-18 after desired-state quiescence at 5e7f23a6.
PINS = {
    ("apps/v1", "deployments", NAME): "e6ba35e2-66e6-4789-b521-7dbfa4d7d83e",
    ("apps/v1", "replicasets", NAME + "-65777966c8"): "37d74df1-8552-4cb3-99c5-b02108e707dd",
    ("v1", "serviceaccounts", NAME): "dd17fb8f-48ed-4fa4-87db-d2c22097c125",
    (RBAC, "roles", ROLE): "4bf0f99f-0f59-4bf3-b57c-0b1d781a6f63",
    (RBAC, "rolebindings", ROLE): "0110b458-d3c5-460d-af51-e3f2df744fbb",
    ("v1", "endpoints", LOCK): "1df00df7-8b46-446e-9de4-31749db42069",
    ("v1", "serviceaccounts", "default"): "d534311e-04bc-4a96-b00d-b174ecb6912b",
    ("v1", "configmaps", "kube-root-ca.crt"): "4f2f9b3d-6f4c-4579-9a7b-357c5ac159de",
}
# Existing events are stateless evidence, not authority to delete their referenced object.
EVENTS = {
    LOCK + ".18dfc12924a0ed6e": "3c581a89-6346-4488-bdd1-9ae2fbed3e85",
    NAME + "-65777966c8.18dfc1288a297c5f": "f56463ee-a538-4ccc-8fca-1e1dd6dec0e3",
    NAME + "-65777966c8.18dfc157640d88f6": "3ede9702-0d5c-4b94-91c1-f2979c13f5bf",
    NAME + "-657tm999.18dfc1288aecd554": "9257039c-58d6-431d-b95a-636036106293",
    NAME + "-657tm999.18dfc128c5763068": "9c4543d8-16ad-4415-bb53-fb777dd8a471",
    NAME + "-657tm999.18dfc1291cefdf14": "17ce4a7e-8137-4f54-94fd-382bc774120e",
    NAME + "-657tm999.18dfc1291ec29450": "27b03c1f-de81-4761-8953-89a4927f1246",
    NAME + "-657tm999.18dfc129226039a2": "e687a7e1-fa28-424c-976b-7787e1b65d5a",
    NAME + "-657tm999.18dfc157642300e8": "894a27b5-5485-483e-98fc-1ea2bdf63dd4",
    NAME + ".18dfc12889915dc0": "be7b0e8e-49bc-400a-a8ea-65984502a426",
    NAME + ".18dfc157631d91f9": "b34b80fb-b10c-4343-abb6-dc9ebb6585db",
}
EVENT_SUBJECTS = {
    NAME: ("Deployment", PINS[("apps/v1", "deployments", NAME)]),
    NAME + "-65777966c8": ("ReplicaSet", PINS[("apps/v1", "replicasets", NAME + "-65777966c8")]),
    NAME + "-657tm999": ("Pod", "8b2f78b6-169a-415e-9e43-d70094c44382"),
    LOCK: ("Endpoints", PINS[("v1", "endpoints", LOCK)]),
}
PINS.update({(version, "events", name): uid for version in ("v1", "events.k8s.io/v1") for name, uid in EVENTS.items()})
DEFAULTS = {("v1", "serviceaccounts", "default"), ("v1", "configmaps", "kube-root-ca.crt")}
NAMESPACE_REMAINDERS = DEFAULTS | {key for key in PINS if key[1] == "events"}
ORDER = [("apps/v1", "deployments", NAME), ("v1", "endpoints", LOCK),
         (RBAC, "rolebindings", ROLE), (RBAC, "roles", ROLE), ("v1", "serviceaccounts", NAME)]
SCOPED = ["scripts/retire-nfs-discovery-race.py", "scripts/test_retire_nfs_discovery_race.py",
          "system/argocd", "system/nfs-client-provisioner", ".agent/rules/foundational-rules.md"]


class Refusal(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def run(args, payload=None):
    result = subprocess.run(args, input=payload, text=True, capture_output=True, cwd=ROOT, check=False)
    # Do not echo stderr: an API, manifest renderer, or credential plugin may include sensitive data.
    require(result.returncode == 0, f"Command failed ({args[0]} {args[1]}); no automatic retry")
    return result.stdout


def prefix(version):
    return "/api/v1" if version == "v1" else "/apis/" + version


class API:
    def call(self, *args, payload=None):
        return run(["kubectl", "--kubeconfig", str(ROOT / "metal/kubeconfig.yaml"), "--request-timeout=30s", *args], payload)

    def raw(self, path):
        return json.loads(self.call("get", "--raw", path))

    def get(self, version, resource, name, namespace=""):
        token = resource + "." + ".".join(reversed(version.split("/"))) if "/" in version else resource
        args = ["get", token, name, "--ignore-not-found", "-o", "json"]
        if namespace:
            args += ["-n", namespace]
        text = self.call(*args)
        return json.loads(text) if text.strip() else None

    def discover(self):
        versions = [("v1", self.raw("/api/v1"))]
        for group in self.raw("/apis")["groups"]:
            for version in group["versions"]:
                gv = version["groupVersion"]
                versions.append((gv, self.raw("/apis/" + gv)))
        resources = set()
        for version, listing in versions:
            require(listing.get("groupVersion") == version, "Discovery group/version mismatch")
            for resource in listing["resources"]:
                if resource["namespaced"] and "list" in resource["verbs"] and "/" not in resource["name"]:
                    resources.add((version, resource["name"]))
        require({("v1", "secrets"), ("v1", "persistentvolumeclaims"), ("apps/v1", "deployments")} <= resources,
                "Incomplete API discovery")
        return sorted(resources)

    def metadata(self, resource, namespace):
        version, plural = resource
        token = plural + "." + ".".join(reversed(version.split("/"))) if "/" in version else plural
        # kubectl has no custom Accept header for raw GET. Project only these fields;
        # never emit Secret bodies or annotations (last-applied may contain credentials).
        projection = ('{range .items[*]}{.metadata.name}{"\\t"}{.metadata.namespace}{"\\t"}'
                      '{.metadata.uid}{"\\t"}{.metadata.resourceVersion}{"\\t"}'
                      '{.metadata.ownerReferences}{"\\n"}{end}')
        try:
            text = self.call("get", token, "-n", namespace, "-o", "jsonpath=" + projection)
        except Refusal as exc:
            raise Refusal(f"Cannot enumerate {version}/{plural} in {namespace}; incomplete discovery") from exc
        result = []
        for line in text.splitlines():
            name, ns, uid, rv, owners = line.split("\t")
            require(ns == namespace and uid and rv, "Invalid metadata inventory")
            result.append({"name": name, "namespace": ns, "uid": uid, "resourceVersion": rv,
                           "ownerReferences": json.loads(owners) if owners else []})
        return result

    def inventory(self, resources, namespace):
        def collect(resource):
            return [(resource + (m["name"],), m) for m in self.metadata(resource, namespace)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(item for batch in pool.map(collect, resources) for item in batch)

    def delete(self, key, obj):
        path, options = delete_request(key, obj)
        try:
            self.call("delete", "--raw", path, "-f", "-", payload=json.dumps(options))
        except Exception as exc:
            raise Refusal("DELETE failed or outcome unknown; stop, inspect exact UID, rerun check; never retry blindly") from exc


def source_gate(apply=False):
    def git(*args):
        return run(["git", *args]).strip()
    require(Path(__file__).resolve().parent.parent == ROOT and ROOT.resolve() == ROOT, "Foreign executor checkout")
    require(git("rev-parse", "--show-toplevel") == str(ROOT), "Foreign checkout")
    require(git("branch", "--show-current") == "master", "master required")
    require(git("config", "--get-all", "remote.origin.url") == ORIGIN
            and git("remote", "get-url", "origin") == ORIGIN, "Canonical origin required")
    head = git("rev-parse", "HEAD")
    require(not (ROOT / "system/nfs-client-provisioner/templates/discovery-race-quiescence.yaml").exists(),
            "Remove quiescence template through desired state before cleanup")
    values = yaml.safe_load((ROOT / "system/argocd/values.yaml").read_text())["argocd-apps"]
    for path in ["system/argocd/values.yaml", "system/argocd/values-seed.yaml"]:
        document = yaml.safe_load((ROOT / path).read_text())
        generator_gate(document["argocd-apps"]["applicationsets"].values(),
                       "https://github.com/brimdor/homelab" if path.endswith("values-seed.yaml") else REPO)
    application_gate({"metadata": {}, "spec": values["applications"][NS]})
    if apply:
        require(not git("status", "--porcelain", "--untracked-files=all", "--", *SCOPED), "Scoped files are dirty or untracked")
        for path in SCOPED[:2]:
            require(git("ls-files", "--error-unmatch", path) == path, "Executor/tests must be committed")
        for path in git("ls-files", "-z", "--", *SCOPED).split("\0"):
            if path:
                local = ROOT / path
                require(local.is_file() and not local.is_symlink()
                        and local.read_text() == run(["git", "show", "HEAD:" + path]), "Scoped bytes differ from HEAD: " + path)
        require(git("ls-remote", "origin", "refs/heads/master") == head + "\trefs/heads/master",
                "Local HEAD must equal pushed Gitea master")
    return head


def generator_gate(sets, repo=REPO):
    for item in sets:
        spec = item.get("spec", item)
        for generator in spec["generators"]:
            require(set(generator) == {"git"}, "Unknown ApplicationSet generator")
            git = generator["git"]
            require(git["repoURL"] == repo and git["revision"] == "master", "Foreign generator source")
            directories = git["directories"]
            includes = any(fnmatch.fnmatchcase("system/" + NS, entry["path"])
                           for entry in directories if not entry.get("exclude", False))
            excludes = any(fnmatch.fnmatchcase("system/" + NS, entry["path"])
                           for entry in directories if entry.get("exclude") is True)
            require(not includes or excludes, "Active generator includes NFS chart")


def application_gate(app):
    require(app is not None, "Missing explicit Application")
    spec, meta = app["spec"], app["metadata"]
    require(not meta.get("ownerReferences") and not meta.get("finalizers") and not meta.get("deletionTimestamp"),
            "Application has owner/finalizer/deletion")
    require(spec.get("source") == {"repoURL": REPO, "path": "system/" + NS, "targetRevision": "master",
                                   "helm": {"releaseName": NS}} and not spec.get("sources"), "Noncanonical Application source")
    require(spec["destination"] == {"name": "in-cluster", "namespace": "kube-system"}, "Wrong Application destination")
    policy = spec.get("syncPolicy", {})
    require("automated" not in policy and {"Prune=false", "Delete=false"} <= set(policy.get("syncOptions", [])),
            "Application automation enabled or deletion protection missing")
    require(not app.get("operation") and app.get("status", {}).get("operationState", {}).get("phase") not in
            ("Running", "Terminating"), "Application operation active")


def manifest_gate(documents):
    expected = {("ServiceAccount", NAME), ("Deployment", NAME), ("Role", ROLE), ("RoleBinding", ROLE),
                ("ClusterRole", NAME + "-runner"), ("ClusterRoleBinding", "run-" + NAME), ("StorageClass", "nfs-rwx")}
    seen = set()
    for obj in documents:
        require(isinstance(obj, dict), "Invalid desired manifest")
        pair = (obj.get("kind"), obj.get("metadata", {}).get("name"))
        require(pair in expected and pair not in seen, "Unexpected/duplicate desired resource")
        namespace = obj["metadata"].get("namespace", "")
        require(namespace in ("", "kube-system"), "Desired template recreates accidental namespace resources")
        seen.add(pair)
    require(seen == expected, "Desired manifest set incomplete")


def identity(obj, uid, name, namespace):
    require(obj is not None, "Missing required object: " + name)
    meta = obj["metadata"]
    require(meta.get("uid") == uid and meta.get("name") == name and meta.get("namespace", "") == namespace,
            "Changed UID or scope: " + name)
    require(bool(meta.get("resourceVersion")), "Missing resourceVersion")


def inventory_gate(inventory):
    for key, meta in inventory.items():
        require(key in PINS, "Unknown/protected namespace resource: " + "/".join(key))
        identity({"metadata": meta}, PINS[key], key[2], NS)
        if key[1] == "replicasets":
            require(meta.get("ownerReferences") == [{"apiVersion": "apps/v1", "kind": "Deployment", "name": NAME,
                    "uid": PINS[ORDER[0]], "controller": True, "blockOwnerDeletion": True}], "Unproven ReplicaSet ownership")
        else:
            require(not meta.get("ownerReferences"), "Unexpected object owner")


def object_gate(key, obj):
    identity(obj, PINS[key], key[2], NS)
    require(not obj["metadata"].get("finalizers"), "Unexpected finalizer; manual observation required")
    resource = key[1]
    if resource == "events":
        reference = obj.get("involvedObject", obj.get("regarding", {}))
        subject = key[2].rsplit(".", 1)[0]
        require(reference.get("namespace") == NS and reference.get("name") == subject
                and (reference.get("kind"), reference.get("uid")) == EVENT_SUBJECTS[subject], "Unproven event association")
    if resource in ("deployments", "replicasets"):
        require(obj["spec"].get("replicas") == 0 and not any(obj.get("status", {}).get(field, 0)
                for field in ("replicas", "readyReplicas", "availableReplicas", "updatedReplicas")), "Controller is not quiescent")
        require(obj.get("status", {}).get("observedGeneration", 0) >= obj["metadata"].get("generation", 1),
                "Controller has not observed scale-to-zero")
        pod = obj["spec"]["template"]["spec"]
        require(pod.get("serviceAccountName") == NAME and pod.get("volumes") == [{
            "name": "nfs-subdir-external-provisioner-root", "nfs": {"server": "10.0.40.3", "path": "/mnt/user/heartlib"}}],
            "Unexpected controller storage/auth configuration; NAS/PVC data protected")
    if resource == "serviceaccounts":
        require(not obj.get("secrets") and not obj.get("imagePullSecrets"), "ServiceAccount references authentication data")
    if resource == "endpoints":
        require(not obj.get("subsets"), "Lock Endpoint has network endpoints")
        lock = json.loads(obj["metadata"].get("annotations", {}).get("control-plane.alpha.kubernetes.io/leader", "{}"))
        require(lock.get("holderIdentity") == NAME + "-657tm999_47ebdf71-f523-4a2a-8cd1-f5475bd1621d"
                and lock.get("renewTime") == "2026-10-18T22:49:17Z", "Lock ownership changed or lease still active")
    if resource == "configmaps":
        require(set(obj.get("data", {})) == {"ca.crt"} and not obj.get("binaryData"), "Unexpected namespace ConfigMap data")


def fingerprint(obj):
    return {"uid": obj["metadata"]["uid"], **{key: value for key, value in obj.items()
            if key not in ("metadata", "status", "apiVersion", "kind")}}


def protected(api, resources):
    result = {}
    for resource in ("persistentvolumes", "persistentvolumeclaims"):
        items = api.raw("/api/v1/" + resource)["items"]
        require(items, "Empty protected storage inventory")
        for obj in items:
            require(obj.get("status", {}).get("phase") == "Bound", "Unbound protected storage")
            require(obj["metadata"].get("namespace") != NS and obj.get("spec", {}).get("claimRef", {}).get("namespace") != NS,
                    "Accidental namespace has storage binding")
            result[(resource, obj["metadata"].get("namespace", ""), obj["metadata"]["name"])] = fingerprint(obj)
    original = api.get("apps/v1", "deployments", NAME, "kube-system")
    identity(original, ORIGINAL_UID, NAME, "kube-system")
    require(original["spec"]["replicas"] == 1 and original["status"].get("readyReplicas") == 1
            and original["status"].get("availableReplicas") == 1, "Original controller unhealthy")
    result[("original",)] = fingerprint(original)
    labels = original["spec"]["selector"]["matchLabels"]
    selector = ",".join(f"{key}={value}" for key, value in sorted(labels.items()))
    pods = api.raw("/api/v1/namespaces/kube-system/pods?" + urlencode({"labelSelector": selector}))["items"]
    require(len(pods) == 1, "Original controller must have exactly one healthy pod")
    pod = pods[0]
    owners = pod["metadata"].get("ownerReferences", [])
    require(len(owners) == 1 and owners[0].get("kind") == "ReplicaSet" and owners[0].get("controller") is True,
            "Original pod ownership unknown")
    rs = api.get("apps/v1", "replicasets", owners[0]["name"], "kube-system")
    require(rs is not None and rs["metadata"]["uid"] == owners[0]["uid"]
            and any(owner.get("uid") == ORIGINAL_UID and owner.get("controller") is True
                    for owner in rs["metadata"].get("ownerReferences", [])), "Original ReplicaSet ownership changed")
    require(not pod["metadata"].get("deletionTimestamp") and pod.get("status", {}).get("phase") == "Running"
            and any(c["type"] == "Ready" and c["status"] == "True" for c in pod["status"].get("conditions", [])),
            "Original pod not healthy")
    result[("original-pod",)] = {"object": fingerprint(pod), "restarts": {
        c["name"]: c["restartCount"] for c in pod["status"].get("containerStatuses", [])}}
    for version, resource, name, ns in [
        ("v1", "serviceaccounts", NAME, "kube-system"), (RBAC, "roles", ROLE, "kube-system"),
        (RBAC, "rolebindings", ROLE, "kube-system"), (RBAC, "clusterroles", NAME + "-runner", ""),
        (RBAC, "clusterrolebindings", "run-" + NAME, ""), ("storage.k8s.io/v1", "storageclasses", "nfs-rwx", "")]:
        obj = api.get(version, resource, name, ns)
        require(obj is not None and not obj["metadata"].get("deletionTimestamp"), "Protected resource missing/deleting")
        if resource == "clusterrolebindings":
            require(obj.get("subjects") == [{"kind": "ServiceAccount", "name": NAME, "namespace": "kube-system"}]
                    and obj.get("roleRef") == {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": NAME + "-runner"},
                    "Original ClusterRoleBinding not restored")
        result[(version, resource, name)] = fingerprint(obj)
    result[("default-namespace",)] = {key: meta["uid"] for key, meta in api.inventory(resources, "default").items()}
    return result


def snapshot(api, head):
    app = api.get("argoproj.io/v1alpha1", "applications", NS, "argocd")
    application_gate(app)
    require({"Prune=false", "Delete=false"} <= set(app["metadata"].get("annotations", {}).get(
        "argocd.argoproj.io/sync-options", "").split(",")), "Application annotation protection missing")
    require(app.get("status", {}).get("sync", {}).get("revision") == head, "Application has not compared current HEAD")
    sets = api.raw("/apis/argoproj.io/v1alpha1/namespaces/argocd/applicationsets")["items"]
    require({"root", "root-crd-replace"} <= {s["metadata"]["name"] for s in sets}, "Missing root generators")
    generator_gate(sets)
    resources = api.discover()
    ns = api.get("v1", "namespaces", NS)
    inventory = api.inventory(resources, NS)
    inventory_gate(inventory)
    if ns is not None:
        identity(ns, NS_UID, NS, "")
        require(not ns["metadata"].get("finalizers") and ns.get("spec", {}).get("finalizers") == ["kubernetes"],
                "Unexpected namespace finalizers; do not remove them")
    else:
        require(not inventory, "Objects exist without expected namespace")
    objects = {}
    for key in inventory:
        obj = api.get(*key, NS)
        object_gate(key, obj)
        if key[1] == "configmaps":
            require(obj.get("data") == api.get("v1", "configmaps", "kube-root-ca.crt", "kube-system").get("data"),
                    "Namespace CA differs from public cluster CA")
        require(obj["metadata"]["resourceVersion"] == inventory[key]["resourceVersion"], "Inventory changed during observation")
        objects[key] = obj
    guard = protected(api, resources)
    return {"namespace": ns, "inventory": inventory, "objects": objects, "protected": guard, "resources": resources}


def delete_request(key, obj):
    if key == ("v1", "namespaces", NS):
        identity(obj, NS_UID, NS, "")
        path = "/api/v1/namespaces/" + NS
    else:
        require(key in ORDER, "Deletion outside exact accidental stateless allowlist")
        object_gate(key, obj)
        path = prefix(key[0]) + "/namespaces/" + NS + "/" + key[1] + "/" + key[2]
    meta = obj["metadata"]
    return path, {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground",
                  "preconditions": {"uid": meta["uid"], "resourceVersion": meta["resourceVersion"]}}


def execute(api, gate, manifests, apply=False, emit=print, sleep=time.sleep, clock=time.monotonic):
    head = gate(apply)
    manifest_gate(manifests(head))
    initial = snapshot(api, head)
    baseline = initial["protected"]

    def checked():
        require(gate(apply) == head, "Repository revision changed")
        current = snapshot(api, head)
        require(current["resources"] == initial["resources"], "API discovery changed")
        require(current["protected"] == baseline, "Protected storage/controller/RBAC/default namespace changed")
        return current

    emit(json.dumps({"mode": "apply" if apply else "check", "head": head,
                     "targets": [{"resource": list(k), "uid": m["uid"], "resourceVersion": m["resourceVersion"]}
                                 for k, m in initial["inventory"].items()],
                     "protected_objects": len(baseline)}))
    if not apply:
        checked()
        return
    try:
        for key in ORDER + [("v1", "namespaces", NS)]:
            current = checked()
            if key[1] == "namespaces":
                require(set(current["inventory"]) <= NAMESPACE_REMAINDERS, "Namespace still contains controller/unknown objects")
                obj = current["namespace"]
                # A second exhaustive census narrows the namespace-controller deletion race.
                require(api.inventory(current["resources"], NS) == current["inventory"], "Namespace inventory changed")
            else:
                obj = current["objects"].get(key)
            if obj is None:
                continue
            require(not obj["metadata"].get("deletionTimestamp"), "Already deleting; observe before resuming")
            api.delete(key, obj)
            emit(json.dumps({"delete_submitted": list(key), "uid": obj["metadata"]["uid"]}))
            # Observe only. Never retry a write or remove a finalizer.
            observation_end = clock() + 600
            while True:
                remaining = api.get(*key, "" if key[1] == "namespaces" else NS)
                if remaining is None:
                    break
                identity(remaining, obj["metadata"]["uid"], key[2], "" if key[1] == "namespaces" else NS)
                require(bool(remaining["metadata"].get("deletionTimestamp")), "DELETE did not enter termination; outcome uncertain")
                require(clock() < observation_end, "Deletion observation exceeded 600 seconds; inspect termination without retrying DELETE")
                sleep(2)
        final = checked()
        require(final["namespace"] is None and not final["inventory"], "Cleanup incomplete")
        emit("Exact accidental namespace/resources absent; protected API identities/specs unchanged. Live all-green gates remain required.")
    finally:
        require(protected(api, initial["resources"]) == baseline, "Post-action protected resource verification failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete exact pinned accidental resources; requires pushed clean scoped master")
    args = parser.parse_args()
    api = API()
    try:
        server = api.call("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        require(server == "https://10.0.20.50:6443", "Wrong Kubernetes API")
        versions = json.loads(api.call("version", "-o", "json"))
        require(versions["serverVersion"]["major"] == "1" and versions["serverVersion"]["minor"] == "33"
                and versions["clientVersion"]["major"] == "1" and int(versions["clientVersion"]["minor"]) in (32, 33, 34),
                "Unsupported Kubernetes version/skew")
        def manifests(head):
            return list(yaml.safe_load_all(run(["argocd", "app", "manifests", NS, "--app-namespace", "argocd", "--revision", head])))
        execute(api, source_gate, manifests, args.apply)
        return 0
    except Refusal as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError):
        print("BLOCKED: malformed/unavailable evidence; no automatic retry", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
