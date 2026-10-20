#!/usr/bin/env python3
"""Refuse changed inputs, escaped isolation and false native ownership evidence."""

import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import ceph_csi_controller_qualification as subject


class ControllerGuards(unittest.TestCase):
    def test_manager_failure_keeps_only_fixed_error_markers_and_state(self):
        raw = b'INFO image set loaded\nERROR unable to load config map: private-sentinel-value not found\n'
        failure = subject.manager_failure(raw, {"Running": True, "ExitCode": 0, "OOMKilled": False})
        self.assertIn('"not found"', failure)
        self.assertIn('"config map"', failure)
        self.assertNotIn('"image set"', failure)
        self.assertNotIn('private-sentinel-value', failure)

    def test_failure_reports_stage_and_fixed_markers_without_raw_values(self):
        failed = subprocess.CompletedProcess([], 1, b"private-sentinel-value", b"Forbidden: private-sentinel-value")
        with patch.object(subject.common, "docker", return_value=failed), self.assertRaises(RuntimeError) as caught:
            subject.checked_docker("exec", "synthetic", stage="create crds.json")
        self.assertIn("create crds.json", str(caught.exception))
        self.assertIn('"forbidden"', str(caught.exception))
        self.assertNotIn("private-sentinel-value", str(caught.exception))

    def manager(self):
        return {"Config": {"Image": subject.IMAGE, "User": "65532:65532", "Entrypoint": ["/manager"],
                           "Cmd": ["--leader-elect"], "Labels": {"io.eaglepass.recovery-run": "run", "io.eaglepass.maintenance": "103"},
                           "Env": ["KUBECONFIG=/identity/config", "OPERATOR_NAMESPACE=rook-ceph", "WATCH_NAMESPACE=",
                                   "CSI_SERVICE_ACCOUNT_PREFIX=", "KUBERNETES_CLUSTER_DOMAIN=cluster.local"]},
                "HostConfig": {"NetworkMode": "container:api", "ReadonlyRootfs": True, "Privileged": False,
                               "CapAdd": [], "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "Devices": [],
                               "PortBindings": {}, "LogConfig": {"Type": "none", "Config": {}},
                               "SecurityOpt": ["no-new-privileges:true"]},
                "Mounts": [{"Type": "bind", "Source": "/owned/identity", "Destination": "/identity", "RW": False}]}

    def test_unreviewed_bundle_refused_before_any_runtime(self):
        with patch.object(subject.common, "qualify") as native:
            with self.assertRaisesRegex(RuntimeError, "bundle changed"):
                subject.qualify({"crds": [], "setup": [], "resources": []}, "test")
            native.assert_not_called()

    def test_manager_refuses_logging_network_credentials_and_mount_drift(self):
        baseline = self.manager()
        subject.require_manager(baseline, "api", Path("/owned/identity"), "run")
        changes = [lambda v: v["HostConfig"].update(LogConfig={"Type": "journald", "Config": {}}),
                   lambda v: v["HostConfig"].update(NetworkMode="host"),
                   lambda v: v["HostConfig"].update(CapAdd=["SYS_ADMIN"]),
                   lambda v: v["HostConfig"].update(Privileged=True),
                   lambda v: v["HostConfig"].update(SecurityOpt=[]),
                   lambda v: v["Mounts"][0].update(RW=True),
                   lambda v: v["Mounts"][0].update(Source="/real/credentials"),
                   lambda v: v["Config"]["Env"].append("KUBECONFIG=/real/config"),
                   lambda v: v["Config"]["Labels"].update({"io.eaglepass.recovery-run": "other"})]
        for change in changes:
            value = copy.deepcopy(baseline)
            change(value)
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                subject.require_manager(value, "api", Path("/owned/identity"), "run")

    def workloads(self):
        drivers = {n: n + "-uid" for n in subject.DRIVERS}
        rows = []
        for kind in ("Deployment", "DaemonSet"):
            for owner in sorted(drivers):
                plugin = {"image": "plugin", "args": ["--v=0", "--forcecephkernelclient=true"],
                          "resources": {"limits": {"memory": "1Gi"}}}
                spec = {"replicas": 2, "strategy": {"type": "Recreate"}, "updateStrategy": {"type": "RollingUpdate"},
                        "template": {"spec": {"hostNetwork": True, "containers": [plugin],
                                             "tolerations": [{"key": "dedicated", "operator": "Exists", "effect": "NoSchedule"}],
                                             "volumes": [{"hostPath": {"path": "/var/lib/kubelet/plugins"}}]}}}
                rows.append({"kind": kind, "metadata": {"name": kind + owner, "uid": kind + owner,
                             "ownerReferences": [{"apiVersion": "csi.ceph.io/v1", "kind": "Driver", "name": owner,
                                                  "uid": drivers[owner], "controller": True}]}, "spec": spec})
        return drivers, rows

    def test_generated_inventory_requires_native_uid_policy_and_both_driver_types(self):
        drivers, rows = self.workloads()
        levels = {n: 0 for n in drivers}
        self.assertEqual(len(subject.require_workloads(rows, drivers, "plugin", levels)), 4)
        for change in (lambda v: v.pop(),
                       lambda v: v[0]["metadata"]["ownerReferences"][0].update(uid="wrong"),
                       lambda v: v[0]["spec"]["template"]["spec"]["containers"][0].update(image="old"),
                       lambda v: v[0]["spec"].update(replicas=1),
                       lambda v: v[2]["spec"]["template"]["spec"]["containers"][0].update(args=["--v=0"])):
            bad = copy.deepcopy(rows)
            change(bad)
            with self.assertRaises(RuntimeError):
                subject.require_workloads(bad, drivers, "plugin", levels)

    def test_cluster_scoped_driver_annotation_uses_native_go_namespaced_name(self):
        rows = [{"metadata": {"name": n, "uid": n, "annotations": {"csi.ceph.io/ownerref": json.dumps({"Name": n, "Namespace": "rook-ceph"})}},
                 "spec": {"fsGroupPolicy": "File", "seLinuxMount": True}} for n in sorted(subject.DRIVERS)]
        self.assertEqual(len(subject.require_csidrivers(rows)), 2)
        for change in (lambda v: v[0]["metadata"].update(uid=""),
                       lambda v: v[0]["spec"].update(seLinuxMount=False),
                       lambda v: v[0]["metadata"]["annotations"].update({"csi.ceph.io/ownerref": "null"})):
            bad = copy.deepcopy(rows)
            change(bad)
            with self.assertRaises(RuntimeError):
                subject.require_csidrivers(bad)


if __name__ == "__main__":
    unittest.main()
