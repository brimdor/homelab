#!/usr/bin/env python3
"""Identity-bound Outline replication and one-shot, non-forced coordinated handoff."""

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import time
import zlib

import outline_valkey_recovery as recovery

common, protected, valkey = recovery.common, recovery.protected, recovery.valkey
require = recovery.require
RUN = "20261102-d77138391105"
MANIFEST = "e5877df8f4addec9bd741ed6528ad8210bda3dc726621ee6f029c6f97111e8fe"
DEST = "outline-valkey-0"
DEST_UID = "d2b57b9b-4ca1-4f3c-b264-6743e8348694"
DEST_CONTAINER = "containerd://628bae5a2c67987bab2dc1a4d98767ddd2f2af47dd5aaa1518ba47fa65da8a09"
CLAIM_UID = "944f20fc-32ff-4ec3-baff-cb588ac471f7"
STEPS = ("plan", "replica-intent", "replica-accepted", "failover-intent", "failover-accepted")


def digest(value):
    return hashlib.sha256(common.canonical(value)).hexdigest()


def records(directory):
    found = []
    for step in STEPS:
        path = directory / (step + ".json")
        if not path.exists():
            break
        meta = protected.protected_file(path)
        require(meta.st_nlink == 1 and meta.st_size <= 65536, "journal file contract changed")
        record = json.loads(path.read_bytes())
        require(set(record) == {"step", "previous", "data"} and record["step"] == step and
                record["previous"] == (digest(found[-1]) if found else None), "journal chain changed")
        found.append(record)
    require({p.name for p in directory.iterdir()} == {r["step"] + ".json" for r in found} | {"lock"},
            "journal has gaps or unknown files")
    return found


def journal_local(operation, payload):
    recovery.configure_profile("growlithe-20261102")
    point = recovery.point_path(RUN)
    recovery.verify_point(point, MANIFEST)
    return journal_directory(point / "handoff", operation, payload)


def journal_directory(directory, operation, payload):
    require(operation in ("read", "append"), "unknown journal operation")
    if not directory.exists():
        require(operation == "append" and payload["step"] == "plan", "handoff plan absent")
        directory.mkdir(mode=0o700)
        parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    meta = directory.lstat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o700,
            "journal directory changed")
    descriptor = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        require(protected.protected_file(directory / "lock").st_nlink == 1, "journal lock changed")
        result = records(directory)
        if operation == "append":
            require(len(result) < len(STEPS) and payload["step"] == STEPS[len(result)] and
                    payload["previous"] == (digest(result[-1]) if result else None),
                    "existing intent or stale journal; observe original outcome, never replay")
            protected.write_json(directory / (payload["step"] + ".json"), payload)
            result = records(directory)
        return result
    finally:
        os.close(descriptor)


def journal(operation="read", payload=None):
    code = "import base64,sys,types,zlib;"
    for name in ("etcd_recovery", "mariadb_recovery", "valkey_recovery", "outline_valkey_recovery"):
        raw = base64.b64encode(zlib.compress(Path(__file__).with_name(name + ".py").read_bytes())).decode()
        code += "m=types.ModuleType(" + repr(name) + ");sys.modules[" + repr(name) + "]=m;exec(zlib.decompress(base64.b64decode(" + repr(raw) + ")),m.__dict__);"
    raw = base64.b64encode(zlib.compress(Path(__file__).read_bytes())).decode()
    code += "m=types.ModuleType('handoff');exec(zlib.decompress(base64.b64decode(" + repr(raw) + ")),m.__dict__);print(m.json.dumps(m.journal_local(" + repr(operation) + ",m.json.loads(sys.argv[1]))))"
    ssh = [*common.SSH[:-1], "root@" + common.RECEIVERS["cyndaquil"]["address"]]
    command = shlex.join(["python3", "-B", "-c", code, json.dumps(payload)])
    require(len(command.encode()) < 120000, "journal transport exceeds reviewed argument bound")
    return json.loads(common.command([*ssh, command]).stdout)


