#!/usr/bin/env python3
"""Exercise the reviewed native CSI manager only in a disconnected synthetic API."""

import copy
import hashlib
import json
import os
import re
import shutil
import sys
import time

import etcd_recovery as common
from ceph_admission_qualification import command_objects


IMAGE = "quay.io/cephcsi/ceph-csi-operator@sha256:a14d8d1a610f381fc1c735eaed43bb18d8ccc04c92cc603af6eab5dc1a37b4f3"
BUNDLE_SHA256 = "6f48e7a309e80341b7ae5f4b21bc7d7ac3a2cb810616d0f2be250b19d290413d"
NAMESPACE = "rook-ceph"
LEASE = "0a62cc8a.ceph.io"
NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
DRIVERS = {"rook-ceph.rbd.csi.ceph.com", "rook-ceph.cephfs.csi.ceph.com"}


def checked_docker(*args, stage):
    result = common.docker(*args, check=False)
    if result.returncode:
        raw = result.stdout.lower() + result.stderr.lower()
        markers = [v for v in ("forbidden", "unauthorized", "permission denied", "x509", "certificate",
                              "unknown flag", "no such file", "not found", "strict decoding", "namespace",
                              "timed out", "connection refused", "invalid", "cannot", "denied") if v.encode() in raw]
        raise RuntimeError("native CSI " + stage + " failed: " + json.dumps({"exit": result.returncode, "markers": markers,
                                                                           "raw_output_discarded": True}))
    return result


def manager_failure(raw, state=None):
    errors = b"\n".join(line.lower() for line in raw.splitlines() if b"error" in line.lower() or b"panic" in line.lower())
    markers = [v for v in ("not found", "no matches for kind", "already exists", "object has been modified",
                          "conflict", "timeout", "connection refused", "invalid", "required", "failed to create",
                          "failed to update", "failed to get", "unable to load", "configmap", "config map",
                          "imageset", "image set", "operatorconfig", "clientprofile", "cephconnection",
                          "snapshotmetadataservice", "volumesnapshot", "namespace", "panic", "unknown flag",
                          "unable to find leader election namespace", "not running in-cluster", "unable to start manager",
                          "context canceled", "the server could not find the requested resource")
               if v.encode() in errors]
    diagnostic = {"markers": markers, "raw_output_discarded": True}
    if state is not None:
        diagnostic.update(running=state["Running"], exit=state["ExitCode"], oom_killed=state["OOMKilled"])
    return "native CSI manager failed: " + json.dumps(diagnostic)


def reconciliation_progress(raw):
    successful, conflicts = set(), 0
    for line in raw.splitlines():
        failed = b"CSI Driver reconciliation failed" in line or b"Reconciler error" in line
        if not failed and b"CSI Driver reconciliation completed successfully" not in line:
            continue
        try:
            fields = json.loads(line[line.index(b"{"):])
        except (ValueError, UnicodeError):
            raise RuntimeError("native CSI reconciliation event shape changed; raw output discarded") from None
        if not isinstance(fields, dict):
            raise RuntimeError("native CSI reconciliation event shape changed; raw output discarded")
        name = fields.get("name")
        if fields.get("namespace") != NAMESPACE or not isinstance(name, str) or name not in DRIVERS:
            raise RuntimeError("native CSI reconciliation event identity changed; raw output discarded")
        if failed:
            error = fields.get("error")
            if not isinstance(error, str) or not re.fullmatch(r'Operation cannot be fulfilled on (configmaps|csidrivers\.storage\.k8s\.io|deployments\.apps|daemonsets\.apps) "[^"\n]+": the object has been modified; please apply your changes to the latest version and try again', error):
                raise RuntimeError("native CSI non-conflict reconciliation error; " + manager_failure(line))
            conflicts += 1
            successful.discard(name)
        else:
            successful.add(name)
    return {"successful_drivers": sorted(successful), "optimistic_conflict_events": conflicts}


