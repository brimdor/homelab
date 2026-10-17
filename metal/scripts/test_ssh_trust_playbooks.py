#!/usr/bin/env python3
"""Offline integration tests of the real SSH-trust Ansible task imports.

Requires ansible-core in the runner's Python environment. Run with:
    python3 -B -m unittest discover -s metal/scripts -p test_ssh_trust_playbooks.py -v

The caller supplies TMPDIR. All synthetic checkouts, Ansible scratch, fake API
state, and logs stay beneath it. Fixtures are retained for inspection. HOME and
credentials are not changed. No provisioning playbook is ever executed: only
validated task imports extracted from source metadata enter the fixture plays.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[2]
HOSTS = {"alpha": "10.0.20.11", "beta": "10.0.20.12",
         "gamma": "10.0.20.13", "delta": "10.0.20.14"}
NODE_PLAYS = ("cluster.yml", "nodes.yml")
READY_PATH = '-o=jsonpath={range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{";"}{end}'


def load_support(scripts):
    """Import the copied fake and pure helpers without running its test suite."""
    spec = importlib.util.spec_from_file_location(
        "fixture_ssh_trust_support", scripts / "test_ssh_trust.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_kubectl():
    """Closed command dispatcher; it has no path to a real kubectl or API."""
    import fcntl
    import traceback

    state_path = Path(os.environ["SSH_TRUST_TEST_STATE"])
    support = load_support(Path(__file__).resolve().parent)
    trust = support.trust
    with state_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text())
        api = support.Kubernetes()
        api.__dict__.update(state["api"])
        command = ["kubectl", *sys.argv[1:]]
        # Common tasks use --server=..., whereas API.run uses two arguments.
        normalized = []
        for argument in command:
            if argument.startswith("--server="):
                normalized.extend(("--server", argument.split("=", 1)[1]))
            else:
                normalized.append(argument)
        state["commands"].append(normalized)
        result = subprocess.CompletedProcess(command, 1, "", "Unexpected fake command")
        try:
            assert normalized[:3] == ["kubectl", "--kubeconfig",
                                      str(trust.ROOT / "metal/kubeconfig.yaml")]
            args = normalized[3:]
            if args[:2] != ["config", "view"]:
                assert args[:3] == ["--server", trust.SERVER, "--request-timeout=20s"]
                args = args[3:]
            if args == ["get", "namespaces", "-o=jsonpath={.items[*].metadata.name}"]:
                result = subprocess.CompletedProcess(command, 0, " ".join(state["namespaces"]), "")
            elif args == ["get", "configmap", trust.NAME, "-n", "kube-system",
                          "--ignore-not-found", "-o", "name"]:
                result = subprocess.CompletedProcess(
                    command, 0, "configmap/" + trust.NAME if trust.NAME in api.cms else "", "")
            elif args[:2] == ["get", "pods"] and args[-1] == READY_PATH:
                if args[3] == "monitoring-system":
                    assert args[:7] == ["get", "pods", "-n", "monitoring-system", "-l",
                                        trust.NODE_LABEL, "--field-selector"]
                    assert len(args) == 9 and args[7].startswith("spec.nodeName=")
                    source = args[7].split("=", 1)[1]
                    assert source in api.hosts
                else:
                    assert args == ["get", "pods", "-n", "gitea", "-l", trust.GITEA_LABEL, READY_PATH]
                    source = "gitea"
                status = "True;"
                rc = 0
                if source == state["read_error"]:
                    status, rc = "", 1
                elif source == state["transient"] and not any(
                        attempt["source"] == source for attempt in state["readiness"]):
                    status = "True;;" if state["replacement"] else "False;"
                state["readiness"].append({"source": source, "status": status, "rc": rc})
                result = subprocess.CompletedProcess(command, rc, status, "synthetic API read error" if rc else "")
            else:
                # Every other operation must satisfy the existing exact-command
                # fake, including public-key exec commands and CAS publication.
                payload = sys.stdin.read() if args[0] in ("create", "replace") else None
                result = api(normalized, input=payload, text=True,
                             capture_output=True, check=False, cwd=trust.ROOT, timeout=60)
        except Exception:
            result = subprocess.CompletedProcess(command, 1, "", traceback.format_exc())
        finally:
            state["api"] = api.__dict__
            state_path.write_text(json.dumps(state))
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode


def extracted_play(support, source, filename):
    """Fail closed before building a harness; never copy roles or other plays."""
    document = support.trust.yaml.safe_load((source / "metal" / filename).read_text())
    assert isinstance(document, list)
    if filename in NODE_PLAYS:
        candidates = [play for play in document if play.get("hosts") == "metal" and "post_tasks" in play]
        assert len(candidates) == 1, "Expected exactly one metal post_tasks play"
        tasks = candidates[0]["post_tasks"]
        assert isinstance(tasks, list) and len(tasks) == 1
        task = tasks[0]
        assert set(task) <= {"name", "ansible.builtin.import_tasks", "delegate_to", "connection",
                             "become", "run_once", "vars", "tags"}
        assert task["ansible.builtin.import_tasks"] == "tasks/ssh-trust.yml"
        assert task["delegate_to"] == "localhost" and task["connection"] == "local"
        assert task["run_once"] is True and task["become"] is False
        assert task["vars"] == {"ansible_python_interpreter": "{{ ansible_playbook_python }}",
                                "ssh_trust_defer_bootstrap": True}
        return {"name": "Only real " + filename + " post_tasks", "hosts": "metal",
                "gather_facts": False, "post_tasks": copy.deepcopy(tasks)}
    assert filename == "ssh-trust.yml" and len(document) == 1
    play = document[0]
    assert play["hosts"] == "localhost" and play["connection"] == "local"
    assert play["gather_facts"] is False and play["become"] is False
    assert "vars" not in play and len(play["tasks"]) == 1
    task = play["tasks"][0]
    assert set(task) <= {"name", "ansible.builtin.import_tasks"}
    assert task["ansible.builtin.import_tasks"] == "tasks/ssh-trust.yml"
    return {"name": "Only real standalone task import", "hosts": "localhost",
            "connection": "local", "gather_facts": False, "become": False,
            "tasks": copy.deepcopy(play["tasks"])}


def check_common_tasks(support, path):
    """Permit only the expected read gates and one automatic helper command."""
    tasks = support.trust.yaml.safe_load(path.read_text())
    commands = []

    def visit(items):
        for task in items:
            assert set(task) <= {"name", "ansible.builtin.command", "ansible.builtin.assert",
                                 "ansible.builtin.debug", "block", "when", "register", "changed_when",
                                 "failed_when", "until", "retries", "delay", "loop"}
            if "block" in task:
                visit(task["block"])
            if "ansible.builtin.command" not in task:
                continue
            command = task["ansible.builtin.command"]
            assert set(command) <= {"argv", "chdir"}
            argv = command["argv"]
            commands.append(argv)
            if argv[0] == "kubectl":
                assert argv[:5] == ["kubectl", "--kubeconfig", "{{ playbook_dir }}/kubeconfig.yaml",
                                    "--server=https://10.0.20.50:6443", "--request-timeout=20s"]
                assert argv[5] == "get" and argv[6] in ("namespaces", "configmap", "pods")
            else:
                assert command["chdir"] == "{{ playbook_dir }}/.."
                assert argv[0] == "{{ ansible_playbook_python }}"
                if argv[1] == "-c":
                    assert argv == ["{{ ansible_playbook_python }}", "-c",
                                    "import json, runpy, sys; module = runpy.run_path(sys.argv[1]); "
                                    "module['API']().establish(); print(json.dumps(module['inventory']()))",
                                    "{{ playbook_dir }}/scripts/ssh-trust.py"]
                else:
                    assert argv[1:4] == ["{{ playbook_dir }}/scripts/ssh-trust.py",
                                         "--automatic", "--known-hosts"]
                    assert len(argv) == 5 and "ssh_trust_known_hosts" in argv[4]
            if "retries" in task or "until" in task:
                assert argv[0] == "kubectl" and argv[5:7] == ["get", "pods"]
                assert ".rc != 0" in task["until"] and ".rc != 0" in task["failed_when"]

    visit(tasks)
    assert len(commands) == 6
    assert commands[0][1] == "-c" and commands[-1][2] == "--automatic"


class Fixture:
    def __init__(self, filename, *, previous=False, namespaces=("monitoring-system", "gitea"),
                 transient="", read_error="", replacement=False):
        # Retain fixtures and logs, including failed subprocess evidence.
        self.root = Path(tempfile.mkdtemp(prefix="ssh-trust-playbooks-")).resolve()
        metal = self.root / "metal"
        scripts = metal / "scripts"
        for directory in (scripts, metal / "tasks", metal / "inventories", self.root / "bin",
                          self.root / "tmp", self.root / "logs", self.root / "ansible",
                          self.root / "cache/local", self.root / "cache/remote",
                          self.root / "cache/control", self.root / "cache/ssh",
                          self.root / "cache/python", self.root / "empty-roles"):
            directory.mkdir(parents=True, exist_ok=True)
        for name in ("ssh-trust.py", "test_ssh_trust.py", Path(__file__).name):
            shutil.copyfile(SOURCE / "metal/scripts" / name, scripts / name)
        shutil.copyfile(SOURCE / "metal/tasks/ssh-trust.yml", metal / "tasks/ssh-trust.yml")
        self.support = load_support(scripts)
        self.trust = self.support.trust
        check_common_tasks(self.support, metal / "tasks/ssh-trust.yml")
        self.play = extracted_play(self.support, SOURCE, filename)
        self.playbook = metal / "fixture.yml"
        self.playbook.write_text(self.trust.yaml.safe_dump([self.play], sort_keys=False))
        inventory = {"metal": {"children": {
            "masters": {"hosts": {"alpha": {"ansible_host": HOSTS["alpha"]}}},
            "workers": {"hosts": {name: {"ansible_host": address}
                                   for name, address in HOSTS.items() if name != "alpha"}}}}}
        self.inventory = metal / "inventories/prod.yml"
        self.inventory.write_text(self.trust.yaml.safe_dump(inventory, sort_keys=False))
        # Public synthetic config only; all reads are dispatched by the fake.
        (metal / "kubeconfig.yaml").write_text("apiVersion: v1\nkind: Config\n")
        self.known_hosts = self.root / "output/homelab_known_hosts"
        self.state_path = self.root / "state.json"
        api = self.support.Kubernetes()
        api.hosts = HOSTS.copy()
        api.nodes = [{"metadata": {"name": name, "uid": name + "-node-uid"}, "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "addresses": [{"type": "InternalIP", "address": address}]}}
            for name, address in HOSTS.items()]
        api.pods = [self.support.pod("exporter-" + name, name) for name in HOSTS]
        api.pods.append(self.support.pod("gitea-0", "alpha", False))
        api.keys = {"exporter-" + name: self.support.public_keys(bytes([97 + index]))
                    for index, name in enumerate(HOSTS)}
        api.keys["gitea-0"] = self.support.public_keys(b"g").splitlines()[2] + "\n"
        self.old = self.old_record = None
        if previous:
            snapshot = self.snapshot(api, ("alpha", "beta"))
            self.old = self.trust.manifest(self.trust.NAME, self.trust.bundle(api.uid, snapshot))
            self.old["metadata"].update(uid=self.trust.NAME + "-uid", resourceVersion="1")
            self.old_record = self.trust.validate_cm(self.old, api.uid)
            api.cms[self.trust.NAME] = copy.deepcopy(self.old)
            api.revision = 1
        self.state_path.write_text(json.dumps({"api": api.__dict__, "commands": [], "readiness": [],
                                              "namespaces": ["default", "kube-node-lease", "kube-public", "kube-system", *namespaces],
                                              "transient": transient, "read_error": read_error,
                                              "replacement": replacement}))
        executable = self.root / "bin/kubectl"
        executable.write_text(f"#!{sys.executable}\nimport sys\n"
                              f"sys.path.insert(0, {str(scripts)!r})\n"
                              "from test_ssh_trust_playbooks import fake_kubectl\n"
                              "raise SystemExit(fake_kubectl())\n")
        executable.chmod(0o700)
        blocker = "#!" + sys.executable + "\nraise SystemExit('SSH is forbidden in this offline fixture')\n"
        for name in ("ssh", "scp", "sftp", "ssh-keyscan"):
            path = self.root / "bin" / name
            path.write_text(blocker)
            path.chmod(0o700)
        config = self.root / "ansible.cfg"
        config.write_text(
            "[defaults]\nstdout_callback = default\nretry_files_enabled = False\n"
            "fact_caching = memory\n"
            f"roles_path = {self.root / 'empty-roles'}\n"
            f"local_tmp = {self.root / 'cache/local'}\n"
            f"remote_tmp = {self.root / 'cache/remote'}\n"
            f"log_path = {self.root / 'logs/ansible.log'}\n"
            f"interpreter_python = {sys.executable}\n"
            "[persistent_connection]\n"
            f"control_path_dir = {self.root / 'cache/control'}\n"
            "[ssh_connection]\n"
            f"ssh_executable = {self.root / 'bin/ssh'}\n"
            f"control_path_dir = {self.root / 'cache/ssh'}\n")
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")}
        self.env.update({"ANSIBLE_CONFIG": str(config), "ANSIBLE_HOME": str(self.root / "ansible"),
                         "ANSIBLE_LOCAL_TEMP": str(self.root / "cache/local"),
                         "ANSIBLE_REMOTE_TEMP": str(self.root / "cache/remote"),
                         "ANSIBLE_LOG_PATH": str(self.root / "logs/ansible.log"),
                         "ANSIBLE_PERSISTENT_CONTROL_PATH_DIR": str(self.root / "cache/control"),
                         "ANSIBLE_SSH_CONTROL_PATH_DIR": str(self.root / "cache/ssh"),
                         "ANSIBLE_STDOUT_CALLBACK": "default", "ANSIBLE_NOCOLOR": "1",
                         "PYTHONDONTWRITEBYTECODE": "1",
                         "PYTHONPYCACHEPREFIX": str(self.root / "cache/python"),
                         "XDG_CACHE_HOME": str(self.root / "cache"), "TMPDIR": str(self.root / "tmp"),
                         "SSH_TRUST_TEST_STATE": str(self.state_path),
                         "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", "")})
        # API.establish deliberately rejects proxies. This fixture has no network.
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            self.env.pop(key, None)
        assert self.env.get("HOME") == os.environ.get("HOME")
        assert shutil.which("kubectl", path=self.env["PATH"]) == str(executable)

    def snapshot(self, api, names):
        entries = {}
        nodes = {node["metadata"]["name"]: node for node in api.nodes}
        for name in (*names, "git.eaglepass.io"):
            exporter = name != "git.eaglepass.io"
            pod = next(p for p in api.pods if p["metadata"]["name"] == (
                "exporter-" + name if exporter else "gitea-0"))
            source = self.trust.pod_source(pod, "monitoring-system" if exporter else "gitea",
                                          "node-exporter" if exporter else "gitea", name if exporter else None)
            source["node_uid"] = nodes[source["node"]]["metadata"]["uid"]
            entries[name] = {"source": source, "keys": self.trust.parse_keys(
                api.keys[pod["metadata"]["name"]], node=exporter)}
        snapshot = {"inventory": {name: api.hosts[name] for name in names}, "entries": entries}
        self.trust.validate_snapshot(snapshot)
        return snapshot

    def run(self, executable, *, limited=True):
        command = [executable, "-i", str(self.inventory), str(self.playbook), "--extra-vars",
                   json.dumps({"ssh_trust_known_hosts": str(self.known_hosts),
                               "ansible_python_interpreter": sys.executable})]
        if limited:
            command.extend(("--limit", "gamma,delta"))
        # A timeout bounds one hung subprocess, not the test suite's duration.
        try:
            result = subprocess.run(command, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, check=False, timeout=180)
        except subprocess.TimeoutExpired as error:
            for name, output in (("stdout", error.stdout), ("stderr", error.stderr)):
                (self.root / "logs" / name).write_bytes(
                    output.encode() if isinstance(output, str) else output or b"")
            raise AssertionError(f"Hung Ansible attempt; retained fixture: {self.root}") from error
        (self.root / "logs/stdout").write_text(result.stdout)
        (self.root / "logs/stderr").write_text(result.stderr)
        return result

    def state(self):
        return json.loads(self.state_path.read_text())


class TrustPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ansible = shutil.which("ansible-playbook")
        if cls.ansible is None:
            raise RuntimeError("ansible-core must be installed in the runner's process environment")

    def assert_result(self, fixture, result, success):
        message = f"Retained fixture: {fixture.root}\n{result.stdout}\n{result.stderr}"
        if success:
            self.assertEqual(result.returncode, 0, message)
            self.assertNotIn("skipping: no hosts matched", result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, message)
            self.assertIn("failed=1", result.stdout, message)

    def assert_unpublished(self, fixture):
        state = fixture.state()
        self.assertEqual(state["api"]["writes"], [], str(fixture.root))
        self.assertFalse(fixture.known_hosts.parent.exists(), str(fixture.root))
        self.assertEqual(state["api"]["cms"],
                         {fixture.trust.NAME: fixture.old} if fixture.old else {})

    def test_source_import_metadata_and_role_free_harness(self):
        for filename in (*NODE_PLAYS, "ssh-trust.yml"):
            with self.subTest(playbook=filename):
                fixture = Fixture(filename)
                play = fixture.trust.yaml.safe_load(fixture.playbook.read_text())[0]
                self.assertFalse(play["gather_facts"])
                self.assertFalse({"roles", "pre_tasks", "import_playbook", "serial"} & set(play))
                self.assertEqual(set(play), {"name", "hosts", "gather_facts", "post_tasks"}
                                 if filename in NODE_PLAYS else {
                                     "name", "hosts", "connection", "gather_facts", "become", "tasks"})
                self.assertEqual((fixture.root / "metal/tasks/ssh-trust.yml").read_bytes(),
                                 (SOURCE / "metal/tasks/ssh-trust.yml").read_bytes())
                self.assertEqual(fixture.trust.inventory(), HOSTS)

    def test_both_limited_node_imports_publish_full_inventory_exactly_once(self):
        for filename in NODE_PLAYS:
            for previous in (False, True):
                with self.subTest(playbook=filename, previous=previous):
                    fixture = Fixture(filename, previous=previous, transient="gamma", replacement=previous)
                    result = fixture.run(self.ansible)
                    self.assert_result(fixture, result, True)
                    state = fixture.state()
                    api = state["api"]
                    cm = api["cms"][fixture.trust.NAME]
                    record = fixture.trust.validate_cm(cm, api["uid"])
                    self.assertEqual(record["snapshot"]["inventory"], HOSTS)
                    self.assertEqual(record["snapshot"], fixture.snapshot(SimpleNamespace(**api), tuple(HOSTS)))
                    self.assertEqual(set(record["snapshot"]["entries"]), set(HOSTS) | {"git.eaglepass.io"})
                    self.assertEqual(record["approval"]["method"], "automatic")
                    self.assertEqual(fixture.known_hosts.read_text(), cm["data"]["known_hosts"])
                    self.assertEqual(stat.S_IMODE(fixture.known_hosts.stat().st_mode), 0o600)
                    self.assertEqual([write for write in api["writes"] if write[1] == fixture.trust.NAME],
                                     [["replace" if previous else "create", fixture.trust.NAME]])
                    # One establish for the common task, one for the helper. A
                    # second idempotent helper execution must not pass unnoticed.
                    self.assertEqual(api["commands"].count(["config", "view", "--minify", "-o", "json"]), 2)
                    self.assertEqual(api["commands"].count(["get", "nodes", "-o", "json"]), 1)
                    self.assertEqual(sorted(attempt["source"] for attempt in state["readiness"]),
                                     sorted([*HOSTS, "gamma", "gitea"]))
                    self.assertEqual([attempt["status"] for attempt in state["readiness"]
                                      if attempt["source"] == "gamma"], ["True;;" if previous else "False;", "True;"])
                    self.assertIn("gamma -> localhost", result.stdout)
                    self.assertNotIn("Type APPROVE", result.stdout)
                    if previous:
                        self.assertEqual(record["source_approval"], fixture.old_record["source_approval"])
                        archives = [value for name, value in api["cms"].items() if name != fixture.trust.NAME]
                        self.assertEqual(len(archives), 1)
                        self.assertIs(archives[0]["immutable"], True)
                        self.assertEqual(archives[0]["data"], fixture.old["data"])
                        self.assertEqual(len(api["writes"]), 2)
                    else:
                        self.assertEqual(len(api["writes"]), 1)
                        self.assertEqual(record["source_approval"]["method"], "automatic")

    def test_first_bootstrap_defers_only_node_imports_not_strict_standalone(self):
        for filename in (*NODE_PLAYS, "ssh-trust.yml"):
            with self.subTest(playbook=filename):
                fixture = Fixture(filename, namespaces=())
                result = fixture.run(self.ansible, limited=filename in NODE_PLAYS)
                self.assert_result(fixture, result, filename in NODE_PLAYS)
                self.assert_unpublished(fixture)
                self.assertEqual(fixture.state()["readiness"], [])
                if filename in NODE_PLAYS:
                    self.assertIn("no trust reference exists", result.stdout)
                else:
                    self.assertIn("SSH trust sources are missing", result.stdout)

    def test_conditionless_gitea_replacement_waits_before_publication(self):
        fixture = Fixture("nodes.yml", transient="gitea", replacement=True)
        result = fixture.run(self.ansible)
        self.assert_result(fixture, result, True)
        state = fixture.state()
        self.assertEqual([attempt["status"] for attempt in state["readiness"]
                          if attempt["source"] == "gitea"], ["True;;", "True;"])
        self.assertEqual([write for write in state["api"]["writes"] if write[1] == fixture.trust.NAME],
                         [["create", fixture.trust.NAME]])

    def test_existing_reference_never_allows_missing_source_deferral(self):
        for filename in (*NODE_PLAYS, "ssh-trust.yml"):
            with self.subTest(playbook=filename):
                fixture = Fixture(filename, previous=True, namespaces=("monitoring-system",))
                result = fixture.run(self.ansible, limited=filename in NODE_PLAYS)
                self.assert_result(fixture, result, False)
                self.assertIn("SSH trust sources are missing", result.stdout)
                self.assert_unpublished(fixture)
                self.assertEqual(fixture.state()["readiness"], [])

    def test_existing_platform_without_reference_never_allows_missing_source_deferral(self):
        for filename in NODE_PLAYS:
            with self.subTest(playbook=filename):
                fixture = Fixture(filename, namespaces=("argocd",))
                result = fixture.run(self.ansible)
                self.assert_result(fixture, result, False)
                self.assertIn("SSH trust sources are missing", result.stdout)
                self.assert_unpublished(fixture)
                self.assertEqual(fixture.state()["readiness"], [])

    def test_readiness_api_error_fails_on_first_attempt_without_publication(self):
        for filename in (*NODE_PLAYS, "ssh-trust.yml"):
            with self.subTest(playbook=filename):
                fixture = Fixture(filename, read_error="gamma")
                result = fixture.run(self.ansible, limited=filename in NODE_PLAYS)
                self.assert_result(fixture, result, False)
                self.assert_unpublished(fixture)
                state = fixture.state()
                self.assertEqual([attempt for attempt in state["readiness"] if attempt["source"] == "gamma"],
                                 [{"source": "gamma", "status": "", "rc": 1}])
                self.assertFalse(any(attempt["source"] == "gitea" for attempt in state["readiness"]))
                self.assertNotIn(["get", "nodes", "-o", "json"], state["api"]["commands"])
                self.assertNotIn("FAILED - RETRYING", result.stdout)


if __name__ == "__main__":
    unittest.main()