class Native:
    def get(self, kind, name, namespace="outline"):
        args = [self.client, "get", kind, name, "-o=json"]
        if namespace:
            args += ["-n", namespace]
        return json.loads(common.command(args).stdout)

    def __init__(self):
        self.client = os.environ.get("KUBECTL", "kubectl")
        recovery.configure_profile("growlithe-20261102")

    def cli(self, side, *arguments):
        pod, container = (recovery.POD, "redis") if side == "source" else (DEST, "main")
        result = common.command([self.client, "exec", "-n=outline", pod, "-c=" + container,
                                 "--", "valkey-cli", "--raw", *map(str, arguments)]).stdout
        require(not result.startswith((b"ERR ", b"READONLY ", b"NOAUTH ", b"LOADING ")), "native Valkey command refused")
        return result.decode().strip()

    def info(self, side):
        return valkey.info(self.cli(side, "INFO", "server", "replication", "persistence", "cluster").encode())

    def identity(self):
        require(self.get("namespace", "kube-system", None)["metadata"]["uid"] == common.CLUSTER_UID, "wrong cluster")
        result = {}
        for name, expected_uid in ((recovery.POD, recovery.POD_UID), (DEST, DEST_UID),
                                   ("outline-postgres-0", None)):
            pod = self.get("pod", name)
            require(not pod["metadata"].get("deletionTimestamp") and
                    (expected_uid is None or pod["metadata"]["uid"] == expected_uid), "Pod identity changed")
            statuses = {c["name"]: c for c in pod["status"]["containerStatuses"]}
            require(all(c["ready"] and c["restartCount"] == 0 and c.get("state", {}).get("running") for c in statuses.values()),
                    "runtime not unchanged and ready")
            if name == recovery.POD:
                require(set(statuses) == {"main", "redis"} and
                        statuses["redis"]["containerID"] == "containerd://" + recovery.CONTAINER and
                        statuses["redis"]["imageID"] == recovery.IMAGE and
                        all(statuses["main"][k] == v for k, v in recovery.MAIN.items()), "source runtime changed")
            if name == DEST:
                require(set(statuses) == {"main"} and statuses["main"]["containerID"] == DEST_CONTAINER and
                        statuses["main"]["imageID"] == recovery.IMAGE and
                        not any("nfs" in v for v in pod["spec"].get("volumes", [])), "destination runtime or storage changed")
            address = str(ipaddress.IPv4Address(pod["status"]["podIP"]))
            require(address.startswith("10.0."), "unexpected Pod address")
            result[name] = {"uid": pod["metadata"]["uid"], "ip": address, "spec_sha256": digest(pod["spec"]),
                            "containers": {n: {k: c[k] for k in ("containerID", "imageID")} for n, c in statuses.items()}}
        for name in ("outline", "outline-valkey-data"):
            claim = self.get("pvc", name)
            require(claim["status"]["phase"] == "Bound" and claim["spec"]["storageClassName"] == "standard-rwo" and
                    (name != "outline-valkey-data" or claim["metadata"]["uid"] == CLAIM_UID), "claim changed")
            pv = self.get("pv", claim["spec"]["volumeName"], None)
            require(pv["spec"]["claimRef"]["uid"] == claim["metadata"]["uid"] and
                    "csi" in pv["spec"] and "nfs" not in pv["spec"], "volume backend changed")
            result[name + "-claim"] = {"uid": claim["metadata"]["uid"], "spec": claim["spec"],
                                       "pv_uid": pv["metadata"]["uid"], "pv_spec_sha256": digest(pv["spec"])}
        for kind, name in (("deployment", "outline"), ("statefulset", "outline-postgres"),
                           ("statefulset", "outline-valkey"), ("service", "outline-valkey")):
            resource = self.get(kind, name)
            result[kind + "/" + name] = {"uid": resource["metadata"]["uid"], "spec_sha256": digest(resource["spec"])}
        endpoints = json.loads(common.command(
            [self.client, "get", "endpointslices", "-n=outline", "-l=kubernetes.io/service-name=outline-valkey", "-o=json"]).stdout)
        actual = [e for s in endpoints["items"] for e in s["endpoints"] if e.get("conditions", {}).get("ready")]
        require(len(actual) == 1 and actual[0]["addresses"] == [result[DEST]["ip"]] and
                actual[0]["targetRef"]["uid"] == DEST_UID, "destination endpoint changed")
        return result


def persistence_ready(info):
    return all(info.get(k) == v for k, v in {"loading": "0", "aof_enabled": "1", "aof_last_write_status": "ok",
               "aof_last_bgrewrite_status": "ok", "aof_rewrite_in_progress": "0", "aof_rewrite_scheduled": "0"}.items())


def stable(backend, plan):
    require(backend.identity() == plan["identity"], "bound Kubernetes or storage identity changed")
    for side in ("source", "destination"):
        info = backend.info(side)
        require(info.get("run_id") == plan["run_ids"][side] and info.get("valkey_version") == "9.1.3" and
                info.get("cluster_enabled") == "0", "native process changed")


def observe(backend, plan, promoted=False, fence=None):
    source, destination = backend.info("source"), backend.info("destination")
    require(all(v.get("run_id") == plan["run_ids"][side] for side, v in
                (("source", source), ("destination", destination))), "native process changed")
    if not persistence_ready(destination):
        return False
    primary, replica = (destination, source) if promoted else (source, destination)
    primary_ip = plan["destination_ip"] if promoted else plan["source_ip"]
    replica_ip = plan["source_ip"] if promoted else plan["destination_ip"]
    if not (primary.get("role") == "master" and replica.get("role") == "slave" and
            primary.get("master_failover_state") == "no-failover" and replica.get("master_failover_state") == "no-failover" and
            replica.get("master_host") == primary_ip and replica.get("master_port") == "6379" and
            replica.get("master_link_status") == "up" and replica.get("master_sync_in_progress") == "0" and
            primary.get("master_replid") == replica.get("master_replid") and
            int(replica.get("slave_repl_offset", "-1")) >= int(primary["master_repl_offset"]) and
            primary.get("connected_slaves") == "1"):
        return False
    peers = [dict(pair.split("=", 1) for pair in v.split(",")) for k, v in primary.items() if re.fullmatch(r"slave\d+", k)]
    if not (len(peers) == 1 and peers[0].get("ip") == replica_ip and peers[0].get("state") == "online"):
        return False
    if promoted:
        require(destination.get("master_replid2") == fence["replid"] and
                int(destination.get("second_repl_offset", "-1")) >= fence["offset"], "replication history discontinuity")
    # Valkey rotates an unused primary history when its first replication backlog is created.
    return {"source_role": source["role"], "destination_role": destination["role"],
            "primary_replid": primary["master_replid"], "observed_offset": int(primary["master_repl_offset"]),
            "destination_persistence_healthy": True, "run_ids_unchanged": True}


