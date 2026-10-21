#!/usr/bin/env python3
"""Stream fixed synthetic TLS packet metadata from the owned Linux guest only."""

import gzip
import hashlib
import ipaddress
import json
import re
import subprocess
import threading

from k3s_qualification import failure_classes


IMAGE = "docker.io/nicolaka/netshoot:v0.16@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70"
TARGETS = {"1.1.1.1", "1.0.0.1"}
FILTER = "ip and tcp port 443 and (host 1.1.1.1 or host 1.0.0.1)"
FLAGS = ["-tt", "-nn", "-l", "-K", "-S", "-i", "any", "-p", "-s", "128",
         "--immediate-mode", "-Z", "root", FILTER]
PACKET = re.compile(
    r"(?P<epoch>[0-9]{10}\.[0-9]{6}) (?P<interface>[a-zA-Z0-9_.-]{1,15}) +(?P<direction>In|Out) +IP "
    r"(?P<source>[0-9.]+)\.(?P<source_port>[0-9]{1,5}) > "
    r"(?P<destination>[0-9.]+)\.(?P<destination_port>[0-9]{1,5}): Flags \[(?P<flags>[FSRPAUEW.]+|none)\], "
    r"(?:seq (?P<sequence>[0-9]{1,10})(?::(?P<sequence_end>[0-9]{1,10}))?, )?"
    r"(?:ack (?P<ack>[0-9]{1,10}), )?win (?P<window>[0-9]{1,5}), "
    r"(?:options \[(?P<options>[^\]]+)\], )?length (?P<length>[0-9]{1,5})\n")
OPTION = re.compile(r"(?:mss [0-9]{1,5}|sackOK|TS val [0-9]{1,10} ecr [0-9]{1,10}|nop|"
                    r"wscale [0-9]{1,2}|eol|sack [1-4] (?:\{[0-9]{1,10}:[0-9]{1,10}\}){1,4})")
READY = "listening on any, link-type LINUX_SLL2 (Linux cooked v2), snapshot length 128 bytes\n"
BANNER = "tcpdump: verbose output suppressed, use -v[v]... for full protocol decode\n"
DLT_BANNER = "tcpdump: data link type LINUX_SLL2\n"
STATISTICS = {"captured": "captured", "received by filter": "received", "dropped by kernel": "dropped"}


def packet(raw, peers):
    if len(raw) > 4096:
        raise RuntimeError("packet metadata line exceeds contract")
    try:
        match = PACKET.fullmatch(raw.decode("ascii"))
    except UnicodeDecodeError:
        match = None
    if not match:
        raise RuntimeError("unrecognized packet metadata")
    item = {key: value for key, value in match.groupdict().items() if value is not None}
    options = item.pop("options", "")
    if options and any(not OPTION.fullmatch(option) for option in options.split(",")):
        raise RuntimeError("unrecognized TCP option metadata")
    for key in ("source_port", "destination_port", "sequence", "sequence_end", "ack", "window", "length"):
        if key in item:
            item[key] = int(item[key])
            if item[key] > (65535 if key in ("source_port", "destination_port", "window", "length") else 4294967295):
                raise RuntimeError("invalid TCP numeric metadata")
    if not all(1 <= item[key] <= 65535 for key in ("source_port", "destination_port")):
        raise RuntimeError("invalid TCP port")
    endpoints = [(item["source"], item["source_port"]), (item["destination"], item["destination_port"])]
    public = [endpoint for endpoint in endpoints if endpoint[0] in TARGETS]
    private = [endpoint for endpoint in endpoints if endpoint[0] not in TARGETS]
    if (len(public) != 1 or public[0][1] != 443 or len(private) != 1 or
            not any(ipaddress.IPv4Address(private[0][0]) in network for network in peers)):
        raise RuntimeError("foreign packet endpoint")
    return item


def identity(item, name, expected_id=None, expected_image=None):
    config, host = item["Config"], item["HostConfig"]
    if (not re.fullmatch(r"[a-f0-9]{64}", item["Id"]) or item["Name"] != "/" + name or
            config["Image"] != IMAGE or config["User"] != "0:0" or
            config["Entrypoint"] != ["tcpdump"] or config["Cmd"] != FLAGS or
            host["NetworkMode"] != "host" or host["Privileged"] or not host["ReadonlyRootfs"] or
            host["CapAdd"] != ["CAP_NET_RAW"] or host["CapDrop"] != ["ALL"] or
            host["SecurityOpt"] != ["no-new-privileges:true"] or host["LogConfig"]["Type"] != "none" or
            host.get("Binds") or host.get("Devices") or host.get("PortBindings") or
            host.get("PidMode") or item["Mounts"] or config.get("Volumes") or
            (expected_id is not None and item["Id"] != expected_id) or
            (expected_image is not None and item["Image"] != expected_image)):
        raise RuntimeError("TLS observer container identity refused")
    return {"container_id": item["Id"], "image_id": item["Image"],
            "configuration_sha256": hashlib.sha256(json.dumps(
                {key: item[key] for key in ("Config", "HostConfig", "Mounts")}, sort_keys=True).encode()).hexdigest()}