def validate_bundle(bundle):
    if hashlib.sha256(common.canonical(bundle)).hexdigest() != BUNDLE_SHA256:
        raise RuntimeError("reviewed CSI controller bundle changed")
    if set(bundle) != {"crds", "setup", "resources"} or len(bundle["crds"]) != 5:
        raise RuntimeError("CSI controller input inventory changed")
    if any(x["spec"]["group"] != "csi.ceph.io" for x in bundle["crds"]):
        raise RuntimeError("foreign CSI CRD")


def require_manager(value, api_id, identity, run_id):
    host, config = value["HostConfig"], value["Config"]
    mounts = {(m.get("Type"), m.get("Source"), m.get("Destination"), m.get("RW")) for m in value["Mounts"]}
    if (config.get("Image") != IMAGE or config.get("User") != "65532:65532" or
            config.get("Entrypoint") != ["/manager"] or config.get("Cmd") != ["--leader-elect"] or
            config.get("Labels", {}).get("io.eaglepass.recovery-run") != run_id or
            config.get("Labels", {}).get("io.eaglepass.maintenance") != "103" or
            host.get("NetworkMode") != "container:" + api_id or not host.get("ReadonlyRootfs") or
            host.get("Privileged") or host.get("CapAdd") or host.get("CapDrop") != ["ALL"] or
            host.get("PidMode") or host.get("IpcMode") != "private" or host.get("Devices") or
            host.get("PortBindings") or host.get("LogConfig") != {"Type": "none", "Config": {}} or
            "no-new-privileges:true" not in host.get("SecurityOpt", []) or
            mounts != {("bind", str(identity), "/identity", False),
                       ("bind", str(identity / "namespace"), NAMESPACE_FILE, False)}):
        raise RuntimeError("native CSI manager isolation changed")
    environment = dict(v.split("=", 1) for v in config.get("Env", []))
    if any(environment.get(k) != v for k, v in {"KUBECONFIG": "/identity/config", "OPERATOR_NAMESPACE": NAMESPACE,
                                               "WATCH_NAMESPACE": "", "CSI_SERVICE_ACCOUNT_PREFIX": "",
                                               "KUBERNETES_CLUSTER_DOMAIN": "cluster.local"}.items()):
        raise RuntimeError("native CSI manager identity or namespace configuration changed")


def require_csidrivers(rows):
    if len(rows) != 2 or {x["metadata"]["name"] for x in rows} != DRIVERS:
        raise RuntimeError("generated Kubernetes CSI driver inventory differs")
    for value in rows:
        owner = json.loads(value["metadata"].get("annotations", {}).get("csi.ceph.io/ownerref", "null"))
        if (not value["metadata"].get("uid") or
                owner != {"Name": value["metadata"]["name"], "Namespace": NAMESPACE} or
                value["spec"].get("fsGroupPolicy") != "File" or value["spec"].get("seLinuxMount") is not True):
            raise RuntimeError("generated Kubernetes CSI driver ownership/policy differs")
    return {v["metadata"]["name"]: {"uid": v["metadata"]["uid"], "spec": v["spec"]} for v in rows}


