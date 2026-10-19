"""Offline regression checks for exact orphan monitor retirement."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("retire_monitor", Path(__file__).with_name("retire-nginx-monitor.py"))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def monitor():
    return {"apiVersion": "monitoring.coreos.com/v1", "kind": "ServiceMonitor",
            "metadata": {"name": r.NAME, "namespace": r.NS, "uid": r.UID, "resourceVersion": "42"},
            "spec": {"endpoints": [{"interval": "30s", "port": "metrics"}],
                     "namespaceSelector": {"matchNames": [r.NS]}, "selector": {"matchLabels": r.SELECTOR}}}


class RetirementTests(unittest.TestCase):
    def test_delete_has_exact_uid_and_resource_version(self):
        path, options = r.delete_request(monitor())
        self.assertEqual(path, r.ENDPOINT)
        self.assertEqual(options["preconditions"], {"uid": r.UID, "resourceVersion": "42"})

    def test_changed_identity_owner_finalizer_or_spec_refused(self):
        for field in ("uid", "ownerReferences", "finalizers", "annotations", "spec"):
            with self.subTest(field=field):
                obj = copy.deepcopy(monitor())
                if field == "spec":
                    obj["spec"]["endpoints"][0]["port"] = "active-metrics"
                else:
                    obj["metadata"][field] = {"uid": "other", "ownerReferences": [{"uid": "active"}],
                                              "finalizers": ["protect"], "annotations": {
                                                  "argocd.argoproj.io/tracking-id": "active"}}[field]
                with self.assertRaises(r.Refusal):
                    r.delete_request(obj)

    def execute(self, objects, apply=False, deletion=None, snapshots=None, heads=None):
        get = Mock(side_effect=objects)
        delete = deletion or Mock()
        gate = Mock(side_effect=heads or ["a" * 40, "a" * 40])
        with patch.object(r, "snapshot", side_effect=snapshots or [[("protected", {})]] * 3):
            result = r.execute(get, delete, gate, apply)
        return result, delete

    def test_default_never_writes(self):
        result, delete = self.execute([monitor(), monitor()])
        self.assertFalse(result["applied"])
        delete.assert_not_called()

    def test_apply_deletes_once_then_proves_absence(self):
        result, delete = self.execute([monitor(), monitor(), None], apply=True)
        self.assertTrue(result["applied"])
        delete.assert_called_once_with(*r.delete_request(monitor()))

    def test_absent_target_never_writes(self):
        result, delete = self.execute([None], apply=True)
        self.assertTrue(result["already_absent"])
        delete.assert_not_called()

    def test_stale_object_protected_state_or_source_refuses_before_delete(self):
        altered = monitor()
        altered["metadata"]["resourceVersion"] = "43"
        for kwargs in ({"objects": [monitor(), altered]},
                       {"objects": [monitor()], "snapshots": [[("before", {})], [("changed", {})]]},
                       {"objects": [monitor()], "heads": ["a" * 40, "b" * 40]}):
            with self.subTest(kwargs=kwargs):
                delete = Mock()
                with self.assertRaises(r.Refusal):
                    self.execute(apply=True, deletion=delete, **kwargs)
                delete.assert_not_called()

    def test_uncertain_delete_is_not_retried(self):
        delete = Mock(side_effect=ConnectionError("synthetic uncertain response"))
        with self.assertRaises(ConnectionError):
            self.execute([monitor(), monitor()], apply=True, deletion=delete)
        self.assertEqual(delete.call_count, 1)

    def test_unconfirmed_delete_is_not_retried(self):
        delete = Mock()
        with self.assertRaises(r.Refusal):
            self.execute([monitor(), monitor(), monitor()], apply=True, deletion=delete)
        self.assertEqual(delete.call_count, 1)

    def test_active_metrics_consumer_blocks_snapshot(self):
        app = {"spec": {"source": {"repoURL": "http://gitea-http.gitea:3000/ops/homelab",
                                 "path": "system/ingress-nginx", "targetRevision": "master", "helm": {"skipCrds": True}}},
               "status": {"sync": {"revision": "a" * 40, "status": "Synced"},
                          "health": {"status": "Healthy"}, "resources": []}}
        services = {"items": [{"metadata": {"labels": r.SELECTOR}, "spec": {"ports": [{"name": "metrics"}]}}]}
        with self.assertRaisesRegex(r.Refusal, "active metrics Service"):
            r.snapshot(Mock(side_effect=[app, services]), "a" * 40)


if __name__ == "__main__":
    unittest.main()
