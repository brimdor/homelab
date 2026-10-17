#!/usr/bin/env python3
"""Offline source and real-Ansible regression checks; requires ansible-core/PyYAML.

Run: python3 -B -m unittest discover -s metal/scripts -p test_host_service_repairs.py -v

Normal tempfile routing respects the caller's TMPDIR; fixtures are retained.
HOME stays unchanged. Docker tests import the remote function and replace its
subprocess dispatcher. Ansible imports only failure-query/reset tasks against a
closed fake systemctl. No provisioning playbook, service module or real service
command runs. Display file/service operations stay static checks. All daemon
JSON is public synthetic data; product ownership behavior remains intact.
"""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


SOURCE = Path(__file__).resolve().parents[2]
DOCKER = SOURCE / "metal/roles/docker/tasks"
DISPLAY = SOURCE / "metal/roles/display_config/tasks"
DISPLAY_UNITS = ["weston-headless.service", "xvfb.service"]
DOCKER_UNITS = ["docker.service", "docker.socket"]
spec = importlib.util.spec_from_file_location("docker_repair", DOCKER.parent / "files/reconcile-daemon.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def load(path):
    return yaml.safe_load(path.read_text())


def flatten(tasks):
    for task in tasks:
        if "block" in task:
            yield from flatten(task["block"])
        else:
            yield task


def fake_command(args):
    """No subprocess or real service access; reject every unlisted command."""
    path = Path(os.environ["HOST_SERVICE_TEST_STATE"])
    state = json.loads(path.read_text())
    state["commands"].append(["systemctl", *args])
    output, error, rc = "", "", 0
    try:
        if state.get("read_error"):
            raise ValueError("synthetic bus authorization failure")
        if len(args) == 2 and args[1] in DOCKER_UNITS + DISPLAY_UNITS:
            action, unit = args
            status = state["states"].get(unit, "inactive")
            if action == "is-failed":
                output = status
                rc = 0 if status == "failed" else 4 if status == "unknown" else 1
            elif action == "reset-failed" and status == "failed":
                state["states"][unit] = "inactive"
            else:
                raise ValueError("Unexpected fake systemctl mutation")
        else:
            raise ValueError("Unexpected fake systemctl command")
    except (AssertionError, ValueError) as exc:
        error, rc = str(exc) or "Unexpected fake arguments", 1
    path.write_text(json.dumps(state))
    sys.stdout.write(output + "\n" if output else "")
    sys.stderr.write(error + "\n" if error else "")
    return rc


class RepairFixture:
    def __init__(self, content=None, flag="--live-restore", *, validation_error=False,
                 read_error=False, mutate=None, timeout=False, environment="", unset_environment=""):
        self.root = Path(tempfile.mkdtemp(prefix="daemon-reconcile-")).resolve()
        self.config = self.root / "daemon.json"
        if content is not None:
            self.config.write_text(content)
            self.config.chmod(0o644)
        self.flag = flag
        self.environment = environment
        self.environment_files = ""
        self.unset_environment = unset_environment
        self.validation_error = validation_error
        self.read_error = read_error
        self.mutate = mutate
        self.timeout = timeout
        self.commands = []
        self.property_reads = []

    def dispatch(self, argv, **kwargs):
        self.commands.append(argv)
        assert kwargs == {"stdin": subprocess.DEVNULL, "capture_output": True,
                          "check": False, "timeout": 30}
        secret = b"https://synthetic-user:synthetic-password@proxy.example.test"
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, 30, output=secret, stderr=secret)
        if argv[:3] == ["systemctl", "show", "docker.service"]:
            properties = {
                "--property=ExecStart": "{ path=/usr/bin/dockerd ; argv[]=/usr/bin/dockerd " + self.flag + " ; }",
                "--property=Environment": self.environment,
                "--property=EnvironmentFiles": self.environment_files,
                "--property=UnsetEnvironment": self.unset_environment,
            }
            assert len(argv) == 5 and argv[-1] == "--value" and argv[3] in properties
            self.property_reads.append((argv[3], properties[argv[3]]))
            return subprocess.CompletedProcess(argv, int(self.read_error), properties[argv[3]].encode(),
                                               secret if self.read_error else b"")
        assert argv[:3] == ["/fake/dockerd", "--validate", "--config-file"] and len(argv) == 4
        candidate = Path(argv[3])
        assert candidate.is_relative_to(self.root)
        assert "live-restore" not in json.loads(candidate.read_text())
        if self.mutate:
            self.mutate(self.config)
        return subprocess.CompletedProcess(argv, int(self.validation_error), secret, secret)

    def run(self):
        with mock.patch.object(repair.subprocess, "run", side_effect=self.dispatch):
            return repair.reconcile(self.config, "/fake/dockerd")

    def backups(self):
        return list(self.root.glob(".daemon.json.backup-*"))

    def validations(self):
        return [command for command in self.commands
                if command[:3] == ["/fake/dockerd", "--validate", "--config-file"]]

    def add_env_file(self, content, name="docker.env", *, optional=False):
        path = self.root / name
        if content is not None:
            path.write_text(content)
        self.environment_files += f" {shlex.quote(str(path))} (ignore_errors={'yes' if optional else 'no'})"
        return path


