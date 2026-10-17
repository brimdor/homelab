#!/usr/bin/env python3
"""Synthetic CORE contract tests. Never run kubectl, Git, inventory tools, or APIs.

Run only through the required artifact launcher:
/Users/chris/.local/bin/test-artifacts run --repo /Users/chris/Documents/Github/homelab \
    --issue homelab-skills-alignment -- \
    /opt/homebrew/opt/yamllint/libexec/bin/python -B scripts/test_homelab_health.py

All fixtures are in memory. File reads, subprocesses and chart discovery use mocks;
no temporary files or credentials are needed. fixture() is a complete example of
the version-1 offline JSON contract documented by homelab-health.py.
"""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location("homelab_health", Path(__file__).with_name("homelab-health.py"))
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
NODES = ["charmander", "squirtle", "bulbasaur", "pikachu", "cyndaquil", "totodile",
         "growlithe", "arcanine", "sprigatito"]
CHARTS = ["system/argocd", "system/monitoring-system", "platform/external-secrets", "apps/example"]


def condition(kind, status, **extra):
    return {"type": kind, "status": status, **extra}


def resource(kind, name, spec=None, status=None, namespace="example", **metadata):
    meta = {"name": name, "generation": 1, **metadata}
    if namespace is not None:
        meta["namespace"] = namespace
    return {"apiVersion": "v1", "kind": kind, "metadata": meta,
            "spec": spec or {}, "status": status or {}}


def listing(kind, items=()):
    return {"apiVersion": "v1", "kind": kind + "List", "items": list(items)}