def require_workloads(rows, drivers, plugin_image, verbosity):
    expected = {(kind, name) for kind in ("Deployment", "DaemonSet") for name in DRIVERS}
    observed, snapshots = set(), {}
    for value in rows:
        if value["kind"] not in ("Deployment", "DaemonSet"):
            continue
        owners = value["metadata"].get("ownerReferences", [])
        owned = [o for o in owners if o.get("apiVersion") == "csi.ceph.io/v1" and
                 o.get("kind") == "Driver" and o.get("controller") is True and
                 o.get("name") in DRIVERS and o.get("uid") == drivers[o["name"]]]
        if len(owned) != 1 or not value["metadata"].get("uid"):
            raise RuntimeError("generated CSI workload ownership is missing or wrong")
        owner = owned[0]["name"]
        key = (value["kind"], owner)
        if key in observed:
            raise RuntimeError("duplicate generated CSI workload")
        observed.add(key)
        spec = value["spec"]
        pod = spec["template"]["spec"]
        plugins = [c for c in pod["containers"] if c.get("image") == plugin_image]
        if len(plugins) != 1 or "--v=" + str(verbosity[owner]) not in plugins[0].get("args", []):
            raise RuntimeError("generated native plugin image or verbosity differs")
        if not any(t.get("key") == "dedicated" and t.get("operator") == "Exists" and
                   t.get("effect") == "NoSchedule" for t in pod.get("tolerations", [])):
            raise RuntimeError("generated CSI tolerations changed")
        if value["kind"] == "Deployment":
            # Native current controllers use pod networking; OperatorConfig hostNetwork is not merged into a populated Driver.
            mismatches = {"replicas": spec.get("replicas") != 2, "strategy": spec.get("strategy", {}).get("type") != "Recreate",
                          "host_network": pod.get("hostNetwork", False) is not False}
            if any(mismatches.values()):
                raise RuntimeError("generated controller intent changed: " + json.dumps(mismatches))
        else:
            if spec.get("updateStrategy", {}).get("type") != "RollingUpdate":
                raise RuntimeError("generated node update strategy changed")
            paths = [v["hostPath"]["path"] for v in pod.get("volumes", []) if "hostPath" in v]
            if not any(p.startswith("/var/lib/kubelet/") for p in paths):
                raise RuntimeError("generated CSI kubelet mount intent is missing")
            if owner == "rook-ceph.cephfs.csi.ceph.com" and "--forcecephkernelclient=true" not in plugins[0].get("args", []):
                raise RuntimeError("generated CephFS kernel client intent changed")
        if not plugins[0].get("resources", {}).get("limits", {}).get("memory"):
            raise RuntimeError("generated CSI resource policy is missing")
        snapshots["/".join(key)] = {"uid": value["metadata"]["uid"], "spec": spec}
    if observed != expected:
        raise RuntimeError("native CSI generated workload inventory is incomplete")
    return snapshots