class Fixture:
    def __init__(self, *, display=False, reconciled=True, states=None, read_error=False):
        self.root = Path(tempfile.mkdtemp(prefix="host-service-repairs-")).resolve()
        for name in ("bin", "tmp", "local", "remote", "cache", "ansible", "logs", "control"):
            (self.root / name).mkdir()
        self.state_path = self.root / "state.json"
        self.state_path.write_text(json.dumps({
            "commands": [],
            "states": states if states is not None else {unit: "failed" for unit in DOCKER_UNITS},
            "read_error": read_error,
        }))
        executable = self.root / "bin/systemctl"
        executable.write_text(
            f"#!{sys.executable}\nimport runpy, sys\n"
            f"sys.argv = [{str(Path(__file__).resolve())!r}, '--fake', *sys.argv[1:]]\n"
            f"runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')\n")
        executable.chmod(0o700)
        if display:
            # No local /etc, service, backup-directory or daemon-reload action.
            tasks = load(DISPLAY / "retire_system_units.yml")[-2:]
            assert [t["ansible.builtin.command"]["argv"][1] for t in tasks] == ["is-failed", "reset-failed"]
            source_import = load(DISPLAY / "main.yaml")[0]
        else:
            tasks = load(DOCKER / "daemon_config.yml")[1:]
            source_import = load(DOCKER / "main.yml")[-2]
        for task in flatten(tasks):
            argv = task["ansible.builtin.command"]["argv"]
            assert argv[0] == "systemctl" and argv[1] in ("is-failed", "reset-failed")
        self.tag = source_import["tags"]
        task_file = self.root / "repair.yml"
        task_file.write_text(yaml.safe_dump(tasks, sort_keys=False))
        self.playbook = self.root / "fixture.yml"
        self.playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "become": False,
            "vars": {"docker_daemon_repair": {"stdout": json.dumps({
                         "changed": False, "validated": reconciled,
                         "reconciled": reconciled, "backup_path": None})},
                     "ansible_python_interpreter": sys.executable},
            "tasks": [{"ansible.builtin.import_tasks": str(task_file), "tags": self.tag}],
        }], sort_keys=False))
        config = self.root / "ansible.cfg"
        config.write_text(
            "[defaults]\nretry_files_enabled = False\nfact_caching = memory\n"
            f"local_tmp = {self.root / 'local'}\nremote_tmp = {self.root / 'remote'}\n"
            f"log_path = {self.root / 'logs/ansible.log'}\n"
            "[persistent_connection]\n"
            f"control_path_dir = {self.root / 'control'}\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
        self.env.update({
            "ANSIBLE_CONFIG": str(config), "ANSIBLE_HOME": str(self.root / "ansible"),
            "ANSIBLE_LOCAL_TEMP": str(self.root / "local"),
            "ANSIBLE_REMOTE_TEMP": str(self.root / "remote"),
            "ANSIBLE_LOG_PATH": str(self.root / "logs/ansible.log"),
            "ANSIBLE_PERSISTENT_CONTROL_PATH_DIR": str(self.root / "control"),
            "ANSIBLE_NOCOLOR": "1", "ANSIBLE_STDOUT_CALLBACK": "default",
            "TMPDIR": str(self.root / "tmp"), "XDG_CACHE_HOME": str(self.root / "cache"),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(self.root / "cache/python"),
            "HOST_SERVICE_TEST_STATE": str(self.state_path),
            "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", ""),
        })
        assert self.env.get("HOME") == os.environ.get("HOME")
        assert shutil.which("systemctl", path=self.env["PATH"]) == str(self.root / "bin/systemctl")

    def run(self):
        # Bounds one hung subprocess, not the overall task or suite.
        result = subprocess.run(
            [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(self.playbook),
             "--tags", self.tag],
            cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, check=False, timeout=180)
        (self.root / "logs/stdout").write_text(result.stdout)
        (self.root / "logs/stderr").write_text(result.stderr)
        return result

    def commands(self):
        return json.loads(self.state_path.read_text())["commands"]


