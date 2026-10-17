#!/usr/bin/env python3
"""Closed fake-API checks. No Kubernetes, Git, subprocesses, or backups are allowed."""

import sys

sys.dont_write_bytecode = True

import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit


SPEC = importlib.util.spec_from_file_location("retire_workloads", Path(__file__).with_name("retire-workloads.py"))
retire = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retire)
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
RESOURCE_TYPES = {resource: (api_version, kind) for kind, (resource, api_version) in retire.WORKLOADS.items()}
RESOURCE_TYPES.update({"namespaces": ("v1", "Namespace"), "persistentvolumes": ("v1", "PersistentVolume"),
    "persistentvolumeclaims": ("v1", "PersistentVolumeClaim"), "secrets": ("v1", "Secret"),
    "configmaps": ("v1", "ConfigMap"), "services": ("v1", "Service"),
    "volumeattachments.storage.k8s.io": ("storage.k8s.io/v1", "VolumeAttachment"),
    "storageclasses.storage.k8s.io": ("storage.k8s.io/v1", "StorageClass"),
    "applications.argoproj.io": ("argoproj.io/v1alpha1", "Application")})


def metadata(resource_name, uid, namespace=""):
    result = {"name": resource_name, "uid": uid, "resourceVersion": "1"}
    if namespace:
        result["namespace"] = namespace
    return result


def fixture(disposition="archived", policy="Delete", namespace="old-app", archived_path=None):
    archived_path = archived_path or "archived/apps/" + namespace
    plan = {"version": 1, "reason": "Owner authorizes exact retirement without backups for eligible data.",
            "namespaces": [], "volumes": [{"name": "pv-old", "uid": "pv-uid", "claim_namespace": namespace,
                "claim_name": "data", "claim_uid": "claim-uid", "driver": retire.DRIVER,
                "volume_handle": "rbd-old", "disposition": disposition}], "historical_jobs": [], "retired_workloads": [],
            "inline_env_exemptions": []}
    objects = {resource: {} for resource in retire.RESOURCES}
    if disposition == "archived":
        plan["namespaces"] = [{"name": namespace, "uid": "namespace-uid", "archived_path": archived_path}]
        objects["namespaces"][("", namespace)] = {"metadata": metadata(namespace, "namespace-uid")}
    objects["persistentvolumes"][("", "pv-old")] = {
        "metadata": metadata("pv-old", "pv-uid"), "spec": {"storageClassName": "standard-rwo",
            "persistentVolumeReclaimPolicy": policy, "csi": {"driver": retire.DRIVER, "volumeHandle": "rbd-old",
                "volumeAttributes": {"clusterID": "rook-ceph", "pool": "standard-rwo", "imageName": "rbd-old"}},
            "claimRef": {"namespace": namespace, "name": "data", "uid": "claim-uid"}}, "status": {"phase": "Bound"}}
    objects["persistentvolumeclaims"][(namespace, "data")] = {
        "metadata": metadata("data", "claim-uid", namespace),
        "spec": {"volumeName": "pv-old", "storageClassName": "standard-rwo"}}
    objects["storageclasses.storage.k8s.io"][("", "standard-rwo")] = {
        "metadata": metadata("standard-rwo", "sc-uid"), "provisioner": retire.DRIVER,
        "parameters": {"clusterID": "rook-ceph", "pool": "standard-rwo"}}
    source = {"head": "a" * 40, "active": set(), "directories": {archived_path}, "texts": [],
              "archive_aliases": retire.archive_aliases({archived_path}, {})}
    return plan, objects, source


class FakeAPI:
    """Dispatch is closed: an unexpected verb/resource/argument is a test failure."""

    def __init__(self, objects):
        self.objects = copy.deepcopy(objects)
        self.writes = []
        self.reads = []
        self.conflict = False
        self.unknown_applied = False
        self.keep_namespace = False
        self.read_failure = False
        self.extra_metadata = []
        self.empty_resources = set()
        self.metadata_failure = False

    def typed(self, resource, obj):
        result = copy.deepcopy(obj)
        if resource in RESOURCE_TYPES:
            api_version, kind = RESOURCE_TYPES[resource]
            result.setdefault("apiVersion", api_version)
            result.setdefault("kind", kind)
        return result

    def discovered(self):
        return ({resource for resource in RESOURCE_TYPES if resource not in retire.CLUSTER}
                | {resource for resource, _ in self.extra_metadata} | self.empty_resources)

    def metadata_resources(self):
        self.reads.append(("metadata_resources",))
        if self.read_failure or self.metadata_failure:
            raise retire.Refusal("Fake metadata discovery failed")
        result = []
        for resource in sorted(self.discovered()):
            if resource.endswith(".metrics.k8s.io"):
                continue
            api_version, kind = RESOURCE_TYPES.get(resource, ("example.io/v1", "Empty"))
            for extra_resource, obj in self.extra_metadata:
                if extra_resource == resource:
                    api_version, kind = self.typed(resource, obj)["apiVersion"], self.typed(resource, obj)["kind"]
            root = "/api/" + api_version if "/" not in api_version else "/apis/" + api_version
            result.append({"resource": resource, "apiVersion": api_version, "kind": kind, "path": root + "/" + resource.split(".")[0]})
        return result

    def metadata_list(self, resource):
        assert resource in self.metadata_resources()
        resource_name = resource["resource"]
        self.reads.append(("metadata_list", resource_name))
        if self.metadata_failure:
            raise retire.Refusal("Fake metadata list failed")
        objects = list(self.objects.get(resource_name, {}).values()) + [obj for kind, obj in self.extra_metadata if kind == resource_name]
        return [retire.metadata_identity(resource["apiVersion"], resource["kind"], obj["metadata"]) for obj in objects]

    def json(self, args, payload=None, local=False):
        assert payload is None and not local
        assert args[0] == "get" and args[1] in retire.RESOURCES
        expected = ["get", args[1]] + ([] if args[1] in retire.CLUSTER else ["-A"]) + ["-o", "json"]
        assert args == expected, args
        self.reads.append(tuple(args))
        if self.read_failure:
            raise retire.Refusal("Fake read failed")
        return {"items": [self.typed(args[1], obj) for obj in self.objects[args[1]].values()]}

    def remove_claim(self, pair):
        pvc = self.objects["persistentvolumeclaims"].pop(pair, None)
        if pvc:
            key = ("", pvc["spec"]["volumeName"])
            pv = self.objects["persistentvolumes"].get(key)
            if pv and pv["spec"]["persistentVolumeReclaimPolicy"] == "Delete":
                self.objects["persistentvolumes"].pop(key)
            elif pv:
                pv["status"]["phase"] = "Released"
                pv["metadata"]["resourceVersion"] = "2"

    def run(self, args, payload=None, local=False):
        assert not local
        if args[0] == "get":
            resource, resource_name = args[1:3]
            assert resource in ("namespaces", "persistentvolumes", "persistentvolumeclaims", "jobs.batch")
            namespace = args[4] if len(args) == 8 and args[3] == "-n" else ""
            assert args == retire.resource_args(resource, resource_name, namespace), args
            assert payload is None
            self.reads.append(tuple(args))
            if self.read_failure:
                raise retire.Refusal("Fake exact GET failed")
            obj = self.objects[resource].get((namespace, resource_name))
            return json.dumps(obj) if obj is not None else ""
        if args[0] == "delete":
            assert args[:2] == ["delete", "--raw"] and args[3:] == ["-f", "-"]
            candidates = [(resource, key, obj) for resource in (
                "namespaces", "persistentvolumeclaims", "jobs.batch")
                for key, obj in self.objects[resource].items()
                if retire.delete_path(resource, key[1], key[0]) == args[2]]
            assert len(candidates) == 1, args
            resource, key, obj = candidates[0]
            options = json.loads(payload)
            assert set(options) == {"apiVersion", "kind", "propagationPolicy", "preconditions"}
            assert options["kind"] == "DeleteOptions" and options["apiVersion"] == "v1"
            assert options["propagationPolicy"] == "Foreground"
            assert options["preconditions"] == {"uid": obj["metadata"]["uid"],
                                                 "resourceVersion": obj["metadata"]["resourceVersion"]}
            self.writes.append((copy.deepcopy(args), copy.deepcopy(options)))
            if self.conflict:
                obj["metadata"]["resourceVersion"] = "changed"
                raise retire.Refusal("Fake stale resourceVersion conflict")
            if resource == "namespaces":
                if not self.keep_namespace:
                    del self.objects[resource][key]
                    for pair in list(self.objects["persistentvolumeclaims"]):
                        if pair[0] == key[1]:
                            self.remove_claim(pair)
                    for kind, _ in retire.WORKLOADS.values():
                        self.objects[kind] = {pair: item for pair, item in self.objects[kind].items() if pair[0] != key[1]}
                    self.extra_metadata = [(kind, item) for kind, item in self.extra_metadata if item["metadata"]["namespace"] != key[1]]
            elif resource == "persistentvolumeclaims":
                self.remove_claim(key)
            else:
                del self.objects[resource][key]
            if self.unknown_applied:
                raise retire.Refusal("Fake lost mutation response")
            return "{}"
        if args[0] == "patch":
            assert payload is None and args[:2] == ["patch", "persistentvolumes"]
            assert args[3:5] == ["--type=json", "-p"] and len(args) == 6
            obj = self.objects["persistentvolumes"][("", args[2])]
            operations = json.loads(args[5])
            self.writes.append((copy.deepcopy(args), copy.deepcopy(operations)))
            if self.conflict:
                raise retire.Refusal("Fake stale resourceVersion conflict")
            for operation in operations[:-1]:
                assert operation["op"] == "test"
                current = obj
                for part in operation["path"].strip("/").split("/"):
                    current = current[part]
                assert current == operation["value"], operation
            assert operations[-1] == {"op": "replace", "path": "/spec/persistentVolumeReclaimPolicy", "value": "Delete"}
            assert not any(pvc["spec"]["volumeName"] == args[2] for pvc in self.objects["persistentvolumeclaims"].values())
            del self.objects["persistentvolumes"][("", args[2])]
            return "{}"
        raise AssertionError("Unexpected fake API command: " + repr(args))


def renovate(objects, plan):
    goal = {"namespace": "renovate", "name": "renovate-29837640", "uid": "old-job-uid",
            "cronjob_name": "renovate", "cronjob_uid": "cron-uid", "cronjob_timezone": "UTC",
            "disposition": "owner-closed-historical"}
    plan["historical_jobs"] = [goal]
    owner = {"apiVersion": "batch/v1", "kind": "CronJob", "name": "renovate", "uid": "cron-uid", "controller": True}
    success = (NOW - timedelta(minutes=30)).isoformat()
    objects["cronjobs.batch"][("renovate", "renovate")] = {
        "metadata": metadata("renovate", "cron-uid", "renovate"),
        "spec": {"schedule": f"0 {(NOW.hour - 1) % 24} * * *"},
        "status": {"lastSuccessfulTime": success, "lastScheduleTime": (NOW - timedelta(hours=1)).isoformat()}}
    old = {"metadata": metadata(goal["name"], goal["uid"], "renovate"),
           "status": {"conditions": [{"type": "Failed", "status": "True"}]}}
    old["metadata"].update(ownerReferences=[owner], creationTimestamp=(NOW - timedelta(days=2)).isoformat())
    new = {"metadata": metadata("renovate-new", "new-job-uid", "renovate"),
           "status": {"conditions": [{"type": "Complete", "status": "True"}], "completionTime": success}}
    new["metadata"].update(ownerReferences=[copy.deepcopy(owner)], creationTimestamp=(NOW - timedelta(hours=1)).isoformat())
    objects["jobs.batch"][("renovate", goal["name"])] = old
    objects["jobs.batch"][("renovate", "renovate-new")] = new


def add_workload(plan, objects, kind, resource_name, uid, namespace="old-app", owner=None, planned=False):
    obj = {"metadata": metadata(resource_name, uid, namespace), "spec": {}}
    if owner:
        obj["metadata"]["ownerReferences"] = [owner]
    objects[retire.WORKLOADS[kind][0]][(namespace, resource_name)] = obj
    if planned:
        plan["retired_workloads"].append({"kind": kind, "namespace": namespace, "name": resource_name, "uid": uid})
    return obj


def owner_ref(kind, resource_name, uid):
    return {"apiVersion": retire.WORKLOADS[kind][1], "kind": kind, "name": resource_name, "uid": uid, "controller": True}


