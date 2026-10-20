#!/usr/bin/env python3
"""Guard production identity and reject incomplete synthetic test evidence."""

import copy
import os
import re
import signal
import subprocess
import sys
import threading
from unittest.mock import patch
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cilium_qualification as qualification


class QualificationGuards(unittest.TestCase):
    def test_inherited_resolver_requires_one_private_nonloopback_ipv4_upstream(self):
        self.assertEqual(qualification.inherited_resolver(
            "nameserver 172.31.240.1\n# ExtServers: [host(192.168.5.1)]\n"), "192.168.5.1")
        for line in ("nameserver 127.0.0.11", "# ExtServers: [host(127.0.0.1)]",
                     "# ExtServers: [host(0.0.0.0)]", "# ExtServers: [host(8.8.8.8)]",
                     "# ExtServers: [host(192.168.5.1) host(192.168.5.2)]",
                     "# ExtServers: [host(192.168.5.999)]"):
            with self.subTest(line=line), self.assertRaises((RuntimeError, ValueError)):
                qualification.inherited_resolver(line)

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

    def test_filter_selects_scenarios_under_exact_test_names(self):
        for name in qualification.TESTS:
            self.assertIsNotNone(re.search(qualification.TEST_FILTER, name + "/pod-to-pod"))
            self.assertIsNone(re.search(qualification.TEST_FILTER, name + "-other/pod-to-pod"))
        self.assertIsNone(re.search(qualification.TEST_FILTER, "unrelated/pod-to-pod"))

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
        self.assertTrue(all(stream.closed for stream in (children[0].stdin, children[0].stdout, children[0].stderr)))
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

    def test_hubble_forward_binds_loopback_and_reaps_after_failure(self):
        children = []
        real_popen = subprocess.Popen

        def start(command, **kwargs):
            self.assertIn("--address=127.0.0.1", command)
            port = command[-2].split(":")[0]
            script = ("import socket,sys,signal; s=socket.socket(); "
                      "s.bind(('127.0.0.1',int(sys.argv[1]))); s.listen(); "
                      "print('Forwarding from 127.0.0.1:'+sys.argv[1]+' -> 4245',flush=True); signal.pause()")
            child = real_popen([sys.executable, "-c", script, port], **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as directory:
            runner = qualification.Qualification.__new__(qualification.Qualification)
            runner.work, runner.env = Path(directory), {**os.environ, "KUBECONFIG": "synthetic"}
            runner.context, runner.args = "synthetic", SimpleNamespace(kubectl="kubectl")
            with patch.object(qualification.subprocess, "Popen", side_effect=start):
                with self.assertRaisesRegex(RuntimeError, "suite failed"):
                    with runner.hubble_forward() as address:
                        self.assertTrue(address.startswith("127.0.0.1:"))
                        raise RuntimeError("suite failed")
            self.assertFalse((runner.work / "hubble-forward.log").exists())
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.kill(children[0].pid, 0)


if __name__ == "__main__":
    unittest.main()
