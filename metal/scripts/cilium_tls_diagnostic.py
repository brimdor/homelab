#!/usr/bin/env python3
"""One fixed TLS sample inside the guarded, disposable K3s baseline fixture."""

import datetime
import hashlib
import ipaddress
import json
import re

from k3s_qualification import CommandFailure, failure_classes


NAMESPACE = "cilium-test-1"
IMAGE = "quay.io/cilium/alpine-curl:v1.10.0@sha256:913e8c9f3d960dde03882defa0edd3a919d529c2eb167caa7f54194528bde364"
TARGETS = ("1.1.1.1", "1.0.0.1")
FIELDS = ("response_code", "ssl_verify_result", "time_connect", "time_appconnect",
          "time_starttransfer", "time_total", "local_ip", "local_port", "remote_ip", "remote_port")
FORMAT = " ".join("%{" + field + "}" for field in FIELDS) + "\n"
POLICY = {"apiVersion": "cilium.io/v2", "kind": "CiliumNetworkPolicy",
          "metadata": {"name": "all-ingress-deny", "namespace": NAMESPACE},
          "spec": {"endpointSelector": {}, "ingress": [{}]}}


def observation(raw, expected_ip):
    # The command emits only this fixed numeric tuple, never arbitrary curl output.
    parts = raw.decode("ascii").split()
    if expected_ip not in TARGETS or len(parts) != len(FIELDS):
        raise RuntimeError("incomplete or foreign TLS observation")
    for index in (0, 1, 7, 9):
        if not re.fullmatch(r"[0-9]{1,5}", parts[index]):
            raise RuntimeError("invalid TLS numeric field")
    for index in (2, 3, 4, 5):
        if not re.fullmatch(r"[0-9]{1,2}\.[0-9]{6}", parts[index]):
            raise RuntimeError("invalid TLS timing field")
    result = dict(zip(FIELDS, parts))
    for field in FIELDS[:2] + ("local_port", "remote_port"):
        result[field] = int(result[field])
    for field in FIELDS[2:6]:
        result[field] = float(result[field])
    local = ipaddress.ip_address(result["local_ip"])
    if (local.version != 4 or not local.is_private or local.is_loopback or
            result["remote_ip"] != expected_ip or result["remote_port"] != 443 or
            not 1 <= result["local_port"] <= 65535 or result["response_code"] != 301 or
            result["ssl_verify_result"] != 0 or not
            0 < result["time_connect"] <= result["time_appconnect"] <=
            result["time_starttransfer"] <= result["time_total"] <= 10):
        raise RuntimeError("TLS observation refused")
    return result