def fixture(charts=None):
    charts = CHARTS if charts is None else charts
    nodes = [resource("Node", node, namespace=None, status={"conditions": [
        condition("Ready", "True"), condition("MemoryPressure", "False"),
        condition("DiskPressure", "False"), condition("PIDPressure", "False")
    ]}) for node in NODES]
    pod = resource("Pod", "web", {"nodeName": "pikachu", "containers": [{"name": "web"}]},
                   {"phase": "Running", "conditions": [condition("Ready", "True")],
                    "containerStatuses": [{"name": "web", "ready": True, "state": {"running": {}}}]})
    completed_job = resource("Job", "finite", {"completions": 1},
                             {"succeeded": 1, "conditions": [condition("Complete", "True")]}, uid="finite-uid")
    completed_pod = resource("Pod", "finite-pod", {"nodeName": "squirtle", "restartPolicy": "Never",
                              "containers": [{"name": "worker"}]},
                             {"phase": "Succeeded", "containerStatuses": [{"name": "worker", "ready": False,
                              "state": {"terminated": {"exitCode": 0, "reason": "Completed"}}}]},
                             ownerReferences=[{"kind": "Job", "name": "finite", "uid": "finite-uid"}])
    deployment = resource("Deployment", "web", {"replicas": 1},
                          {"observedGeneration": 1, "replicas": 1, "readyReplicas": 1,
                           "availableReplicas": 1, "updatedReplicas": 1})
    statefulset = resource("StatefulSet", "database", {"replicas": 1},
                           {"observedGeneration": 1, "replicas": 1, "readyReplicas": 1, "updatedReplicas": 1})
    daemonset = resource("DaemonSet", "agent", {},
                         {"observedGeneration": 1, "desiredNumberScheduled": 9, "currentNumberScheduled": 9,
                          "updatedNumberScheduled": 9, "numberReady": 9, "numberAvailable": 9})
    apps = []
    for path in charts:
        app_name = path.split("/")[1]
        source = {"path": path, "repoURL": health.ARGO_REPO, "targetRevision": "master",
                  "helm": {"valueFiles": ["values.yaml"]}}
        destination = {"name": "in-cluster", "namespace": app_name}
        apps.append(resource("Application", app_name, {"source": source, "destination": destination},
                              {"sync": {"status": "Synced", "revision": REVISION,
                                        "comparedTo": {"source": copy.deepcopy(source),
                                                       "destination": {"server": health.ARGO_SERVER,
                                                                       "namespace": app_name}}},
                              "health": {"status": "Healthy"}, "operationState": {
                                  "phase": "Succeeded", "syncResult": {"revision": REVISION}}}, namespace="argocd"))
    return {
        "schema_version": 1,
        "repository": {"path": "/synthetic/homelab", "origin": health.ORIGIN, "branch": "master",
                       "revision": REVISION, "dirty": False},
        "inventory": {"metal": {"children": ["masters", "workers"]},
                      "masters": {"hosts": NODES[:3]}, "workers": {"hosts": NODES[3:]},
                      "_meta": {"hostvars": {"charmander": {"unused-secret": "DO_NOT_EMIT"}}}},
        "charts": charts[:],
        "sources": {
            "kubeconfig": {"clusters": [{"cluster": {"server": health.VIP}}]},
            "version": {"clientVersion": {"major": "1", "minor": "34"},
                        "serverVersion": {"major": "1", "minor": "34+"}},
            "nodes": listing("Node", nodes), "pods": listing("Pod", [pod, completed_pod]),
            "deployments": listing("Deployment", [deployment]), "statefulsets": listing("StatefulSet", [statefulset]),
            "daemonsets": listing("DaemonSet", [daemonset]), "jobs": listing("Job", [completed_job]),
            "applications": listing("Application", apps),
            "certificates": listing("Certificate", [resource("Certificate", "tls", status={
                "conditions": [condition("Ready", "True", observedGeneration=1)]})]),
            "pvcs": listing("PersistentVolumeClaim", [resource("PersistentVolumeClaim", "data", status={"phase": "Bound"})]),
            "warnings": listing("Event"), "ceph": {"status": "HEALTH_OK"},
        },
    }


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.no_process = patch.object(health.subprocess, "Popen", side_effect=AssertionError("Real subprocess forbidden"))
        self.no_process.start()
        self.addCleanup(self.no_process.stop)
        self.no_signals = patch.object(health.os, "killpg")
        self.no_signals.start()
        self.addCleanup(self.no_signals.stop)

    def evaluate(self, revision=None):
        return health.evaluate(self.data["sources"], health.inventory_nodes(self.data["inventory"]),
                               health.chart_paths(self.data["charts"]), revision)

    def codes(self):
        _, findings, errors = self.evaluate()
        self.assertEqual(errors, [])
        return {item["code"] for item in findings}

    def cli(self, args=(), read_error=None):
        stdout = io.StringIO()
        with patch.object(health, "read_json", side_effect=read_error, return_value=self.data), \
                contextlib.redirect_stdout(stdout):
            code = health.main(["--fixture", "synthetic.json", "--json", *args])
        return code, json.loads(stdout.getvalue())

    def test_core_pass_is_not_all_green(self):
        code, report = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["core_status"], "PASS")
        self.assertFalse(report["all_layers_verified"])
        self.assertIn("whole-homelab ALL GREEN completion", report["untested"])
        self.assertEqual(report["repository"]["identity"], "synthetic_unverified")
        self.assertEqual(len(report["expected"]["nodes"]), 9)
        self.assertNotIn("chikorita", report["expected"]["nodes"])
        self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_missing_active_node(self):
        self.data["sources"]["nodes"]["items"].pop()
        self.assertIn("expected_node_missing", self.codes())
        self.assertEqual(self.cli()[0], 1)

    def test_not_ready_or_unknown_or_missing_conditions(self):
        for value in ("False", "Unknown", None):
            with self.subTest(value=value):
                self.data = fixture()
                conditions = self.data["sources"]["nodes"]["items"][0]["status"]["conditions"]
                if value is None:
                    conditions.pop(0)
                else:
                    conditions[0]["status"] = value
                self.assertIn("node_condition", self.codes())

    def test_pressures_and_unschedulable(self):
        for kind in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            for value in ("True", "Unknown"):
                with self.subTest(kind=kind, value=value):
                    self.data = fixture()
                    conditions = self.data["sources"]["nodes"]["items"][0]["status"]["conditions"]
                    next(c for c in conditions if c["type"] == kind)["status"] = value
                    self.assertIn("node_condition", self.codes())
        self.data = fixture()
        self.data["sources"]["nodes"]["items"][0]["spec"]["unschedulable"] = True
        self.assertIn("node_unschedulable", self.codes())

    def test_retired_node_status_ignored_but_pods_not_ignored(self):
        retired = resource("Node", "chikorita", namespace=None,
                           status={"conditions": [condition("Ready", "Unknown")]})
        self.data["sources"]["nodes"]["items"].append(retired)
        self.assertEqual(self.codes(), set())
        pod = self.data["sources"]["pods"]["items"][0]
        pod["spec"]["nodeName"] = "chikorita"
        pod["status"]["conditions"][0]["status"] = "False"
        evidence, findings, errors = self.evaluate()
        self.assertEqual(errors, [])
        self.assertIn("pod_not_ready", {f["code"] for f in findings})
        self.assertFalse(evidence["pods"][0]["node_in_active_inventory"])
        self.assertEqual(evidence["nodes"][-1]["scope"], "retired_or_unknown_status_only")

    def test_ready_nonterminal_pods_outside_active_inventory_are_findings(self):
        for node in ("chikorita", "unknown-node"):
            for phase in ("Running", "Pending", "Unknown"):
                with self.subTest(node=node, phase=phase):
                    self.data = fixture()
                    pod = self.data["sources"]["pods"]["items"][0]
                    pod["spec"]["nodeName"] = node
                    pod["status"]["phase"] = phase
                    self.assertIn("pod_node_outside_active_inventory", self.codes())
        self.data = fixture()
        pod = self.data["sources"]["pods"]["items"][0]
        pod["spec"].pop("nodeName")
        pod["status"]["phase"] = "Pending"
        self.assertEqual(self.codes(), {"pod_phase_unhealthy"})
        self.data = fixture()
        self.data["sources"]["pods"]["items"][1]["spec"]["nodeName"] = "chikorita"
        self.assertEqual(self.codes(), set())

    def test_running_pod_ready_condition_and_each_container(self):
        pod = self.data["sources"]["pods"]["items"][0]
        pod["status"]["containerStatuses"][0]["ready"] = False
        self.assertIn("containers_not_ready", self.codes())
        pod["status"]["containerStatuses"][0]["ready"] = True
        pod["status"]["conditions"] = []
        self.assertIn("pod_not_ready", self.codes())
        pod["status"]["conditions"] = [condition("Ready", "True")]
        pod["spec"]["containers"].append({"name": "missing-status"})
        self.assertIn("containers_not_ready", self.codes())

    def test_waiting_container_and_init_failure(self):
        pod = self.data["sources"]["pods"]["items"][0]
        pod["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": "CrashLoopBackOff", "message": "DO_NOT_EMIT"}}
        pod["spec"]["initContainers"] = [{"name": "init"}]
        pod["status"]["initContainerStatuses"] = [{"name": "init", "ready": False,
                                                    "state": {"terminated": {"exitCode": 1, "reason": "Error"}}}]
        self.assertTrue({"containers_not_ready", "init_container_not_successful"}.issubset(self.codes()))
        self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))

    def test_sidecar_init_readiness(self):
        pod = self.data["sources"]["pods"]["items"][0]
        pod["spec"]["initContainers"] = [{"name": "sidecar", "restartPolicy": "Always"}]
        pod["status"]["initContainerStatuses"] = [{"name": "sidecar", "ready": True, "state": {"running": {}}}]
        self.assertEqual(self.codes(), set())
        pod["status"]["initContainerStatuses"][0]["ready"] = False
        self.assertIn("init_container_not_successful", self.codes())

    def test_completed_job_sidecar_shutdown_requires_proven_main_success(self):
        pod = self.data["sources"]["pods"]["items"][1]
        pod["spec"]["initContainers"] = [{"name": "sidecar", "restartPolicy": "Always"}]
        pod["status"]["initContainerStatuses"] = [{"name": "sidecar", "ready": False,
                                                   "state": {"terminated": {"exitCode": 137, "reason": "Error"}}}]
        self.assertEqual(self.codes(), set())
        completed = copy.deepcopy(self.data)
        for failure in ("wrong_uid", "job_not_complete", "job_failed", "main_failed", "ordinary_init", "not_terminated"):
            with self.subTest(failure=failure):
                self.data = copy.deepcopy(completed)
                pod = self.data["sources"]["pods"]["items"][1]
                if failure == "wrong_uid":
                    pod["metadata"]["ownerReferences"][0]["uid"] = "different-uid"
                elif failure == "job_not_complete":
                    self.data["sources"]["jobs"]["items"][0]["status"]["conditions"] = []
                elif failure == "job_failed":
                    self.data["sources"]["jobs"]["items"][0]["status"]["conditions"].append(condition("Failed", "True"))
                elif failure == "main_failed":
                    pod["status"]["containerStatuses"][0]["state"]["terminated"]["exitCode"] = 1
                elif failure == "ordinary_init":
                    pod["spec"]["initContainers"][0].pop("restartPolicy")
                else:
                    pod["status"]["initContainerStatuses"][0]["state"] = {"running": {}}
                self.assertIn("init_container_not_successful", self.codes())

    def test_legitimate_completed_job_pod(self):
        self.assertEqual(self.codes(), set())
        completed = self.evaluate()[0]["pods"][1]
        self.assertEqual(completed["containers"][0]["exit_code"], 0)
        self.assertFalse(completed["containers"][0]["ready"])
        self.assertEqual(completed["owners"][0]["kind"], "Job")

    def test_completed_cuda_validator_requires_exact_shape_and_current_policy_owner(self):
        owner = {"apiVersion": "nvidia.com/v1", "kind": "ClusterPolicy", "name": "cluster-policy", "uid": "DO_NOT_EMIT"}
        daemonset = copy.deepcopy(self.data["sources"]["daemonsets"]["items"][0])
        daemonset["metadata"].update({"namespace": "gpu-operator", "name": "nvidia-operator-validator",
                                      "ownerReferences": [copy.deepcopy(owner)]})
        self.data["sources"]["daemonsets"]["items"].append(daemonset)
        pod = resource("Pod", "nvidia-cuda-validator-6jwnw", {
            "nodeName": "sprigatito", "restartPolicy": "OnFailure", "serviceAccountName": "nvidia-operator-validator",
            "containers": [{"name": "nvidia-cuda-validator"}], "initContainers": [{"name": "cuda-validation"}]}, {
            "phase": "Succeeded", "containerStatuses": [{"name": "nvidia-cuda-validator", "ready": False,
                "state": {"terminated": {"exitCode": 0, "reason": "Completed"}}}],
            "initContainerStatuses": [{"name": "cuda-validation", "ready": False,
                "state": {"terminated": {"exitCode": 0, "reason": "Completed"}}}]},
            namespace="gpu-operator", labels={"app": "nvidia-cuda-validator"}, ownerReferences=[copy.deepcopy(owner)])
        self.data["sources"]["pods"]["items"].append(pod)
        for node, pod_name in (("sprigatito", "nvidia-cuda-validator-6jwnw"), ("arcanine", "nvidia-cuda-validator-ntzl7")):
            with self.subTest(node=node):
                pod["spec"]["nodeName"] = node
                pod["metadata"]["name"] = pod_name
                self.assertEqual(self.codes(), set())
                code, report = self.cli()
                self.assertEqual(code, 0)
                self.assertEqual(report["evidence"]["pods"][-1]["owners"][0]["kind"], "ClusterPolicy")
                self.assertNotIn("DO_NOT_EMIT", json.dumps(report))
        completed = copy.deepcopy(self.data)
        for target, path, value, expected in (
            ("pod", ("metadata", "ownerReferences", 0, "uid"), "different-uid", "pod_completion_not_proven"),
            ("pod", ("metadata", "ownerReferences", 0, "uid"), "", "pod_completion_not_proven"),
            ("pod", ("metadata", "ownerReferences"), [], "pod_completion_not_proven"),
            ("pod", ("metadata", "ownerReferences", 0, "apiVersion"), "nvidia.com/v2", "pod_completion_not_proven"),
            ("pod", ("metadata", "ownerReferences", 0, "name"), "other-policy", "pod_completion_not_proven"),
            ("pod", ("metadata", "ownerReferences", 0, "kind"), "OtherPolicy", "pod_completion_not_proven"),
            ("sources", ("daemonsets", "items"), [], "pod_completion_not_proven"),
            ("daemonset", ("metadata", "ownerReferences", 0, "uid"), "different-uid", "pod_completion_not_proven"),
            ("daemonset", ("metadata", "ownerReferences"), [], "pod_completion_not_proven"),
            ("daemonset", ("metadata", "ownerReferences", 0, "apiVersion"), "nvidia.com/v2", "pod_completion_not_proven"),
            ("daemonset", ("metadata", "ownerReferences", 0, "name"), "other-policy", "pod_completion_not_proven"),
            ("daemonset", ("metadata", "namespace"), "example", "pod_completion_not_proven"),
            ("daemonset", ("metadata", "name"), "other-validator", "pod_completion_not_proven"),
            ("daemonset", ("status", "numberReady"), 8, "daemonset_not_available"),
            ("daemonset", ("status", "numberAvailable"), 8, "daemonset_not_available"),
            ("daemonset", ("status", "currentNumberScheduled"), 8, "daemonset_not_available"),
            ("daemonset", ("status", "updatedNumberScheduled"), 8, "daemonset_not_available"),
            ("daemonset", ("status", "desiredNumberScheduled"), 0, "daemonset_not_available"),
            ("daemonset", ("status", "numberMisscheduled"), 1, "daemonset_not_available"),
            ("daemonset", ("status", "numberUnavailable"), 1, "daemonset_not_available"),
            ("daemonset", ("metadata", "generation"), 2, "controller_generation_stale"),
            ("daemonset", ("metadata", "deletionTimestamp"), "2026-10-17T00:00:00Z", "pod_completion_not_proven"),
            ("pod", ("metadata", "namespace"), "example", "pod_completion_not_proven"),
            ("pod", ("metadata", "name"), "other-validator-ntzl7", "pod_completion_not_proven"),
            ("pod", ("metadata", "labels", "app"), "other-validator", "pod_completion_not_proven"),
            ("pod", ("spec", "serviceAccountName"), "default", "pod_completion_not_proven"),
            ("pod", ("spec", "restartPolicy"), "Never", "pod_completion_not_proven"),
            ("pod", ("spec", "nodeName"), "chikorita", "pod_completion_not_proven"),
            ("pod", ("spec", "nodeName"), "", "pod_completion_not_proven"),
            ("pod", ("spec", "initContainers"), [], "pod_completion_not_proven"),
            ("pod", ("spec", "initContainers", 0, "restartPolicy"), "Always", "pod_completion_not_proven"),
            ("pod", ("status", "initContainerStatuses"), [], "init_container_not_successful"),
            ("pod", ("status", "initContainerStatuses", 0, "state"), {"terminated": {"exitCode": 1}}, "init_container_not_successful"),
            ("pod", ("status", "initContainerStatuses", 0, "state"), {"running": {}}, "init_container_not_successful"),
            ("pod", ("status", "containerStatuses", 0, "state"), {"terminated": {"exitCode": 1}}, "pod_completion_not_proven"),
            ("pod", ("status", "containerStatuses", 0, "state"), {"running": {}}, "pod_completion_not_proven"),
            ("pod", ("status", "containerStatuses"), [], "pod_completion_not_proven"),
            ("pod", ("metadata", "deletionTimestamp"), "2026-10-17T00:00:00Z", "pod_terminating"),
        ):
            with self.subTest(target=target, path=path, value=value):
                self.data = copy.deepcopy(completed)
                sources = self.data["sources"]
                obj = {"pod": sources["pods"]["items"][-1], "daemonset": sources["daemonsets"]["items"][-1],
                       "sources": sources}[target]
                for part in path[:-1]:
                    obj = obj[part]
                obj[path[-1]] = value
                if path == ("spec", "initContainers"):
                    sources["pods"]["items"][-1]["status"]["initContainerStatuses"] = []
                self.assertIn("pod_completion_not_proven", self.codes())
                self.assertIn(expected, self.codes())
                self.assertEqual(self.cli()[0], 1)
        self.data = copy.deepcopy(completed)
        self.data["sources"]["daemonsets"]["items"][-1]["status"].update({field: 0 for field in (
            "desiredNumberScheduled", "currentNumberScheduled", "updatedNumberScheduled", "numberReady", "numberAvailable")})
        self.assertEqual(self.codes(), {"pod_completion_not_proven"})
        for field, status_field in (("containers", "containerStatuses"), ("initContainers", "initContainerStatuses")):
            with self.subTest(unknown_container=field):
                self.data = copy.deepcopy(completed)
                pod = self.data["sources"]["pods"]["items"][-1]
                pod["spec"][field][0]["name"] = "unknown-container"
                pod["status"][status_field][0]["name"] = "unknown-container"
                self.assertIn("pod_completion_not_proven", self.codes())
                pod["status"][status_field][0]["name"] = "undeclared-container"
                self.assertEqual(self.cli()[0], 2)

    def test_indexed_job_success_policy_trusts_terminal_complete(self):
        for rule in ({"succeededIndexes": "0"}, {"succeededIndexes": "0-1", "succeededCount": 1},
                     {"succeededCount": 1}):
            with self.subTest(rule=rule):
                self.data = fixture()
                job = self.data["sources"]["jobs"]["items"][0]
                job["spec"].update({"completionMode": "Indexed", "completions": 4, "parallelism": 2,
                                    "successPolicy": {"rules": [rule]}})
                job["status"] = {"succeeded": 1, "completedIndexes": "0", "conditions": [
                    condition("SuccessCriteriaMet", "True", reason="SuccessPolicy"), condition("Complete", "True")]}
                self.assertEqual(self.codes(), set())
                self.assertEqual(self.cli()[0], 0)
                self.assertTrue(self.evaluate()[0]["jobs"][0]["complete"])
                job["status"]["conditions"].pop()
                job["status"]["active"] = 1
                self.assertFalse(self.evaluate()[0]["jobs"][0]["complete"])
                self.assertEqual(self.codes(), set())

    def test_finished_pod_in_active_parallel_job_with_native_sidecar_shutdown(self):
        for restart_policy in ("Never", "OnFailure"):
            for sidecar in (False, True):
                with self.subTest(restart_policy=restart_policy, sidecar=sidecar):
                    self.data = fixture()
                    job = self.data["sources"]["jobs"]["items"][0]
                    job["spec"].update({"completions": 2, "parallelism": 2})
                    job["status"] = {"active": 1, "succeeded": 1, "failed": 1}
                    pod = self.data["sources"]["pods"]["items"][1]
                    pod["spec"]["restartPolicy"] = restart_policy
                    if sidecar:
                        pod["spec"]["initContainers"] = [{"name": "sidecar", "restartPolicy": "Always"}]
                        pod["status"]["initContainerStatuses"] = [{"name": "sidecar", "ready": False,
                            "state": {"terminated": {"exitCode": 137, "reason": "Error"}}}]
                    self.assertEqual(self.codes(), set())
                    self.assertEqual(self.cli()[0], 0)
                    self.assertFalse(self.evaluate()[0]["jobs"][0]["complete"])

    def test_parallel_job_finished_pod_still_requires_ownership_and_success(self):
        for failure in ("wrong_uid", "missing_uid", "restart_always", "main_failed", "main_running", "missing_status",
                        "Failed", "FailureTarget", "Pending", "FailedPod", "ordinary_init_failed"):
            with self.subTest(failure=failure):
                self.data = fixture()
                job = self.data["sources"]["jobs"]["items"][0]
                job["spec"].update({"completions": 2, "parallelism": 2})
                job["status"] = {"active": 1, "succeeded": 1}
                pod = self.data["sources"]["pods"]["items"][1]
                pod["spec"]["initContainers"] = [{"name": "sidecar", "restartPolicy": "Always"}]
                pod["status"]["initContainerStatuses"] = [{"name": "sidecar", "ready": False,
                    "state": {"terminated": {"exitCode": 137}}}]
                expected = "pod_completion_not_proven"
                if failure == "wrong_uid":
                    pod["metadata"]["ownerReferences"][0]["uid"] = "different-uid"
                elif failure == "missing_uid":
                    pod["metadata"]["ownerReferences"][0].pop("uid")
                elif failure == "restart_always":
                    pod["spec"]["restartPolicy"] = "Always"
                elif failure == "main_failed":
                    pod["status"]["containerStatuses"][0]["state"]["terminated"]["exitCode"] = 1
                elif failure == "main_running":
                    pod["status"]["containerStatuses"][0]["state"] = {"running": {}}
                elif failure == "missing_status":
                    pod["status"]["containerStatuses"] = []
                elif failure in ("Failed", "FailureTarget"):
                    job["status"]["conditions"] = [condition(failure, "True")]
                    self.assertIn("job_failed_including_retained", self.codes())
                elif failure in ("Pending", "FailedPod"):
                    pod["status"]["phase"] = "Pending" if failure == "Pending" else "Failed"
                    expected = "pod_phase_unhealthy"
                else:
                    pod["spec"]["initContainers"][0].pop("restartPolicy")
                    expected = "init_container_not_successful"
                self.assertIn(expected, self.codes())
                self.assertIn("init_container_not_successful", self.codes())
                self.assertEqual(self.cli()[0], 1)

    def test_malformed_job_evidence_cannot_pass_completion_or_parallel_pod(self):
        for status in ({"active": True}, {"active": -1}, {"succeeded": "1"},
                       {"conditions": [condition("Complete", True)]},
                       {"conditions": [condition("Complete", "True"), condition("Complete", "False")]}):
            with self.subTest(status=status):
                self.data = fixture()
                self.data["sources"]["jobs"]["items"][0]["status"] = status
                self.assertEqual(self.cli()[0], 2)

    def test_succeeded_pod_requires_matching_successful_finite_job(self):
        for failure in ("no_owner", "missing_job", "wrong_uid", "job_not_complete", "container_failed", "restart_always"):
            with self.subTest(failure=failure):
                self.data = fixture()
                pod = self.data["sources"]["pods"]["items"][1]
                if failure == "no_owner":
                    pod["metadata"]["ownerReferences"] = []
                elif failure == "missing_job":
                    self.data["sources"]["jobs"]["items"] = []
                elif failure == "wrong_uid":
                    pod["metadata"]["ownerReferences"][0]["uid"] = "different-uid"
                elif failure == "job_not_complete":
                    self.data["sources"]["jobs"]["items"][0]["status"]["conditions"] = []
                elif failure == "container_failed":
                    pod["status"]["containerStatuses"][0]["state"]["terminated"]["exitCode"] = 1
                else:
                    pod["spec"]["restartPolicy"] = "Always"
                self.assertIn("pod_completion_not_proven", self.codes())

    def test_completed_job_retries_are_not_terminal_failures(self):
        job = self.data["sources"]["jobs"]["items"][0]
        job["status"]["failed"] = 1
        self.assertEqual(self.codes(), set())
        self.assertTrue(self.evaluate()[0]["jobs"][0]["complete"])
        for kind in ("Failed", "FailureTarget"):
            with self.subTest(kind=kind):
                job["status"]["conditions"] = [condition("Complete", "True"), condition(kind, "True")]
                self.assertTrue({"job_failed_including_retained", "pod_completion_not_proven",
                                 "job_completion_inconsistent"}.issubset(self.codes()))

    def test_failed_jobs_require_terminal_conditions_even_with_zero_failed_count(self):
        self.data["sources"]["pods"]["items"].pop()
        for kind in ("Failed", "FailureTarget"):
            with self.subTest(kind=kind):
                self.data["sources"]["jobs"]["items"][0]["status"] = {"conditions": [condition(kind, "True")]}
                self.assertIn("job_failed_including_retained", self.codes())

    def test_active_job_allowed_incomplete_inactive_job_reported(self):
        job = self.data["sources"]["jobs"]["items"][0]
        self.data["sources"]["pods"]["items"].pop()
        job["status"] = {"active": 1, "failed": 1}
        self.assertEqual(self.codes(), set())
        job["status"] = {}
        self.assertIn("job_incomplete_without_active_work", self.codes())

    def test_pod_pending_failed_unknown_not_completed_table_status(self):
        for phase in ("Pending", "Failed", "Unknown", "Completed"):
            with self.subTest(phase=phase):
                self.data = fixture()
                self.data["sources"]["pods"]["items"][0]["status"]["phase"] = phase
                self.assertIn("pod_phase_unhealthy", self.codes())

    def test_current_controller_generations_and_replicas(self):
        for key in ("deployments", "statefulsets"):
            with self.subTest(key=key):
                self.data = fixture()
                obj = self.data["sources"][key]["items"][0]
                obj["status"]["readyReplicas"] = 0
                obj["metadata"]["generation"] = 2
                self.assertTrue({"controller_generation_stale", "controller_replicas_unavailable"}.issubset(self.codes()))
        self.data = fixture()
        self.data["sources"]["deployments"]["items"][0]["status"]["availableReplicas"] = 0
        self.assertIn("controller_replicas_unavailable", self.codes())
        self.data = fixture()
        self.data["sources"]["deployments"]["items"][0]["status"]["conditions"] = [condition("Available", "False")]
        self.assertIn("controller_not_available_condition", self.codes())

    def test_daemonset_desired_ready_and_available(self):
        for field in ("numberReady", "numberAvailable", "updatedNumberScheduled"):
            with self.subTest(field=field):
                self.data = fixture()
                self.data["sources"]["daemonsets"]["items"][0]["status"][field] = 8
                self.assertIn("daemonset_not_available", self.codes())

    def test_zero_desired_controllers_report_retired_node_dependencies(self):
        for key in ("deployments", "statefulsets", "daemonsets"):
            for template in (
                {"nodeName": "chikorita"},
                {"nodeSelector": {"kubernetes.io/hostname": "chikorita"}},
                {"affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{"matchExpressions": [{"key": "kubernetes.io/hostname",
                                                                 "operator": "In", "values": ["chikorita"]}]}]}}}},
                {"affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{"matchFields": [{"key": "metadata.name",
                                                            "operator": "In", "values": ["chikorita"]}]}]}}}},
                {"affinity": {"nodeAffinity": {"preferredDuringSchedulingIgnoredDuringExecution": [{
                    "weight": 1, "preference": {"matchExpressions": [{"key": "kubernetes.io/hostname",
                                                                     "operator": "In", "values": ["chikorita"]}]}}]}}},
            ):
                with self.subTest(key=key, template=template):
                    self.data = fixture()
                    obj = self.data["sources"][key]["items"][0]
                    obj["spec"].update({"replicas": 0, "template": {"spec": template}})
                    obj["status"] = {field: 0 for field in obj["status"]}
                    obj["status"]["observedGeneration"] = 1
                    evidence, findings, errors = self.evaluate()
                    self.assertEqual(errors, [])
                    self.assertEqual({f["code"] for f in findings}, {"controller_node_dependency_outside_active_inventory"})
                    self.assertEqual(evidence[key][0]["desired"], 0)
                    self.assertEqual(evidence[key][0]["node_dependencies_outside_active_inventory"], ["chikorita"])

    def test_affinity_alternatives_report_dependencies_not_exclusions(self):
        expression = {"key": "kubernetes.io/hostname", "operator": "In", "values": ["chikorita", "pikachu"]}
        terms = [{"matchExpressions": [expression]}, {"matchExpressions": [
            {"key": "kubernetes.io/hostname", "operator": "In", "values": ["squirtle"]}]}]
        template = {"nodeSelector": {"kubernetes.io/hostname": "pikachu"}, "affinity": {"nodeAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": terms}}}}
        self.data["sources"]["deployments"]["items"][0]["spec"]["template"] = {"spec": template}
        self.assertEqual(self.codes(), {"controller_node_dependency_outside_active_inventory"})
        expression["operator"] = "NotIn"
        self.assertEqual(self.codes(), set())
        expression["operator"] = "In"
        expression["key"] = "example.invalid/unrelated-label"
        self.assertEqual(self.codes(), set())

    def test_missing_expected_apps_includes_separate_crd_charts(self):
        self.data["sources"]["applications"]["items"] = []
        _, findings, errors = self.evaluate()
        self.assertEqual(errors, [])
        missing = {f["name"] for f in findings if f["code"] == "expected_application_missing"}
        self.assertEqual(missing, {path.split("/")[1] for path in CHARTS})
        self.assertTrue({"monitoring-system", "external-secrets"}.issubset(missing))

    def test_exact_argo_sync_and_health_not_substring(self):
        app = self.data["sources"]["applications"]["items"][0]
        app["status"]["sync"]["status"] = "NotSynced"
        app["status"]["health"]["status"] = "NotHealthy"
        self.assertIn("application_not_synced_healthy", self.codes())

    def test_bad_source_repo_path_revision_and_comparison(self):
        for field, value in (("path", "archived/apps/argocd"), ("repoURL", "https://secret:DO_NOT_EMIT@example.invalid/repo"),
                             ("targetRevision", "feature")):
            with self.subTest(field=field):
                self.data = fixture()
                app = self.data["sources"]["applications"]["items"][0]
                app["spec"]["source"][field] = value
                self.assertIn("application_source_mismatch", self.codes())
                self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))
        self.data = fixture()
        self.data["sources"]["applications"]["items"][0]["status"]["sync"]["comparedTo"]["source"]["path"] = "apps/stale"
        self.assertIn("application_comparison_source_mismatch", self.codes())

    def test_application_destination_requires_local_cluster_and_chart_namespace(self):
        for cluster in ({"name": "in-cluster"}, {"server": health.ARGO_SERVER}):
            with self.subTest(cluster=cluster):
                app = self.data["sources"]["applications"]["items"][0]
                app["spec"]["destination"] = {**cluster, "namespace": "argocd"}
                self.assertEqual(self.codes(), set())
        for destination in (
            {}, {"namespace": "argocd"}, {"name": "other-cluster", "namespace": "argocd"},
            {"server": "https://DO_NOT_EMIT.invalid", "namespace": "argocd"},
            {"name": "in-cluster", "namespace": "DO_NOT_EMIT"},
            {"name": "in-cluster", "namespace": "example"}, {"name": "in-cluster"},
            {"name": "in-cluster", "server": "https://DO_NOT_EMIT.invalid", "namespace": "argocd"},
            {"name": "DO_NOT_EMIT", "server": health.ARGO_SERVER, "namespace": "argocd"},
        ):
            with self.subTest(destination=destination):
                self.data = fixture()
                self.data["sources"]["applications"]["items"][0]["spec"]["destination"] = destination
                self.assertIn("application_destination_mismatch", self.codes())
                self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))

    def test_compared_destination_normalizes_local_name_and_server(self):
        clusters = ({"name": "in-cluster"}, {"server": health.ARGO_SERVER},
                    {"name": "in-cluster", "server": health.ARGO_SERVER})
        for desired in clusters:
            for compared in clusters:
                with self.subTest(desired=desired, compared=compared):
                    self.data = fixture()
                    app = self.data["sources"]["applications"]["items"][0]
                    app["spec"]["destination"] = {**desired, "namespace": "argocd"}
                    app["status"]["sync"]["comparedTo"]["destination"] = {**compared, "namespace": "argocd"}
                    self.assertEqual(self.cli(["--expected-revision", REVISION])[0], 0)

    def test_stale_or_missing_compared_destination_blocks_even_expected_revision(self):
        for destination in ({}, {"namespace": "argocd"}, {"name": "in-cluster", "namespace": "example"},
                            {"name": "DO_NOT_EMIT", "namespace": "argocd"},
                            {"server": "https://DO_NOT_EMIT.invalid", "namespace": "argocd"},
                            {"name": "in-cluster", "server": "https://DO_NOT_EMIT.invalid", "namespace": "argocd"},
                            {"name": "DO_NOT_EMIT", "server": health.ARGO_SERVER, "namespace": "argocd"},
                            {"server": health.ARGO_SERVER, "namespace": "DO_NOT_EMIT"}, None):
            for revision in (None, REVISION):
                with self.subTest(destination=destination, revision=revision):
                    self.data = fixture()
                    compared = self.data["sources"]["applications"]["items"][0]["status"]["sync"]["comparedTo"]
                    if destination is None:
                        compared.pop("destination")
                    else:
                        compared["destination"] = destination
                    code, report = self.cli(["--expected-revision", revision] if revision else [])
                    self.assertEqual(code, 1)
                    self.assertIn("application_comparison_destination_mismatch", {f["code"] for f in report["findings"]})
                    self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_malformed_compared_destination_is_an_evidence_error(self):
        for destination in (None, [], "DO_NOT_EMIT"):
            with self.subTest(destination=destination):
                self.data = fixture()
                self.data["sources"]["applications"]["items"][0]["status"]["sync"]["comparedTo"]["destination"] = destination
                code, report = self.cli(["--expected-revision", REVISION])
                self.assertEqual(code, 2)
                self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_full_application_source_comparison_redacts_helm_and_plugin_values(self):
        for options in (
            {"helm": {"parameters": [{"name": "password", "value": "DO_NOT_EMIT"}]}},
            {"helm": {"values": "password: DO_NOT_EMIT", "valueFiles": ["private-values.yaml"]}},
            {"helm": {"valuesObject": {"password": "DO_NOT_EMIT"}}},
            {"plugin": {"name": "custom", "env": [{"name": "PASSWORD", "value": "DO_NOT_EMIT"}]}},
        ):
            with self.subTest(options=options):
                self.data = fixture()
                app = self.data["sources"]["applications"]["items"][0]
                app["spec"]["source"].update(options)
                self.assertIn("application_comparison_source_mismatch", self.codes())
                self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))
                app["status"]["sync"]["comparedTo"]["source"] = copy.deepcopy(app["spec"]["source"])
                self.assertEqual(self.codes(), set())
                self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))
                app["status"]["sync"]["comparedTo"]["source"]["directory"] = {"recurse": True}
                self.assertIn("application_comparison_source_mismatch", self.codes())

    def test_expected_revision_requires_current_observed_revision(self):
        self.assertEqual(self.cli(["--expected-revision", REVISION])[0], 0)
        for observed in (OTHER_REVISION, None, "master"):
            with self.subTest(observed=observed):
                self.data = fixture()
                app = self.data["sources"]["applications"]["items"][0]
                if observed is None:
                    app["status"]["sync"].pop("revision")
                else:
                    app["status"]["sync"]["revision"] = observed
                code, report = self.cli(["--expected-revision", REVISION])
                self.assertEqual(code, 1)
                self.assertIn("expected_revision_not_observed", {f["code"] for f in report["findings"]})
        self.assertEqual(self.cli(["--expected-revision", "master"])[0], 2)

    def test_explicit_empty_expected_revision_is_rejected_before_collection(self):
        with patch.object(health, "collect_live", side_effect=AssertionError("unexpected collection")) as collector:
            code, _ = self.cli(["--expected-revision", ""])
            self.assertEqual(code, 2)
            collector.assert_not_called()

    def test_expected_revision_accepts_67_unchanged_apps_with_older_successful_operations(self):
        self.data = fixture(CHARTS + [f"apps/unchanged-{index}" for index in range(63)])
        for app in self.data["sources"]["applications"]["items"]:
            app["status"]["operationState"]["syncResult"]["revision"] = OTHER_REVISION
        code, report = self.cli(["--expected-revision", REVISION])
        self.assertEqual(code, 0)
        self.assertEqual(report["findings"], [])
        self.assertEqual(len(report["evidence"]["applications"]), 67)
        for app in report["evidence"]["applications"]:
            self.assertEqual(app["observed_revision"], REVISION)
            self.assertEqual(app["last_operation_revision"], OTHER_REVISION)
            self.assertEqual(app["operation_phase"], "Succeeded")
            self.assertNotIn("deployed_revision", app)

    def test_expected_revision_allows_missing_operation_history(self):
        for operation in (None, {}, {"phase": "Succeeded"}, {"phase": "Succeeded", "syncResult": {}}):
            with self.subTest(operation=operation):
                self.data = fixture()
                for app in self.data["sources"]["applications"]["items"]:
                    if operation is None:
                        app["status"].pop("operationState")
                    else:
                        app["status"]["operationState"] = copy.deepcopy(operation)
                code, report = self.cli(["--expected-revision", REVISION])
                self.assertEqual(code, 0)
                self.assertTrue(all(app["last_operation_revision"] is None for app in report["evidence"]["applications"]))

    def test_expected_revision_still_requires_current_comparison_sync_and_health(self):
        for failure, expected in (
            ("source_path", "application_source_mismatch"),
            ("source_options", "application_comparison_source_mismatch"),
            ("destination", "application_destination_mismatch"),
            ("compared_destination", "application_comparison_destination_mismatch"),
            ("sync", "application_not_synced_healthy"),
            ("health", "application_not_synced_healthy"),
        ):
            with self.subTest(failure=failure):
                self.data = fixture()
                app = self.data["sources"]["applications"]["items"][0]
                app["status"]["operationState"]["syncResult"]["revision"] = OTHER_REVISION
                if failure == "source_path":
                    app["spec"]["source"]["path"] = "apps/stale"
                elif failure == "source_options":
                    app["spec"]["source"]["helm"]["parameters"] = [{"name": "password", "value": "DO_NOT_EMIT"}]
                elif failure == "destination":
                    app["spec"]["destination"]["namespace"] = "example"
                elif failure == "compared_destination":
                    app["status"]["sync"]["comparedTo"]["destination"]["server"] = "https://DO_NOT_EMIT.invalid"
                elif failure == "sync":
                    app["status"]["sync"]["status"] = "OutOfSync"
                else:
                    app["status"]["health"]["status"] = "Degraded"
                code, report = self.cli(["--expected-revision", REVISION])
                self.assertEqual(code, 1)
                self.assertIn(expected, {f["code"] for f in report["findings"]})
                self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_failed_or_active_operations_remain_findings_at_expected_revision(self):
        for phase in ("Failed", "Error", "Running", "Terminating"):
            for args in ([], ["--expected-revision", REVISION]):
                with self.subTest(phase=phase, args=args):
                    self.data = fixture()
                    app = self.data["sources"]["applications"]["items"][0]
                    app["status"]["operationState"]["phase"] = phase
                    code, report = self.cli(args)
                    self.assertEqual(code, 1)
                    codes = {f["code"] for f in report["findings"]}
                    self.assertIn("application_operation_not_succeeded", codes)
                    self.assertNotIn("expected_revision_not_observed", codes)

    def test_certificates_ready_current_and_pvc_bound(self):
        cert = self.data["sources"]["certificates"]["items"][0]
        cert["status"]["conditions"][0]["status"] = "False"
        cert["metadata"]["generation"] = 2
        self.data["sources"]["pvcs"]["items"][0]["status"]["phase"] = "Pending"
        self.assertTrue({"certificate_not_ready", "certificate_generation_not_observed", "pvc_not_bound"}.issubset(self.codes()))

    def test_warning_metadata_redacts_messages(self):
        event = resource("Event", "warning-event")
        event.update({"type": "Warning", "reason": "FailedMount", "count": 7, "message": "DO_NOT_EMIT",
                      "firstTimestamp": "2026-10-10T10:00:00Z", "lastTimestamp": "2026-10-10T11:00:00Z",
                      "involvedObject": {"kind": "Pod", "name": "web", "namespace": "example"}})
        self.data["sources"]["warnings"]["items"] = [event]
        code, report = self.cli()
        self.assertEqual(code, 1)
        row = report["evidence"]["warnings"][0]
        self.assertEqual(row["reason"], "FailedMount")
        self.assertEqual(row["count"], 7)
        self.assertEqual(row["object"]["name"], "web")
        self.assertIsNotNone(row["first_timestamp"])
        self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_identifier_shaped_diagnostics_are_redacted_not_hashed(self):
        for secret in ("DO_NOT_EMIT", "secret.token_123", "c" * 64):
            with self.subTest(secret=secret):
                self.data = fixture()
                node = self.data["sources"]["nodes"]["items"][0]
                node["status"]["conditions"][0]["reason"] = secret
                node["status"]["conditions"].append(condition(secret, "True", reason=secret))
                pod = self.data["sources"]["pods"]["items"][0]
                pod["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": secret}}
                pod["spec"]["initContainers"] = [{"name": "init"}]
                pod["status"]["initContainerStatuses"] = [{"name": "init", "ready": False,
                                                           "state": {"terminated": {"exitCode": 0, "reason": secret}}}]
                event = resource("Event", "warning-event")
                event.update({"type": "Warning", "reason": secret,
                              "involvedObject": {"kind": "Pod", "name": "web", "namespace": "example"}})
                self.data["sources"]["warnings"]["items"] = [event]
                app = self.data["sources"]["applications"]["items"][0]
                app["status"]["conditions"] = [{"type": secret}]
                _, report = self.cli()
                self.assertNotIn(secret, json.dumps(report))
                evidence = report["evidence"]
                self.assertEqual(evidence["nodes"][0]["conditions"][0]["reason"], "[redacted]")
                self.assertEqual(evidence["nodes"][0]["conditions"][-1]["type"], "[redacted]")
                self.assertEqual(evidence["pods"][0]["containers"][0]["reason"], "[redacted]")
                self.assertEqual(evidence["pods"][0]["init_containers"][0]["reason"], "[redacted]")
                self.assertEqual(evidence["warnings"][0]["reason"], "[redacted]")
                self.assertEqual(evidence["applications"][0]["conditions"][0]["type"], "[redacted]")

    def test_job_ownership_uses_raw_uid_without_emitting_it(self):
        self.data["sources"]["jobs"]["items"][0]["metadata"]["uid"] = "DO_NOT_EMIT"
        self.data["sources"]["pods"]["items"][1]["metadata"]["ownerReferences"][0]["uid"] = "DO_NOT_EMIT"
        self.assertEqual(self.codes(), set())
        self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))
        self.data["sources"]["pods"]["items"][1]["metadata"]["ownerReferences"][0]["uid"] = "different-uid"
        self.assertIn("pod_completion_not_proven", self.codes())

    def test_ceph_requires_exact_health_ok(self):
        self.data["sources"]["ceph"] = "HEALTH_OK\n"
        self.assertEqual(self.codes(), set())
        self.data["sources"]["ceph"] = {"status": "HEALTH_WARN", "checks": {"secret": "DO_NOT_EMIT"}}
        self.assertIn("ceph_not_health_ok", self.codes())
        self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli()[1]))
        self.data["sources"]["ceph"] = "HEALTH_OK but not actually healthy"
        self.assertEqual(self.cli()[0], 2)

    def test_client_skew_and_missing_server_version(self):
        for client_minor, expected in (("33", True), ("34", True), ("35+", True), ("32", False), ("36", False)):
            with self.subTest(client_minor=client_minor):
                version = copy.deepcopy(self.data["sources"]["version"])
                version["clientVersion"]["minor"] = client_minor
                self.assertEqual(health.versions(version)["compatible"], expected)
        self.data["sources"]["version"]["clientVersion"]["minor"] = "36"
        self.assertIn("client_server_version_skew", self.codes())
        self.data["sources"]["version"].pop("serverVersion")
        self.assertEqual(self.cli()[0], 2)

    def test_wrong_vip_insecure_tls_and_proxy_rejected(self):
        for field, value in (("server", "https://10.0.20.11:6443"), ("insecure-skip-tls-verify", True),
                             ("proxy-url", "https://proxy.invalid")):
            with self.subTest(field=field):
                self.data = fixture()
                self.data["sources"]["kubeconfig"]["clusters"][0]["cluster"][field] = value
                self.assertEqual(self.cli()[0], 2)

    def test_tables_headers_invalid_schema_and_boolean_counts_cannot_pass(self):
        for bad in ("NAME STATUS\nall Ready\n", {"kind": "Table", "items": []},
                    {"kind": "NodeList"}, {"kind": "NodeList", "items": "Ready"}):
            with self.subTest(bad=bad):
                self.data = fixture()
                self.data["sources"]["nodes"] = bad
                self.assertEqual(self.cli()[0], 2)
        self.data = fixture()
        self.data["sources"]["deployments"]["items"][0]["status"]["readyReplicas"] = True
        self.assertEqual(self.cli()[0], 2)

    def test_failed_and_missing_reads_never_pass_or_leak_diagnostics(self):
        self.data["sources"]["pods"] = {"error": "DO_NOT_EMIT"}
        code, report = self.cli()
        self.assertEqual(code, 2)
        self.assertEqual(report["core_status"], "ERROR")
        self.assertNotIn("DO_NOT_EMIT", json.dumps(report))
        del self.data["sources"]["pods"]
        self.assertEqual(self.cli()[0], 2)

    def test_fixture_file_and_cli_errors_have_json_nonzero(self):
        code, report = self.cli(read_error=health.EvidenceError("Cannot read fixture/inventory JSON file."))
        self.assertEqual(code, 2)
        self.assertFalse(report["core_passed"])
        self.assertEqual(self.cli(["--unknown", "DO_NOT_EMIT"])[0], 2)
        self.assertNotIn("DO_NOT_EMIT", json.dumps(self.cli(["--unknown", "DO_NOT_EMIT"])[1]))
        self.data["schema_version"] = 99
        self.assertEqual(self.cli()[0], 2)

    def test_unexpected_errors_remain_json_without_exception_text(self):
        code, report = self.cli(read_error=RuntimeError("DO_NOT_EMIT"))
        self.assertEqual(code, 2)
        self.assertFalse(report["core_passed"])
        self.assertNotIn("DO_NOT_EMIT", json.dumps(report))

    def test_inventory_nested_yaml_and_json_current_active_only(self):
        nested = {"all": {"vars": {}}, "metal": {"children": {
            "masters": {"hosts": {node: {} for node in NODES[:3]}},
            "workers": {"hosts": {node: {} for node in NODES[3:]}}
        }}}
        self.assertEqual(health.inventory_nodes(nested), sorted(NODES))
        self.assertEqual(health.inventory_nodes(self.data["inventory"]), sorted(NODES))
        additional = copy.deepcopy(self.data["inventory"])
        additional["metal"]["hosts"] = ["additional-active-node"]
        self.assertIn("additional-active-node", health.inventory_nodes(additional))
        self.data["inventory"]["workers"]["children"] = ["metal"]
        self.assertEqual(self.cli()[0], 2)

    def test_fixture_inventory_override_only_and_no_repository_commands(self):
        inventory = copy.deepcopy(self.data["inventory"])
        inventory["workers"]["hosts"] = NODES[3:] + ["new-active-node"]
        output = io.StringIO()
        with patch.object(health, "read_json", side_effect=[self.data, inventory]), contextlib.redirect_stdout(output):
            code = health.main(["--fixture", "fixture.json", "--inventory", "inventory.json", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("new-active-node", json.loads(output.getvalue())["expected"]["nodes"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(health.main(["--inventory", "inventory.json", "--json"]), 2)
        self.assertIn("only with --fixture", json.loads(output.getvalue())["errors"][0]["detail"])

    def test_archived_and_duplicate_charts_rejected(self):
        for charts in (["archived/apps/example"], ["apps/archived"], ["apps/../example"],
                       ["system/example", "apps/example"], []):
            with self.subTest(charts=charts):
                self.data["charts"] = charts
                self.assertEqual(self.cli()[0], 2)

    def test_discovery_only_direct_charts_including_crd_appset(self):
        root = Path("/synthetic/homelab")
        children = {root / layer: [root / path for path in CHARTS if path.startswith(layer + "/")]
                    for layer in ("system", "platform", "apps")}
        children[root / "apps"].append(root / "apps/non-chart")
        chart_files = {root / path / "Chart.yaml" for path in CHARTS}
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(Path, "iterdir", autospec=True, side_effect=lambda path: iter(children[path])), \
                patch.object(Path, "exists", autospec=True, side_effect=lambda path: path in chart_files), \
                patch.object(Path, "is_file", return_value=True):
            self.assertEqual(health.discover_charts(root), health.chart_paths(CHARTS))
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(health.EvidenceError):
                health.discover_charts(root)

    def test_missing_inventory_tools_does_not_install_or_probe(self):
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(health.importlib, "import_module", side_effect=ModuleNotFoundError), \
                patch.object(health.shutil, "which", return_value=None):
            with self.assertRaisesRegex(health.EvidenceError, "nothing is installed"):
                health.load_inventory(health.CANONICAL, float("inf"))

    def test_existing_pyyaml_inventory_parser_reads_only_synthetic_input(self):
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(Path, "open", return_value=io.StringIO(json.dumps(self.data["inventory"]))), \
                patch.object(health, "command", side_effect=AssertionError("Inventory subprocess forbidden")):
            nodes, reader = health.load_inventory(health.CANONICAL, float("inf"))
        self.assertEqual(nodes, sorted(NODES))
        self.assertEqual(reader, "PyYAML")

    def test_ansible_inventory_fallback_uses_canonical_file(self):
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(health.time, "monotonic", return_value=100.0), \
                patch.object(health.importlib, "import_module", side_effect=ModuleNotFoundError), \
                patch.object(health.shutil, "which", return_value="/installed/ansible-inventory"), \
                patch.object(health, "command", return_value=json.dumps(self.data["inventory"])) as command:
            nodes, reader = health.load_inventory(health.CANONICAL, 1234.0)
        self.assertEqual(nodes, sorted(NODES))
        self.assertEqual(reader, "ansible-inventory")
        command.assert_called_once_with(["ansible-inventory", "-i", str(health.CANONICAL / "metal/inventories/prod.yml"), "--list"],
                                        1234.0)

    def test_repository_identity_master_dirty_and_other_host(self):
        for platform, root in (("darwin", health.CANONICAL), ("linux", Path("/synthetic/homelab"))):
            with self.subTest(platform=platform), patch.object(health.sys, "platform", platform), \
                    patch.object(Path, "resolve", autospec=True, side_effect=lambda path: path), \
                    patch.object(Path, "is_file", return_value=True), patch.object(health, "command", side_effect=[
                        str(root), health.ORIGIN, "master", REVISION, " M apps/example/values.yaml\n"
                    ]) as command:
                repo, metadata = health.repository_metadata(root, 1234.0)
                self.assertEqual(repo, root)
                self.assertTrue(metadata["dirty"])
                self.assertEqual(metadata["changed_entries"], 1)
                self.assertTrue(all(call.args[0][0] == "git" for call in command.call_args_list))
                self.assertTrue(all(call.args[1] == 1234.0 for call in command.call_args_list))
        with patch.object(health.sys, "platform", "darwin"):
            with self.assertRaisesRegex(health.EvidenceError, "macOS requires"):
                health.repository_metadata(Path("/not-canonical"), float("inf"))

    def test_bad_repository_origin_or_branch_rejected_without_raw_url(self):
        for responses in ([str(health.CANONICAL), "https://secret:DO_NOT_EMIT@example.invalid/repo"],
                          [str(health.CANONICAL), health.ORIGIN, "feature"]):
            with patch.object(health, "command", side_effect=responses):
                with self.assertRaises(health.EvidenceError) as error:
                    health.repository_metadata(health.CANONICAL, float("inf"))
                self.assertNotIn("DO_NOT_EMIT", str(error.exception))

    def test_live_collector_bounded_pinned_context_and_failed_reads(self):
        sources = self.data["sources"]
        def reply(argv, deadline):
            self.assertIsInstance(deadline, float)
            self.assertIn("--request-timeout=15000ms", argv)
            self.assertEqual(argv[argv.index("--kubeconfig") + 1], str(health.CANONICAL / "metal/kubeconfig.yaml"))
            if "config" in argv:
                self.assertNotIn("--raw", argv)
                return json.dumps(sources["kubeconfig"])
            self.assertIn("--server=" + health.VIP, argv)
            if "version" in argv:
                return json.dumps(sources["version"])
            if "exec" in argv:
                self.assertEqual(argv[-4:], ["ceph", "health", "-f", "json"])
                return json.dumps(sources["ceph"])
            resource_name = argv[argv.index("get") + 1]
            key = next(key for key, resource in health.RESOURCES.items() if resource[0] == resource_name)
            if key == "pods":
                raise health.EvidenceError("Command failed; raw stdout/stderr suppressed.")
            return json.dumps(sources[key])
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(health, "command", side_effect=reply):
            collected, receipts = health.collect_live(health.CANONICAL, health.time.monotonic() + 240)
        self.assertIn("error", collected["pods"])
        self.assertEqual(receipts["pods"]["read"], "error")
        self.assertTrue(health.evaluate(collected, NODES, health.chart_paths(CHARTS))[2])

    def test_live_gate_stops_before_queries_on_wrong_vip_or_skew(self):
        for failure in ("vip", "skew"):
            self.data = fixture()
            if failure == "vip":
                self.data["sources"]["kubeconfig"]["clusters"][0]["cluster"]["server"] = "https://wrong.invalid"
            else:
                self.data["sources"]["version"]["clientVersion"]["minor"] = "36"
            replies = [json.dumps(self.data["sources"][key]) for key in ("kubeconfig", "version")]
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                    patch.object(health, "command", side_effect=replies) as command:
                with self.assertRaises(health.EvidenceError):
                    health.collect_live(health.CANONICAL, health.time.monotonic() + 240)
                self.assertEqual(command.call_count, 1 if failure == "vip" else 2)

    def test_shared_deadline_includes_five_git_commands_inventory_and_api(self):
        clock = [100.0]
        git_replies = iter([str(health.CANONICAL), health.ORIGIN, "master", REVISION, ""])
        calls = []

        def reply(argv, deadline):
            calls.append(argv)
            self.assertEqual(deadline, 340.0)
            self.assertLess(clock[0], deadline)
            if argv[0] == "git":
                clock[0] += 20
                return next(git_replies)
            if argv[0] == "ansible-inventory":
                clock[0] += 20
                return json.dumps(self.data["inventory"])
            timeout = next(arg for arg in argv if arg.startswith("--request-timeout="))
            self.assertEqual(timeout, f"--request-timeout={min(15000, int((deadline - clock[0]) * 1000))}ms")
            clock[0] += 10
            if "config" in argv:
                key = "kubeconfig"
            elif "version" in argv:
                key = "version"
            else:
                resource_name = argv[argv.index("get") + 1]
                key = next(key for key, resource in health.RESOURCES.items() if resource[0] == resource_name)
            return json.dumps(self.data["sources"][key])

        output = io.StringIO()
        with patch.object(Path, "resolve", autospec=True, side_effect=lambda path: path), \
                patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_symlink", return_value=False), \
                patch.object(health.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(health.importlib, "import_module", side_effect=ModuleNotFoundError), \
                patch.object(health.shutil, "which", return_value="/installed/ansible-inventory"), \
                patch.object(health, "discover_charts", return_value=health.chart_paths(CHARTS)), \
                patch.object(health, "command", side_effect=reply), contextlib.redirect_stdout(output):
            self.assertEqual(health.main(["--repo", str(health.CANONICAL), "--json"]), 2)
        report = json.loads(output.getvalue())
        self.assertEqual(sum(argv[0] == "git" for argv in calls), 5)
        self.assertEqual(sum(argv[0] == "ansible-inventory" for argv in calls), 1)
        self.assertEqual(sum(argv[0] == "kubectl" for argv in calls), 12)
        self.assertFalse(any("exec" in argv for argv in calls))
        self.assertEqual(report["collection"]["sources"]["ceph"]["detail"], "Collection deadline exceeded.")

    def test_api_deadline_remainder_never_resets_or_uses_zero_timeout(self):
        for remaining, timeout in ((2.0, "--request-timeout=2000ms"), (0.0005, None), (0.0, None)):
            with self.subTest(remaining=remaining), patch.object(Path, "is_file", return_value=True), \
                    patch.object(Path, "is_symlink", return_value=False), \
                    patch.object(health.time, "monotonic", return_value=100.0), \
                    patch.object(health, "command", side_effect=health.EvidenceError("Synthetic read failure.")) as command:
                with self.assertRaises(health.EvidenceError):
                    health.collect_live(health.CANONICAL, 100.0 + remaining)
                if timeout is None:
                    command.assert_not_called()
                else:
                    self.assertIn(timeout, command.call_args.args[0])
                    self.assertEqual(command.call_args.args[1], 102.0)

    def test_expired_shared_deadline_stops_before_child_start(self):
        with patch.object(health.time, "monotonic", return_value=0.0):
            with self.assertRaisesRegex(health.EvidenceError, "Collection deadline exceeded"):
                health.command(["synthetic-command"], 0.0)
        health.subprocess.Popen.assert_not_called()

    def test_command_failure_discards_raw_stdout_and_stderr(self):
        process = MagicMock()
        process.wait.return_value = 1
        process.poll.return_value = 1
        selector = MagicMock()
        selector.get_map.side_effect = [True, False]
        key = MagicMock(fd=123)
        selector.select.return_value = [(key, None)]
        with patch.object(health.subprocess, "Popen", return_value=process) as popen, \
                patch.object(health.selectors, "DefaultSelector") as factory, \
                patch.object(health.os, "read", return_value=b"DO_NOT_EMIT"):
            factory.return_value.__enter__.return_value = selector
            with self.assertRaises(health.EvidenceError) as error:
                health.command(["synthetic-command"])
        self.assertNotIn("DO_NOT_EMIT", str(error.exception))
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        health.os.killpg.assert_called_with(process.pid, health.signal.SIGKILL)

    def test_command_output_bound_and_timeout(self):
        for failure in ("size", "timeout", "shared_deadline"):
            with self.subTest(failure=failure):
                process = MagicMock()
                process.poll.return_value = None
                selector = MagicMock()
                selector.get_map.side_effect = [True, False]
                selector.select.return_value = [(MagicMock(fd=123), None)]
                clocks = {"size": [0, 0, 1], "timeout": [0, 0, 21], "shared_deadline": [0, 0, 6]}[failure]
                with patch.object(health.subprocess, "Popen", return_value=process), \
                        patch.object(health.selectors, "DefaultSelector") as factory, \
                        patch.object(health.time, "monotonic", side_effect=clocks), \
                        patch.object(health, "MAX_BYTES", 3), patch.object(health.os, "read", return_value=b"large"):
                    factory.return_value.__enter__.return_value = selector
                    with self.assertRaises(health.EvidenceError):
                        health.command(["synthetic-command"], 5 if failure == "shared_deadline" else None)
                    process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