def qualify(bundle, run_id):
    validate_bundle(bundle)

    def controller(api_id, scratch, client, identifier):
        def kubectl(*args, stage=None):
            return checked_docker(*client, *args, stage=stage or "kubectl " + args[0])

        def get(resource):
            return json.loads(kubectl("get", resource, "-n", NAMESPACE, "-o=json").stdout)

        def create(items, name):
            (scratch / name).write_bytes(common.canonical({"apiVersion": "v1", "kind": "List", "items": items}))
            rows = command_objects(kubectl("create", "--namespace=" + NAMESPACE, "--validate=strict", "-f=/work/" + name, "-o=json",
                                            stage="create " + name).stdout)
            if len(rows) != len(items):
                raise RuntimeError("native CSI create evidence is incomplete")
            return rows

        create([{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}}], "namespace.json")
        create(bundle["crds"], "crds.json")
        kubectl("wait", "--for=condition=Established", "--timeout=180s",
                *["crd/" + c["metadata"]["name"] for c in bundle["crds"]])
        create(bundle["setup"], "setup.json")
        create(bundle["resources"], "resources.json")
        drivers = {d["metadata"]["name"]: d["metadata"]["uid"] for d in get("drivers.csi.ceph.io")["items"]}
        if set(drivers) != DRIVERS or any(not v for v in drivers.values()):
            raise RuntimeError("synthetic CSI Driver identities changed")
        plugin = next(x["data"]["plugin"] for x in bundle["setup"] if x["kind"] == "ConfigMap")
        if plugin != "quay.io/cephcsi/cephcsi:v3.17.1":
            raise RuntimeError("reviewed candidate CSI plugin changed")
        config = json.loads(kubectl("config", "view", "--raw", "--minify", "-o=json").stdout)
        cluster = config["clusters"][0]["cluster"]
        if cluster.get("server") != "https://127.0.0.1:16443" or not cluster.get("certificate-authority-data"):
            raise RuntimeError("synthetic CSI API TLS contract changed")
        token = kubectl("create", "token", "ceph-csi", "-n", NAMESPACE, "--duration=1h").stdout.decode().strip()
        if not token:
            raise RuntimeError("synthetic ServiceAccount token was not issued")
        identity = scratch / "csi-identity"
        identity.mkdir(mode=0o700)
        os.chown(identity, 65532, 65532)
        synthetic_config = {"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "synthetic", "cluster": cluster}],
                            "contexts": [{"name": "synthetic", "context": {"cluster": "synthetic", "user": "ceph-csi"}}],
                            "current-context": "synthetic", "users": [{"name": "ceph-csi", "user": {"token": token}}]}
        path = identity / "config"
        path.write_bytes(common.canonical(synthetic_config))
        path.chmod(0o600)
        os.chown(path, 65532, 65532)
        namespace_path = identity / "namespace"
        namespace_path.write_text(NAMESPACE)
        namespace_path.chmod(0o600)
        os.chown(namespace_path, 65532, 65532)
        before_images = set(common.docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
        manager = image_id = capture = None
        captures = []
        try:
            capacity = shutil.disk_usage(scratch)
            if capacity.free / capacity.total <= 0.2:
                raise RuntimeError("insufficient actual capacity for native CSI qualification")
            checked_docker("pull", IMAGE, stage="pull reviewed manager image")
            image = json.loads(common.docker("image", "inspect", IMAGE).stdout)[0]
            image_id = image["Id"]
            if (image.get("Architecture") != "amd64" or image.get("Os") != "linux" or
                    image["Config"].get("Volumes") or image["Config"].get("User") != "65532:65532" or
                    image["Config"].get("Entrypoint") != ["/manager"]):
                raise RuntimeError("native CSI manager image contract changed")
            capacity = shutil.disk_usage(scratch)
            if capacity.free / capacity.total <= 0.2:
                raise RuntimeError("native CSI image pull crossed actual free-space guard")
            manager = checked_docker("create", "--network=container:" + api_id, "--user=65532:65532",
                                    "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                                    "--ipc=private", "--pids-limit=128", "--cpus=1", "--memory=256m",
                                    "--label=io.eaglepass.maintenance=103", "--label=io.eaglepass.recovery-run=" + identifier,
                                    "--mount=type=bind,source=" + str(identity) + ",target=/identity,readonly",
                                    "--mount=type=bind,source=" + str(namespace_path) + ",target=" + NAMESPACE_FILE + ",readonly",
                                    "--env=KUBECONFIG=/identity/config", "--env=OPERATOR_NAMESPACE=" + NAMESPACE,
                                    "--env=WATCH_NAMESPACE=", "--env=CSI_SERVICE_ACCOUNT_PREFIX=",
                                    "--env=KUBERNETES_CLUSTER_DOMAIN=cluster.local", IMAGE, "--leader-elect",
                                    stage="create isolated manager").stdout.decode().strip()
            if not re.fullmatch(r"[a-f0-9]{64}", manager):
                raise RuntimeError("native CSI manager returned an invalid container identity")
            require_manager(common.inspect(manager), api_id, identity, identifier)

            def alive():
                value = common.inspect(manager)
                require_manager(value, api_id, identity, identifier)
                raw = capture.output().stdout
                if re.search(rb"\b(forbidden|unauthorized)\b|x509:|permission denied", raw, re.I):
                    raise RuntimeError("native CSI manager encountered an access or trust denial; raw output discarded")
                if not value["State"]["Running"]:
                    raise RuntimeError(manager_failure(raw, value["State"]))
                reconciliation_progress(raw)
                return value

            def await_value(read, accept, description, seconds=180):
                end = time.monotonic() + seconds
                while True:
                    alive()
                    value = read()
                    if accept(value):
                        return value
                    if time.monotonic() >= end:
                        raise RuntimeError("native CSI timed out waiting for " + description)
                    time.sleep(1)

            def lease():
                result = kubectl("get", "lease", LEASE, "-n", NAMESPACE, "-o=json", "--ignore-not-found")
                return json.loads(result.stdout) if result.stdout.strip() else {}

            def workloads():
                return get("deployments,daemonsets")["items"]

            def complete(rows):
                return len(rows) == 4

            def health():
                pid = alive()["State"]["Pid"]
                parent_pid = common.inspect(api_id)["State"]["Pid"]
                if os.readlink("/proc/" + str(pid) + "/ns/net") != os.readlink("/proc/" + str(parent_pid) + "/ns/net"):
                    raise RuntimeError("native CSI manager does not share the isolated API namespace")
                namespace = ["nsenter", "--target", str(pid), "--net", "--"]
                links = json.loads(common.command(namespace + ["ip", "-j", "address"]).stdout)
                routes = []
                for family in ("-4", "-6"):
                    routes.extend(json.loads(common.command(namespace + ["ip", family, "-j", "route", "show", "table", "all"]).stdout))
                common.require_network(links, routes)
                probe = "import urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); assert all(o.open('http://127.0.0.1:8081/'+p,timeout=5).status==200 for p in ('healthz','readyz')); print('ok')"
                return common.command(namespace + [sys.executable, "-c", probe], check=False).returncode == 0

            capture = common.CapturedContainer(manager)
            captures.append(capture)
            def reconciled(offset, expected, description):
                return await_value(lambda: reconciliation_progress(capture.output().stdout[offset:]),
                                   lambda p: set(p["successful_drivers"]) >= expected, description)
            await_value(health, bool, "native manager probes")
            first_lease = await_value(lease, lambda x: bool(x.get("spec", {}).get("holderIdentity")), "leader ownership")
            reconciled(0, DRIVERS, "initial successful native reconciliations")
            baseline = require_workloads(await_value(workloads, complete, "four generated workloads"), drivers, plugin,
                                         {n: 0 for n in DRIVERS})
            csidrivers = get("csidrivers.storage.k8s.io")["items"]
            baseline_csidrivers = require_csidrivers(csidrivers)
            original = next(copy.deepcopy(x) for x in bundle["resources"] if x["kind"] == "Driver" and x["metadata"]["name"] == "rook-ceph.rbd.csi.ceph.com")
            changed = copy.deepcopy(original["spec"])
            changed.setdefault("log", {})["verbosity"] = 3
            offset = len(capture.output().stdout)
            kubectl("patch", "driver", original["metadata"]["name"], "-n", NAMESPACE, "--type=json", "-p",
                    json.dumps([{"op": "test", "path": "/metadata/uid", "value": drivers[original["metadata"]["name"]]},
                                {"op": "replace", "path": "/spec", "value": changed}]))
            reconciled(offset, {original["metadata"]["name"]}, "changed Driver successful reconciliation")
            def changed_ready(rows):
                return sum(c.get("image") == plugin and "--v=3" in c.get("args", [])
                           for r in rows for c in r["spec"]["template"]["spec"]["containers"]) == 2
            updated = require_workloads(await_value(workloads, changed_ready, "synthetic verbosity reconciliation"), drivers, plugin,
                                        {n: 3 if n == original["metadata"]["name"] else 0 for n in DRIVERS})
            if {k: v["uid"] for k, v in updated.items()} != {k: v["uid"] for k, v in baseline.items()}:
                raise RuntimeError("CSI update replaced generated workload identities")
            offset = len(capture.output().stdout)
            kubectl("patch", "driver", original["metadata"]["name"], "-n", NAMESPACE, "--type=json", "-p",
                    json.dumps([{"op": "test", "path": "/metadata/uid", "value": drivers[original["metadata"]["name"]]},
                                {"op": "replace", "path": "/spec", "value": original["spec"]}]))
            reconciled(offset, {original["metadata"]["name"]}, "restored Driver successful reconciliation")
            def restored(rows):
                return require_workloads(rows, drivers, plugin, {n: 0 for n in DRIVERS}) == baseline
            # Wait for the known changed argument before strict comparison of the complete restored specification.
            await_value(workloads, lambda rows: all("--v=3" not in c.get("args", []) for r in rows for c in r["spec"]["template"]["spec"]["containers"]), "original verbosity")
            if not restored(workloads()):
                raise RuntimeError("CSI specification restoration differs from baseline")
            common.docker("stop", "--time=10", manager)
            alive_output = capture.output().stdout
            first_progress = reconciliation_progress(alive_output)
            if set(first_progress["successful_drivers"]) != DRIVERS:
                raise RuntimeError("native CSI stopped with unresolved reconciliation conflicts")
            capture.close()
            capture = common.CapturedContainer(manager)
            captures.append(capture)
            await_value(health, bool, "restarted manager probes")
            next_lease = await_value(lease, lambda x: x.get("spec", {}).get("holderIdentity") != first_lease["spec"]["holderIdentity"] and bool(x.get("spec", {}).get("renewTime")), "new native leader owner")
            next_progress = reconciled(0, DRIVERS, "restarted successful native reconciliations")
            if (next_lease["metadata"]["uid"] != first_lease["metadata"]["uid"] or
                    next_lease["spec"].get("leaseTransitions", 0) <= first_lease["spec"].get("leaseTransitions", 0) or
                    not restored(workloads()) or require_csidrivers(get("csidrivers.storage.k8s.io")["items"]) != baseline_csidrivers):
                raise RuntimeError("native CSI restart changed resource identity or generated specification")
            nodes = get("nodes")["items"]
            pods = get("pods")["items"]
            if nodes or any(p.get("spec", {}).get("nodeName") for p in pods):
                raise RuntimeError("agentless CSI generation unexpectedly scheduled a workload")
            return {"accepted": True, "bundle_sha256": BUNDLE_SHA256, "image": IMAGE,
                    "drivers": sorted(DRIVERS), "generated_workloads": len(baseline), "generated_csidrivers": len(csidrivers),
                    "generated_spec_sha256": hashlib.sha256(common.canonical(baseline)).hexdigest(),
                    "actual_service_account": "system:serviceaccount:rook-ceph:ceph-csi", "native_leader_restart": True,
                    "synthetic_change_and_restore": True, "resource_uids_preserved": True, "synthetic_nodes": 0,
                    "resolved_optimistic_conflict_events": first_progress["optimistic_conflict_events"] + next_progress["optimistic_conflict_events"],
                    "scheduled_plugins": 0, "production_writes": 0,
                    "measured_scratch_allocated_bytes": sum(p.lstat().st_blocks * 512 for p in scratch.rglob("*")),
                    "limitation": "native CSI controller generation only; plugins, kernel mounts and Rook/Ceph orchestration unqualified"}
        finally:
            if manager:
                require_manager(common.inspect(manager), api_id, identity, identifier)
                common.docker("rm", "--force", "--volumes", manager)
                if common.docker("inspect", manager, check=False).returncode == 0:
                    raise RuntimeError("owned CSI manager remains after cleanup")
            for captured in captures:
                captured.close()
                if captured.descriptor is not None or captured.process.poll() is None:
                    raise RuntimeError("CSI output capture was not reaped and closed")
            shutil.rmtree(identity)
            if image_id and image_id not in before_images:
                if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                    common.docker("image", "rm", IMAGE)
                    if common.docker("image", "inspect", image_id, check=False).returncode == 0:
                        raise RuntimeError("new unused CSI test image remains")

    return common.qualify(common.run_identifier(run_id), synthetic_check=controller)