def running_renovate(objects, age=10):
    created = (NOW - timedelta(minutes=age)).isoformat()
    job = {"metadata": metadata("renovate-current", "current-job-uid", "renovate"), "status": {"active": 1}}
    job["metadata"].update(creationTimestamp=created, ownerReferences=[owner_ref("CronJob", "renovate", "cron-uid")],
        annotations={"batch.kubernetes.io/cronjob-scheduled-timestamp": created})
    pod = {"metadata": metadata("renovate-current-pod", "current-pod-uid", "renovate"), "spec": {},
           "status": {"phase": "Running", "containerStatuses": [
               {"name": "renovate", "ready": True, "restartCount": 0, "state": {"running": {}}}]}}
    pod["metadata"].update(creationTimestamp=created, ownerReferences=[owner_ref("Job", "renovate-current", "current-job-uid")])
    objects["jobs.batch"][("renovate", "renovate-current")] = job
    objects["pods"][("renovate", "renovate-current-pod")] = pod
    cron = objects["cronjobs.batch"][("renovate", "renovate")]
    cron["status"].update(lastScheduleTime=created, active=[{"uid": "current-job-uid"}])
    source_time = retire.instant(created)
    cron["spec"]["schedule"] = f"{source_time.minute} {source_time.hour} * * *"
    return job, pod