class Observer:
    def __init__(self, fixture, guest_addresses):
        fixture.identity()
        if fixture.command(["docker", "info", "--format", "{{.Name}}"]).decode().strip() != fixture.args.docker_server:
            raise RuntimeError("TLS observer requires the guarded private daemon")
        self.fixture = fixture
        self.name = fixture.args.name + "-tls-observer"
        if not re.fullmatch(r"qualification-[a-f0-9]{8}-tls-observer", self.name):
            raise RuntimeError("TLS observer fixture name refused")
        addresses = [ipaddress.IPv4Address(value) for value in guest_addresses]
        if not addresses or any(not address.is_private or address.is_loopback or address.is_link_local for address in addresses):
            raise RuntimeError("TLS observer guest addresses refused")
        self.peers = [ipaddress.ip_network(str(address) + "/32") for address in addresses]
        self.peers.append(ipaddress.ip_network("172.31.240.0/24"))
        self.ready = threading.Event()
        self.errors, self.stats, self.threads = [], {}, []
        self.status_failures = []
        self.container = self.child = self.output = self.created_id = None
        self.count = 0

    def inspect(self):
        return json.loads(self.fixture.command(["docker", "inspect", self.name]))[0]

    def read(self, stream, packets):
        try:
            while True:
                raw = stream.readline(4097)
                if not raw:
                    break
                if packets and raw == b"\n":
                    continue
                if self.errors:
                    continue
                try:
                    if packets:
                        item = packet(raw, self.peers)
                        self.output.write((json.dumps(item, sort_keys=True) + "\n").encode())
                        self.count += 1
                    elif raw == READY.encode():
                        if self.ready.is_set():
                            raise RuntimeError("duplicate capture ready banner")
                        self.ready.set()
                    elif raw not in (b"\n", BANNER.encode(), DLT_BANNER.encode()):
                        match = re.fullmatch(rb"([0-9]{1,12}) packet(s?) (captured|received by filter|dropped by kernel)\n", raw)
                        if (not match or bool(match[2]) != (int(match[1]) != 1) or
                                STATISTICS[match[3].decode()] in self.stats):
                            raise RuntimeError("unrecognized capture status")
                        self.stats[STATISTICS[match[3].decode()]] = int(match[1])
                except (RuntimeError, ValueError):
                    # Drain without retaining further input so owner shutdown cannot block on a full pipe.
                    self.errors.append("packet-format-refused" if packets else "capture-status-refused")
                    self.status_failures.append({"stream": "packets" if packets else "status", "bytes": len(raw),
                                                 "sha256": hashlib.sha256(raw).hexdigest(),
                                                 "classes": failure_classes(raw) if not packets else ["packet-format-refused"]})
                    self.ready.set()
        except BaseException as error:
            self.errors.append(type(error).__name__)
            self.ready.set()

    def check(self):
        if self.errors:
            raise RuntimeError("TLS observer refused metadata: " + self.errors[0])
        if self.child is None or self.child.poll() is not None:
            raise RuntimeError("TLS observer ended before owner stop")

    def start(self):
        created = self.fixture.command(["docker", "create", "--name", self.name, "--network=host", "--user=0:0",
                              "--read-only", "--cap-drop=ALL", "--cap-add=NET_RAW",
                              "--security-opt=no-new-privileges:true", "--log-driver=none",
                              "--entrypoint=tcpdump", IMAGE, *FLAGS])
        self.created_id = created.decode("ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", self.created_id):
            self.created_id = None
            raise RuntimeError("TLS observer creation identity missing")
        self.container = identity(self.inspect(), self.name, self.created_id)
        self.output = gzip.open(self.fixture.work / "tls-packets.jsonl.gz", "wb")
        self.child = subprocess.Popen(["docker", "start", "--attach", self.container["container_id"]],
                                      env=self.fixture.env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        for stream, packets in ((self.child.stdout, True), (self.child.stderr, False)):
            thread = threading.Thread(target=self.read, args=(stream, packets), daemon=True)
            self.threads.append(thread)
            thread.start()
        if not self.ready.wait(30):
            raise RuntimeError("TLS observer readiness not established")
        self.check()
        return self.container

    def stop(self):
        try:
            if self.container:
                measured = identity(self.inspect(), self.name, self.container["container_id"], self.container["image_id"])
                if measured != self.container:
                    raise RuntimeError("TLS observer configuration changed")
                if self.child is not None and self.child.poll() is None:
                    self.fixture.command(["docker", "kill", "--signal=SIGINT", self.container["container_id"]])
                if self.child is not None:
                    self.child.wait(timeout=10)
                    for thread in self.threads:
                        thread.join(timeout=10)
                    if any(thread.is_alive() for thread in self.threads):
                        raise RuntimeError("TLS observer readers did not stop")
                    if self.child.returncode != 0:
                        raise RuntimeError("TLS observer attach failed")
                if self.errors or set(self.stats) != {"captured", "received", "dropped"} or self.stats["dropped"] or self.stats["captured"] != self.count or not self.count:
                    raise RuntimeError("TLS observer metadata/counters incomplete")
                return {**self.container, "parsed_packets": self.count, **self.stats,
                        "payload_or_raw_lines_retained": False, "production_change": False}
        finally:
            cleanup_error = None
            if self.created_id:
                try:
                    self.fixture.command(["docker", "rm", "--force", self.created_id])
                except BaseException as error:
                    cleanup_error = error
            if self.child is not None and self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait()
            for thread in self.threads:
                thread.join(timeout=10)
            if any(thread.is_alive() for thread in self.threads):
                raise RuntimeError("TLS observer reader cleanup incomplete")
            if self.child is not None:
                for stream in (self.child.stdout, self.child.stderr):
                    stream.close()
            if self.output is not None:
                self.output.close()
            if self.created_id:
                if self.fixture.command(["docker", "ps", "-aq", "--no-trunc", "--filter", "id=" + self.created_id]).strip():
                    raise RuntimeError("TLS observer container cleanup incomplete")
            if cleanup_error is not None:
                raise cleanup_error
