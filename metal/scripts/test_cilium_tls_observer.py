#!/usr/bin/env python3
"""Exercise packet privacy, exact ownership and observer teardown refusal."""

import copy
import gzip
import io
import ipaddress
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cilium_tls_observer as o


LINE = (b"1792587900.123456 eth0 Out IP 192.168.5.2.30123 > 1.0.0.1.443: Flags [S], "
        b"seq 4294967295, win 64240, options [mss 1460,sackOK,TS val 123 ecr 0,nop,wscale 7], length 0\n")


class Guards(unittest.TestCase):
    def item(self):
        return {"Id": "a" * 64, "Name": "/qualification-1234abcd-tls-observer", "Image": "sha256:" + "b" * 64,
                "Config": {"Image": o.IMAGE, "User": "0:0", "Entrypoint": ["tcpdump"], "Cmd": o.FLAGS},
                "HostConfig": {"NetworkMode": "host", "Privileged": False, "ReadonlyRootfs": True,
                               "CapAdd": ["CAP_NET_RAW"], "CapDrop": ["ALL"],
                               "SecurityOpt": ["no-new-privileges:true"], "LogConfig": {"Type": "none"}},
                "Mounts": []}

    def observer(self, directory):
        fixture = SimpleNamespace(identity=Mock(), args=SimpleNamespace(name="qualification-1234abcd", docker_server="colima-q"),
                                  command=Mock(return_value=b"colima-q\n"), work=Path(directory), env={})
        return o.Observer(fixture, ["192.168.5.2"])

    def test_numeric_only_packet_and_refusals(self):
        peers = [ipaddress.ip_network("192.168.5.2/32")]
        item = o.packet(LINE, peers)
        self.assertEqual(item["sequence"], 4294967295)
        self.assertNotIn("options", item)
        for old, new in ((b"192.168.5.2", b"192.168.5.3"), (b"1.0.0.1", b"8.8.8.8"),
                         (b".443:", b".80:"), (b"30123", b"65536"), (b"4294967295", b"4294967296"),
                         (b"wscale 7", b"secret=do-not-save"), (b"length 0", b"length 0: PRIVATE_PAYLOAD"),
                         (b"Out", b"unknown"), (b"1792587900.123456", b"nan")):
            with self.subTest(new=new), self.assertRaises((RuntimeError, ValueError)):
                o.packet(LINE.replace(old, new), peers)
        for raw in (LINE[:-1], LINE + b"PRIVATE", b"\xff", b"X" * 4097):
            with self.assertRaises(RuntimeError):
                o.packet(raw, peers)
        reply = (b"1792587900.123457 eth0 In IP 1.0.0.1.443 > 192.168.5.2.30123: "
                 b"Flags [P.], seq 123:140, ack 22, win 12, length 17\n")
        self.assertEqual(o.packet(reply, peers)["length"], 17)

    def test_exact_minimal_container_configuration(self):
        item = self.item()
        accepted = o.identity(item, item["Name"][1:])
        for section, key, value in (("Config", "Image", "other"), ("Config", "Cmd", ["-w", "dump"]),
                                    ("HostConfig", "Privileged", True), ("HostConfig", "CapAdd", ["NET_ADMIN"]),
                                    ("HostConfig", "LogConfig", {"Type": "json-file"}),
                                    ("HostConfig", "Binds", ["/private:/private"]),
                                    ("HostConfig", "PidMode", "host"), ("Config", "User", "1000")):
            changed = copy.deepcopy(item)
            changed[section][key] = value
            with self.assertRaises(RuntimeError):
                o.identity(changed, item["Name"][1:])
        with self.assertRaises(RuntimeError):
            o.identity(item, item["Name"][1:], "foreign", accepted["image_id"])

    def test_streams_retain_no_unclassified_output(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(directory)
            path = Path(directory) / "typed.gz"
            observer.output = gzip.open(path, "wb")
            observer.read(io.BytesIO(LINE + b"\n"), True)
            observer.read(io.BytesIO(o.BANNER.encode() + o.READY.encode() + b"1 packet captured\n"
                                    b"2 packets received by filter\n0 packets dropped by kernel\n"), False)
            self.assertEqual(observer.stats, {"captured": 1, "received": 2, "dropped": 0})
            self.assertTrue(observer.ready.is_set())
            observer.read(io.BytesIO(b"PRIVATE_TOKEN\n"), True)
            observer.output.close()
            self.assertNotIn("PRIVATE_TOKEN", json.dumps(observer.errors))
            self.assertNotIn(b"PRIVATE_TOKEN", gzip.decompress(path.read_bytes()))
            self.assertEqual(observer.count, 1)
            with self.assertRaises(RuntimeError):
                observer.check()

    def test_counter_failure_still_removes_exact_container_and_reaps(self):
        with tempfile.TemporaryDirectory() as directory:
            for stats in ({"captured": 2, "received": 2, "dropped": 0},
                          {"captured": 1, "received": 1, "dropped": 1}, {}):
                observer = self.observer(directory)
                observer.container = o.identity(self.item(), observer.name)
                observer.created_id = observer.container["container_id"]
                observer.count, observer.stats = 1, stats
                observer.child = Mock(returncode=0, stdout=io.BytesIO(), stderr=io.BytesIO())
                observer.child.poll.return_value = 0
                observer.fixture.command.return_value = b""
                with patch.object(observer, "inspect", return_value=self.item()), self.assertRaises(RuntimeError):
                    observer.stop()
                observer.child.wait.assert_called_once_with(timeout=10)
                self.assertIn(unittest.mock.call(["docker", "rm", "--force", "a" * 64]),
                              observer.fixture.command.call_args_list)
                self.assertTrue(observer.child.stdout.closed)

    def test_start_attach_uses_private_pipes_and_no_persistent_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(directory)
            observer.fixture.command.reset_mock()
            observer.fixture.command.side_effect = [b"a" * 64, json.dumps([self.item()]).encode(),
                                                     json.dumps([self.item()]).encode(), b"", b""]
            child = Mock(returncode=0, stdout=io.BytesIO(LINE), stderr=io.BytesIO(
                o.READY.encode() + b"1 packet captured\n1 packet received by filter\n0 packets dropped by kernel\n"))
            child.poll.return_value = None
            with patch.object(o.subprocess, "Popen", return_value=child) as launch:
                observer.start()
                for thread in observer.threads:
                    thread.join()
                child.poll.return_value = 0
                result = observer.stop()
            self.assertEqual(result["parsed_packets"], 1)
            self.assertIs(launch.call_args.kwargs["stdin"], o.subprocess.DEVNULL)
            self.assertIs(launch.call_args.kwargs["stdout"], o.subprocess.PIPE)
            create = observer.fixture.command.call_args_list[0].args[0]
            self.assertIn("--log-driver=none", create)
            self.assertNotIn("--privileged", create)


if __name__ == "__main__":
    unittest.main()