def clients(pods, nodes):
    result = {}
    for pod in pods:
        meta, spec, status = pod["metadata"], pod["spec"], pod["status"]
        name = meta.get("labels", {}).get("name")
        if name not in ("client", "client2", "client3"):
            continue
        containers = status.get("containerStatuses", [])
        if (name in result or not meta.get("uid") or meta.get("deletionTimestamp") or
                meta.get("namespace") != NAMESPACE or spec.get("hostNetwork") or
                spec.get("nodeName") not in nodes or not spec["nodeName"].endswith(("-agent-0", "-agent-1")) or
                len(spec.get("containers", [])) != 1 or spec["containers"][0]["image"] != IMAGE or
                spec["containers"][0]["name"] != name or len(containers) != 1 or
                containers[0]["name"] != name or not containers[0]["ready"] or
                set(containers[0].get("state", {})) != {"running"} or
                not containers[0].get("containerID") or status.get("phase") != "Running"):
            raise RuntimeError("synthetic TLS client identity refused")
        address = ipaddress.ip_address(status["podIP"])
        if address.version != 4 or address not in ipaddress.ip_network("10.0.0.0/8"):
            raise RuntimeError("synthetic TLS client address refused")
        result[name] = {"pod": meta["name"], "uid": meta["uid"], "node": spec["nodeName"],
                        "container": name, "container_id": containers[0]["containerID"],
                        "image_id": containers[0]["imageID"], "restarts": containers[0]["restartCount"],
                        "ip": str(address),
                        "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()}
    if (set(result) != {"client", "client2", "client3"} or
            any(len({p[key] for p in result.values()}) != 3 for key in ("uid", "container_id", "ip"))):
        raise RuntimeError("exactly three synthetic TLS clients required")
    return result


def require_policy(item, uid):
    meta = item.get("metadata", {})
    if (item.get("apiVersion") != POLICY["apiVersion"] or item.get("kind") != POLICY["kind"] or
            not uid or meta.get("uid") != uid or meta.get("deletionTimestamp") or
            meta.get("name") != POLICY["metadata"]["name"] or meta.get("namespace") != NAMESPACE or
            item.get("spec") != POLICY["spec"]):
        raise RuntimeError("synthetic TLS policy identity refused")


def run(fixture):
    fixture.identity()
    if any(version != "v1.33.6+k3s1" for version in fixture.versions.values()):
        raise RuntimeError("TLS diagnostic requires the unchanged baseline")
    for resource in ("networkpolicies", "ciliumnetworkpolicies"):
        if fixture.kubectl("get", resource, "-n", NAMESPACE)["items"]:
            raise RuntimeError("TLS diagnostic has preexisting policy")
    if fixture.kubectl("get", "ciliumclusterwidenetworkpolicies")["items"]:
        raise RuntimeError("TLS diagnostic has preexisting cluster policy")

    def current():
        fixture.identity()
        return clients(fixture.kubectl("get", "pods", "-n", NAMESPACE)["items"], fixture.versions)

    original = current()
    result = {"planned_observations": 36, "observations": [], "client_identities": original,
              "full_ha_acceptance": False, "production_change": False, "upgrade_restore_history": False}
    path = fixture.work / "tls-diagnostic.json"
    for phase in ("no-policy", "all-ingress-deny"):
        uid = None
        if phase == "all-ingress-deny":
            created = fixture.kubectl("create", "-f", "-", data=json.dumps(POLICY).encode())
            uid = created["metadata"]["uid"]
            require_policy(created, uid)
            result["policy_uid"] = uid
        for round_number in range(3):
            for name in sorted(original):
                for target in TARGETS:
                    if current() != original:
                        raise RuntimeError("TLS client identity changed during diagnostic")
                    if uid:
                        require_policy(fixture.kubectl("get", "ciliumnetworkpolicy", "all-ingress-deny",
                                                       "-n", NAMESPACE), uid)
                    entry = {"phase": phase, "round": round_number + 1, "client": name, "target": target,
                             "started": datetime.datetime.now(datetime.timezone.utc).isoformat()}
                    client = original[name]
                    try:
                        raw = fixture.kubectl("exec", "-n", NAMESPACE, client["pod"], "-c", name, "--",
                                              "curl", "--disable", "--silent", "--fail", "--show-error",
                                              "--noproxy", "*", "--connect-timeout", "2", "--max-time", "10",
                                              "-4", "--retry", "0", "--output", "/dev/null", "--write-out", FORMAT,
                                              "https://" + target + ":443", json_output=False)
                        entry.update(observation(raw, target))
                        if entry["local_ip"] != client["ip"]:
                            raise RuntimeError("TLS request used a foreign source address")
                    except RuntimeError as error:
                        entry.update(failed=True, type=type(error).__name__,
                                     message_sha256=hashlib.sha256(str(error).encode()).hexdigest())
                        if isinstance(error, CommandFailure):
                            entry.update(exit_code=error.code, classes=failure_classes(error.stderr),
                                         stderr_bytes=len(error.stderr),
                                         stderr_sha256=hashlib.sha256(error.stderr).hexdigest())
                        result["observations"].append(entry)
                        path.write_text(json.dumps(result, indent=2))
                        raise
                    result["observations"].append(entry)
                    path.write_text(json.dumps(result, indent=2))
    if current() != original:
        raise RuntimeError("TLS clients changed after diagnostic")
    result["sample_completed"] = True
    path.write_text(json.dumps(result, indent=2))
    return result
