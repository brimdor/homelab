#!/usr/bin/env python3
"""Guard production identity and reject incomplete synthetic test evidence."""

import copy
import os
import signal
import subprocess
import sys
import threading
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

import cilium_qualification as qualification


class QualificationGuards(unittest.TestCase):
    def setUp(self):
        self.name = "qualification-1234abcd"
        self.config = {"current-context": "k3d-" + self.name, "clusters": [
            {"cluster": {"server": "https://127.0.0.1:63443"}}]}
        self.namespace = {"metadata": {"uid": "synthetic-cluster"}}
        self.nodes = {"items": [{"metadata": {"name": "k3d-" + self.name + suffix},
                                  "status": {"nodeInfo": {"kubeletVersion": "v1.33.6+k3s1"}}}
                                 for suffix in ("-server-0", "-agent-0", "-agent-1")]}

    def test_exact_synthetic_cluster(self):
        self.assertEqual(qualification.require_cluster(self.config, self.name, self.namespace, self.nodes),
                         "synthetic-cluster")

    def test_reject_other_api_origins_and_contexts(self):
        for address in ("https://10.0.20.50:6443", "http://127.0.0.1:6443", "https://localhost:6443", "https://127.0.0.1:0"):
            config = copy.deepcopy(self.config)
            config["clusters"][0]["cluster"]["server"] = address
            with self.assertRaises(RuntimeError):
                qualification.require_cluster(config, self.name, self.namespace, self.nodes)
        config = {**self.config, "current-context": "production"}
        with self.assertRaises(RuntimeError):
            qualification.require_cluster(config, self.name, self.namespace, self.nodes)

    def test_reject_production_uid(self):
        with self.assertRaises(RuntimeError):
            qualification.require_cluster(self.config, self.name,
                                          {"metadata": {"uid": qualification.PRODUCTION_UID}}, self.nodes)

    def test_reject_other_nodes_or_version(self):
        for field, value in (("name", "production-node"), ("version", "v1.34.0+k3s1")):
            nodes = copy.deepcopy(self.nodes)
            if field == "name":
                nodes["items"][0]["metadata"]["name"] = value
            else:
                nodes["items"][0]["status"]["nodeInfo"]["kubeletVersion"] = value
            with self.assertRaises(RuntimeError):
                qualification.require_cluster(self.config, self.name, self.namespace, nodes)

    def test_reject_remote_or_unowned_docker_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            for host in ("tcp://127.0.0.1:2375", "unix:///var/run/docker.sock"):
                with self.assertRaises(RuntimeError):
                    qualification.require_root(root, self.name, host)

    def test_cancellation_interrupts_communicate_and_reaps_owned_child(self):
        children, timers = [], []
        real_popen = subprocess.Popen

        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            timer = threading.Timer(0.2, os.kill, args=(os.getpid(), signal.SIGTERM))
            timers.append(timer)
            timer.start()
            return child

        previous = signal.signal(signal.SIGTERM, qualification.interrupted)
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner = qualification.Qualification.__new__(qualification.Qualification)
                runner.work, runner.env, runner.count = Path(directory), os.environ.copy(), 0
                with patch.object(qualification.subprocess, "Popen", side_effect=start):
                    with self.assertRaisesRegex(RuntimeError, "qualification interrupted"):
                        runner.command([sys.executable, "-c", "import time; time.sleep(10)"], private=True)
        finally:
            for timer in timers:
                timer.cancel()
                timer.join()
            signal.signal(signal.SIGTERM, previous)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.kill(children[0].pid, 0)

    def test_require_executed_allow_deny_and_l7_cases(self):
        cases = ''.join('<testcase name="' + name + '"/>' for name in qualification.TESTS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suite.xml"
            path.write_text('<testsuite>' + cases + '</testsuite>')
            self.assertEqual(qualification.require_results(path)["executed_cases"], 4)
            for value in ('<testsuite/>', '<testsuite><testcase name="no-policies"/></testsuite>',
                          '<testsuite>' + cases.replace('/>', '><skipped/></testcase>', 1) + '</testsuite>',
                          '<testsuite>' + cases.replace('/>', '><failure/></testcase>', 1) + '</testsuite>'):
                path.write_text(value)
                with self.assertRaises(RuntimeError):
                    qualification.require_results(path)


if __name__ == "__main__":
    unittest.main()
