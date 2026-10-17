#!/usr/bin/env python3
"""Offline trust-boundary tests. No kubectl or SSH process is executed."""

import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("ssh_trust", Path(__file__).with_name("ssh-trust.py"))
trust = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trust)
READ_INVENTORY = trust.inventory


def wire(*fields):
    return base64.b64encode(b"".join(struct.pack(">I", len(field)) + field for field in fields)).decode()


def public_keys(seed=b"a"):
    return "\n".join((
        "ssh-ed25519 " + wire(b"ssh-ed25519", seed * 32),
        "ecdsa-sha2-nistp256 " + wire(b"ecdsa-sha2-nistp256", b"nistp256", b"\x04" + seed * 64),
        "ssh-rsa " + wire(b"ssh-rsa", b"\x01\x00\x01", b"\x00\x80" + seed * 254 + b"\x01"),
    )) + "\n"


def pod(name, node, exporter=True):
    container = "node-exporter" if exporter else "gitea"
    namespace = "monitoring-system" if exporter else "gitea"
    return {
        "metadata": {"name": name, "uid": name + "-uid", "namespace": namespace,
                     "labels": {"app.kubernetes.io/name": "prometheus-node-exporter" if exporter else "gitea"}},
        "spec": {"nodeName": node, "containers": [{"name": container, "volumeMounts": [{
            "name": "data", "mountPath": "/host/root" if exporter else "/data", "readOnly": exporter}]}],
            "volumes": [{"name": "data", **({"hostPath": {"path": "/"}} if exporter else {
                "persistentVolumeClaim": {"claimName": "gitea"}})}]},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                   "containerStatuses": [{"name": container, "ready": True, "state": {"running": {}}}]},
    }