def wait_for(backend, plan, promoted=False, fence=None):
    deadline = time.monotonic() + 90
    while True:
        result = observe(backend, plan, promoted, fence)
        if result:
            stable(backend, plan)
            return result
        require(time.monotonic() < deadline, "transition unproved; preserve both stores and original intent; no replay")
        time.sleep(1)


def append(entries, step, data, journal_fn=journal):
    return journal_fn("append", {"step": step, "previous": digest(entries[-1]) if entries else None, "data": data})


def execute(mode, backend, journal_fn=journal):
    if mode == "plan":
        recovery.source()
        identity = backend.identity()
        source, dest = backend.info("source"), backend.info("destination")
        require(source.get("role") == dest.get("role") == "master" and source.get("connected_slaves") ==
                dest.get("connected_slaves") == "0" and persistence_ready(dest) and backend.cli("destination", "DBSIZE") == "0",
                "source or empty persistent destination prerequisite changed")
        clients = backend.cli("destination", "CLIENT", "LIST").splitlines()
        require(all("cmd=client|list" in c for c in clients), "destination has application clients")
        config = backend.cli("source", "CONFIG", "GET", "protected-mode").splitlines()
        require(config == ["protected-mode", "no"], "source access configuration changed")
        for info in (source, dest):
            require(info.get("valkey_version") == "9.1.3" and info.get("cluster_enabled") == "0" and
                    re.fullmatch(r"[0-9a-f]{40}", info.get("run_id", "")), "native profile changed")
        plan = {"identity": identity, "source_ip": identity[recovery.POD]["ip"], "destination_ip": identity[DEST]["ip"],
                "run_ids": {"source": source["run_id"], "destination": dest["run_id"]},
                "original_replid": source["master_replid"], "recovery_manifest": MANIFEST}
        return append([], "plan", plan, journal_fn)
    entries = journal_fn()
    require(entries and entries[0]["step"] == "plan", "protected plan absent")
    plan = entries[0]["data"]
    require(plan["recovery_manifest"] == MANIFEST, "protected recovery changed")
    stable(backend, plan)
    if mode == "replicate":
        require(len(entries) <= 3, "failover already dispatched; do not reconfigure replicas")
        if len(entries) == 1:
            source, dest = backend.info("source"), backend.info("destination")
            require(source["role"] == dest["role"] == "master" and dest["connected_slaves"] == "0" and
                    backend.cli("destination", "DBSIZE") == "0" and persistence_ready(dest), "replication precondition changed")
            entries = append(entries, "replica-intent", {"target_ip": plan["source_ip"]}, journal_fn)
            stable(backend, plan)
            require(backend.cli("destination", "REPLICAOF", plan["source_ip"], "6379") == "OK", "replication dispatch uncertain")
        result = wait_for(backend, plan)
        return append(entries, "replica-accepted", result, journal_fn) if len(entries) == 2 else entries
    require(mode == "failover" and len(entries) >= 3, "replication not accepted")
    if len(entries) == 3:
        observed = observe(backend, plan)
        require(observed and observed["primary_replid"] == entries[2]["data"]["primary_replid"],
                "replica or accepted synchronization history changed")
        info = backend.info("source")
        fence = {"replid": info["master_replid"], "offset": int(info["master_repl_offset"]),
                 "target_ip": plan["destination_ip"], "timeout_ms": 15000, "force": False}
        entries = append(entries, "failover-intent", fence, journal_fn)
        stable(backend, plan)
        require(backend.cli("source", "FAILOVER", "TO", plan["destination_ip"], "6379", "TIMEOUT", "15000") == "OK",
                "failover dispatch uncertain; observe original intent, never replay")
    fence = entries[3]["data"]
    result = wait_for(backend, plan, True, fence)
    return append(entries, "failover-accepted", result, journal_fn) if len(entries) == 4 else entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "replicate", "failover"))
    args = parser.parse_args()
    os.umask(0o077)
    result = execute(args.mode, Native())
    print(json.dumps({"phase": result[-1]["step"], "journal_head": digest(result[-1]), "records": len(result)}))


if __name__ == "__main__":
    main()
