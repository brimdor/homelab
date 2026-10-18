#!/usr/bin/env python3
"""Offline regression tests: python3 -B -m unittest discover -s scripts -p test_retire_nfs_discovery_race.py."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("nfs_cleanup", Path(__file__).with_name("retire-nfs-discovery-race.py"))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
HEAD = "a" * 40


def obj(name, uid, namespace=m.NS):
    metadata = {"name": name, "uid": uid, "resourceVersion": "17", "generation": 1}
    if namespace:
        metadata["namespace"] = namespace
    return {"metadata": metadata}


def generators():
    return [{"metadata": {"name": name}, "spec": {"generators": [{"git": {
        "repoURL": m.REPO, "revision": "master", "directories": [
            {"path": "system/*"}, {"path": "system/" + m.NS, "exclude": True}]}}]}}
        for name in ("root", "root-crd-replace")]


def app():
    return {"metadata": {"annotations": {"argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}},
            "spec": {"source": {"repoURL": m.REPO, "path": "system/" + m.NS, "targetRevision": "master",
                                "helm": {"releaseName": m.NS}},
                     "destination": {"name": "in-cluster", "namespace": "kube-system"},
                     "syncPolicy": {"syncOptions": ["Prune=false", "Delete=false"]}},
            "status": {"sync": {"revision": HEAD}}}


def manifests(_head):
    return [{"kind": kind, "metadata": {"name": name, "namespace": namespace}} for kind, name, namespace in [
        ("Deployment", m.NAME, "kube-system"), ("ServiceAccount", m.NAME, "kube-system"),
        ("Role", m.ROLE, "kube-system"), ("RoleBinding", m.ROLE, "kube-system"),
        ("ClusterRole", m.NAME + "-runner", ""), ("ClusterRoleBinding", "run-" + m.NAME, ""),
        ("StorageClass", "nfs-rwx", "")]]


class FakeAPI(m.API):
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.sets = generators()
        self.resources = sorted({key[:2] for key in m.PINS} | {("v1", "pods"), ("v1", "secrets"),
                                ("v1", "persistentvolumeclaims"), ("example.test/v1", "unknowns")})
        self.objects[("v1", "namespaces", m.NS, "")] = obj(m.NS, m.NS_UID, "")
        self.objects[("v1", "namespaces", m.NS, "")]["spec"] = {"finalizers": ["kubernetes"]}
        for key, uid in m.PINS.items():
            item = obj(key[2], uid)
            if key[1] in ("deployments", "replicasets"):
                item["spec"] = {"replicas": 0, "selector": {"matchLabels": {"app": "nfs"}},
                                "template": {"spec": {"serviceAccountName": m.NAME, "volumes": [{
                                    "name": "nfs-subdir-external-provisioner-root",
                                    "nfs": {"server": "10.0.40.3", "path": "/mnt/user/heartlib"}}]}}}
                item["status"] = {"observedGeneration": 1}
            if key[1] == "replicasets":
                item["metadata"]["ownerReferences"] = [{"apiVersion": "apps/v1", "kind": "Deployment", "name": m.NAME,
                    "uid": m.PINS[m.ORDER[0]], "controller": True, "blockOwnerDeletion": True}]
            if key[1] == "endpoints":
                item["metadata"]["annotations"] = {"control-plane.alpha.kubernetes.io/leader": json.dumps({
                    "holderIdentity": m.NAME + "-657tm999_47ebdf71-f523-4a2a-8cd1-f5475bd1621d",
                    "renewTime": "2026-10-18T22:49:17Z"})}
            if key[1] == "configmaps":
                item["data"] = {"ca.crt": "public-certificate"}
            if key[1] == "events":
                subject = key[2].rsplit(".", 1)[0]
                kind, uid = m.EVENT_SUBJECTS[subject]
                item["involvedObject"] = {"namespace": m.NS, "name": subject, "kind": kind, "uid": uid}
            self.objects[key + (m.NS,)] = item
        original = copy.deepcopy(self.objects[m.ORDER[0] + (m.NS,)])
        original["metadata"].update(uid=m.ORIGINAL_UID, namespace="kube-system")
        original["spec"]["replicas"] = 1
        original["status"].update(readyReplicas=1, availableReplicas=1)
        self.objects[("apps/v1", "deployments", m.NAME, "kube-system")] = original
        for version, resource, name, namespace in [
            ("v1", "serviceaccounts", m.NAME, "kube-system"), (m.RBAC, "roles", m.ROLE, "kube-system"),
            (m.RBAC, "rolebindings", m.ROLE, "kube-system"), (m.RBAC, "clusterroles", m.NAME + "-runner", ""),
            (m.RBAC, "clusterrolebindings", "run-" + m.NAME, ""), ("storage.k8s.io/v1", "storageclasses", "nfs-rwx", "")]:
            item = obj(name, "protected-" + resource, namespace)
            if resource == "clusterrolebindings":
                item.update(subjects=[{"kind": "ServiceAccount", "name": m.NAME, "namespace": "kube-system"}],
                            roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": m.NAME + "-runner"})
            self.objects[(version, resource, name, namespace)] = item
        self.objects[("argoproj.io/v1alpha1", "applications", m.NS, "argocd")] = app()
        self.objects[("v1", "configmaps", "kube-root-ca.crt", "kube-system")] = {"data": {"ca.crt": "public-certificate"}}
        self.pv = obj("protected-pv", "pv-uid", "")
        self.pv.update(spec={"claimRef": {"namespace": "active", "name": "data", "uid": "pvc-uid"},
                             "nfs": {"server": "10.0.40.3", "path": "/mnt/user/heartlib/active"},
                             "persistentVolumeReclaimPolicy": "Retain"}, status={"phase": "Bound"})
        self.pvc = obj("data", "pvc-uid", "active")
        self.pvc.update(spec={"volumeName": "protected-pv"}, status={"phase": "Bound"})
        self.pod = obj("original-pod", "original-pod-uid", "kube-system")
        self.pod["metadata"]["ownerReferences"] = [{"kind": "ReplicaSet", "name": "original-rs", "uid": "rs-uid", "controller": True}]
        self.pod["status"] = {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                              "containerStatuses": [{"name": "nfs", "restartCount": 0}]}
        rs = obj("original-rs", "rs-uid", "kube-system")
        rs["metadata"]["ownerReferences"] = [{"uid": m.ORIGINAL_UID, "controller": True}]
        self.objects[("apps/v1", "replicasets", "original-rs", "kube-system")] = rs

    def get(self, version, resource, name, namespace=""):
        return copy.deepcopy(self.objects.get((version, resource, name, namespace)))

    def raw(self, path):
        if path == "/api/v1/persistentvolumes":
            return {"items": [copy.deepcopy(self.pv)]}
        if path == "/api/v1/persistentvolumeclaims":
            return {"items": [copy.deepcopy(self.pvc)]}
        if path.startswith("/api/v1/namespaces/kube-system/pods?"):
            return {"items": [copy.deepcopy(self.pod)]}
        if path.endswith("/applicationsets"):
            return {"items": copy.deepcopy(self.sets)}
        raise AssertionError(path)

    def discover(self):
        return self.resources[:]

    def inventory(self, resources, namespace):
        return {key[:3]: copy.deepcopy(item["metadata"]) for key, item in self.objects.items()
                if key[3] == namespace and key[:2] in resources}

    def call(self, *args, payload=None):
        self.writes.append((args, json.loads(payload)))
        uid = json.loads(payload)["preconditions"]["uid"]
        keys = [key for key, item in self.objects.items() if item.get("metadata", {}).get("uid") == uid]
        for key in keys:
            del self.objects[key]
            if key[1] == "deployments":
                for child in list(self.objects):
                    if child[1] == "replicasets" and child[3] == m.NS:
                        del self.objects[child]
            if key[1] == "namespaces":
                for child in list(self.objects):
                    if child[3] == m.NS:
                        del self.objects[child]
        return "{}"


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()

    def execute(self, apply=False):
        m.execute(self.api, lambda _apply: HEAD, manifests, apply, emit=lambda _: None, sleep=lambda _: None)

    def test_check_never_writes(self):
        self.execute()
        self.assertEqual(self.api.writes, [])

    def test_unexpected_namespace_finalizers_refused(self):
        for section, finalizers in [("metadata", ["example.test/hold"]), ("spec", ["kubernetes", "example.test/hold"])]:
            self.api = FakeAPI()
            self.api.objects[("v1", "namespaces", m.NS, "")][section]["finalizers"] = finalizers
            with self.assertRaisesRegex(m.Refusal, "namespace finalizers"):
                self.execute(True)
            self.assertFalse(self.api.writes)

    def test_stalled_deletion_stops_and_checks_protected_objects(self):
        def stalled(*args, payload=None):
            self.api.writes.append((args, json.loads(payload)))
            self.api.objects[m.ORDER[0] + (m.NS,)]["metadata"]["deletionTimestamp"] = "2026-10-18T23:00:00Z"
        with patch.object(self.api, "call", side_effect=stalled), \
                patch.object(m, "protected", wraps=m.protected) as protected:
            with self.assertRaisesRegex(m.Refusal, "observation exceeded"):
                m.execute(self.api, lambda _: HEAD, manifests, True, emit=lambda _: None,
                          sleep=lambda _: None, clock=iter([0, 601]).__next__)
            self.assertGreaterEqual(protected.call_count, 3)
        self.assertEqual(len(self.api.writes), 1)

    def test_exact_delete_options_and_protected_storage(self):
        before = copy.deepcopy((self.api.pv, self.api.pvc, self.api.pod))
        self.execute(True)
        self.assertEqual(len(self.api.writes), 6)
        for args, payload in self.api.writes:
            self.assertEqual(args[0:2], ("delete", "--raw"))
            self.assertEqual(args[-2:], ("-f", "-"))
            self.assertEqual(payload, {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground",
                                      "preconditions": {"uid": payload["preconditions"]["uid"], "resourceVersion": "17"}})
            self.assertIn(payload["preconditions"]["uid"], {m.PINS[k] for k in m.ORDER} | {m.NS_UID})
            self.assertNotIn("kube-system", args[2])
            self.assertNotIn("persistentvolume", args[2])
        self.assertEqual((self.api.pv, self.api.pvc, self.api.pod), before)
        self.assertIsNone(self.api.get("v1", "namespaces", m.NS))

    def test_replacements_refused_before_write(self):
        for key in list(m.PINS) + [("v1", "namespaces", m.NS)]:
            with self.subTest(key=key):
                self.api = FakeAPI()
                namespace = "" if key[1] == "namespaces" else m.NS
                self.api.objects[key + (namespace,)]["metadata"]["uid"] = "replacement"
                with self.assertRaises(m.Refusal):
                    self.execute(True)
                self.assertFalse(self.api.writes)

    def test_any_pod_pvc_secret_or_unknown_refused(self):
        for version, resource in [("v1", "pods"), ("v1", "persistentvolumeclaims"), ("v1", "secrets"),
                                  ("example.test/v1", "unknowns")]:
            with self.subTest(resource=resource):
                self.api = FakeAPI()
                item = obj("surprise", "unknown")
                item["status"] = {"phase": "Running"}
                self.api.objects[(version, resource, "surprise", m.NS)] = item
                with self.assertRaisesRegex(m.Refusal, "Unknown/protected"):
                    self.execute(True)
                self.assertFalse(self.api.writes)

    def test_replicas_or_unobserved_scale_refused(self):
        for key, value in [("replicas", 1), ("observedGeneration", 0)]:
            self.api = FakeAPI()
            item = self.api.objects[m.ORDER[0] + (m.NS,)]
            item["spec" if key == "replicas" else "status"][key] = value
            with self.assertRaises(m.Refusal):
                self.execute(True)
            self.assertFalse(self.api.writes)

    def test_namespace_storage_binding_refused(self):
        self.api.pv["spec"]["claimRef"]["namespace"] = m.NS
        with self.assertRaisesRegex(m.Refusal, "storage binding"):
            self.execute(True)
        self.assertFalse(self.api.writes)

    def test_nas_pvc_and_other_namespaces_never_delete_targets(self):
        for key in [("v1", "persistentvolumes", "protected-pv"), ("v1", "persistentvolumeclaims", "data"),
                    ("v1", "namespaces", "default"), (m.RBAC, "clusterrolebindings", "run-" + m.NAME)]:
            with self.assertRaises(m.Refusal):
                m.delete_request(key, self.api.pv)
        original = self.api.get("apps/v1", "deployments", m.NAME, "kube-system")
        with self.assertRaises(m.Refusal):
            m.delete_request(m.ORDER[0], original)
        for volume in [{"name": "data", "persistentVolumeClaim": {"claimName": "data"}},
                       {"name": "data", "nfs": {"server": "10.0.40.3", "path": "/mnt/user/other"}}]:
            target = self.api.get(*m.ORDER[0], m.NS)
            target["spec"]["template"]["spec"]["volumes"] = [volume]
            with self.assertRaises(m.Refusal):
                m.delete_request(m.ORDER[0], target)

    def test_discovery_failure_refuses_before_writes(self):
        with patch.object(self.api, "discover", side_effect=m.Refusal("discovery unavailable")):
            with self.assertRaises(m.Refusal):
                self.execute(True)
        self.assertFalse(self.api.writes)

    def test_generator_and_application_drift_refused(self):
        self.api.sets[0]["spec"]["generators"][0]["git"]["directories"].pop()
        with self.assertRaisesRegex(m.Refusal, "Active generator"):
            self.execute(True)
        self.assertFalse(self.api.writes)
        for change in ("automated", "source", "owner", "destination", "revision"):
            self.api = FakeAPI()
            application = self.api.objects[("argoproj.io/v1alpha1", "applications", m.NS, "argocd")]
            if change == "automated":
                application["spec"]["syncPolicy"]["automated"] = {}
            elif change == "source":
                application["spec"]["source"]["repoURL"] = "foreign"
            elif change == "owner":
                application["metadata"]["ownerReferences"] = [{"uid": "generator"}]
            elif change == "destination":
                application["spec"]["destination"]["namespace"] = m.NS
            else:
                application["status"]["sync"]["revision"] = "stale"
            with self.assertRaises(m.Refusal):
                self.execute(True)
            self.assertFalse(self.api.writes)

    def test_desired_recreation_refused(self):
        documents = manifests(HEAD)
        documents[0]["metadata"]["namespace"] = m.NS
        with self.assertRaisesRegex(m.Refusal, "recreates"):
            m.execute(self.api, lambda _: HEAD, lambda _: documents, True)
        self.assertFalse(self.api.writes)

    def test_uncertain_write_not_retried(self):
        with patch.object(self.api, "call", side_effect=OSError("transport failed")) as call:
            with self.assertRaisesRegex(m.Refusal, "outcome unknown"):
                self.execute(True)
            self.assertEqual(call.call_count, 1)

    def test_storage_change_stops_next_write(self):
        original = self.api.call
        def change_after_first(*args, **kwargs):
            result = original(*args, **kwargs)
            self.api.pv["spec"]["nfs"]["path"] = "/changed"
            return result
        with patch.object(self.api, "call", side_effect=change_after_first):
            with self.assertRaises(m.Refusal):
                self.execute(True)
        self.assertEqual(len(self.api.writes), 1)

    def test_changed_lock_and_token_reference_refused(self):
        for key, field, value in [(m.ORDER[1], "subsets", [{"addresses": [{"ip": "10.0.0.1"}]}]),
                                   (m.ORDER[-1], "secrets", [{"name": "token"}])]:
            self.api = FakeAPI()
            self.api.objects[key + (m.NS,)][field] = value
            with self.assertRaises(m.Refusal):
                self.execute(True)
            self.assertFalse(self.api.writes)

    def test_new_object_before_namespace_delete_blocks(self):
        original = self.api.inventory
        def changed_inventory(resources, namespace):
            inventory = original(resources, namespace)
            if len(self.api.writes) == 5 and namespace == m.NS:
                inventory[("v1", "secrets", "late-token")] = obj("late-token", "late")["metadata"]
            return inventory
        with patch.object(self.api, "inventory", side_effect=changed_inventory):
            with self.assertRaises(m.Refusal):
                self.execute(True)
        self.assertEqual(len(self.api.writes), 5)
        self.assertIsNotNone(self.api.get("v1", "namespaces", m.NS))

    def test_metadata_projection_does_not_emit_secrets_or_annotations(self):
        api = m.API()
        with patch.object(api, "call", return_value="secret\tns\tuid\t1\t\n") as call:
            self.assertEqual(api.metadata(("v1", "secrets"), "ns")[0]["uid"], "uid")
            projection = call.call_args.args[-1]
            self.assertNotIn(".data", projection)
            self.assertNotIn(".annotations", projection)
            self.assertNotIn("-o=json", call.call_args.args)

    def test_discovery_visits_every_served_version(self):
        api = m.API()
        listings = {
            "/api/v1": {"groupVersion": "v1", "resources": [
                {"name": name, "namespaced": True, "verbs": ["list"]}
                for name in ("secrets", "persistentvolumeclaims")]},
            "/apis": {"groups": [{"versions": [{"groupVersion": "apps/v1"}, {"groupVersion": "example.test/v1beta1"}]}]},
            "/apis/apps/v1": {"groupVersion": "apps/v1", "resources": [
                {"name": "deployments", "namespaced": True, "verbs": ["list"]}]},
            "/apis/example.test/v1beta1": {"groupVersion": "example.test/v1beta1", "resources": [
                {"name": "unknowns", "namespaced": True, "verbs": ["list"]}]},
        }
        with patch.object(api, "raw", side_effect=lambda path: listings[path]):
            self.assertIn(("example.test/v1beta1", "unknowns"), api.discover())


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.dirty = ""
        self.remote_head = HEAD
        self.branch = "master"
        self.bytes = "code\n"

    def git(self, args, payload=None):
        command = args[1:]
        if command == ["rev-parse", "--show-toplevel"]:
            return str(m.ROOT)
        if command == ["branch", "--show-current"]:
            return self.branch
        if command in (["config", "--get-all", "remote.origin.url"], ["remote", "get-url", "origin"]):
            return m.ORIGIN
        if command == ["rev-parse", "HEAD"]:
            return HEAD
        if command[0] == "status":
            return self.dirty
        if command[:2] == ["ls-files", "--error-unmatch"]:
            return command[2]
        if command[:2] == ["ls-files", "-z"]:
            return "\0".join(m.SCOPED[:2]) + "\0"
        if command[0] == "show":
            return self.bytes
        if command[0] == "ls-remote":
            return self.remote_head + "\trefs/heads/master\n"
        raise AssertionError(args)

    def text(self, path):
        if path.name in ("values.yaml", "values-seed.yaml"):
            sets = {s["metadata"]["name"]: s["spec"] for s in generators()}
            if path.name == "values-seed.yaml":
                for item in sets.values():
                    item["generators"][0]["git"]["repoURL"] = "https://github.com/brimdor/homelab"
            return json.dumps({"argocd-apps": {"applications": {m.NS: app()["spec"]}, "applicationsets": sets}})
        return "code\n"

    def gate(self, apply=True, template=False):
        with patch.object(m, "run", side_effect=self.git), patch.object(Path, "exists", return_value=template), \
                patch.object(Path, "read_text", autospec=True, side_effect=self.text):
            return m.source_gate(apply)

    def test_pushed_clean_scoped_master_required(self):
        self.assertEqual(self.gate(), HEAD)
        for field, value in [("dirty", "?? scripts/retire-nfs-discovery-race.py"),
                             ("remote_head", "b" * 40), ("branch", "feature"), ("bytes", "different\n")]:
            with self.subTest(field=field):
                self.setUp()
                setattr(self, field, value)
                with self.assertRaises(m.Refusal):
                    self.gate()

    def test_quiescence_template_blocks_check_and_apply(self):
        for apply in (False, True):
            with self.assertRaisesRegex(m.Refusal, "quiescence template"):
                self.gate(apply, template=True)

    def test_check_can_inspect_uncommitted_executor(self):
        self.dirty = "?? scripts/retire-nfs-discovery-race.py"
        self.assertEqual(self.gate(False), HEAD)


if __name__ == "__main__":
    unittest.main()