class Kubernetes:
    """Small exact-command subprocess fake, including create/replace concurrency."""

    def __init__(self):
        self.hosts = {"alpha": "10.0.20.11", "beta": "10.0.20.12"}
        self.uid = "cluster-uid"
        self.server = trust.SERVER
        self.client_version = "v1.33.5"
        self.server_version = "v1.33.6+k3s1"
        self.cluster_overrides = {}
        self.nodes = [{"metadata": {"name": name, "uid": name + "-node-uid"}, "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "addresses": [{"type": "InternalIP", "address": address}]}}
            for name, address in self.hosts.items()]
        self.pods = [pod("exporter-" + name, name) for name in self.hosts] + [pod("gitea-0", "alpha", False)]
        self.keys = {"exporter-alpha": public_keys(), "exporter-beta": public_keys(b"b"),
                      "gitea-0": public_keys(b"g").splitlines()[2] + "\n"}
        self.cms = {}
        self.writes = []
        self.commands = []
        self.revision = 0
        self.replace_pod_on_read = False
        self.bad_readback = False
        self.fail_exec = False

    def __call__(self, command, *, input, text, capture_output, check, cwd, timeout):
        assert command[:3] == ["kubectl", "--kubeconfig", str(trust.ROOT / "metal/kubeconfig.yaml")]
        assert cwd == trust.ROOT and text and capture_output and not check and timeout == 60
        args = command[3:]
        local = args[:2] == ["config", "view"]
        if not local:
            assert args[:3] == ["--server", trust.SERVER, "--request-timeout=20s"]
            args = args[3:]
        self.commands.append(args)
        result = None
        if args == ["config", "view", "--minify", "-o", "json"]:
            result = {"clusters": [{"cluster": {"server": self.server,
                      "certificate-authority-data": "DATA+OMITTED", **self.cluster_overrides}}]}
        elif args == ["version", "-o", "json"]:
            result = {"clientVersion": {"gitVersion": self.client_version},
                      "serverVersion": {"gitVersion": self.server_version}}
        elif args == ["get", "namespace", "kube-system", "-o", "json"]:
            result = {"metadata": {"name": "kube-system", "uid": self.uid}}
        elif args == ["get", "nodes", "-o", "json"]:
            result = {"items": self.nodes}
        elif args[:2] == ["get", "node"]:
            assert args[3:] == ["-o", "json"]
            result = next(node for node in self.nodes if node["metadata"]["name"] == args[2])
        elif args[:2] == ["get", "pods"]:
            assert args[2:] in (["-n", "monitoring-system", "-l", trust.NODE_LABEL, "-o", "json"],
                                ["-n", "gitea", "-l", trust.GITEA_LABEL, "-o", "json"])
            result = {"items": [p for p in self.pods if p["metadata"]["namespace"] == args[3]]}
        elif args[:2] == ["get", "pod"]:
            assert args[3] == "-n" and args[5:] == ["-o", "json"]
            result = next(p for p in self.pods if p["metadata"]["name"] == args[2])
            assert result["metadata"]["namespace"] == args[4]
            if self.replace_pod_on_read:
                result["metadata"]["uid"] += "-replacement"
        elif args[:2] == ["get", "configmap"]:
            assert args[3:] == ["-n", "kube-system", "--ignore-not-found", "-o", "json"]
            result = copy.deepcopy(self.cms.get(args[2]))
            if result is None:
                return subprocess.CompletedProcess(command, 0, "", "")
            if self.bad_readback and self.writes:
                result["metadata"]["resourceVersion"] += "9"
        elif args[0] == "exec":
            name = args[3]
            if name.startswith("exporter-"):
                assert args == ["exec", "-n", "monitoring-system", name, "-c", "node-exporter", "--", *trust.NODE_COMMAND]
            else:
                assert args == ["exec", "-n", "gitea", "gitea-0", "-c", "gitea", "--", "cat", "/data/ssh/gitea.rsa.pub"]
            if self.fail_exec:
                return subprocess.CompletedProcess(command, 1, "sensitive stdout", "sensitive stderr")
            return subprocess.CompletedProcess(command, 0, self.keys[name], "")
        elif args[0] in ("create", "replace"):
            assert args[1:] == ["-f", "-", "-o", "json"]
            result = json.loads(input)
            name = result["metadata"]["name"]
            old = self.cms.get(name)
            if args[0] == "create":
                assert old is None
            else:
                assert old is not None and not old.get("immutable")
                if result["metadata"]["resourceVersion"] != old["metadata"]["resourceVersion"]:
                    return subprocess.CompletedProcess(command, 1, "", "Conflict")
            self.revision += 1
            result["metadata"].update(uid=name + "-uid", resourceVersion=str(self.revision))
            self.cms[name] = copy.deepcopy(result)
            self.writes.append((args[0], name))
        else:
            raise AssertionError("Unexpected command: " + repr(args))
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")


class TrustTests(unittest.TestCase):
    def setUp(self):
        # tempfile inherits the parent's verified TMPDIR. Never override it here.
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "homelab_known_hosts"
        self.path.write_text("prior trust\n")
        self.other = self.path.with_name("known_hosts")
        self.other.write_text("unrelated trust\n")
        self.api = Kubernetes()
        self.patches = [
            mock.patch.object(trust.subprocess, "run", side_effect=self.api),
            mock.patch.object(trust, "inventory", return_value=self.api.hosts),
            mock.patch.dict(os.environ, {key: "" for key in (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")}),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, *args, answer="exact"):
        if callable(answer):
            responder = answer
        elif answer == "exact":
            responder = lambda prompt: "APPROVE " + prompt.split()[2].rstrip(":")
        elif answer is EOFError:
            responder = EOFError
        else:
            responder = lambda prompt: answer
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                mock.patch("builtins.input", side_effect=responder) as confirmation:
            result = trust.main([*args, "--known-hosts", str(self.path)])
        return result, stdout.getvalue(), stderr.getvalue(), confirmation.call_count

    def enroll(self):
        result, _, error, calls = self.run_main()
        self.assertEqual((result, error, calls), (0, "", 1))
        return copy.deepcopy(self.api.cms[trust.NAME])

    def assert_untouched(self):
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.path.read_text(), "prior trust\n")
        self.assertEqual(self.other.read_text(), "unrelated trust\n")

    def test_public_key_wire_validation_and_fingerprint(self):
        keys = trust.parse_keys(public_keys())
        self.assertEqual(trust.fingerprint(keys[0]), "SHA256:" + base64.b64encode(
            trust.hashlib.sha256(base64.b64decode(keys[0]["key"])).digest()).decode().rstrip("="))
        self.assertEqual(trust.parse_key(public_keys().splitlines()[0] + " safe-comment"), keys[0])
        invalid = ["ssh-ed25519 !!!", "ssh-ed25519 " + wire(b"ssh-rsa", b"a" * 32),
                   "ssh-ed25519 " + wire(b"ssh-ed25519", b"short"),
                   public_keys().splitlines()[0] + "\x1b[31m", "@cert-authority ssh-rsa AAAA",
                   "ssh-rsa " + wire(b"ssh-rsa", b"\x80", b"\x01"),
                   "ecdsa-sha2-nistp256 " + wire(b"ecdsa-sha2-nistp256", b"nistp384", b"a" * 65)]
        for line in invalid:
            with self.subTest(line=line), self.assertRaises(trust.Refusal):
                trust.parse_key(line)
        for text in ("", public_keys().splitlines()[0], public_keys() + public_keys()):
            with self.assertRaises(trust.Refusal):
                trust.parse_keys(text)

    def test_inventory_safe_load_and_retired_exclusion(self):
        path = Path(self.directory.name) / "inventory.yml"
        path.write_text("""metal:
  children:
    masters:
      hosts:
        alpha: {ansible_host: 10.0.20.11}
    workers:
      hosts:
        beta: {ansible_host: 10.0.20.12}
        # old-comment: {ansible_host: 10.0.20.13}
        chikorita: {ansible_host: 10.0.20.15}
""")
        self.assertEqual(READ_INVENTORY(path), self.api.hosts)
        for hosts in ({"bad,alias": "10.0.20.11"}, {"alpha": "10.0.20.50"},
                      {"alpha": "10.0.20.11", "beta": "10.0.20.11"}):
            with self.assertRaises(trust.Refusal):
                trust.validate_inventory(hosts)

    def test_preview_and_rejected_approval_never_write(self):
        result, output, error, calls = self.run_main("--preview")
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("git.eaglepass.io", output)
        self.assertIn("alpha/10.0.20.11", output)
        self.assertIn("Batch SHA256:", output)
        self.assert_untouched()
        for answer in (EOFError, "yes", "APPROVE " + "0" * 64):
            with self.subTest(answer=answer):
                result, _, _, calls = self.run_main(answer=answer)
                self.assertEqual((result, calls), (1, 1))
                self.assert_untouched()

    def test_exact_approval_no_whitespace_or_prefix_acceptance(self):
        digest = "a" * 64
        for answer in ("APPROVE " + digest[:16], " APPROVE " + digest,
                       "APPROVE " + digest + " ", "approve " + digest):
            with mock.patch("builtins.input", return_value=answer), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(trust.Refusal):
                trust.approve(digest)

    def test_manual_publication_and_dedicated_atomic_install(self):
        cm = self.enroll()
        record = trust.validate_cm(cm, self.api.uid)
        self.assertEqual(record["approval"]["method"], "manual")
        self.assertEqual(set(record["snapshot"]["entries"]), {"alpha", "beta", "git.eaglepass.io"})
        self.assertEqual(self.path.read_text(), cm["data"]["known_hosts"])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.other.read_text(), "unrelated trust\n")
        gitea_lines = [line for line in self.path.read_text().splitlines() if line.startswith("git.")]
        self.assertEqual(len(gitea_lines), 1)
        self.assertTrue(gitea_lines[0].startswith("git.eaglepass.io ssh-rsa "))
        self.assertEqual(self.api.writes, [("create", trust.NAME)])

    def test_incomplete_or_untrusted_sources_refuse_without_mutation(self):
        cases = ("missing-key", "duplicate-key", "writable-root", "wrong-root", "shadowed-root", "wrong-ip", "unready",
                 "duplicate-pod", "replaced-pod", "missing-gitea", "wrong-gitea-volume")
        for case in cases:
            with self.subTest(case=case):
                self.api = Kubernetes()
                self.patches[0].stop()
                self.patches[0] = mock.patch.object(trust.subprocess, "run", side_effect=self.api)
                self.patches[0].start()
                self.addCleanup(self.patches[0].stop)
                if case == "missing-key":
                    self.api.keys["exporter-alpha"] = public_keys().splitlines()[0]
                elif case == "duplicate-key":
                    self.api.keys["exporter-beta"] = self.api.keys["exporter-alpha"]
                elif case == "writable-root":
                    self.api.pods[0]["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] = False
                elif case == "wrong-root":
                    self.api.pods[0]["spec"]["volumes"][0]["hostPath"]["path"] = "/etc"
                elif case == "shadowed-root":
                    self.api.pods[0]["spec"]["containers"][0]["volumeMounts"].append({
                        "name": "other", "mountPath": "/host/root/etc/ssh"})
                elif case == "wrong-ip":
                    self.api.nodes[0]["status"]["addresses"][0]["address"] = "10.0.20.99"
                elif case == "unready":
                    self.api.nodes[0]["status"]["conditions"][0]["status"] = "False"
                elif case == "duplicate-pod":
                    self.api.pods.append(copy.deepcopy(self.api.pods[0]))
                elif case == "replaced-pod":
                    self.api.replace_pod_on_read = True
                elif case == "missing-gitea":
                    self.api.pods.pop()
                else:
                    self.api.pods[-1]["spec"]["volumes"][0] = {"name": "data", "emptyDir": {}}
                result, _, _, calls = self.run_main()
                self.assertEqual((result, calls), (1, 0))
                self.assert_untouched()

    def test_automatic_first_publication_never_prompts_and_is_idempotent(self):
        result, output, error, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("SSH_TRUST_CHANGED=1", output)
        cm = copy.deepcopy(self.api.cms[trust.NAME])
        record = trust.validate_cm(cm, self.api.uid)
        self.assertEqual(record["approval"]["method"], "automatic")
        self.assertEqual(record["source_approval"]["method"], "automatic")
        self.assertEqual(record["source_approval"]["batch_digest"], record["batch_digest"])
        self.assertEqual(self.path.read_text(), cm["data"]["known_hosts"])
        writes = list(self.api.writes)
        result, output, error, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("SSH_TRUST_CHANGED=0", output)
        self.assertEqual(self.api.writes, writes)
        self.assertEqual(self.api.cms[trust.NAME], cm)

    def test_automatic_first_publication_still_refuses_incomplete_sources(self):
        self.api.keys["exporter-alpha"] = public_keys().splitlines()[0]
        result, _, _, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, calls), (1, 0))
        self.assert_untouched()

    def test_pod_replacement_during_manual_confirmation_refuses_publication(self):
        def replace_then_approve(prompt):
            self.api.pods[0]["metadata"]["uid"] = "replacement-pod-uid"
            return "APPROVE " + prompt.split()[2].rstrip(":")

        result, _, error, calls = self.run_main(answer=replace_then_approve)
        self.assertEqual((result, calls), (1, 1))
        self.assertIn("Source pod changed", error)
        self.assert_untouched()

    def test_key_rotation_during_manual_confirmation_refuses_publication(self):
        def rotate_then_approve(prompt):
            self.api.keys["exporter-alpha"] = public_keys(b"z")
            return "APPROVE " + prompt.split()[2].rstrip(":")

        result, _, error, calls = self.run_main(answer=rotate_then_approve)
        self.assertEqual((result, calls), (1, 1))
        self.assertIn("Public keys changed", error)
        self.assert_untouched()

    def test_automatic_rotation_archives_approval_and_is_idempotent(self):
        old = self.enroll()
        self.api.keys["exporter-alpha"] = public_keys(b"c")
        result, output, error, calls = self.run_main("--automatic")
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("CHANGED", output)
        self.assertIn("REMOVED alpha ssh-ed25519", output)
        self.assertIn("SSH_TRUST_CHANGED=1", output)
        archives = [cm for name, cm in self.api.cms.items() if name != trust.NAME]
        self.assertEqual(len(archives), 1)
        self.assertIs(archives[0]["immutable"], True)
        self.assertEqual(archives[0]["data"], old["data"])
        record = trust.validate_cm(self.api.cms[trust.NAME], self.api.uid)
        self.assertEqual(record["approval"]["method"], "automatic")
        self.assertEqual(record["source_approval"], json.loads(old["data"]["record.json"])["source_approval"])
        writes = list(self.api.writes)
        current = copy.deepcopy(self.api.cms[trust.NAME])
        result, output, _, calls = self.run_main("--automatic")
        self.assertEqual((result, calls), (0, 0))
        self.assertIn("SSH_TRUST_CHANGED=0", output)
        self.assertEqual(self.api.writes, writes)
        self.assertEqual(self.api.cms[trust.NAME], current)

    def test_automatic_recollects_new_cluster_without_prompting_but_read_refuses_stale_trust(self):
        old = self.enroll()
        before, writes = self.path.read_text(), list(self.api.writes)
        self.api.uid = "new-cluster-uid"
        result, _, _, calls = self.run_main("--read")
        self.assertEqual((result, calls), (1, 0))
        self.assertEqual(self.api.writes, writes)
        self.assertEqual(self.path.read_text(), before)
        result, _, error, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, error, calls), (0, "", 0))
        record = trust.validate_cm(self.api.cms[trust.NAME], self.api.uid)
        self.assertEqual(record["cluster_uid"], "new-cluster-uid")
        self.assertEqual(record["source_approval"]["method"], "automatic")
        self.assertEqual(record["source_approval"]["batch_digest"], record["batch_digest"])
        self.assertTrue(any(cm["data"] == old["data"] and cm.get("immutable")
                            for name, cm in self.api.cms.items() if name != trust.NAME))

    def test_automatic_inventory_addition_and_retirement_do_not_prompt(self):
        self.enroll()
        self.api.hosts["gamma"] = "10.0.20.13"
        self.api.nodes.append({"metadata": {"name": "gamma", "uid": "gamma-node-uid"}, "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "addresses": [{"type": "InternalIP", "address": "10.0.20.13"}]}})
        self.api.pods.append(pod("exporter-gamma", "gamma"))
        self.api.keys["exporter-gamma"] = public_keys(b"c")
        result, _, error, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("gamma,10.0.20.13 ", self.path.read_text())
        del self.api.hosts["beta"]
        self.api.nodes = [n for n in self.api.nodes if n["metadata"]["name"] != "beta"]
        self.api.pods = [p for p in self.api.pods if p["metadata"]["name"] != "exporter-beta"]
        result, output, error, calls = self.run_main("--automatic", answer=AssertionError)
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("REMOVED beta", output)
        self.assertNotIn("beta,10.0.20.12 ", self.path.read_text())

    def test_incomplete_or_tampered_stored_record_is_refused(self):
        original = self.enroll()
        before, writes = self.path.read_text(), list(self.api.writes)
        for case in ("digest", "entry", "known-hosts", "source", "approval"):
            cm = copy.deepcopy(original)
            record = json.loads(cm["data"]["record.json"])
            if case == "digest":
                record["batch_digest"] = "0" * 64
            elif case == "entry":
                del record["snapshot"]["entries"]["beta"]
            elif case == "known-hosts":
                cm["data"]["known_hosts"] += "malicious.example ssh-rsa AAAA\n"
            elif case == "source":
                record["snapshot"]["entries"]["alpha"]["source"]["node"] = "beta"
            else:
                record["source_approval"]["method"] = "automatic"
            cm["data"]["record.json"] = trust.canonical(record)
            self.api.cms[trust.NAME] = cm
            for mode in ("--read", "--automatic"):
                with self.subTest(case=case, mode=mode):
                    self.assertEqual(self.run_main(mode)[0], 1)
                    self.assertEqual(self.api.writes, writes)
                    self.assertEqual(self.path.read_text(), before)

    def test_stale_pointer_and_namespace_uid_refuse_publication(self):
        self.enroll()
        before, writes = self.path.read_text(), list(self.api.writes)
        original_get = trust.API.get_cm
        reads = 0

        def changed_pointer(api, name=trust.NAME):
            nonlocal reads
            reads += 1
            if reads == 2:
                self.api.cms[trust.NAME]["metadata"]["resourceVersion"] = "900"
            return original_get(api, name)

        with mock.patch.object(trust.API, "get_cm", changed_pointer):
            self.assertEqual(self.run_main("--automatic")[0], 1)
        with mock.patch.object(trust.API, "cluster_uid", side_effect=[self.api.uid, "replacement-uid"]):
            self.assertEqual(self.run_main("--automatic")[0], 1)
        self.assertEqual(self.api.writes, writes)
        self.assertEqual(self.path.read_text(), before)

    def test_failed_exact_readback_never_installs_local_trust(self):
        self.api.bad_readback = True
        result, _, error, _ = self.run_main()
        self.assertEqual(result, 1)
        self.assertIn("exact GET readback failed", error)
        self.assertEqual(self.api.writes, [("create", trust.NAME)])
        self.assertEqual(self.path.read_text(), "prior trust\n")

    def test_read_installs_without_collecting_or_publishing(self):
        cm = self.enroll()
        self.path.write_text("local stale bundle\n")
        self.api.commands.clear()
        writes = list(self.api.writes)
        result, output, error, calls = self.run_main("--read")
        self.assertEqual((result, error, calls), (0, "", 0))
        self.assertIn("SSH_TRUST_CHANGED=1", output)
        self.assertEqual(self.path.read_text(), cm["data"]["known_hosts"])
        self.assertFalse(any(command[0] == "exec" for command in self.api.commands))
        self.assertEqual(self.api.writes, writes)

    def test_symlink_destination_is_never_followed(self):
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with self.assertRaises(trust.Refusal):
            trust.install(link, "replacement\n")
        self.assertEqual(self.path.read_text(), "prior trust\n")

    def test_config_version_and_command_errors_are_sanitized(self):
        for change in ("server", "insecure", "proxy", "skew", "exec-error"):
            with self.subTest(change=change):
                self.api.server = trust.SERVER
                self.api.cluster_overrides = {}
                self.api.client_version = "v1.33.5"
                self.api.fail_exec = False
                if change == "server":
                    self.api.server = "https://unapproved.example:6443"
                elif change == "insecure":
                    self.api.cluster_overrides["insecure-skip-tls-verify"] = True
                elif change == "proxy":
                    self.api.cluster_overrides["proxy-url"] = "http://unapproved.example"
                elif change == "skew":
                    self.api.client_version = "v1.35.0"
                else:
                    self.api.fail_exec = True
                result, output, error, calls = self.run_main()
                self.assertEqual((result, calls), (1, 0))
                self.assertNotIn("sensitive", output + error)
                self.assert_untouched()


if __name__ == "__main__":
    unittest.main()