class HostServiceRepairTests(unittest.TestCase):
    def run_fixture(self, fixture, *, success=True):
        result = fixture.run()
        message = f"Retained fixture: {fixture.root}\n{result.stdout}\n{result.stderr}"
        self.assertEqual(result.returncode == 0, success, message)
        self.assertNotIn("skipping: no hosts matched", result.stdout, message)
        return result

    def test_tag_selection_and_final_start_are_narrow(self):
        for directory, filename, tag, imported in (
            (DOCKER, "main.yml", "docker_daemon_config", "daemon_config.yml"),
            (DISPLAY, "main.yaml", "display_legacy_cleanup", "retire_system_units.yml"),
        ):
            tasks = load(directory / filename)
            selected = [t for t in tasks if t.get("tags") == tag]
            self.assertEqual(selected[0]["ansible.builtin.import_tasks"], imported)
            if directory == DOCKER:
                self.assertEqual(tasks[-2:], selected)
                self.assertEqual(selected[-1]["systemd"], {
                    "name": "docker", "enabled": True, "state": "started"})
            else:
                self.assertEqual(tasks[:1], selected)
            for task in tasks:
                self.assertNotEqual(task.get("tags"), "always")
        node_play = load(SOURCE / "metal/nodes.yml")[0]
        self.assertTrue(all(t.get("tags") == "ssh_trust" for t in node_play["post_tasks"]))
        self.assertFalse(any(isinstance(r, dict) and r.get("tags") in
                              ("docker_daemon_config", "display_legacy_cleanup", "always")
                              for r in node_play["roles"]))
        plays = load(SOURCE / "metal/host-service-repair.yml")
        self.assertEqual([p["hosts"] for p in plays], ["charmander", "arcanine"])
        self.assertTrue(all(p["gather_facts"] is False and "roles" not in p for p in plays))
        self.assertEqual(plays[0]["tasks"][0]["ansible.builtin.import_tasks"], "roles/docker/tasks/daemon_config.yml")
        self.assertEqual(plays[1]["tasks"][0]["ansible.builtin.import_tasks"], "roles/display_config/tasks/retire_system_units.yml")
        self.assertEqual(plays[0]["tasks"][-1]["ansible.builtin.systemd_service"], {
            "name": "docker", "enabled": True, "state": "started"})
        self.assertEqual(plays[0]["tasks"][1]["ansible.builtin.assert"]["that"], [
            "(docker_daemon_repair.stdout | from_json).validated",
            "(docker_daemon_repair.stdout | from_json).reconciled"])
        self.assertEqual(len(plays[0]["tasks"]), 3)

    def test_docker_source_privacy_validation_and_failure_gate(self):
        tasks = load(DOCKER / "daemon_config.yml")
        invocation, failure_block = tasks
        self.assertEqual(invocation["ansible.builtin.script"]["executable"], "/usr/bin/python3")
        command = invocation["ansible.builtin.script"]["cmd"]
        self.assertIn("playbook_dir ~ '/roles/docker/files/reconcile-daemon.py'", command)
        self.assertNotIn("role_path", command)
        self.assertIn("daemon_config_path | default('/etc/docker/daemon.json') | quote", command)
        self.assertIn("daemon_binary | default('/usr/bin/dockerd') | quote", command)
        self.assertEqual(invocation["changed_when"],
                         "docker_daemon_repair.rc == 0 and (docker_daemon_repair.stdout | from_json).changed")
        for task in flatten(tasks):
            self.assertFalse(set(task) & {"ansible.builtin.slurp", "ansible.builtin.copy",
                                          "ansible.builtin.fetch", "ansible.builtin.set_fact"})
        self.assertEqual(failure_block["when"], "(docker_daemon_repair.stdout | from_json).reconciled")
        self.assertEqual(failure_block["block"][0]["loop"], DOCKER_UNITS)
        self.assertEqual(failure_block["block"][1]["when"], "item.stdout == 'failed' and item.rc == 0")

    def test_duplicate_removal_preserves_unrelated_values_and_is_idempotent(self):
        original = {"live-restore": True, "registry-mirrors": ["https://mirror.example.test"],
                    "runtimes": {"nvidia": {"path": "nvidia-container-runtime", "runtimeArgs": []}},
                    "features": {"buildkit": False}, "max-concurrent-downloads": 7}
        for flag in ("--live-restore", "--live-restore=true", "--live-restore=false"):
            with self.subTest(flag=flag):
                content = json.dumps(original)
                fixture = RepairFixture(content, flag)
                result = fixture.run()
                self.assertEqual(json.loads(fixture.config.read_text()),
                                 {k: v for k, v in original.items() if k != "live-restore"})
                self.assertEqual(stat.S_IMODE(fixture.config.stat().st_mode), 0o600)
                backups = fixture.backups()
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), content)
                self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
                self.assertEqual(backups[0].stat().st_uid, os.geteuid())
                self.assertEqual(fixture.config.stat().st_uid, os.geteuid())
                self.assertEqual(result, {"changed": True, "validated": True,
                                         "reconciled": True, "backup_path": str(backups[0])})
                self.assertEqual(fixture.run(), {"changed": False, "validated": True,
                                                "reconciled": True, "backup_path": None})
                self.assertEqual(fixture.validations()[-1][-1], str(fixture.config))
                self.assertEqual(fixture.backups(), backups)
                self.assertFalse(list(fixture.root.glob(".daemon.json.candidate-*")))

    def test_missing_config_and_absent_flag_are_noops(self):
        for content, flag in ((None, "--live-restore"), ('{"live-restore":true}', ""),
                              ('{"live-restore":true}', "--live-restore-extra"),
                              ('{"live-restore":true}', "--label=--live-restore")):
            with self.subTest(content=content, flag=flag):
                fixture = RepairFixture(content, flag)
                files = list(fixture.root.iterdir())
                self.assertEqual(fixture.run(), {"changed": False, "validated": False,
                                                "reconciled": False, "backup_path": None})
                self.assertEqual(fixture.config.read_text() if fixture.config.exists() else None, content)
                self.assertEqual(list(fixture.root.iterdir()), files)
                self.assertEqual(len(fixture.commands), 0 if content is None else 1)

    def test_multiline_fedora_options_resolve_without_exporting_environment(self):
        original = {"live-restore": True, "runtimes": {"nvidia": {"path": "nvidia-container-runtime"}}}
        fixture = RepairFixture(json.dumps(original), "$OPTIONS")
        fixture.add_env_file(
            "# Public synthetic Fedora sysconfig fixture\n"
            "OPTIONS='--log-driver=journald\n"
            "  --live-restore\n"
            "  --label=\"public fixture\"'\n"
            "UNUSED='$(synthetic-not-executed)'\n", optional=True)
        result = fixture.run()
        self.assertEqual((result["changed"], result["validated"], result["reconciled"]), (True, True, True))
        self.assertEqual(json.loads(fixture.config.read_text()), {"runtimes": original["runtimes"]})
        self.assertEqual(set(result), {"changed", "validated", "reconciled", "backup_path"})
        properties = [name for name, value in fixture.property_reads]
        expected = ["--property=ExecStart", "--property=Environment", "--property=EnvironmentFiles",
                    "--property=UnsetEnvironment"]
        self.assertEqual(properties[:4], expected)
        self.assertEqual(set(properties), set(expected))
        self.assertTrue(all(properties.count(name) >= 2 for name in expected))
        self.assertFalse(fixture.run()["changed"])
        self.assertEqual(len(fixture.backups()), 1)

    def test_referenced_environment_values_require_exact_flag_tokens(self):
        cases = [(reference, option, True) for reference in ("$OPTIONS", "${OPTIONS}")
                 for option in ("--live-restore", "--live-restore=true", "--live-restore=false")]
        cases += [("$OPTIONS", "--label='note --live-restore'", False),
                  ("$OPTIONS", "--label=--live-restore", False),
                  ("$OPTIONS", "--live-restore-extra", False),
                  ("${OPTIONS}", "--debug --live-restore", False)]
        for reference, option, owned in cases:
            with self.subTest(reference=reference, option=option):
                fixture = RepairFixture('{"live-restore":true}', reference,
                                        environment="OPTIONS=" + shlex.quote(option))
                self.assertEqual(fixture.run()["reconciled"], owned)
        fixture = RepairFixture('{"live-restore":true}', "$OPTIONS",
                                environment="UNUSED=--live-restore OPTIONS=--debug")
        self.assertFalse(fixture.run()["reconciled"])
        self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_environment_file_assignments_are_line_based(self):
        content = ("# Comment with an unmatched ' quote\n"
                   '; Comment with an unmatched " quote\n'
                   "UNUSED=note OPTIONS=--live-restore\n"
                   "EMPTY=\n"
                   "  OPTIONS = '--debug\n--live-restore'  \n")
        self.assertEqual(repair.environment_file_assignments(content), {
            "UNUSED": "note OPTIONS=--live-restore", "EMPTY": "", "OPTIONS": "--debug\n--live-restore"})
        fixture = RepairFixture('{"live-restore":true}', "$OPTIONS")
        fixture.add_env_file("UNUSED=note OPTIONS=--live-restore\n")
        result = fixture.run()
        self.assertEqual((result["changed"], result["validated"], result["reconciled"]), (False, False, False))
        self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
        self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_double_quoted_fedora_line_continuations_preserve_option_words(self):
        fixture = RepairFixture('{"live-restore":true,"features":{"buildkit":false}}', "$OPTIONS")
        content = 'OPTIONS="--log-driver=journald \\\n  --live-restore \\\n  --log-level=info"\n'
        fixture.add_env_file(content, optional=True)
        parsed = repair.environment_file_assignments(content)
        self.assertEqual(shlex.split(parsed["OPTIONS"]),
                         ["--log-driver=journald", "--live-restore", "--log-level=info"])
        result = fixture.run()
        self.assertTrue(result["changed"] and result["validated"] and result["reconciled"])
        self.assertEqual(json.loads(fixture.config.read_text()), {"features": {"buildkit": False}})
        self.assertFalse(fixture.run()["changed"])
        self.assertEqual(len(fixture.backups()), 1)

    def test_environment_file_rejects_inner_quotes_concatenation_and_unquoted_continuations(self):
        for content in ("OPTIONS=--label='note --live-restore'\n",
                        'OPTIONS=--label="note --live-restore"\n',
                        "OPTIONS='--live-restore'junk\n",
                        "OPTIONS='--live-restore'' --debug'\n",
                        "OPTIONS='--live-restore' # trailing comment\n",
                        "OPTIONS=--live-restore\\\n MORE=--debug\n",
                        'OPTIONS="--live-restore\\q"\n'):
            with self.subTest(content=content):
                fixture = RepairFixture('{"live-restore":true}', "$OPTIONS")
                fixture.add_env_file(content)
                with self.assertRaisesRegex(repair.RepairError, "^Docker daemon reconciliation failed\\.$"):
                    fixture.run()
                self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                self.assertFalse(fixture.backups())
                self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_nonempty_unset_environment_fails_closed(self):
        for reference in ("--live-restore", "$OPTIONS"):
            for unset in ("OPTIONS", "OPTIONS=--live-restore"):
                with self.subTest(reference=reference, unset=unset):
                    fixture = RepairFixture('{"live-restore":true}', reference,
                                            environment="OPTIONS=--live-restore", unset_environment=unset)
                    with self.assertRaises(repair.RepairError):
                        fixture.run()
                    self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                    self.assertFalse(fixture.backups())
                    self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_changed_unit_properties_refuse_write_or_already_repaired_success(self):
        for reference in ("--live-restore", "$OPTIONS"):
            for content in ('{"live-restore":true}', '{"runtimes":{}}'):
                for attribute, value in (("flag", "--debug"), ("environment", "OPTIONS=--debug"),
                                         ("environment_files", "/changed (ignore_errors=yes)"),
                                         ("unset_environment", "OPTIONS")):
                    with self.subTest(reference=reference, content=content, attribute=attribute):
                        fixture = RepairFixture(content, reference, environment="OPTIONS=--live-restore")

                        def mutate(path):
                            setattr(fixture, attribute, value)

                        fixture.mutate = mutate
                        with self.assertRaisesRegex(repair.RepairError, "^Docker daemon reconciliation failed\\.$"):
                            fixture.run()
                        self.assertEqual(len(fixture.validations()), 1)
                        self.assertEqual(fixture.config.read_text(), content)
                        self.assertFalse(fixture.backups())
                        self.assertFalse(list(fixture.root.glob(".daemon.json.candidate-*")))

    def test_environment_file_order_overrides_unit_environment(self):
        for last_option in ("--debug", "--live-restore"):
            with self.subTest(last_option=last_option):
                fixture = RepairFixture('{"live-restore":true}', "$OPTIONS",
                                        environment="OPTIONS=" + ("--live-restore" if last_option == "--debug" else "--debug"))
                fixture.add_env_file("OPTIONS=--live-restore\n", "first.env")
                fixture.add_env_file(f"OPTIONS={last_option}\n", "second.env")
                result = fixture.run()
                self.assertEqual(result["reconciled"], last_option == "--live-restore")
                if last_option == "--debug":
                    self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                    self.assertFalse(fixture.backups())
                    self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_missing_environment_files_require_explicit_optional_metadata(self):
        for optional in (True, False):
            with self.subTest(optional=optional):
                fixture = RepairFixture('{"live-restore":true}', "$OPTIONS",
                                        environment="OPTIONS=--live-restore")
                fixture.add_env_file(None, optional=optional)
                if optional:
                    self.assertTrue(fixture.run()["reconciled"])
                else:
                    with self.assertRaises(repair.RepairError):
                        fixture.run()
                    self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                    self.assertFalse((fixture.root / repair.LOCK_NAME).exists())

    def test_stale_environment_file_and_optional_file_appearance_fail_closed(self):
        for mutation in ("content", "inode", "optional-appeared"):
            with self.subTest(mutation=mutation):
                fixture = RepairFixture('{"live-restore":true}', "$OPTIONS",
                                        environment="OPTIONS=--live-restore")
                env = fixture.add_env_file(None if mutation == "optional-appeared" else "OPTIONS=--live-restore\n",
                                           optional=mutation == "optional-appeared")

                def mutate(path):
                    if mutation == "inode":
                        replacement = fixture.root / "replacement.env"
                        replacement.write_bytes(env.read_bytes())
                        os.replace(replacement, env)
                    else:
                        env.write_text("OPTIONS=--debug\n")

                fixture.mutate = mutate
                with self.assertRaises(repair.RepairError):
                    fixture.run()
                self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                self.assertFalse(fixture.backups())
                self.assertFalse(list(fixture.root.glob(".daemon.json.candidate-*")))

    def test_environment_is_rechecked_after_backup_before_replacement(self):
        fixture = RepairFixture('{"live-restore":true}', "$OPTIONS")
        env = fixture.add_env_file("OPTIONS=--live-restore\n")
        private_file = repair.private_file

        def change_after_backup(path, kind, content):
            name = private_file(path, kind, content)
            if kind == "backup":
                env.write_text("OPTIONS=--debug\n")
            return name

        with mock.patch.object(repair, "private_file", side_effect=change_after_backup):
            with self.assertRaises(repair.RepairError):
                fixture.run()
        self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
        self.assertEqual(len(fixture.backups()), 1)

    def test_environment_parser_failures_and_symlinks_are_sanitized(self):
        for failure in ("unit-quote", "file-quote", "assignment", "metadata", "substitution", "value-expansion", "symlink"):
            with self.subTest(failure=failure):
                fixture = RepairFixture('{"live-restore":true}', "$OPTIONS")
                if failure == "unit-quote":
                    fixture.environment = 'OPTIONS="synthetic-password'
                elif failure in ("file-quote", "assignment"):
                    fixture.add_env_file('OPTIONS="synthetic-password' if failure == "file-quote"
                                         else "export OPTIONS=synthetic-password\n")
                elif failure == "metadata":
                    fixture.environment_files = "/synthetic-password (ignore_errors=maybe)"
                elif failure == "substitution":
                    fixture.flag = "${OPTIONS:-synthetic-password}"
                elif failure == "value-expansion":
                    fixture.environment = "OPTIONS=" + shlex.quote("$UNSUPPORTED --live-restore synthetic-password")
                else:
                    target = fixture.root / "target.env"
                    target.write_text("OPTIONS=--live-restore\n")
                    fixture.add_env_file(None, optional=True).symlink_to(target)
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(repair.subprocess, "run", side_effect=fixture.dispatch):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = repair.main(["--config", str(fixture.config), "--daemon", "/fake/dockerd"])
                self.assertEqual((rc, stdout.getvalue(), stderr.getvalue()), (1, "", repair.ERROR + "\n"))
                self.assertEqual(fixture.config.read_text(), '{"live-restore":true}')
                self.assertFalse(fixture.backups())

    def test_already_repaired_file_validates_without_config_writes(self):
        content = '{"runtimes":{"nvidia":{"path":"nvidia-container-runtime"}}}'
        fixture = RepairFixture(content)
        before = fixture.config.stat()
        self.assertEqual(fixture.run(), {"changed": False, "validated": True,
                                        "reconciled": True, "backup_path": None})
        self.assertEqual(fixture.config.read_text(), content)
        self.assertEqual(fixture.config.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(fixture.validations()[-1], ["/fake/dockerd", "--validate", "--config-file", str(fixture.config)])
        lock = fixture.root / repair.LOCK_NAME
        self.assertEqual(set(fixture.root.iterdir()), {fixture.config, lock})
        self.assertEqual(lock.read_bytes(), b"")
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_invalid_json_validation_and_authorization_fail_closed(self):
        for content, options in (("{invalid", {}), ("[]", {}), ('{"other":NaN}', {}),
                                 ('{"runtimes":{},"runtimes":{}}', {}),
                                 ('{"live-restore":true}', {"validation_error": True}),
                                 ('{"live-restore":true}', {"read_error": True}),
                                 ('{"live-restore":true}', {"timeout": True}),
                                 ('{"runtimes":{}}', {"validation_error": True})):
            with self.subTest(content=content, options=options):
                fixture = RepairFixture(content, **options)
                with self.assertRaisesRegex(repair.RepairError, "^Docker daemon reconciliation failed\\.$"):
                    fixture.run()
                self.assertEqual(fixture.config.read_text(), content)
                expected = {fixture.config}
                if options.get("validation_error"):
                    expected.add(fixture.root / repair.LOCK_NAME)
                self.assertEqual(set(fixture.root.iterdir()), expected)

    def test_private_file_fsync_failure_removes_only_its_partial_file(self):
        for kind in ("candidate", "backup"):
            with self.subTest(kind=kind):
                fixture = RepairFixture('{"live-restore":true}')
                retained = fixture.root / "retained-backup"
                retained.write_bytes(b"retained synthetic evidence")
                with mock.patch.object(repair.os, "fsync", side_effect=OSError("synthetic fsync failure")):
                    with self.assertRaises(OSError):
                        repair.private_file(fixture.config, kind, b"public synthetic content")
                self.assertEqual(set(fixture.root.iterdir()), {fixture.config, retained})
                self.assertEqual(retained.read_bytes(), b"retained synthetic evidence")

    def test_private_file_failure_never_unlinks_a_replacement_inode(self):
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                fixture = RepairFixture()
                retained = fixture.root / "retained"
                retained.write_bytes(b"retained synthetic evidence")
                replacements = []

                def replace_then_fail(fd):
                    path = next(fixture.root.glob(".daemon.json.candidate-*"))
                    path.unlink()
                    if kind == "file":
                        path.write_bytes(b"replacement synthetic evidence")
                    else:
                        path.symlink_to(retained)
                    replacements.append(path)
                    raise OSError("synthetic fsync failure")

                with mock.patch.object(repair.os, "fsync", side_effect=replace_then_fail):
                    with self.assertRaises(OSError):
                        repair.private_file(fixture.config, "candidate", b"public synthetic content")
                self.assertEqual(len(replacements), 1)
                self.assertEqual(replacements[0].is_symlink(), kind == "symlink")
                self.assertEqual(replacements[0].read_bytes(), b"retained synthetic evidence"
                                 if kind == "symlink" else b"replacement synthetic evidence")
                self.assertEqual(retained.read_bytes(), b"retained synthetic evidence")

    def test_shared_lock_source_contract_and_private_metadata(self):
        lock_path = "/etc/docker/" + repair.LOCK_NAME
        self.assertEqual(lock_path, "/etc/docker/.homelab-daemon.lock")
        tasks = load(DOCKER / "main.yml")
        writer = next(t for t in tasks if t["name"] == "Configure Docker with nvidia runtime")
        self.assertEqual(writer["command"],
                         f"flock -x -w 30 {lock_path} nvidia-ctk runtime configure --runtime=docker")
        before_writer = tasks[:tasks.index(writer)]
        directory = next(t for t in before_writer if t.get("ansible.builtin.file", {}).get("path") == "/etc/docker")
        prepare = next(t for t in before_writer if t.get("ansible.builtin.file", {}).get("path") == lock_path)
        inspect = next(t for t in before_writer if t.get("ansible.builtin.stat", {}).get("path") == lock_path)
        guard = next(t for t in before_writer if t["name"] == "Require a regular shared Docker daemon lock if present")
        self.assertIs(inspect["ansible.builtin.stat"]["follow"], False)
        self.assertEqual(directory["ansible.builtin.file"]["state"], "directory")
        self.assertEqual(prepare["ansible.builtin.file"], {
            "path": lock_path, "state": "touch", "owner": "root", "group": "root",
            "mode": "0600", "follow": False, "access_time": "preserve", "modification_time": "preserve"})
        for task in (directory, inspect, guard, prepare, writer):
            self.assertEqual(task["when"], "gpu_type is defined")
            self.assertNotIn("tags", task)
        fixture = RepairFixture('{"live-restore":true}')
        fixture.run()
        lock = fixture.root / repair.LOCK_NAME
        info = lock.stat()
        self.assertEqual((stat.S_IMODE(info.st_mode), info.st_uid, info.st_size), (0o600, os.geteuid(), 0))
        with repair.daemon_lock(lock):
            fd = os.open(lock, os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    repair.fcntl.flock(fd, repair.fcntl.LOCK_EX | repair.fcntl.LOCK_NB)
            finally:
                os.close(fd)
        self.assertEqual(lock.stat().st_ino, info.st_ino)

    def test_shared_lock_rejects_unsafe_metadata_and_replaced_inode(self):
        for kind in ("symlink", "directory", "mode", "hardlink", "owner", "replaced"):
            with self.subTest(kind=kind):
                fixture = RepairFixture()
                lock = fixture.root / repair.LOCK_NAME
                target = fixture.root / "retained"
                target.write_bytes(b"retained synthetic evidence")
                target.chmod(0o600)
                if kind == "symlink":
                    lock.symlink_to(target)
                elif kind == "directory":
                    lock.mkdir()
                elif kind == "hardlink":
                    os.link(target, lock)
                else:
                    lock.touch(mode=0o600)
                    if kind == "mode":
                        lock.chmod(0o644)

                def replace_lock(fd, operation):
                    lock.unlink()
                    lock.write_bytes(b"replacement synthetic metadata")
                    lock.chmod(0o600)

                if kind == "replaced":
                    patch = mock.patch.object(repair.fcntl, "flock", side_effect=replace_lock)
                else:
                    patch = mock.patch.object(repair.os, "geteuid", return_value=os.geteuid() + (kind == "owner"))
                with patch:
                    with self.assertRaises(repair.RepairError):
                        with repair.daemon_lock(lock):
                            self.fail("Unsafe lock entered the writer section")
                self.assertEqual(target.read_bytes(), b"retained synthetic evidence")
                if kind == "replaced":
                    self.assertEqual(lock.read_bytes(), b"replacement synthetic metadata")

    def test_shared_lock_wait_uses_the_bounded_context(self):
        fixture = RepairFixture()
        lock = fixture.root / repair.LOCK_NAME

        def expire(fd, operation):
            self.assertEqual(operation, repair.fcntl.LOCK_EX)
            self.assertGreater(repair.signal.getitimer(repair.signal.ITIMER_REAL)[0], 0)
            repair.signal.getsignal(repair.signal.SIGALRM)(repair.signal.SIGALRM, None)

        with mock.patch.object(repair.fcntl, "flock", side_effect=expire):
            with self.assertRaises(repair.RepairError):
                with repair.daemon_lock(lock):
                    self.fail("Expired lock wait entered the writer section")

    def test_repair_holds_shared_lock_through_validation_and_replace(self):
        fixture = RepairFixture('{"live-restore":true}')
        dispatch, replace = fixture.dispatch, repair.os.replace

        def assert_locked():
            fd = os.open(fixture.root / repair.LOCK_NAME, os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    repair.fcntl.flock(fd, repair.fcntl.LOCK_EX | repair.fcntl.LOCK_NB)
            finally:
                os.close(fd)

        def validate_locked(argv, **kwargs):
            if argv[0] == "/fake/dockerd":
                assert_locked()
            return dispatch(argv, **kwargs)

        def replace_locked(source, target):
            assert_locked()
            replace(source, target)

        with mock.patch.object(fixture, "dispatch", side_effect=validate_locked):
            with mock.patch.object(repair.os, "replace", side_effect=replace_locked):
                self.assertTrue(fixture.run()["changed"])

    def test_stale_content_inode_and_symlink_changes_refuse_replacement(self):
        def replace_inode(path):
            replacement = path.with_name("replacement.json")
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)

        def replace_with_symlink(path):
            target = path.with_name("other.json")
            target.write_text('{"concurrent":true}')
            path.unlink()
            path.symlink_to(target)

        for mutate in (lambda p: p.write_text('{"concurrent":true}'), replace_inode, replace_with_symlink):
            with self.subTest(mutate=mutate):
                fixture = RepairFixture('{"live-restore":true}', mutate=mutate)
                with self.assertRaises(repair.RepairError):
                    fixture.run()
                self.assertFalse(fixture.backups())
                self.assertFalse(list(fixture.root.glob(".daemon.json.candidate-*")))
                expected = {"live-restore": True} if mutate is replace_inode else {"concurrent": True}
                self.assertEqual(json.loads(fixture.config.read_text()), expected)

    def test_stale_change_after_backup_preserves_both_backup_and_concurrent_data(self):
        content = '{"live-restore":true}'
        fixture = RepairFixture(content)
        original = repair.private_file

        def write_then_mutate(path, kind, data):
            name = original(path, kind, data)
            if kind == "backup":
                path.write_text('{"concurrent":true}')
            return name

        with mock.patch.object(repair, "private_file", side_effect=write_then_mutate):
            with self.assertRaises(repair.RepairError):
                fixture.run()
        self.assertEqual(fixture.config.read_text(), '{"concurrent":true}')
        self.assertEqual(len(fixture.backups()), 1)
        self.assertEqual(fixture.backups()[0].read_text(), content)
        self.assertEqual(stat.S_IMODE(fixture.backups()[0].stat().st_mode), 0o600)

    def test_symlink_and_nonregular_config_are_rejected_without_commands(self):
        for kind in ("symlink", "directory", "fifo"):
            with self.subTest(kind=kind):
                fixture = RepairFixture()
                if kind == "symlink":
                    target = fixture.root / "other.json"
                    target.write_text('{"live-restore":true}')
                    fixture.config.symlink_to(target)
                elif kind == "directory":
                    fixture.config.mkdir()
                else:
                    os.mkfifo(fixture.config)
                with self.assertRaises(repair.RepairError):
                    fixture.run()
                self.assertFalse(fixture.commands)
                self.assertFalse(fixture.backups())

    def test_cli_outputs_only_public_metadata_or_fixed_error(self):
        for options in ({}, {"read_error": True}, {"validation_error": True}, {"timeout": True}):
            with self.subTest(options=options):
                fixture = RepairFixture('{"live-restore":true}', **options)
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(repair.subprocess, "run", side_effect=fixture.dispatch):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = repair.main(["--config", str(fixture.config), "--daemon", "/fake/dockerd"])
                if options:
                    self.assertEqual((rc, stdout.getvalue(), stderr.getvalue()), (1, "", repair.ERROR + "\n"))
                else:
                    self.assertEqual(rc, 0)
                    self.assertEqual(set(json.loads(stdout.getvalue())),
                                     {"changed", "validated", "reconciled", "backup_path"})
                    self.assertEqual(stderr.getvalue(), "")
                self.assertNotIn("synthetic-password", stdout.getvalue() + stderr.getvalue())

    def test_docker_retry_resets_failed_units_even_when_configuration_unchanged(self):
        for reconciled, read_error in ((True, False), (False, False), (True, True)):
            fixture = Fixture(reconciled=reconciled, read_error=read_error,
                              states={"docker.service": "failed", "docker.socket": "active"})
            self.run_fixture(fixture, success=not read_error)
            resets = [c for c in fixture.commands() if c[1] == "reset-failed"]
            self.assertEqual(resets, [["systemctl", "reset-failed", "docker.service"]]
                             if reconciled and not read_error else [])
            if not reconciled:
                self.assertEqual(fixture.commands(), [])

    def test_display_retirement_exact_paths_backups_and_order(self):
        tasks = load(DISPLAY / "retire_system_units.yml")
        show, inspect, regular, stop, directory, backup, remove, reload, query, reset = tasks
        self.assertEqual(show["loop"], DISPLAY_UNITS)
        self.assertEqual(show["ansible.builtin.command"]["argv"],
                         ["systemctl", "show", "{{ item }}", "--property=LoadState", "--value"])
        self.assertEqual(inspect["loop"], DISPLAY_UNITS)
        self.assertEqual(inspect["ansible.builtin.stat"]["path"], "/etc/systemd/system/{{ item }}")
        self.assertEqual(regular["when"], "item.stat.exists")
        self.assertEqual(stop["ansible.builtin.systemd_service"], {
            "name": "{{ item.item }}", "scope": "system", "enabled": False, "state": "stopped"})
        self.assertEqual(stop["when"], "item.stdout != 'not-found'")
        self.assertEqual(directory["ansible.builtin.file"], {
            "path": "/var/lib/homelab/retired-display-services", "state": "directory",
            "owner": "root", "group": "root", "mode": "0700"})
        self.assertEqual(backup["ansible.builtin.copy"], {
            "remote_src": True, "src": "/etc/systemd/system/{{ item.item }}",
            "dest": "/var/lib/homelab/retired-display-services/{{ item.item }}",
            "owner": "root", "group": "root", "mode": "0600", "backup": True})
        self.assertEqual(remove["ansible.builtin.file"], {
            "path": "/etc/systemd/system/{{ item.item }}", "state": "absent"})
        for task in (backup, remove):
            self.assertEqual(task["loop"], "{{ display_legacy_files.results }}")
            self.assertEqual(task["when"], "item.stat.exists")
        self.assertEqual(reload["ansible.builtin.systemd_service"], {"daemon_reload": True, "scope": "system"})
        self.assertIn("selectattr('changed')", reload["when"])
        self.assertEqual(query["loop"], DISPLAY_UNITS)
        for task in tasks + list(flatten(load(DOCKER / "daemon_config.yml"))):
            self.assertNotIn("ignore_errors", task)
            self.assertNotIn("shell", task)
            self.assertNotIn("ansible.builtin.shell", task)
            if "ansible.builtin.command" in task:
                self.assertEqual(task["timeout"], 30)
        self.assertEqual(reset["when"], "item.stdout == 'failed' and item.rc == 0")

    def test_display_failure_reset_is_conditional_and_missing_units_are_safe(self):
        for states, read_error in ((dict(zip(DISPLAY_UNITS, ["failed", "inactive"])), False),
                                   (dict.fromkeys(DISPLAY_UNITS, "unknown"), False),
                                   (dict.fromkeys(DISPLAY_UNITS, "failed"), True)):
            with self.subTest(states=states, read_error=read_error):
                fixture = Fixture(display=True, states=states, read_error=read_error)
                self.run_fixture(fixture, success=not read_error)
                resets = [c for c in fixture.commands() if c[1] == "reset-failed"]
                self.assertEqual(resets, [] if read_error else [
                    ["systemctl", "reset-failed", unit] for unit in DISPLAY_UNITS if states[unit] == "failed"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        raise SystemExit(fake_command(sys.argv[2:]))
    unittest.main()