class RetirementTests(unittest.TestCase):
    def setUp(self):
        # Even an accidental call outside FakeAPI cannot reach kubectl or Git.
        self.process = patch.object(retire.subprocess, "run", side_effect=AssertionError("No subprocess is allowed"))
        self.real_api = patch.object(retire, "load_api", side_effect=AssertionError("No real API is allowed"))
        self.process_mock = self.process.start()
        self.api_mock = self.real_api.start()
        self.native_proxy = patch.object(retire.subprocess, "Popen", side_effect=AssertionError("No real proxy is allowed"))
        self.native_socket = patch.object(retire.socket, "socket", side_effect=AssertionError("No real socket is allowed"))
        self.proxy_mock = self.native_proxy.start()
        self.socket_mock = self.native_socket.start()
        self.addCleanup(self.process.stop)
        self.addCleanup(self.real_api.stop)
        self.addCleanup(self.native_proxy.stop)
        self.addCleanup(self.native_socket.stop)
        self.receipts = []

    def run_plan(self, plan, api, source, apply=True, now=NOW):
        seconds = [0]

        def sleep(duration):
            seconds[0] += duration

        retire.execute(api, plan, lambda: source, apply, self.receipts.append,
                       clock=lambda: seconds[0], sleep=sleep, now=lambda: now)
        self.process_mock.assert_not_called()
        self.api_mock.assert_not_called()

    def blocked(self, plan, objects, source):
        api = FakeAPI(objects)
        with self.assertRaises(retire.Refusal):
            self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])

    def test_default_check_has_zero_writes(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        self.run_plan(plan, api, source, apply=False)
        self.assertEqual(api.writes, [])
        self.assertEqual(api.objects, objects)

    def test_collect_accepts_long_volumeattachment_subdomain_component(self):
        _, objects, _ = fixture()
        attachment_name = "csi-" + "a" * 64
        objects["volumeattachments.storage.k8s.io"][("", attachment_name)] = {
            "metadata": metadata(attachment_name, "attachment-uid"),
            "spec": {"source": {"persistentVolumeName": "pv-old"}}}
        api = FakeAPI(objects)
        snapshot = retire.collect(api)
        self.assertEqual(snapshot["volumeattachments.storage.k8s.io"][("", attachment_name)]["metadata"]["uid"], "attachment-uid")
        self.assertEqual(api.writes, [])
        self.process_mock.assert_not_called()
        self.api_mock.assert_not_called()

    def test_resource_subdomains_and_namespace_label_limits_are_distinct(self):
        self.assertEqual(retire.name("a" * 253), "a" * 253)
        self.assertEqual(retire.name("a" * 68 + ".valid"), "a" * 68 + ".valid")
        self.assertEqual(retire.name("a" * 63, namespace=True), "a" * 63)
        for invalid in ("a" * 64, "valid.namespace", "", "-invalid", "invalid-", "Name", "name_space"):
            with self.subTest(namespace=invalid), self.assertRaises(retire.Refusal):
                retire.name(invalid, namespace=True)
        with self.assertRaises(retire.Refusal):
            retire.name("a" * 254)

    def test_collect_still_rejects_invalid_namespace_names(self):
        for invalid in ("a" * 64, "invalid.namespace"):
            with self.subTest(namespace=invalid):
                _, objects, _ = fixture()
                objects["namespaces"] = {("", invalid): {"metadata": metadata(invalid, "namespace-uid")}}
                api = FakeAPI(objects)
                with self.assertRaises(retire.Refusal):
                    retire.collect(api)
                self.assertEqual(api.writes, [])

    def test_resource_subdomains_reject_bad_components_and_injection(self):
        for invalid in ("", ".name", "name.", "a..b", "a.-b", "a-.b", "Name", "name_space", "námé",
                        "name/path", "../name", "name;id", "$(id)", "name\nother", "name\x00", "name other"):
            with self.subTest(resource=invalid), self.assertRaises(retire.Refusal):
                retire.name(invalid)

    def test_unlabeled_unplanned_workload_blocks_all_namespace_writes(self):
        for kind in retire.WORKLOADS:
            with self.subTest(kind=kind):
                plan, objects, source = fixture()
                add_workload(plan, objects, kind, "foreign", "foreign-uid")
                self.blocked(plan, objects, source)

    def test_explicit_legacy_weaviate_statefulset_and_its_pod_are_retired(self):
        plan, objects, source = fixture(namespace="code")
        add_workload(plan, objects, "StatefulSet", "weaviate", "weaviate-uid", "code", planned=True)
        pod = add_workload(plan, objects, "Pod", "weaviate-0", "weaviate-pod-uid", "code",
                           owner_ref("StatefulSet", "weaviate", "weaviate-uid"))
        pod["spec"]["volumes"] = [{"persistentVolumeClaim": {"claimName": "data"}}]
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.objects["statefulsets.apps"], {})

    def test_planned_deployment_recursive_replicaset_pod_chain_is_valid(self):
        plan, objects, source = fixture()
        add_workload(plan, objects, "Deployment", "old", "deployment-uid", planned=True)
        add_workload(plan, objects, "ReplicaSet", "old-rs", "rs-uid", owner=owner_ref("Deployment", "old", "deployment-uid"))
        add_workload(plan, objects, "Pod", "old-pod", "pod-uid", owner=owner_ref("ReplicaSet", "old-rs", "rs-uid"))
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_replaced_planned_controller_foreign_child_and_cycles_block(self):
        for fault in ("replacement", "foreign-child", "cycle", "active-owner"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                controller = add_workload(plan, objects, "Deployment", "old", "deployment-uid", planned=True)
                child = add_workload(plan, objects, "ReplicaSet", "old-rs", "rs-uid",
                                     owner=owner_ref("Deployment", "old", "deployment-uid"))
                if fault == "replacement":
                    controller["metadata"]["uid"] = "replacement-uid"
                elif fault == "foreign-child":
                    child["metadata"]["ownerReferences"][0]["uid"] = "foreign-deployment-uid"
                elif fault == "cycle":
                    controller["metadata"]["ownerReferences"] = [owner_ref("ReplicaSet", "old-rs", "rs-uid")]
                else:
                    source["active"] = {"active-app"}
                    controller["metadata"]["labels"] = {"app.kubernetes.io/instance": "active-app"}
                self.blocked(plan, objects, source)

    def test_retired_workloads_schema_is_required_exact_and_namespace_scoped(self):
        for fault in ("missing", "unknown-kind", "foreign-namespace", "extra-field", "duplicate"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                add_workload(plan, objects, "Pod", "old", "pod-uid", planned=True)
                if fault == "missing":
                    del plan["retired_workloads"]
                elif fault == "unknown-kind":
                    plan["retired_workloads"][0]["kind"] = "CustomOperator"
                elif fault == "foreign-namespace":
                    plan["retired_workloads"][0]["namespace"] = "active-app"
                elif fault == "extra-field":
                    plan["retired_workloads"][0]["force"] = True
                else:
                    plan["retired_workloads"].append(copy.deepcopy(plan["retired_workloads"][0]))
                self.blocked(plan, objects, source)

    def test_namespace_unknown_snapshot_pushsecret_and_bucket_block_metadata_only(self):
        for api_version, kind, resource in (("snapshot.storage.k8s.io/v1", "VolumeSnapshot", "volumesnapshots.snapshot.storage.k8s.io"),
                ("external-secrets.io/v1alpha1", "PushSecret", "pushsecrets.external-secrets.io"),
                ("objectbucket.io/v1alpha1", "ObjectBucketClaim", "objectbucketclaims.objectbucket.io")):
            with self.subTest(kind=kind):
                plan, objects, source = fixture()
                api = FakeAPI(objects)
                api.extra_metadata.append((resource, {"apiVersion": api_version, "kind": kind,
                    "metadata": metadata("effect", "effect-uid", "old-app"), "spec": {"private": "do-not-project"}}))
                with self.assertRaisesRegex(retire.Refusal, "deletion-effect"):
                    self.run_plan(plan, api, source)
                self.assertEqual(api.writes, [])
                self.assertTrue(any(args[0] == "metadata_list" for args in api.reads))

    def test_unknown_effect_outside_target_is_ignored_and_secret_values_never_projected(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        api.extra_metadata = [("volumesnapshots.snapshot.storage.k8s.io", {
            "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot",
            "metadata": metadata("outside", "outside-uid", "active-app"), "spec": {"private": "do-not-project"}}),
            ("secrets", {"metadata": metadata("old-secret", "secret-uid", "old-app"), "data": {"private": "do-not-project"}}),
            ("rolebindings.rbac.authorization.k8s.io", {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
                "metadata": metadata("system:controller:leader", "rbac-uid", "kube-system")}),
            ("things.example.io", {"apiVersion": "example.io/stable", "kind": "Thing",
                "metadata": metadata("outside-thing", "thing-uid", "active-app"), "spec": {"private": "do-not-project"}})]
        projected = retire.namespace_metadata(api)
        self.assertNotIn("do-not-project", json.dumps(projected))
        self.assertTrue(all(set(obj) == {"apiVersion", "kind", "metadata"} for obj in projected))
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_metadata_lists_use_separate_interface_and_skip_readonly_metrics(self):
        _, objects, _ = fixture()
        api = FakeAPI(objects)
        api.empty_resources.update({f"empty{index}.example.io" for index in range(30)} | {"pods.metrics.k8s.io"})
        retire.namespace_metadata(api)
        resources = [args[1] for args in api.reads if args[0] == "metadata_list"]
        self.assertEqual(set(resources), {resource["resource"] for resource in api.metadata_resources()})
        self.assertNotIn("pods.metrics.k8s.io", resources)
        self.assertFalse(any(args[0] == "get" for args in api.reads))

    def test_failed_or_malformed_namespace_metadata_blocks_writes(self):
        plan, objects, source = fixture()
        for fault in ("query", "malformed", "changed-pvc"):
            with self.subTest(fault=fault):
                api = FakeAPI(objects)
                original_list = api.metadata_list

                def metadata_list(resource):
                    if fault == "query":
                        raise retire.Refusal("Fake metadata list failed")
                    if fault == "malformed":
                        return [{"apiVersion": "v1", "kind": "Secret", "metadata": {}}]
                    result = original_list(resource)
                    for obj in result:
                        if obj["kind"] == "PersistentVolumeClaim":
                            obj["metadata"]["uid"] = "replacement-uid"
                    return result

                with patch.object(api, "metadata_list", side_effect=metadata_list), self.assertRaises(retire.Refusal):
                    self.run_plan(plan, api, source)
                self.assertEqual(api.writes, [])

    def test_partial_metadata_accept_header_and_406_have_no_fallback(self):
        self.assertEqual(retire.METADATA_ACCEPT, "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1")
        resource = {"resource": "secrets", "apiVersion": "v1", "kind": "Secret", "path": "/api/v1/secrets"}
        client = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        client._resources, client._list_paths = [resource], {resource["path"]}
        response, connection = Mock(status=406), Mock()
        connection.getresponse.return_value = response
        with patch.object(retire, "UnixHTTPConnection", return_value=connection), \
                patch.object(retire, "metadata_deadline", return_value=nullcontext()), \
                self.assertRaisesRegex(retire.Refusal, "no full-object fallback"):
            client.metadata_list(resource)
        connection.request.assert_called_once_with("GET", "/api/v1/secrets?limit=500", headers={"Accept": retire.METADATA_ACCEPT})
        response.read.assert_not_called()
        connection.close.assert_called_once()

    def test_partial_metadata_pagination_discards_annotations_and_lists_are_fresh(self):
        resource = {"resource": "secrets", "apiVersion": "v1", "kind": "Secret", "path": "/api/v1/secrets"}
        client = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        client._resources, client._list_paths = [resource], {resource["path"]}
        pages = []
        for index, token in ((1, "opaque+/="), (2, "")):
            pages.append({"apiVersion": "meta.k8s.io/v1", "kind": "PartialObjectMetadataList",
                "metadata": {"resourceVersion": "10", "continue": token}, "items": [{"metadata": {
                    "namespace": "old-app", "name": f"secret-{index}", "uid": f"secret-uid-{index}",
                    "annotations": {"private": "do-not-retain"}, "managedFields": [{"private": "do-not-retain"}]}}]})
        responses = [Mock(status=200) for _ in range(4)]
        for response, body in zip(responses, pages + pages):
            response.read.return_value = json.dumps(body).encode()
        connection = Mock()
        connection.getresponse.side_effect = responses
        with patch.object(retire, "UnixHTTPConnection", return_value=connection), \
                patch.object(retire, "metadata_deadline", return_value=nullcontext()):
            first, second = client.metadata_list(resource), client.metadata_list(resource)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertNotIn("do-not-retain", json.dumps(first))
        self.assertTrue(all(set(obj["metadata"]) == {"namespace", "name", "uid"} for obj in first))
        self.assertEqual(connection.request.call_count, 4)
        for call in connection.request.call_args_list:
            self.assertEqual(call.args[0], "GET")
            self.assertEqual(call.kwargs["headers"], {"Accept": retire.METADATA_ACCEPT})
            self.assertEqual(parse_qs(urlsplit(call.args[1]).query)["limit"], ["500"])
        query = parse_qs(urlsplit(connection.request.call_args_list[1].args[1]).query)
        self.assertEqual(query["continue"], ["opaque+/="])

    def test_full_object_response_is_refused_without_retry(self):
        resource = {"resource": "secrets", "apiVersion": "v1", "kind": "Secret", "path": "/api/v1/secrets"}
        client = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        client._resources, client._list_paths = [resource], {resource["path"]}
        connection = Mock()
        response = Mock(status=200)
        response.read.return_value = b'{"apiVersion":"v1","kind":"SecretList","items":[]}'
        connection.getresponse.return_value = response
        with patch.object(retire, "UnixHTTPConnection", return_value=connection), \
                patch.object(retire, "metadata_deadline", return_value=nullcontext()), self.assertRaises(retire.Refusal):
            client.metadata_list(resource)
        self.assertEqual(connection.request.call_count, 1)
        with self.assertRaises(retire.Refusal):
            client._read("/api/v1/secrets")

    def test_empty_partial_metadata_list_accepts_explicit_null_items_only(self):
        resource = {"resource": "limitranges", "apiVersion": "v1", "kind": "LimitRange", "path": "/api/v1/limitranges"}
        client = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        client._resources, client._list_paths = [resource], {resource["path"]}
        document = {"apiVersion": "meta.k8s.io/v1", "kind": "PartialObjectMetadataList", "metadata": {}, "items": None}
        with patch.object(client, "_read", return_value=document):
            self.assertEqual(client.metadata_list(resource), [])
            del document["items"]
            with self.assertRaises(retire.Refusal):
                client.metadata_list(resource)

    def test_metadata_discovery_registers_only_preferred_namespaced_deletable_routes(self):
        client = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        documents = {"/apis": {"kind": "APIGroupList", "groups": [{"name": "example.io",
            "preferredVersion": {"version": "stable", "groupVersion": "example.io/stable"}}]},
            "/api/v1": {"kind": "APIResourceList", "groupVersion": "v1", "resources": [
                {"name": "secrets", "kind": "Secret", "namespaced": True, "verbs": ["get", "list", "delete"]},
                {"name": "pods/status", "kind": "Pod", "namespaced": True, "verbs": ["list", "delete"]},
                {"name": "nodes", "kind": "Node", "namespaced": False, "verbs": ["list", "delete"]}]},
            "/apis/example.io/stable": {"kind": "APIResourceList", "groupVersion": "example.io/stable", "resources": [
                {"name": "things", "kind": "Thing", "namespaced": True, "verbs": ["list", "delete"]},
                {"name": "readonly", "kind": "ReadOnly", "namespaced": True, "verbs": ["get", "list"]}]}}
        with patch.object(client, "_read", side_effect=lambda path: documents[path]) as reads:
            resources = client.metadata_resources()
            self.assertEqual(client.metadata_resources(), resources)
            self.assertEqual(reads.call_count, 3)
        self.assertEqual({resource["resource"] for resource in resources}, {"secrets", "things.example.io"})
        self.assertEqual(client._list_paths, {"/api/v1/secrets", "/apis/example.io/stable/things"})
        documents["/api/v1"]["resources"][0]["namespaced"] = None
        malformed = retire.MetadataAPI(SimpleNamespace(), "/fake-private-directory")
        with patch.object(malformed, "_read", side_effect=lambda path: documents[path]), \
                self.assertRaisesRegex(retire.Refusal, "scope discovery"):
            malformed.metadata_resources()

    def test_unix_connection_uses_relative_socket_and_restores_directory_on_failure(self):
        connection = retire.UnixHTTPConnection("/fake/very-long-parent/" + "x" * 160)
        native = Mock()
        native.connect.side_effect = OSError("synthetic failure")
        with patch.object(retire.socket, "socket", return_value=native) as factory, \
                patch.object(retire.os, "open", return_value=71), patch.object(retire.os, "chdir") as change, \
                patch.object(retire.os, "fchdir") as restore, patch.object(retire.os, "close") as close, \
                self.assertRaises(OSError):
            connection.connect()
        factory.assert_called_once_with(retire.socket.AF_UNIX, retire.socket.SOCK_STREAM)
        native.connect.assert_called_once_with("s")
        native.close.assert_called_once()
        change.assert_called_once_with(connection.directory)
        restore.assert_called_once_with(71)
        close.assert_called_once_with(71)

    def test_private_proxy_cleanup_uses_only_owned_process_and_no_tcp(self):
        directory = "/synthetic-parent/" + "x" * 160
        process = Mock()
        process.poll.return_value = None
        info = SimpleNamespace(st_mode=retire.stat.S_IFSOCK | 0o600, st_uid=retire.os.getuid())
        temporary = Mock()
        temporary.__enter__ = Mock(return_value=directory)
        temporary.__exit__ = Mock(return_value=False)
        api = SimpleNamespace(base=["kubectl", "--kubeconfig", str(retire.ROOT / "metal/kubeconfig.yaml"),
                                    "--cache-dir", "/synthetic-cache"])
        with patch.dict(retire.os.environ, {"TMPDIR": "/synthetic-parent", "KUBECACHEDIR": "/synthetic-cache"}), \
                patch.object(retire.Path, "is_dir", return_value=True), patch.object(retire.Path, "lstat", return_value=info), \
                patch.object(retire.tempfile, "TemporaryDirectory", return_value=temporary), patch.object(retire.os, "chmod") as chmod, \
                patch.object(retire.subprocess, "Popen", return_value=process) as start:
            with self.assertRaisesRegex(RuntimeError, "synthetic stop"):
                with retire.metadata_api(api) as client:
                    self.assertIs(client.api, api)
                    raise RuntimeError("synthetic stop")
        args, kwargs = start.call_args.args[0], start.call_args.kwargs
        self.assertEqual(args[:len(api.base)], api.base)
        self.assertEqual(args[args.index("--cache-dir") + 1], "/synthetic-cache")
        self.assertIn("--unix-socket=s", args)
        self.assertIn("--reject-methods=POST,PUT,PATCH,DELETE,CONNECT", args)
        self.assertIn(retire.SERVER, args)
        self.assertFalse(any(arg.startswith(("--port", "--address", "--insecure", "--disable-filter")) for arg in args))
        self.assertEqual(kwargs["cwd"], directory)
        self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]), (retire.subprocess.DEVNULL,) * 3)
        chmod.assert_any_call(directory, 0o700)
        chmod.assert_any_call(retire.Path(directory) / "s", 0o600)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=20)
        process.kill.assert_not_called()

    def test_proxy_startup_timeout_still_terminates_and_reaps_owned_child(self):
        process = Mock()
        process.poll.return_value = None
        temporary = Mock()
        temporary.__enter__ = Mock(return_value="/synthetic-parent/private")
        temporary.__exit__ = Mock(return_value=False)
        api = SimpleNamespace(base=["kubectl", "--kubeconfig", str(retire.ROOT / "metal/kubeconfig.yaml")])
        with patch.dict(retire.os.environ, {"TMPDIR": "/synthetic-parent", "KUBECACHEDIR": "/synthetic-cache"}), \
                patch.object(retire.Path, "is_dir", return_value=True), patch.object(retire.os, "chmod"), \
                patch.object(retire.tempfile, "TemporaryDirectory", return_value=temporary), \
                patch.object(retire.subprocess, "Popen", return_value=process), \
                patch.object(retire.time, "monotonic", side_effect=[0, 21]), \
                self.assertRaisesRegex(retire.Refusal, "startup exceeded 20 seconds"):
            with retire.metadata_api(api):
                self.fail("Timed-out proxy must not be yielded")
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=20)

    def test_main_routes_cache_before_establish_and_metadata_proxy(self):
        plan, _, source = fixture()
        cache = "/synthetic-parent/kubectl-cache"
        api = Mock(base=["kubectl"])

        def establish():
            self.assertEqual(api.base, ["kubectl", "--cache-dir", cache])
            mkdir.assert_called_once_with(mode=0o700, exist_ok=True)
            return "cluster-uid"

        api.establish.side_effect = establish
        with patch.dict(retire.os.environ, {"KUBECACHEDIR": cache}), \
                patch.object(retire, "source_gate", return_value=source), \
                patch.object(retire.Path, "read_bytes", return_value=json.dumps(plan).encode()), \
                patch.object(retire.Path, "mkdir") as mkdir, patch.object(retire.Path, "is_dir", return_value=True), \
                patch.object(retire, "load_api", return_value=api), \
                patch.object(retire, "metadata_api", return_value=nullcontext(api)) as proxy, \
                patch.object(retire, "execute") as execute, patch("builtins.print"):
            self.assertEqual(retire.main(["scripts/retirements/run.json"]), 0)
        api.establish.assert_called_once_with()
        proxy.assert_called_once_with(api)
        execute.assert_called_once()
        self.process_mock.assert_not_called()
        self.proxy_mock.assert_not_called()

    def test_unsafe_or_unavailable_cache_refuses_before_api_or_writes(self):
        plan, _, source = fixture()
        for fault in ("missing", "relative", "symlink", "unwritable", "not-directory"):
            with self.subTest(fault=fault):
                cache = "relative-cache" if fault == "relative" else "/synthetic-parent/kubectl-cache"
                env = {} if fault == "missing" else {"KUBECACHEDIR": cache}
                with patch.dict(retire.os.environ, env, clear=True), \
                        patch.object(retire, "source_gate", return_value=source), \
                        patch.object(retire.Path, "read_bytes", return_value=json.dumps(plan).encode()), \
                        patch.object(retire.Path, "resolve", return_value=Path("/different") if fault == "symlink" else Path(cache)), \
                        patch.object(retire.Path, "mkdir", side_effect=OSError("synthetic refusal") if fault == "unwritable" else None) as mkdir, \
                        patch.object(retire.Path, "is_dir", return_value=fault != "not-directory"), \
                        patch.object(retire, "execute") as execute, patch("builtins.print"):
                    self.assertEqual(retire.main(["scripts/retirements/run.json", "--apply"]), 1)
                if fault in ("missing", "relative", "symlink"):
                    mkdir.assert_not_called()
                self.api_mock.assert_not_called()
                self.process_mock.assert_not_called()
                self.proxy_mock.assert_not_called()
                execute.assert_not_called()

    def test_nfs_pv_and_namespace_never_deleted(self):
        for backend in ("native", "class", "csi"):
            with self.subTest(backend=backend):
                plan, objects, source = fixture()
                spec = objects["persistentvolumes"][("", "pv-old")]["spec"]
                if backend == "native":
                    spec["nfs"] = {"server": "nas", "path": "/durable"}
                elif backend == "class":
                    spec["storageClassName"] = "nfs-rwx"
                else:
                    spec["csi"]["driver"] = "nfs.csi.k8s.io"
                self.blocked(plan, objects, source)

    def test_unplanned_pvc_blocks_namespace(self):
        plan, objects, source = fixture()
        plan["volumes"] = []
        self.blocked(plan, objects, source)

    def test_released_unplanned_nfs_pv_protects_namespace(self):
        plan, objects, source = fixture()
        objects["persistentvolumes"][("", "nas-pv")] = {
            "metadata": metadata("nas-pv", "nas-pv-uid"), "spec": {"nfs": {"server": "nas", "path": "/durable"},
                "claimRef": {"namespace": "old-app", "name": "former-nas", "uid": "former-nas-uid"}}}
        self.blocked(plan, objects, source)

    def test_unplanned_released_pv_claimref_blocks_even_without_its_pvc(self):
        for policy, driver in (("Retain", "unknown.csi.example"), ("Retain", retire.DRIVER), ("Delete", retire.DRIVER)):
            with self.subTest(policy=policy, driver=driver):
                plan, objects, source = fixture()
                objects["persistentvolumes"][("", "unplanned-pv")] = {
                    "metadata": metadata("unplanned-pv", "unplanned-pv-uid"),
                    "spec": {"persistentVolumeReclaimPolicy": policy, "storageClassName": "standard-rwo",
                        "csi": {"driver": driver, "volumeHandle": "unplanned-handle"},
                        "claimRef": {"namespace": "old-app", "name": "gone", "uid": "gone-pvc-uid"}},
                    "status": {"phase": "Released"}}
                api = FakeAPI(objects)
                with self.assertRaisesRegex(retire.Refusal, "unplanned PV claimRef"):
                    self.run_plan(plan, api, source)
                self.assertEqual(api.writes, [])

    def test_inline_nfs_blocks_namespace(self):
        plan, objects, source = fixture()
        objects["pods"][("old-app", "old")] = {"metadata": metadata("old", "pod-uid", "old-app"),
            "spec": {"volumes": [{"name": "nas", "nfs": {"server": "nas", "path": "/durable"}}]}}
        plan["retired_workloads"] = [{"kind": "Pod", "namespace": "old-app", "name": "old", "uid": "pod-uid"}]
        self.blocked(plan, objects, source)

    def test_shared_handle_or_active_consumer_blocks(self):
        for kind in ("handle", "claim", "source", "dns-dependency", "inline"):
            with self.subTest(kind=kind):
                plan, objects, source = fixture()
                if kind == "handle":
                    other = copy.deepcopy(objects["persistentvolumes"][("", "pv-old")])
                    other["metadata"] = metadata("pv-active", "active-pv-uid")
                    other["spec"]["claimRef"] = {"namespace": "active-app", "name": "active-data", "uid": "active-claim-uid"}
                    objects["persistentvolumes"][("", "pv-active")] = other
                elif kind == "claim":
                    objects["persistentvolumeclaims"][("active-app", "shared")] = {
                        "metadata": metadata("shared", "active-claim-uid", "active-app"), "spec": {"volumeName": "pv-old"}}
                elif kind == "source":
                    source["texts"] = ["existingVolume: rbd-old"]
                elif kind == "dns-dependency":
                    source["texts"] = ["DATABASE_HOST: old-app.old-app.svc.cluster.local"]
                else:
                    objects["pods"][("active-app", "active")] = {"metadata": metadata("active", "pod-uid", "active-app"),
                        "spec": {"volumes": [{"csi": {"driver": retire.DRIVER, "volumeHandle": "rbd-old"}}]}}
                self.blocked(plan, objects, source)

    def test_generic_code_words_prose_and_full_line_comments_do_not_block_namespace(self):
        plan, objects, source = fixture(namespace="code")
        source["texts"] = ["""# namespace: code
  # DATABASE_HOST=weaviate.code.svc.cluster.local
# existingVolume: rbd-old
description: 'Example source code and prose namespace: code'
command: [code, --version]
"""]
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.writes[0][0][2], "/api/v1/namespaces/code")

    def test_real_code_namespace_database_fqdn_blocks(self):
        for host in ("weaviate.code.svc", "weaviate.code.svc.cluster.local", "weaviate.code.svc.cluster.local."):
            with self.subTest(host=host):
                plan, objects, source = fixture(namespace="code")
                source["texts"] = ["DATABASE_HOST=" + host + ":8080"]
                self.blocked(plan, objects, source)

    def test_short_namespace_endpoint_keys_block_but_free_text_does_not(self):
        for text in ("DATABASE_HOST: db.old-app", "PGHOST: db.old-app", "URL: http://db.old-app:8080/path", "dbHost: db.old-app", "endpoint: https://db.old-app"):
            with self.subTest(text=text):
                plan, objects, source = fixture()
                source["texts"] = [text]
                self.blocked(plan, objects, source)
        self.assertEqual(retire.namespace_references(
            "# DB_HOST: db.old-app\ndescription: db.old-app\ncommand: code\nname: ollama\n"), set())

    def test_native_and_wrapped_source_env_endpoints_block(self):
        for text in ("env: [{name: DATABASE_HOST, value: db.old-app}]",
                     "env: {DATABASE_HOST: {value: db.old-app}}",
                     "env:\n  DATABASE_HOST:\n    value: db.old-app\n",
                     "{{- if .Values.enabled }}\nenv: [{name: DATABASE_HOST, value: db.old-app}]\n{{- end }}",
                     "{{- if .Values.enabled }}\nenv: {DATABASE_HOST: {value: db.old-app}}\n{{- end }}",
                     "{{- if .Values.enabled }}\nenv:\n  - name: DATABASE_HOST\n    value: db.old-app\n{{- end }}"):
            with self.subTest(text=text):
                self.assertEqual(retire.namespace_references(text), {"old-app"})
                plan, objects, source = fixture()
                source["texts"] = [text]
                self.blocked(plan, objects, source)

    def test_endpoint_flow_lists_accept_external_empty_and_namespace_hosts(self):
        for key in ("hosts", "hostnames", "endpoints"):
            for value, expected in (("[builder.example.io]", set()), ("[]", set()),
                    ('["db.old-app", https://api.other-app:8080/path]', {"old-app", "other-app"}),
                    (" [db.old-app, cache.other-app.svc.cluster.local] # hosts", {"old-app", "other-app"})):
                with self.subTest(key=key, value=value):
                    self.assertEqual(retire.namespace_references(key + ": " + value), expected)

    def test_endpoint_flow_lists_and_malformed_endpoints_refuse_without_values(self):
        for value in ("[private-host", "[private-host, 42]", "[private-host, null]",
                      "[private-host, {host: db.old-app}]", "[[private-host]]",
                      "https://[private-host", '["https://[private-host"]'):
            with self.subTest(value=value):
                with self.assertRaises(retire.Refusal) as caught:
                    retire.endpoint_references("hosts", value)
                self.assertNotIn("private-host", str(caught.exception))
        self.assertEqual(retire.endpoint_references("host", "http://[::1]:8080"), set())

    def test_exact_env_templates_resolve_native_wrapped_and_empty_values(self):
        for env, expected in (([{"name": "DATABASE_HOST", "value": "db.old-app"}], {"old-app"}),
                ({"DATABASE_HOST": {"value": "db.old-app"}}, {"old-app"}),
                ({"DATABASE_HOST": "db.old-app"}, {"old-app"}), ([], set()), ({}, set()), (None, set())):
            with self.subTest(env=env):
                text = "{{- if .Values.enabled }}\n  env: {{ toYaml .Values.driver.manager.env | nindent 6 }}\n{{- end }}\n"
                values = json.dumps({"driver": {"manager": {"env": env}}})
                resolved = retire.resolve_env_templates(text, values)
                self.assertIn("  env: " + json.dumps(env) + "\n", resolved)
                self.assertEqual(retire.namespace_references(resolved), expected)
                if expected:
                    plan, objects, source = fixture()
                    source["texts"] = [resolved]
                    self.blocked(plan, objects, source)
        values = "driver:\n  env:\n    - name: DATABASE_HOST\n      value: db.old-app\n"
        for text in ("env:{{ toYaml .Values.driver.env | nindent 6 }}",
                     "env: {{toYaml .Values.driver.env|nindent 8}}  "):
            self.assertEqual(retire.namespace_references(retire.resolve_env_templates(text, values)), {"old-app"})

    def test_env_templates_refuse_missing_unsupported_and_invalid_values(self):
        text = "env: {{ toYaml .Values.driver.env | nindent 6 }}\n"
        for values in (None, "driver: {}", "{}", "driver: null", "driver: []", "driver: [private-value",
                       "driver: {env: private-value}", "driver: {env: 42}", "driver: {env: true}",
                       "driver: {env: [2026-10-17]}"):
            with self.subTest(values=values):
                with self.assertRaises(retire.Refusal) as caught:
                    retire.resolve_env_templates(text, values)
                self.assertNotIn("private-value", str(caught.exception))
                self.assertNotIn("driver", str(caught.exception))
        for expression in ("{{ .Values.driver.env }}", "{{ toYaml .Values.driver.env | indent 6 }}",
                '{{ toYaml .Values.driver.env | default "private-value" | nindent 6 }}',
                "{{ toYaml .Values.driver.env | nindent six }}",
                "{{ toYaml .Values.driver.env | nindent -6 }}",
                "{{ toYaml .Values.driver.env | nindent 6 }} trailing",
                '"{{ toYaml .Values.driver.env | nindent 6 }}"'):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(retire.Refusal, "Unsupported env template; values withheld") as caught:
                    retire.resolve_env_templates("env: " + expression, "driver: {env: []}")
                self.assertNotIn("private-value", str(caught.exception))

    def test_env_template_absent_path_exempted_only_by_guard_on_that_same_path(self):
        guarded = ("{{- if .Values.driver }}\ndriver:\n  {{- if .Values.driver.cuda }}\n  cuda:\n"
                   "    {{- if .Values.driver.cuda.env }}\n    env: {{ toYaml .Values.driver.cuda.env | nindent 8 }}\n"
                   "    {{- end }}\n  {{- end }}\n{{- end }}\n")
        for values in ("driver: {image: nvidia}\n", "driver: {cuda: {enabled: true}}\n"):
            with self.subTest(values=values):
                resolved = retire.resolve_env_templates(guarded, values)
                self.assertNotIn("toYaml", resolved)
                self.assertEqual(retire.namespace_references(resolved), set())
        text = "env: {{ toYaml .Values.driver.cuda.env | nindent 6 }}\n"
        for guard, values in (("", "driver: {cuda: {}}\n"),
                ("{{- if .Values.driver.enabled }}\n", "driver: {enabled: false}\n"),
                ("{{- if .Values.other }}\n", "driver: {cuda: {}}\n")):
            with self.subTest(guard=guard, values=values):
                with self.assertRaisesRegex(retire.Refusal, "Missing env template path; values withheld"):
                    retire.resolve_env_templates(guard + text + ("{{- end }}\n" if guard else ""), values)

    def test_inline_env_exemption_is_stated_path_scoped_and_never_stale(self):
        templated = "env:\n  - name: DATABASE_HOST\n    value: \"{{ .Values.driver.host }}\"\n"
        literal = "{{- if .Values.enabled }}\nnamespace: old-app\n{{- end }}\n" + templated
        with self.assertRaisesRegex(retire.Refusal, "Unresolved inline env syntax"):
            retire.namespace_references(templated)
        self.assertEqual(retire.namespace_references(literal, True), {"old-app"})
        path = "apps/consumer/templates/deployment.yaml"
        plan, objects, source = fixture()
        source["texts"], source["text_paths"] = [templated], [path]
        self.blocked(plan, objects, source)
        plan["inline_env_exemptions"] = [{"path": path, "reason": "Helm-templated env values hide no literal endpoint"}]
        self.run_plan(plan, FakeAPI(objects), source, apply=False)
        source["texts"] = [literal]
        self.blocked(plan, objects, source)
        source["texts"], source["text_paths"] = [templated], ["apps/consumer/templates/other.yaml"]
        self.blocked(plan, objects, source)
        source["text_paths"] = [path]
        source["texts"] = ["env:\n  - name: DATABASE_HOST\n    value: old-app\n"]
        self.blocked(plan, objects, source)
        for exemption in ({}, {"path": path}, {"path": "/etc/passwd.yaml", "reason": "x"},
                {"path": "apps/consumer/templates/deployment.txt", "reason": "x"}, {"path": path, "reason": "  "}):
            with self.subTest(exemption=exemption):
                plan["inline_env_exemptions"] = [exemption]
                with self.assertRaises(retire.Refusal):
                    retire.validate_plan(plan)
        plan["inline_env_exemptions"] = [{"path": path, "reason": "x"}, {"path": path, "reason": "x"}]
        with self.assertRaisesRegex(retire.Refusal, "invalid or duplicate"):
            retire.validate_plan(plan)

    def test_env_template_prose_comments_and_block_scalars_are_not_resolved(self):
        stanza = "env: {{ toYaml .Values.missing.env | nindent 6 }}"
        for text in ("# " + stanza, "description: '" + stanza + "'",
                "description: |\n  " + stanza + "\n", "description: >-\n  " + stanza + "\n",
                "{{- if .Values.enabled }}\nconfig: |2-\n  " + stanza + "\n{{- end }}"):
            with self.subTest(text=text):
                self.assertEqual(retire.resolve_env_templates(text, None), text)
                self.assertEqual(retire.namespace_references(text), set())
        text = "description: |\n  " + stanza + "\nenv: {{ toYaml .Values.driver.env | nindent 6 }}\n"
        resolved = retire.resolve_env_templates(text, "driver: {env: {DATABASE_HOST: db.old-app}}")
        self.assertIn(stanza, resolved)
        self.assertEqual(retire.namespace_references(resolved), {"old-app"})

    def test_unresolved_inline_helm_env_refuses_without_writes_or_values(self):
        for env in ("env: [{name: DATABASE_HOST, value: {{ .Values.privateHost }}}]",
                    "env: {DATABASE_HOST: {value: {{ .Values.privateHost }}}}",
                    'env: "{{ .Values.privateHost }}"',
                    'env: [{name: DATABASE_HOST, value: "{{ .Values.privateHost }}"}]',
                    "env:\n  - name: DATABASE_HOST\n    value: {{ .Values.privateHost }}",
                    "env:\n  DATABASE_HOST:\n    value: {{ .Values.privateHost }}"):
            with self.subTest(env=env):
                with self.assertRaisesRegex(retire.Refusal, "Unresolved inline env syntax; values withheld"):
                    retire.namespace_references(env)
                plan, objects, source = fixture()
                source["texts"] = ["{{- if .Values.enabled }}\n" + env + "\n{{- end }}"]
                api = FakeAPI(objects)
                with self.assertRaisesRegex(retire.Refusal, "Unresolved inline env syntax; values withheld") as caught:
                    self.run_plan(plan, api, source)
                self.assertNotIn("privateHost", str(caught.exception))
                self.assertEqual(api.writes, [])

    def test_unrelated_env_prose_and_permissions_do_not_become_consumers(self):
        for text in ("env: [{name: MESSAGE, value: db.old-app}, {name: CODE, value: code}]",
                     "env:\n  MESSAGE:\n    value: db.old-app\n  TEXT_PROVIDER: ollama\n",
                     "description: |\n  env:\n    DATABASE_HOST:\n      value: db.old-app\n",
                     "{{- if .Values.enabled }}\nenv: [{name: MESSAGE, value: db.old-app}]\n{{- end }}",
                     "{{- if .Values.enabled }}\nconfig: |\n  env: [{name: DATABASE_HOST, value: db.old-app}]\n{{- end }}",
                     "{{- if .Values.enabled }}\ndescription: >-\n  env: {DATABASE_HOST: {value: db.old-app}}\n{{- end }}",
                     "{{- if .Values.enabled }}\nconfig: |2-\n  env: {DATABASE_HOST: {value: db.old-app}}\n{{- end }}",
                     "{{- if .Values.enabled }}\ndescription: |\n  env:\n    DATABASE_HOST:\n      value: db.old-app\n{{- end }}",
                     "networkPolicies:\n  main:\n    egress:\n      - name: ollama\n"):
            with self.subTest(text=text):
                self.assertEqual(retire.namespace_references(text), set())

    def test_live_pod_and_controller_template_env_endpoints_block_without_source_text(self):
        for kind in ("Pod", "Deployment", "StatefulSet", "CronJob"):
            with self.subTest(kind=kind):
                plan, objects, source = fixture()
                obj = add_workload(plan, objects, kind, "active", "active-uid", namespace="active-app")
                pod_spec = {"containers": [{"name": "app", "env": [{"name": "DATABASE_HOST", "value": "db.old-app"}]}]}
                if kind == "Pod":
                    obj["spec"] = pod_spec
                elif kind == "CronJob":
                    obj["spec"] = {"jobTemplate": {"spec": {"template": {"spec": pod_spec}}}}
                else:
                    obj["spec"] = {"template": {"spec": pod_spec}}
                self.blocked(plan, objects, source)
        self.assertEqual(retire.env_references({"containers": [{"env": [
            {"name": "MESSAGE", "value": "db.old-app"}, {"name": "CODE", "value": "code"}]}]}), set())

    def test_egress_only_ollama_permission_is_not_a_consumer(self):
        plan, objects, source = fixture(namespace="ollama")
        source["texts"] = ["""# Permission for ollama is not an ollama consumer.
kind: NetworkPolicy
metadata:
  namespace: active-app
spec:
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: ollama
    - toFQDNs:
        - matchName: ollama.ollama.svc.cluster.local
"""]
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_values_policy_egress_is_ignored_but_app_config_egress_still_blocks(self):
        permission = "networkPolicies:\n  main:\n    egress:\n      - matchName: ollama.ollama.svc.cluster.local\n"
        self.assertEqual(retire.namespace_references(permission), set())
        app_config = "egress:\n  DATABASE_HOST: weaviate.code.svc.cluster.local\n"
        self.assertEqual(retire.namespace_references(app_config), {"code"})
        plan, objects, source = fixture(namespace="code")
        source["texts"] = [app_config]
        self.blocked(plan, objects, source)

    def test_policy_egress_filter_ends_at_next_yaml_document(self):
        text = "kind: NetworkPolicy\nspec:\n  egress:\n    - matchName: ollama.ollama.svc\n---\negress:\n  DATABASE_HOST: weaviate.code.svc\n"
        self.assertEqual(retire.namespace_references(text), {"code"})

    def test_namespace_fields_are_anchored_and_direct_declarations_still_block(self):
        text = "# namespace: code\ndescription: 'namespace: code'\nmetadata:\n  namespace: 'active-app'\n"
        self.assertEqual(retire.namespace_references(text), {"active-app"})
        for declaration in ("metadata:\n  namespace: code\n", 'releaseNamespace: "code"\n'):
            with self.subTest(declaration=declaration):
                plan, objects, source = fixture(namespace="code")
                source["texts"] = [declaration]
                self.blocked(plan, objects, source)

    def test_strong_pv_and_handle_source_references_still_block_in_egress(self):
        for key, value in (("volumeName", "pv-old"), ("volumeHandle", "rbd-old")):
            with self.subTest(key=key):
                plan, objects, source = fixture()
                source["texts"] = ["kind: NetworkPolicy\nspec:\n  egress:\n    - " + key + ": " + value]
                self.blocked(plan, objects, source)

    def test_active_basename_replacement_and_namespace_block(self):
        for active in ("old-app", "nibble", "backlog", "omni-tools"):
            with self.subTest(active=active):
                plan, objects, source = fixture()
                source["active"] = {active}
                if active != "old-app":
                    plan["namespaces"][0]["archived_path"] = "archived/apps/" + active
                    source["directories"].add("archived/apps/" + active)
                    source["archive_aliases"]["archived/apps/" + active] = {active, "old-app"}
                self.blocked(plan, objects, source)

    def test_namespace_cannot_borrow_unrelated_committed_archive_directory(self):
        plan, objects, source = fixture(namespace="code", archived_path="archived/apps/unrelated")
        api = FakeAPI(objects)
        with self.assertRaisesRegex(retire.Refusal, "does not match archive"):
            self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])

    def test_explicit_chart_name_allows_legacy_steam_archive_alias(self):
        archive = "archived/apps/OLDsteam-headless"
        plan, objects, source = fixture(namespace="steam-headless", archived_path=archive)
        source["archive_aliases"] = retire.archive_aliases(source["directories"], {
            archive + "/Chart.yaml": "apiVersion: v2\nname: steam-headless\ndependencies:\n  - name: app-template\n"})
        self.assertEqual(source["archive_aliases"][archive], {"OLDsteam-headless", "steam-headless"})
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_archive_alias_cannot_override_active_backlog_replacement(self):
        archive = "archived/apps/backlog-companion"
        plan, objects, source = fixture(namespace="backlog-companion", archived_path=archive)
        source["archive_aliases"] = retire.archive_aliases(source["directories"], {
            archive + "/Chart.yaml": "apiVersion: v2\nname: backlog\n"})
        source["active"] = {"backlog"}
        api = FakeAPI(objects)
        with self.assertRaisesRegex(retire.Refusal, "Active replacement"):
            self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])

    def test_only_one_explicit_top_level_chart_name_can_grant_an_alias(self):
        archive = "archived/apps/OLDsteam-headless"
        for text in ("# name: steam-headless\ndependencies:\n  - name: steam-headless\n",
                     "name: steam-headless\nname: other-app\n"):
            with self.subTest(text=text):
                aliases = retire.archive_aliases({archive}, {archive + "/Chart.yaml": text})
                self.assertEqual(aliases[archive], {"OLDsteam-headless"})

    def test_live_application_even_terminating_blocks(self):
        plan, objects, source = fixture()
        objects["applications.argoproj.io"][("argocd", "old-app")] = {
            "metadata": {**metadata("old-app", "app-uid", "argocd"), "deletionTimestamp": NOW.isoformat()},
            "spec": {"destination": {"namespace": "old-app"}}}
        self.blocked(plan, objects, source)

    def test_active_chart_pod_or_claim_in_retired_namespace_blocks(self):
        for target in ("pod", "claim"):
            with self.subTest(target=target):
                plan, objects, source = fixture()
                source["active"] = {"active-app"}
                if target == "pod":
                    objects["pods"][("old-app", "active")] = {
                        "metadata": {**metadata("active", "active-pod-uid", "old-app"),
                                     "labels": {"app.kubernetes.io/instance": "active-app"}},
                        "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "data"}}]}}
                else:
                    objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["annotations"] = {
                        "argocd.argoproj.io/tracking-id": "active-app:/PersistentVolumeClaim:old-app/data"}
                self.blocked(plan, objects, source)

    def test_deleted_unarchived_flags_stay(self):
        flags = [("pv", "policy", "Retain"), ("pvc", "helm.sh/resource-policy", "keep"),
                 ("pv", "argocd.argoproj.io/sync-options", "Prune=false"),
                 ("pvc", "argocd.argoproj.io/sync-options", "Delete=confirm"),
                 ("pvc", "example.io/persist", "true"), ("pv", "example.io/retain", "yes")]
        for target, key, value in flags:
            with self.subTest(target=target, key=key, value=value):
                plan, objects, source = fixture("deleted-unarchived")
                obj = objects["persistentvolumes"][("", "pv-old")] if target == "pv" else objects["persistentvolumeclaims"][("old-app", "data")]
                if key == "policy":
                    obj["spec"]["persistentVolumeReclaimPolicy"] = value
                else:
                    obj["metadata"]["annotations"] = {key: value}
                api = FakeAPI(objects)
                self.run_plan(plan, api, source)
                self.assertEqual(api.writes, [])
                self.assertEqual(api.objects, objects)
                self.assertEqual(self.receipts[-1]["protected_pvs"], ["pv-old"])

    def test_unflagged_orphan_pvc_deleted_without_namespace_or_backup(self):
        plan, objects, source = fixture("deleted-unarchived")
        objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["finalizers"] = ["kubernetes.io/pvc-protection"]
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        args, options = api.writes[0]
        self.assertEqual(args, ["delete", "--raw", "/api/v1/namespaces/old-app/persistentvolumeclaims/data", "-f", "-"])
        self.assertEqual(options["preconditions"], {"uid": "claim-uid", "resourceVersion": "1"})
        self.assertEqual(api.objects["persistentvolumes"], {})
        self.assertFalse(any("backup" in str(command).lower() or "create" in command[0] for command in api.writes))

    def test_orphan_controller_reference_including_zero_replica_statefulset_blocks(self):
        for resource in ("pods", "deployments.apps", "statefulsets.apps", "cronjobs.batch"):
            with self.subTest(resource=resource):
                plan, objects, source = fixture("deleted-unarchived")
                spec = {"volumes": [{"persistentVolumeClaim": {"claimName": "data"}}]}
                if resource == "deployments.apps":
                    spec = {"replicas": 0, "template": {"spec": spec}}
                elif resource == "cronjobs.batch":
                    spec = {"suspend": True, "jobTemplate": {"spec": {"template": {"spec": spec}}}}
                elif resource == "statefulsets.apps":
                    plan["volumes"][0]["claim_name"] = "data-old-0"
                    pvc = objects["persistentvolumeclaims"].pop(("old-app", "data"))
                    pvc["metadata"]["name"] = "data-old-0"
                    objects["persistentvolumeclaims"][("old-app", "data-old-0")] = pvc
                    objects["persistentvolumes"][("", "pv-old")]["spec"]["claimRef"]["name"] = "data-old-0"
                    spec = {"replicas": 0, "volumeClaimTemplates": [{"metadata": {"name": "data"}}]}
                objects[resource][("old-app", "old")] = {"metadata": metadata("old", "controller-uid", "old-app"), "spec": spec}
                self.blocked(plan, objects, source)

    def test_deleted_unarchived_custom_or_unresolved_pvc_owners_block_all_writes(self):
        for owner in ({"apiVersion": "example.io/v1", "kind": "Database", "name": "db", "uid": "db-uid", "controller": True},
                      {"apiVersion": "example.io/v1", "kind": "Database", "name": "db", "uid": "db-uid", "controller": False},
                      owner_ref("StatefulSet", "missing", "missing-uid"),
                      owner_ref("Pod", "missing", "missing-uid"), {}):
            with self.subTest(owner=owner):
                plan, objects, source = fixture()
                orphan_plan, orphan_objects, _ = fixture("deleted-unarchived", namespace="deleted-app")
                item = orphan_plan["volumes"][0]
                item.update(name="pv-orphan", uid="orphan-pv-uid", volume_handle="rbd-orphan")
                plan["volumes"].append(item)
                pvc = orphan_objects["persistentvolumeclaims"][("deleted-app", "data")]
                pvc["metadata"]["ownerReferences"] = [owner]
                pvc["spec"]["volumeName"] = "pv-orphan"
                pv = orphan_objects["persistentvolumes"][("", "pv-old")]
                pv["metadata"].update(name="pv-orphan", uid="orphan-pv-uid")
                pv["spec"]["csi"].update(volumeHandle="rbd-orphan")
                pv["spec"]["csi"]["volumeAttributes"]["imageName"] = "rbd-orphan"
                objects["persistentvolumeclaims"][("deleted-app", "data")] = pvc
                objects["persistentvolumes"][("", "pv-orphan")] = pv
                api = FakeAPI(objects)
                with self.assertRaisesRegex(retire.Refusal, "Orphan PVC ownerReferences"):
                    self.run_plan(plan, api, source)
                self.assertEqual(api.writes, [])

    def test_archived_pvc_owner_does_not_override_planned_workload_ownership(self):
        for planned in (False, True):
            with self.subTest(planned=planned):
                plan, objects, source = fixture()
                add_workload(plan, objects, "StatefulSet", "old", "old-uid", planned=planned)
                objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["ownerReferences"] = [
                    owner_ref("StatefulSet", "old", "old-uid")]
                api = FakeAPI(objects)
                if planned:
                    self.run_plan(plan, api, source, apply=False)
                    self.assertEqual(api.writes, [])
                    self.assertEqual(api.objects, objects)
                    self.run_plan(plan, api, source)
                    self.assertEqual(len(api.writes), 1)
                else:
                    with self.assertRaisesRegex(retire.Refusal, "Unplanned or foreign workload"):
                        self.run_plan(plan, api, source)
                    self.assertEqual(api.writes, [])

    def test_archived_pvc_unproven_or_ambiguous_owners_block_all_writes(self):
        valid = owner_ref("StatefulSet", "old", "old-uid")
        custom = {"apiVersion": "example.io/v1", "kind": "ClusterDatabase",
                  "name": "db", "uid": "db-uid", "controller": True}
        cases = [[custom], [dict(valid, apiVersion="example.io/v1")],
                 [dict(valid, kind="Deployment")], [dict(valid, name="missing")],
                 [dict(valid, uid="replaced-uid")], [dict(valid, namespace="active-app")],
                 [valid, dict(custom, controller=False)], [valid, valid],
                 [dict(valid, controller=False), dict(valid, controller=False)], [{}],
                 *[[{key: value for key, value in valid.items() if key != missing}]
                   for missing in ("apiVersion", "kind", "name", "uid")]]
        for owners in cases:
            with self.subTest(owners=owners):
                plan, objects, source = fixture()
                add_workload(plan, objects, "StatefulSet", "old", "old-uid", planned=True)
                objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["ownerReferences"] = owners
                self.blocked(plan, objects, source)

    def test_archived_pvc_owner_in_another_namespace_blocks_all_writes(self):
        plan, objects, source = fixture()
        add_workload(plan, objects, "StatefulSet", "old", "old-uid", namespace="active-app")
        objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["ownerReferences"] = [
            owner_ref("StatefulSet", "old", "old-uid")]
        self.blocked(plan, objects, source)

    def test_archived_retain_uses_exact_cas_patch_after_namespace_removal(self):
        plan, objects, source = fixture(policy="Retain")
        objects["persistentvolumeclaims"][("old-app", "data")]["metadata"]["annotations"] = {"helm.sh/resource-policy": "keep"}
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual([entry[0][0] for entry in api.writes], ["delete", "patch"])
        operations = api.writes[1][1]
        tests = {operation["path"]: operation["value"] for operation in operations[:-1]}
        self.assertEqual(tests, {"/metadata/uid": "pv-uid", "/metadata/resourceVersion": "2",
            "/spec/csi/driver": retire.DRIVER, "/spec/csi/volumeHandle": "rbd-old",
            "/spec/storageClassName": "standard-rwo", "/spec/persistentVolumeReclaimPolicy": "Retain"})
        self.assertEqual(self.receipts[-1]["physical_bytes_reclaimed"], "not-measured")

    def test_orphan_generic_ephemeral_pod_claim_is_not_unused(self):
        plan, objects, source = fixture("deleted-unarchived")
        claim = "old-scratch"
        plan["volumes"][0]["claim_name"] = claim
        pvc = objects["persistentvolumeclaims"].pop(("old-app", "data"))
        pvc["metadata"].update(name=claim, ownerReferences=[{"kind": "Pod", "name": "old", "uid": "pod-uid"}])
        objects["persistentvolumeclaims"][("old-app", claim)] = pvc
        objects["persistentvolumes"][("", "pv-old")]["spec"]["claimRef"]["name"] = claim
        objects["pods"][("old-app", "old")] = {"metadata": metadata("old", "pod-uid", "old-app"),
            "spec": {"volumes": [{"name": "scratch", "ephemeral": {"volumeClaimTemplate": {"spec": {}}}}]}}
        self.blocked(plan, objects, source)

    def test_replacement_uids_fail_before_mutation(self):
        for resource, pair in (("namespaces", ("", "old-app")), ("persistentvolumes", ("", "pv-old")),
                               ("persistentvolumeclaims", ("old-app", "data"))):
            with self.subTest(resource=resource):
                plan, objects, source = fixture()
                objects[resource][pair]["metadata"]["uid"] = "replacement-uid"
                self.blocked(plan, objects, source)

    def test_stale_resource_version_fails_without_retry(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        api.conflict = True
        with self.assertRaisesRegex(retire.Refusal, "same UID still present"):
            self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertTrue(any("--ignore-not-found" in args for args in api.reads))

    def test_reclaim_patch_conflict_does_not_retry_or_strip_finalizers(self):
        plan, objects, _ = fixture(policy="Retain")
        item = plan["volumes"][0]
        pv = objects["persistentvolumes"][("", "pv-old")]
        pv["metadata"]["finalizers"] = ["external-provisioner.volume.kubernetes.io/finalizer"]
        api = FakeAPI(objects)
        api.conflict = True
        with self.assertRaisesRegex(retire.Refusal, "same UID still present"):
            retire.mutate(api, "persistentvolumes", pv, item)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.objects["persistentvolumes"][("", "pv-old")], pv)

    def test_lost_mutation_response_reads_absence_then_stops(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        api.unknown_applied = True
        with self.assertRaisesRegex(retire.Refusal, "GET shows absence"):
            self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.objects["namespaces"], {})

    def test_unknown_backend_blocks_even_archived(self):
        plan, objects, source = fixture()
        objects["persistentvolumes"][("", "pv-old")]["spec"]["csi"]["driver"] = "other.csi.example"
        self.blocked(plan, objects, source)

    def test_different_rbd_handles_same_physical_image_block(self):
        plan, objects, source = fixture()
        other = copy.deepcopy(objects["persistentvolumes"][("", "pv-old")])
        other["metadata"] = metadata("active-pv", "active-pv-uid")
        other["spec"]["claimRef"] = {"namespace": "active-app", "name": "active-data", "uid": "active-claim-uid"}
        other["spec"]["csi"]["volumeHandle"] = "different-handle"
        objects["persistentvolumes"][("", "active-pv")] = other
        self.blocked(plan, objects, source)

    def test_different_cluster_ids_never_prove_disjoint_rbd_images(self):
        for inline in (False, True):
            with self.subTest(inline=inline):
                plan, objects, source = fixture()
                other = copy.deepcopy(objects["persistentvolumes"][("", "pv-old")])
                other["spec"]["csi"]["volumeAttributes"]["clusterID"] = "another-config-id"
                other["spec"]["csi"]["volumeHandle"] = "other-handle"
                if inline:
                    obj = add_workload(plan, objects, "Pod", "active", "active-uid", namespace="active-app")
                    obj["spec"]["volumes"] = [{"name": "inline", "csi": other["spec"]["csi"]}]
                else:
                    other["metadata"] = metadata("other-pv", "other-pv-uid")
                    other["spec"].pop("claimRef")
                    objects["persistentvolumes"][("", "other-pv")] = other
                self.blocked(plan, objects, source)

    def test_unresolved_other_static_rbd_identity_blocks(self):
        plan, objects, source = fixture()
        objects["persistentvolumes"][("", "static-pv")] = {"metadata": metadata("static-pv", "static-uid"),
            "spec": {"storageClassName": "standard-rwo", "csi": {"driver": retire.DRIVER, "volumeHandle": "static-other",
                "volumeAttributes": {"clusterID": "rook-ceph", "pool": "standard-rwo", "staticVolume": "true"}}}}
        self.blocked(plan, objects, source)

    def test_distinct_resolved_rbd_image_does_not_block(self):
        plan, objects, source = fixture()
        other = copy.deepcopy(objects["persistentvolumes"][("", "pv-old")])
        other["metadata"] = metadata("other-pv", "other-pv-uid")
        other["spec"].pop("claimRef")
        other["spec"]["csi"].update(volumeHandle="other-handle")
        other["spec"]["csi"]["volumeAttributes"]["imageName"] = "other-image"
        objects["persistentvolumes"][("", "other-pv")] = other
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertIn(("", "other-pv"), api.objects["persistentvolumes"])

    def test_known_foreign_cephfs_is_not_misclassified_as_rbd(self):
        plan, objects, source = fixture()
        objects["persistentvolumes"][("", "cephfs-pv")] = {"metadata": metadata("cephfs-pv", "cephfs-uid"),
            "spec": {"storageClassName": "standard-rwx", "csi": {"driver": "rook-ceph.cephfs.csi.ceph.com",
                "volumeHandle": "cephfs-handle", "volumeAttributes": {"clusterID": "rook-ceph", "pool": "cephfs-data", "fsName": "standard-rwx"}}}}
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertIn(("", "cephfs-pv"), api.objects["persistentvolumes"])

    def test_default_dynamic_rbd_resolution_and_unsafe_derivation_refusals(self):
        _, objects, _ = fixture()
        pv = objects["persistentvolumes"][("", "pv-old")]
        pv["spec"]["csi"]["volumeAttributes"].pop("imageName")
        uuid = "11111111-2222-3333-4444-555555555555"
        pv["spec"]["csi"]["volumeHandle"] = "0001-0009-rook-ceph-0000000000000001-" + uuid
        classes = objects["storageclasses.storage.k8s.io"]
        self.assertEqual(retire.rbd_identity(pv, classes), ("rook-ceph", "standard-rwo", "csi-vol-" + uuid))
        for fault in ("cluster", "prefix", "provisioner", "pool", "static", "handle"):
            with self.subTest(fault=fault):
                current, current_classes = copy.deepcopy(pv), copy.deepcopy(classes)
                attrs = current["spec"]["csi"]["volumeAttributes"]
                sc = current_classes[("", "standard-rwo")]
                if fault == "cluster":
                    attrs["clusterID"] = "other-cluster"
                elif fault == "prefix":
                    sc["parameters"]["volumeNamePrefix"] = "custom-"
                elif fault == "provisioner":
                    sc["provisioner"] = "other.rbd.csi.ceph.com"
                elif fault == "pool":
                    attrs.pop("pool")
                elif fault == "static":
                    attrs["staticVolume"] = "true"
                else:
                    current["spec"]["csi"]["volumeHandle"] = "unresolved-handle"
                with self.assertRaises(retire.Refusal):
                    retire.rbd_identity(current, current_classes)

    def test_dynamic_and_explicit_image_aliases_block(self):
        plan, objects, source = fixture()
        pv = objects["persistentvolumes"][("", "pv-old")]
        other = copy.deepcopy(pv)
        uuid = "11111111-2222-3333-4444-555555555555"
        handle = "0001-0009-rook-ceph-0000000000000001-" + uuid
        pv["spec"]["csi"]["volumeAttributes"].pop("imageName")
        pv["spec"]["csi"]["volumeHandle"] = plan["volumes"][0]["volume_handle"] = handle
        other["metadata"] = metadata("alias-pv", "alias-pv-uid")
        other["spec"].pop("claimRef")
        other["spec"]["csi"]["volumeHandle"] = "different-handle"
        other["spec"]["csi"]["volumeAttributes"]["imageName"] = "csi-vol-" + uuid
        objects["persistentvolumes"][("", "alias-pv")] = other
        self.blocked(plan, objects, source)

    def test_inline_physical_rbd_alias_and_unresolved_custom_rbd_block(self):
        for fault in ("alias", "unresolved"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                csi = {"driver": retire.DRIVER, "volumeAttributes": {
                    "clusterID": "rook-ceph", "pool": "standard-rwo", "imageName": "rbd-old"}}
                if fault == "unresolved":
                    csi = {"driver": "custom-rbd.csi.example", "volumeAttributes": {}}
                pod = add_workload(plan, objects, "Pod", "active", "active-pod-uid", namespace="active-app")
                pod["spec"]["volumes"] = [{"name": "inline", "csi": csi}]
                self.blocked(plan, objects, source)

    def test_direct_pv_delete_and_unscoped_claim_delete_are_not_supported(self):
        for resource, namespace in (("persistentvolumes", ""), ("persistentvolumeclaims", ""), ("jobs.batch", "")):
            with self.subTest(resource=resource), self.assertRaises(retire.Refusal):
                retire.delete_path(resource, "resource", namespace)

    def test_interrupted_missing_goals_resume_without_writes(self):
        plan, objects, source = fixture()
        for resource in ("namespaces", "persistentvolumeclaims", "persistentvolumes"):
            objects[resource] = {}
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])
        self.assertEqual(self.receipts[-1]["event"], "planned-absence-verified")

    def test_retained_pv_resumes_after_namespace_and_claim_gone(self):
        plan, objects, source = fixture(policy="Retain")
        objects["namespaces"] = {}
        objects["persistentvolumeclaims"] = {}
        objects["persistentvolumes"][("", "pv-old")]["status"]["phase"] = "Released"
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual([entry[0][0] for entry in api.writes], ["patch"])

    def test_attachment_blocks_orphan_and_prevents_archived_reclaim_until_detached(self):
        for disposition in ("archived", "deleted-unarchived"):
            with self.subTest(disposition=disposition):
                plan, objects, source = fixture(disposition, "Retain" if disposition == "archived" else "Delete")
                objects["volumeattachments.storage.k8s.io"][("", "attachment")] = {
                    "metadata": metadata("attachment", "attachment-uid"),
                    "spec": {"source": {"persistentVolumeName": "pv-old"}}}
                api = FakeAPI(objects)
                with self.assertRaises(retire.Refusal):
                    self.run_plan(plan, api, source)
                self.assertEqual([entry[0][0] for entry in api.writes], ["delete"] if disposition == "archived" else [])
                self.assertIn(("", "attachment"), api.objects["volumeattachments.storage.k8s.io"])

    def test_read_errors_and_json_null_are_not_absence(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        api.read_failure = True
        with self.assertRaisesRegex(retire.Refusal, "read failed"):
            self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])
        with patch.object(api, "run", return_value="null"):
            with self.assertRaises(retire.Refusal):
                retire.get_goal(api, "namespaces", "old-app", "namespace-uid")

    def test_namespace_wait_is_bounded_without_force(self):
        plan, objects, source = fixture()
        api = FakeAPI(objects)
        api.keep_namespace = True
        with self.assertRaisesRegex(retire.Refusal, "Timed out"):
            self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_healthy_renovate_historical_closeout_only(self):
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        unrelated = {"metadata": metadata("unrelated-failure", "other-job-uid", "renovate"),
                     "status": {"conditions": [{"type": "Failed", "status": "True"}]}}
        objects["jobs.batch"][("renovate", "unrelated-failure")] = unrelated
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(api.writes[0][0][2], "/apis/batch/v1/namespaces/renovate/jobs/renovate-29837640")
        self.assertIn(("renovate", "renovate-new"), api.objects["jobs.batch"])
        self.assertIn(("renovate", "unrelated-failure"), api.objects["jobs.batch"])
        self.assertEqual(api.objects["cronjobs.batch"], objects["cronjobs.batch"])
        receipt = next(item for item in self.receipts if item["event"] == "owner-closed-historical")
        self.assertFalse(receipt["root_cause_repaired"])

    def test_healthy_current_renovate_run_within_window_does_not_hide_or_block_history(self):
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        running_renovate(objects)
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        self.assertIn(("renovate", "renovate-current"), api.objects["jobs.batch"])
        self.assertIn(("renovate", "renovate-current-pod"), api.objects["pods"])

    def test_benign_current_renovate_initialization_is_bounded_and_corroborated(self):
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        _, pod = running_renovate(objects)
        pod["status"]["phase"] = "Pending"
        pod["status"]["containerStatuses"][0].update(ready=False, state={"waiting": {"reason": "ContainerCreating"}})
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)

    def test_renovate_retrying_failed_pods_waiting_exits_and_overdue_work_block_all_writes(self):
        for fault in ("failed-count", "failure-target", "failed-pod", "waiting", "nonzero-exit", "restart", "overdue", "foreign-pod", "missing-schedule-job"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                renovate(objects, plan)
                job, pod = running_renovate(objects, age=31 if fault == "overdue" else 10)
                container = pod["status"]["containerStatuses"][0]
                if fault == "failed-count":
                    job["status"]["failed"] = 1
                elif fault == "failure-target":
                    job["status"]["conditions"] = [{"type": "FailureTarget", "status": "True"}]
                elif fault == "failed-pod":
                    pod["status"]["phase"] = "Failed"
                elif fault == "waiting":
                    container["state"] = {"waiting": {"reason": "ImagePullBackOff"}}
                elif fault == "nonzero-exit":
                    container["lastState"] = {"terminated": {"exitCode": 1}}
                elif fault == "restart":
                    container["restartCount"] = 1
                elif fault == "foreign-pod":
                    pod["metadata"]["ownerReferences"][0]["uid"] = "foreign-job-uid"
                elif fault == "missing-schedule-job":
                    objects["cronjobs.batch"][("renovate", "renovate")]["status"]["lastScheduleTime"] = (NOW - timedelta(minutes=5)).isoformat()
                self.blocked(plan, objects, source)

    def test_missing_historical_job_resumes_with_current_success_without_touching_older_failures(self):
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        old = objects["jobs.batch"].pop(("renovate", "renovate-29837640"))
        old["metadata"].update(name="renovate-older", uid="older-job-uid")
        objects["jobs.batch"][("renovate", "renovate-older")] = old
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])
        self.assertEqual(api.objects, objects)

    def test_renovate_closeout_requires_all_health_and_owner_evidence(self):
        for fault in ("stale", "owner", "running", "not-complete", "newer-failure", "cron-replacement"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                renovate(objects, plan)
                cron = objects["cronjobs.batch"][("renovate", "renovate")]
                old = objects["jobs.batch"][("renovate", "renovate-29837640")]
                new = objects["jobs.batch"][("renovate", "renovate-new")]
                if fault == "stale":
                    cron["status"]["lastSuccessfulTime"] = (NOW - timedelta(hours=37)).isoformat()
                elif fault == "owner":
                    old["metadata"]["ownerReferences"][0]["uid"] = "foreign-uid"
                elif fault == "running":
                    old["status"]["active"] = 1
                elif fault == "not-complete":
                    new["status"]["conditions"] = []
                elif fault == "newer-failure":
                    new["status"]["conditions"] = [{"type": "Failed", "status": "True"}]
                else:
                    cron["metadata"]["uid"] = "replacement-cron-uid"
                self.blocked(plan, objects, source)

    def test_renovate_missed_daily_schedule_blocks_despite_success_inside_36_hours(self):
        plan, objects, source = fixture()
        renovate(objects, plan)
        created = NOW - timedelta(hours=25)
        completed = created + timedelta(minutes=30)
        new = objects["jobs.batch"][("renovate", "renovate-new")]
        new["metadata"]["creationTimestamp"] = created.isoformat()
        new["status"]["completionTime"] = completed.isoformat()
        cron = objects["cronjobs.batch"][("renovate", "renovate")]
        cron["status"].update(lastScheduleTime=created.isoformat(), lastSuccessfulTime=completed.isoformat())
        api = FakeAPI(objects)
        with self.assertRaisesRegex(retire.Refusal, "Latest due daily"):
            self.run_plan(plan, api, source)
        self.assertEqual(api.writes, [])

    def test_renovate_five_minute_scheduling_grace_is_not_a_36_hour_loophole(self):
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        created = NOW - timedelta(days=1)
        completed = created + timedelta(minutes=30)
        new = objects["jobs.batch"][("renovate", "renovate-new")]
        new["metadata"]["creationTimestamp"] = created.isoformat()
        new["status"]["completionTime"] = completed.isoformat()
        cron = objects["cronjobs.batch"][("renovate", "renovate")]
        cron["spec"]["schedule"] = "0 12 * * *"
        cron["status"].update(lastScheduleTime=created.isoformat(), lastSuccessfulTime=completed.isoformat())
        api = FakeAPI(objects)
        self.run_plan(plan, api, source)
        self.assertEqual(len(api.writes), 1)
        late_api = FakeAPI(objects)
        with self.assertRaisesRegex(retire.Refusal, "Latest due daily"):
            self.run_plan(plan, late_api, source, now=NOW + timedelta(minutes=6))
        self.assertEqual(late_api.writes, [])

    def test_daily_due_handles_chicago_dst_gaps_folds_and_grace(self):
        cases = [
            ("0 9 * * *", "2026-03-08T14:04:00+00:00", "2026-03-07T15:00:00+00:00"),
            ("0 9 * * *", "2026-03-08T14:05:00+00:00", "2026-03-08T14:00:00+00:00"),
            ("30 2 * * *", "2026-03-08T09:00:00+00:00", "2026-03-07T08:30:00+00:00"),
            ("30 1 * * *", "2026-11-01T07:34:00+00:00", "2026-11-01T06:30:00+00:00"),
            ("30 1 * * *", "2026-11-01T07:35:00+00:00", "2026-11-01T07:30:00+00:00")]
        for schedule, current, expected in cases:
            with self.subTest(schedule=schedule, current=current):
                self.assertEqual(retire.latest_daily_due(schedule, "America/Chicago", retire.instant(current)), retire.instant(expected))

    def test_timezone_plan_field_and_fixed_daily_expression_are_strict(self):
        for fault in ("missing-zone", "unknown-zone", "mismatched-zone", "unsupported-cron"):
            with self.subTest(fault=fault):
                plan, objects, source = fixture()
                renovate(objects, plan)
                cron = objects["cronjobs.batch"][("renovate", "renovate")]
                if fault == "missing-zone":
                    del plan["historical_jobs"][0]["cronjob_timezone"]
                elif fault == "unknown-zone":
                    plan["historical_jobs"][0]["cronjob_timezone"] = "Not/A_Zone"
                elif fault == "mismatched-zone":
                    cron["spec"]["timeZone"] = "America/Chicago"
                else:
                    cron["spec"]["schedule"] = "*/5 * * * *"
                self.blocked(plan, objects, source)
        for schedule in ("@daily", "0 9 * * 1", "60 9 * * *", "0 24 * * *"):
            with self.subTest(schedule=schedule), self.assertRaises(retire.Refusal):
                retire.latest_daily_due(schedule, "UTC", NOW)
        with self.assertRaises(retire.Refusal):
            retire.cron_timezone("localtime")
        plan, objects, source = fixture()
        plan["namespaces"], plan["volumes"] = [], []
        renovate(objects, plan)
        objects["cronjobs.batch"][("renovate", "renovate")]["spec"]["timeZone"] = "UTC"
        self.run_plan(plan, FakeAPI(objects), source)

    def test_unknown_plan_fields_actions_and_duplicate_json_rejected(self):
        for target in ("top", "namespace", "volume", "job"):
            with self.subTest(target=target):
                plan, objects, source = fixture()
                renovate(objects, plan)
                obj = plan if target == "top" else plan[{"namespace": "namespaces", "volume": "volumes", "job": "historical_jobs"}[target]][0]
                obj["action"] = "force-delete"
                self.blocked(plan, objects, source)
        with self.assertRaises(retire.Refusal):
            retire.decode_plan('{"version":1,"version":1}')

    def test_uncommitted_source_or_plan_rejected_without_external_process(self):
        calls = []

        def dirty(*args):
            calls.append(args)
            self.assertEqual(args[0], "status")
            return b"?? scripts/retirements/run.json\n"

        with self.assertRaisesRegex(retire.Refusal, "dirty or untracked"):
            retire.committed_files(("scripts/retirements/run.json",), dirty)
        self.assertEqual(len(calls), 1)

    def test_committed_source_must_be_byte_identical_to_head(self):
        def read_git(*args):
            if args[0] == "status":
                return b""
            if args[0] == "ls-tree":
                return b"100644 blob abcdef\tscripts/retire-workloads.py\n"
            if args[0] == "show":
                return b"not the committed executor"
            self.fail("Unexpected fake Git read")

        with self.assertRaisesRegex(retire.Refusal, "differs from committed HEAD"):
            retire.committed_files(("scripts/retire-workloads.py",), read_git)

    def test_foundational_policy_is_required_clean_but_agents_is_not(self):
        policy = ".agent/rules/foundational-rules.md"
        self.assertIn(policy, retire.SOURCES)
        self.assertNotIn("AGENTS.md", retire.SOURCES)

        def dirty_policy(*args):
            self.assertEqual(args, ("status", "--porcelain=v1", "--untracked-files=all", "--", policy))
            return (" M " + policy + "\n").encode()

        with self.assertRaisesRegex(retire.Refusal, "dirty or untracked"):
            retire.committed_files((policy,), dirty_policy)

    def test_batched_committed_texts_preserve_utf8_empty_and_unterminated_blob_boundaries(self):
        blobs = {f"apps/consumer/templates/item-{index:03}.yaml": (f"value: café-{index}".encode() if index else b"")
                 for index in range(65)}
        inventory = b"".join(b"100644 blob " + b"a" * 40 + b" " + str(len(raw)).encode() + b"\t" + path.encode() + b"\0"
                             for path, raw in blobs.items())
        sizes = retire.tree_files(inventory)
        calls = []

        def read_git(*args):
            self.assertEqual(args[0], "show")
            self.assertLessEqual(len(args) - 1, 64)
            calls.append(args)
            self.assertTrue(all(ref.startswith("HEAD:") for ref in args[1:]))
            return b"".join(blobs[ref.removeprefix("HEAD:")] for ref in args[1:])

        texts = retire.committed_texts(blobs, sizes, read_git)
        self.assertEqual(texts, {path: raw.decode() for path, raw in blobs.items()})
        self.assertEqual(len(calls), 2)
        self.process_mock.assert_not_called()

    def test_truncated_committed_inventory_or_batch_is_not_accepted(self):
        with self.assertRaises(retire.Refusal):
            retire.tree_files(b"100644 blob abc 12\tapps/consumer/values.yaml")
        with self.assertRaisesRegex(retire.Refusal, "byte lengths changed"):
            retire.committed_texts(["apps/consumer/values.yaml"], {"apps/consumer/values.yaml": 12}, lambda *args: b"short")

    def test_source_gate_batches_head_and_preserves_uncommitted_active_chart_protection(self):
        archive = "archived/apps/OLDsteam-headless"
        blobs = {"apps/consumer/Chart.yaml": b"apiVersion: v2\nname: consumer\n",
                 "apps/consumer/values.yaml": b"# namespace: code\ndescription: 'namespace: code'\nnamespace: shared-hosting\n",
                 archive + "/Chart.yaml": b"apiVersion: v2\nname: steam-headless\n"}
        inventory = b"".join(b"100644 blob " + b"a" * 40 + b" " + str(len(raw)).encode() + b"\t" + path.encode() + b"\0"
                             for path, raw in blobs.items())
        outputs = {
            ("rev-parse", "--show-toplevel"): str(retire.ROOT).encode() + b"\n",
            ("symbolic-ref", "--short", "HEAD"): b"master\n",
            ("config", "--get-all", "remote.origin.url"): retire.ORIGIN.encode() + b"\n",
            ("remote", "get-url", "origin"): retire.ORIGIN.encode() + b"\n",
            ("rev-parse", "HEAD"): b"a" * 40 + b"\n",
            ("ls-remote", "origin", "refs/heads/master"): b"a" * 40 + b"\trefs/heads/master\n",
            ("ls-tree", "-r", "--long", "-z", "HEAD"): inventory}
        for local_chart in (False, True):
            with self.subTest(local_chart=local_chart):
                calls = []

                def read_git(*args):
                    calls.append(args)
                    if args[0] == "show":
                        return b"".join(blobs[ref.removeprefix("HEAD:")] for ref in args[1:])
                    return outputs[args]

                chart_paths = [retire.ROOT / "apps/local-active/Chart.yaml"] if local_chart else []
                local_files = [SimpleNamespace(is_file=lambda: True, suffix=".yaml",
                    relative_to=lambda root: "apps/local-active/values.yaml",
                    read_text=lambda: "# namespace: code\nnamespace: worktree-active\n")] if local_chart else []
                with patch.object(retire, "committed_files") as checked_files, \
                        patch.object(retire.Path, "glob", return_value=chart_paths), \
                        patch.object(retire.Path, "rglob", return_value=local_files):
                    source = retire.source_gate("scripts/retirements/run.json", read_git)
                self.assertEqual(source["archive_aliases"][archive], {"OLDsteam-headless", "steam-headless"})
                expected_active = {"consumer", "shared-hosting"} | ({"local-active", "worktree-active"} if local_chart else set())
                self.assertEqual(source["active"], expected_active)
                self.assertEqual(len([args for args in calls if args[0] == "show"]), 1)
                self.assertEqual(calls.count(("rev-parse", "HEAD")), 2)
                checked_files.assert_called_once_with((*retire.SOURCES, "scripts/retirements/run.json"), read_git)
        self.process_mock.assert_not_called()

    def test_source_gate_resolves_committed_and_worktree_env_with_separate_values(self):
        chart = "apps/consumer"
        template = chart + "/templates/workload.yaml"
        values_path = chart + "/values.yaml"
        stanza = "{{- if .Values.enabled }}\nenv: {{ toYaml .Values.driver.env | nindent 6 }}\n{{- end }}\n"
        committed = {chart + "/Chart.yaml": "name: consumer\n", template: stanza,
            values_path: "driver:\n  env: [{name: DATABASE_HOST, value: db.committed-target}]\n"
                         "unused:\n  env: {DATABASE_HOST: {value: db.committed-values}}\n"}
        current = {chart + "/Chart.yaml": "name: consumer\n", template: stanza,
            values_path: "driver:\n  env: {DATABASE_HOST: {value: db.worktree-target}}\n"
                         "unused:\n  env: [{name: DATABASE_HOST, value: db.worktree-values}]\n"}
        outputs = {
            ("rev-parse", "--show-toplevel"): str(retire.ROOT).encode() + b"\n",
            ("symbolic-ref", "--short", "HEAD"): b"master\n",
            ("config", "--get-all", "remote.origin.url"): retire.ORIGIN.encode() + b"\n",
            ("remote", "get-url", "origin"): retire.ORIGIN.encode() + b"\n",
            ("rev-parse", "HEAD"): b"a" * 40 + b"\n",
            ("ls-remote", "origin", "refs/heads/master"): b"a" * 40 + b"\trefs/heads/master\n",
            ("ls-tree", "-r", "--long", "-z", "HEAD"): b""}
        for context in (None, "committed", "worktree"):
            for fault in ((None,) if context is None else ("missing-values", "missing-path", "invalid-values")):
                with self.subTest(context=context, fault=fault):
                    head_texts, worktree_texts = dict(committed), dict(current)
                    target = head_texts if context == "committed" else worktree_texts
                    if fault == "missing-values":
                        del target[values_path]
                    elif fault == "missing-path":
                        target[values_path] = "driver: {}\n"
                    elif fault == "invalid-values":
                        target[values_path] = "driver: [private-value\n"
                    files = dict.fromkeys(head_texts, 0)
                    with patch.object(retire, "committed_files"), \
                            patch.object(retire, "tree_files", return_value=files), \
                            patch.object(retire, "committed_texts", return_value=head_texts), \
                            patch.object(retire.Path, "glob", return_value=[]), \
                            patch.object(retire.Path, "rglob", return_value=[retire.ROOT / path for path in worktree_texts]), \
                            patch.object(retire.Path, "is_file", autospec=True,
                                side_effect=lambda path: str(path.relative_to(retire.ROOT)) in worktree_texts), \
                            patch.object(retire.Path, "read_text", autospec=True,
                                side_effect=lambda path: worktree_texts[str(path.relative_to(retire.ROOT))]):
                        if fault:
                            with self.assertRaises(retire.Refusal) as caught:
                                retire.source_gate("scripts/retirements/run.json", lambda *args: outputs[args])
                            self.assertNotIn("private-value", str(caught.exception))
                        else:
                            source = retire.source_gate("scripts/retirements/run.json", lambda *args: outputs[args])
                            refs = set().union(*(retire.namespace_references(text) for text in source["texts"]))
                            self.assertEqual(refs, {"committed-target", "committed-values", "worktree-target", "worktree-values"})
                            self.assertIn(retire.strip_source_comments(retire.resolve_env_templates(stanza, committed[values_path])), source["texts"])
                            self.assertIn(retire.strip_source_comments(retire.resolve_env_templates(stanza, current[values_path])), source["texts"])
        self.process_mock.assert_not_called()
        self.api_mock.assert_not_called()

    def test_wrong_origin_branch_or_unpushed_head_refused(self):
        for fault in ("origin", "branch", "remote-head"):
            with self.subTest(fault=fault):
                outputs = {
                    ("rev-parse", "--show-toplevel"): str(retire.ROOT).encode() + b"\n",
                    ("symbolic-ref", "--short", "HEAD"): b"master\n",
                    ("config", "--get-all", "remote.origin.url"): retire.ORIGIN.encode() + b"\n",
                    ("remote", "get-url", "origin"): retire.ORIGIN.encode() + b"\n",
                    ("rev-parse", "HEAD"): b"a" * 40 + b"\n",
                    ("ls-remote", "origin", "refs/heads/master"): b"a" * 40 + b"\trefs/heads/master\n"}
                if fault == "origin":
                    outputs[("config", "--get-all", "remote.origin.url")] = b"git@foreign:repo.git\n"
                elif fault == "branch":
                    outputs[("symbolic-ref", "--short", "HEAD")] = b"feature\n"
                else:
                    outputs[("ls-remote", "origin", "refs/heads/master")] = b"b" * 40 + b"\trefs/heads/master\n"
                with patch.object(retire, "committed_files"), self.assertRaises(retire.Refusal):
                    retire.source_gate("scripts/retirements/run.json", lambda *args: outputs[args])
        self.process_mock.assert_not_called()

    def test_foreign_plan_path_and_foreign_checkout_rejected(self):
        for path in ("/tmp/run.json", "scripts/retirements/../run.json", "apps/run.json"):
            with self.subTest(path=path), self.assertRaises(retire.Refusal):
                retire.source_gate(path, lambda *args: self.fail("Foreign plan must fail before Git"))
        with self.assertRaisesRegex(retire.Refusal, "Foreign Git checkout"):
            retire.source_gate("scripts/retirements/run.json", lambda *args: b"/foreign/checkout\n")
        self.process_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
