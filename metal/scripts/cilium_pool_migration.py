#!/usr/bin/env python3
"""UID-scoped, compare-and-swap pool field migration for maintenance 103."""

import argparse
import copy
import json
import subprocess


UID = "c54f68a2-1100-438b-b34e-3c5aad6d6109"
SERVER = "https://10.0.20.50:6443"
RESOURCE = "ciliumloadbalancerippool.cilium.io"
BLOCKS = [{"cidr": "10.0.20.224/27"}]
LEGACY = {"cidrs": BLOCKS, "disabled": False}
CURRENT = {"blocks": BLOCKS, "allowFirstLastIPs": "No", "disabled": False}


def transition(pool, mode):
    """Refuse changed identity or intent; test the entire old spec atomically."""
    metadata = pool.get("metadata", {})
    if (pool.get("kind") != "CiliumLoadBalancerIPPool" or
            pool.get("apiVersion") != "cilium.io/v2alpha1" or
            metadata.get("name") != "default" or metadata.get("uid") != UID or
            metadata.get("deletionTimestamp") or not metadata.get("resourceVersion")):
        raise RuntimeError("pool identity differs from the reviewed maintenance target")
    rollback = mode.startswith("rollback")
    original, desired = (CURRENT, LEGACY) if rollback else (LEGACY, CURRENT)
    if pool.get("spec") != original:
        raise RuntimeError("pool specification differs from the reviewed precondition")
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": UID},
        {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
        {"op": "test", "path": "/spec", "value": original},
        {"op": "replace", "path": "/spec", "value": desired},
    ]
    return copy.deepcopy(patch), copy.deepcopy(desired)


def execute(args, run=subprocess.run):
    base = [args.kubectl, "--kubeconfig", args.kubeconfig, "--cache-dir", args.cache_dir]

    def call(arguments, payload=None):
        result = run(base + arguments, input=payload, capture_output=True, text=True)
        if result.returncode:
            # Do not repeat arbitrary kubectl stderr, kubeconfig or auth material.
            markers = [word for word in ("forbidden", "unauthorized", "x509", "conflict", "timeout")
                       if word in result.stderr.lower()]
            raise RuntimeError("kubectl refused operation: " + json.dumps({"exit": result.returncode, "markers": markers}))
        return result.stdout

    server = call(["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"])
    if server != SERVER:
        raise RuntimeError("kubeconfig API endpoint differs from the canonical VIP")
    base.extend(["--server", SERVER, "--request-timeout=30s"])
    before = json.loads(call(["get", RESOURCE, "default", "-o", "json"]))
    patch, desired = transition(before, "apply" if args.mode == "inspect" else args.mode)
    if args.mode == "inspect":
        return {"mode": args.mode, "uid": UID, "before": before["spec"], "desired": desired, "changed": False}
    dry_run = args.mode in ("dry-run", "rollback-dry-run")
    command = ["patch", RESOURCE, "default", "--type=json", "--patch-file=/dev/stdin", "-o", "json"]
    if dry_run:
        command.append("--dry-run=server")
    result = json.loads(call(command, json.dumps(patch)))
    if result.get("metadata", {}).get("uid") != UID or result.get("spec") != desired:
        raise RuntimeError("API patch result differs from reviewed desired state; inspect before continuing")
    after = json.loads(call(["get", RESOURCE, "default", "-o", "json"]))
    expected = before["spec"] if dry_run else desired
    if after.get("metadata", {}).get("uid") != UID or after.get("spec") != expected:
        raise RuntimeError("pool readback differs; inspect before continuing")
    if dry_run and after["metadata"]["resourceVersion"] != before["metadata"]["resourceVersion"]:
        raise RuntimeError("pool changed concurrently during dry-run; obtain a new baseline")
    return {"mode": args.mode, "uid": UID, "before": before["spec"], "after": after["spec"],
            "desired": desired, "changed": not dry_run, "server_dry_run": dry_run,
            "resource_version": after["metadata"]["resourceVersion"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--mode", choices=("inspect", "dry-run", "apply", "rollback-dry-run", "rollback"), default="inspect")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), sort_keys=True))
    except (RuntimeError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
