"""Focused Tsurreal private deployment and projected-identity checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "apps/tsurreal-canary"
spec = importlib.util.spec_from_file_location("prepare_identity", CHART / "files/prepare-identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def render(*overrides, namespace="tsurreal-canary", good=True):
    command = ["helm", "template", "tsurreal-canary", str(CHART), "--namespace", namespace]
    for value in overrides:
        command.extend(["--set-string", value])
    result = subprocess.run(command, text=True, capture_output=True)
    if good:
        if result.returncode:
            raise AssertionError(result.stderr)
        return [obj for obj in yaml.safe_load_all(result.stdout) if obj]
    if result.returncode == 0:
        raise AssertionError("Unsafe chart values were admitted")


class ChartTests(unittest.TestCase):
    def test_namespace_and_foundation_are_inert(self):
        self.assertEqual([o["kind"] for o in render("stage=namespace")], ["Namespace"])
        objects = render("stage=foundation")
        kinds = [o["kind"] for o in objects]
        self.assertEqual(sorted(kinds), sorted(["Namespace", "Certificate", "Service", "NetworkPolicy", "ConfigMap"] + ["PersistentVolumeClaim"] * 3))
        for obj in objects:
            self.assertNotIn(obj["kind"], ["Ingress", "Deployment", "Pod", "Job", "Secret"])
            self.assertNotIn("production", obj["metadata"]["name"])
            if obj["kind"] != "Namespace": self.assertEqual(obj["metadata"]["namespace"], "tsurreal-canary")
        service = next(o for o in objects if o["kind"] == "Service")
        self.assertFalse(service["spec"]["allocateLoadBalancerNodePorts"])
        self.assertEqual(service["metadata"]["annotations"]["external-dns.alpha.kubernetes.io/cloudflare-proxied"], "false")
        policy = next(o for o in objects if o["kind"] == "NetworkPolicy")["spec"]
        self.assertEqual(policy["egress"], [])
        self.assertEqual(policy["ingress"][0]["from"], [{"ipBlock": {"cidr": "10.0.0.0/16"}}])
        config = json.loads(next(o for o in objects if o["kind"] == "ConfigMap")["data"]["hq.json"])
        self.assertEqual(config["access_mode"], "lan")
        self.assertEqual(config["origin"], "https://tsurreal-canary.eaglepass.io")
        self.assertFalse(set(config).intersection(["native_file", "execution_file", "push_file", "email_file", "backup_file", "installation_id"]))
        for obj in objects:
            if obj["kind"] in ["Namespace", "PersistentVolumeClaim"]:
                self.assertIn("Prune=false", obj["metadata"]["annotations"]["argocd.argoproj.io/sync-options"])

    def test_candidate_is_restricted(self):
        objects = render("stage=candidate", "image=10.0.20.11:32309/tsurreal/hq@sha256:" + "a" * 64, "sourceCommit=" + "b" * 40, "sourceTree=" + "c" * 40)
        spec = next(o for o in objects if o["kind"] == "Deployment")["spec"]
        self.assertEqual((spec["replicas"], spec["strategy"]["type"]), (1, "Recreate"))
        pod = spec["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 65532)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        self.assertNotIn("imagePullSecrets", pod)
        for container in pod["containers"] + pod["initContainers"]:
            security = container["securityContext"]
            self.assertTrue(security["readOnlyRootFilesystem"])
            self.assertFalse(security["allowPrivilegeEscalation"])
            self.assertEqual(security["capabilities"]["drop"], ["ALL"])
        self.assertFalse(any("hostPath" in v for v in pod["volumes"]))
        self.assertNotIn("hostNetwork", pod)
        self.assertNotIn("hostPID", pod)

    def test_invalid_candidate_or_target_refused(self):
        for overrides in [("stage=invalid",), ("stage=candidate", "image="), ("stage=candidate", "sourceCommit="), ("stage=candidate", "sourceTree=invalid"), ("hostname=public.example",), ("stage=candidate", "image=private.example/tsurreal:latest")]:
            with self.subTest(overrides=overrides):
                render(*overrides, good=False)
        render("stage=candidate", "image=public.example/tsurreal/hq@sha256:" + "a" * 64, "sourceCommit=" + "b" * 40, "sourceTree=" + "c" * 40, good=False)
        render("imagePullSecret=unnecessary-credential", good=False)
        render(namespace="tsurreal-production", good=False)
        render("stage=foundation", "privateSources[0]=0.0.0.0/0", good=False)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.generation = self.source / "generation-one"
        self.generation.mkdir()
        for name, value in [("tls.crt", b"synthetic certificate"), ("tls.key", b"synthetic key")]:
            (self.generation / name).write_bytes(value)
        (self.source / "..data").symlink_to(self.generation.name)
        self.output = self.root / "identity"

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_regular_outputs_and_replay_refusal(self):
        identity.stage(self.source, self.output)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        for name in ["tls.crt", "tls.key"]:
            path = self.output / name
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_bytes(), (self.generation / name).read_bytes())
        with self.assertRaises(FileExistsError):
            identity.stage(self.source, self.output)
        self.assertEqual((self.output / "tls.key").read_bytes(), b"synthetic key")

    def test_one_generation_even_during_rotation(self):
        next_generation = self.source / "generation-two"
        next_generation.mkdir()
        for name in ["tls.crt", "tls.key"]:
            (next_generation / name).write_bytes(b"changed")
        original = identity.os.open
        def rotating_open(path, flags, *args, **kwargs):
            fd = original(path, flags, *args, **kwargs)
            if Path(path).name == "..data":
                (self.source / "..data").unlink()
                (self.source / "..data").symlink_to(next_generation.name)
            return fd
        identity.os.open = rotating_open
        try:
            identity.stage(self.source, self.output)
        finally:
            identity.os.open = original
        self.assertEqual((self.output / "tls.key").read_bytes(), b"synthetic key")

    def test_missing_empty_oversize_link_fifo_refused(self):
        key = self.generation / "tls.key"
        for mode in ["missing", "empty", "oversize", "symlink", "fifo"]:
            with self.subTest(mode=mode):
                key.unlink(missing_ok=True)
                if mode == "empty": key.write_bytes(b"")
                if mode == "oversize": key.write_bytes(b"x" * (1024 * 1024 + 1))
                if mode == "symlink": key.symlink_to("tls.crt")
                if mode == "fifo": os.mkfifo(key)
                with self.assertRaises((OSError, ValueError)):
                    identity.stage(self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_destination_symlinks_refused(self):
        self.output.symlink_to(self.root / "absent")
        with self.assertRaises(FileExistsError): identity.stage(self.source, self.output)
        self.output.unlink()
        linked = self.root / "linked"
        linked.symlink_to(self.root)
        with self.assertRaises(ValueError): identity.stage(self.source, linked / "identity")


if __name__ == "__main__":
    unittest.main()
