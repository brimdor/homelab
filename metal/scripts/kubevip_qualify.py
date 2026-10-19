#!/usr/bin/env python3
"""Qualify the exact kube-vip candidate against an isolated synthetic k3s API."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time

import etcd_recovery as RECOVERY


IMAGE = "ghcr.io/kube-vip/kube-vip@sha256:26ead1e4f7ce486d1e60351181957f35ae54d30c11e8ae0a30d8e9ca1d8acb51"
INTERFACE = "qualify0"
VIP = "192.0.2.103"


def require_candidate(container, parent_id, scratch, run_id):
    host = container["HostConfig"]
    labels = container["Config"].get("Labels", {})
    if (labels.get("io.eaglepass.maintenance") != "103" or
            labels.get("io.eaglepass.recovery-run") != run_id or
            container["Config"]["Image"] != IMAGE or
            host.get("NetworkMode") != "container:" + parent_id or
            not host.get("ReadonlyRootfs") or host.get("Privileged") or
            host.get("CapDrop") != ["ALL"] or set(host.get("CapAdd") or []) != {"NET_ADMIN", "NET_RAW"} or
            host.get("SecurityOpt") != ["no-new-privileges:true"] or
            any(host.get(k) for k in ("PidMode", "UTSMode", "UsernsMode", "Devices", "DeviceRequests", "PortBindings")) or
            host.get("IpcMode") != "private" or host.get("RestartPolicy", {}).get("Name") != "no" or
            host.get("Memory") != 67108864 or host.get("NanoCpus") != 200000000 or host.get("PidsLimit") != 64 or
            host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev"}):
        raise RuntimeError("candidate isolation or ownership changed")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("RW") is not False or
            mounts[0].get("Source") != str(scratch / "kubeconfig") or
            mounts[0].get("Destination") != "/etc/kubernetes/admin.conf"):
        raise RuntimeError("candidate must mount only the synthetic read-only kubeconfig")


def check(parent_id, scratch, client, run_id):
    parent = RECOVERY.inspect(parent_id)
    RECOVERY.require_isolation(parent, scratch, run_id)
    if not parent["State"]["Running"] or parent["State"]["Pid"] <= 0:
        raise RuntimeError("owned synthetic server is not running")
    kubeconfig = scratch / "kubeconfig"
    metadata = kubeconfig.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
            stat.S_IMODE(metadata.st_mode) != 0o600 or
            "server: https://127.0.0.1:16443" not in kubeconfig.read_text()):
        raise RuntimeError("synthetic kubeconfig contract changed")
    before_images = set(RECOVERY.docker("image", "ls", "--no-trunc", "-q").stdout.decode().split())
    candidates = {}
    image_id = None
    namespace_fd = None
    interface_created = paused = False
    result = {"accepted": False, "image": IMAGE}
    try:
        # Pin the inspected private namespace so PID reuse cannot target another namespace.
        namespace_fd = os.open("/proc/" + str(parent["State"]["Pid"]) + "/ns/net", os.O_RDONLY | os.O_CLOEXEC)
        if os.fstat(namespace_fd).st_ino == os.stat("/proc/self/ns/net").st_ino:
            raise RuntimeError("refusing the host network namespace")
        namespace = ["nsenter", "--net=/proc/" + str(os.getpid()) + "/fd/" + str(namespace_fd), "--"]
        RECOVERY.docker("pull", IMAGE)
        image = json.loads(RECOVERY.docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image["Id"]
        if image["Architecture"] != "amd64" or image["Os"] != "linux" or image["Config"].get("Volumes"):
            raise RuntimeError("candidate platform or volume contract changed")
        # The dummy interface belongs to the already-proven private network namespace.
        RECOVERY.command(namespace + ["ip", "link", "add", INTERFACE, "type", "dummy"])
        interface_created = True
        RECOVERY.command(namespace + ["ip", "address", "add", "192.0.2.1/24", "dev", INTERFACE])
        RECOVERY.command(namespace + ["ip", "link", "set", INTERFACE, "up"])
        if RECOVERY.command(namespace + ["ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("synthetic namespace can route to production")
        for number, name in enumerate(("qualify-a", "qualify-b")):
            env = {"address": VIP, "vip_arp": "true", "port": "16443", "cp_enable": "true",
                   "svc_enable": "false", "vip_leaderelection": "true", "vip_interface": INTERFACE,
                   "vip_subnet": "32", "vip_leaseduration": "30", "vip_renewdeadline": "20",
                   "vip_retryperiod": "4", "vip_nodename": name, "cp_namespace": "kube-system",
                   "prometheus_server": "127.0.0.1:" + str(2113 + number)}
            arguments = ["create", "--network=container:" + parent_id, "--read-only", "--cap-drop=ALL",
                         "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--security-opt=no-new-privileges:true",
                         "--ipc=private", "--pids-limit=64", "--cpus=0.2", "--memory=64m",
                         "--label=io.eaglepass.maintenance=103", "--label=io.eaglepass.recovery-run=" + run_id,
                         "--mount=type=bind,source=" + str(kubeconfig) + ",target=/etc/kubernetes/admin.conf,readonly",
                         "--tmpfs=/tmp:rw,nosuid,nodev"]
            for key, value in env.items():
                arguments.append("--env=" + key + "=" + value)
            identity = RECOVERY.docker(*arguments, IMAGE, "manager").stdout.decode().strip()
            candidates[name] = identity
            require_candidate(RECOVERY.inspect(identity), parent_id, scratch, run_id)
            RECOVERY.docker("start", identity)

        def healthy(names):
            for name in names:
                container = RECOVERY.inspect(candidates[name])
                require_candidate(container, parent_id, scratch, run_id)
                if not container["State"]["Running"] or container["State"].get("OOMKilled"):
                    log = RECOVERY.docker("logs", candidates[name], check=False)
                    result["failed_candidate"] = {"name": name, "exit": container["State"].get("ExitCode"),
                                                   "log_sha256": hashlib.sha256(log.stdout + log.stderr).hexdigest()}
                    raise RuntimeError("synthetic candidate exited or exceeded its existing memory limit")

        def lease():
            response = RECOVERY.docker(*client, "get", "lease", "plndr-cp-lock", "-n=kube-system", "-o=json", check=False)
            return json.loads(response.stdout)["spec"] if response.returncode == 0 else None

        renewals = set()
        first_holder = None
        started = time.monotonic()
        while time.monotonic() - started < 45:
            healthy(candidates)
            current = lease()
            if current and current.get("holderIdentity"):
                if current["holderIdentity"] not in candidates or current["leaseDurationSeconds"] != 30:
                    raise RuntimeError("unexpected synthetic lease identity or timer")
                first_holder = first_holder or current["holderIdentity"]
                if current["holderIdentity"] != first_holder:
                    raise RuntimeError("synthetic leader changed without an injected failure")
                renewals.add(current["renewTime"])
            time.sleep(3)
        if not first_holder or len(renewals) < 3:
            raise RuntimeError("candidate did not demonstrate repeated stable lease renewal")
        RECOVERY.docker("pause", parent_id)
        paused = True
        time.sleep(10)
        RECOVERY.docker("unpause", parent_id)
        paused = False
        healthy(candidates)
        current = lease()
        if not current or current.get("holderIdentity") != first_holder:
            raise RuntimeError("candidate did not preserve leadership across a sub-deadline API stall")
        RECOVERY.docker("kill", "--signal=KILL", candidates[first_holder])
        remaining = next(name for name in candidates if name != first_holder)
        failover_start = time.monotonic()
        while True:
            healthy([remaining])
            current = lease()
            if current and current.get("holderIdentity") == remaining:
                break
            if time.monotonic() - failover_start > 60:
                raise RuntimeError("synthetic failover exceeded the declared sixty-second acceptance bound")
            time.sleep(2)
        addresses = json.loads(RECOVERY.command(namespace + ["ip", "-j", "address", "show", "dev", INTERFACE]).stdout)
        if not any(a.get("local") == VIP for link in addresses for a in link.get("addr_info", [])):
            raise RuntimeError("replacement leader did not retain the synthetic VIP")
        if RECOVERY.docker(*client, "get", "--raw=/readyz").stdout.strip() != b"ok":
            raise RuntimeError("synthetic API is not healthy after failover")
        result.update(accepted=True, image_id=image_id, stable_renewals=len(renewals),
                      initial_holder=first_holder, replacement_holder=remaining, api_stall_seconds=10,
                      failover_seconds=time.monotonic() - failover_start, vip=VIP,
                      production_credentials_used=False, physical_arp_not_proven=True)
    except Exception as error:
        result.update(accepted=False, error=str(error))
    finally:
        if paused:
            RECOVERY.docker("unpause", parent_id)
        for identity in candidates.values():
            require_candidate(RECOVERY.inspect(identity), parent_id, scratch, run_id)
            RECOVERY.docker("rm", "--force", "--volumes", identity)
            if RECOVERY.docker("inspect", identity, check=False).returncode == 0:
                raise RuntimeError("owned candidate remains after cleanup")
        if interface_created:
            RECOVERY.command(namespace + ["ip", "link", "delete", INTERFACE])
        if namespace_fd is not None:
            os.close(namespace_fd)
        if image_id and image_id not in before_images:
            if RECOVERY.docker("ps", "--all", "--quiet", "--filter=ancestor=" + image_id).stdout.strip():
                raise RuntimeError("new test image unexpectedly has another consumer")
            RECOVERY.docker("image", "rm", IMAGE)
            if RECOVERY.docker("image", "inspect", image_id, check=False).returncode == 0:
                raise RuntimeError("new test image remains after cleanup")
        result["candidate_cleanup"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=RECOVERY.run_identifier)
    parser.add_argument("--internal", action="store_true")
    args = parser.parse_args()
    if args.internal:
        receipt = RECOVERY.qualify(args.run_id, synthetic_check=check)
    else:
        dependency = Path(RECOVERY.__file__).read_text()
        source = Path(__file__).read_text()
        bootstrap = ("import types,sys; m=types.ModuleType('etcd_recovery');sys.modules[m.__name__]=m;"
                     "exec(compile(" + repr(dependency) + ",'<recovery>','exec'),m.__dict__);"
                     "exec(compile(" + repr(source) + ",'<qualification>','exec'))")
        remote = "python3 -B -c " + shlex.quote(bootstrap) + " --internal --run-id " + shlex.quote(args.run_id)
        response = RECOVERY.command([*RECOVERY.SSH, remote], check=False)
        try:
            receipt = json.loads(response.stdout)
        except (ValueError, UnicodeError):
            raise RuntimeError("remote qualification returned no sanitized receipt") from None
        if (response.returncode == 0) != (receipt.get("accepted") is True):
            raise RuntimeError("remote qualification exit disagrees with receipt")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt.get("accepted") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
