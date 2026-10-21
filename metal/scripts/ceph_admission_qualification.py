#!/usr/bin/env python3
"""Check candidate Ceph CRDs in an agentless, disconnected synthetic API."""

import hashlib
import json

import etcd_recovery as common


GROUPS = {"ceph.rook.io", "csi.ceph.io"}
MINOR_BUNDLE_SHA256 = "83131d0514fc7b085ef5111c1fb38a9d26acc9bd23b067a57677629ba116fde4"


def command_objects(data):
    text = data.decode().strip()
    rows = []
    while text:
        value, end = json.JSONDecoder().raw_decode(text)
        if not isinstance(value, dict):
            raise RuntimeError("invalid native admission response")
        rows.extend(value["items"] if value.get("kind") == "List" else [value])
        text = text[end:].lstrip()
    return rows


def validate_bundle(bundle):
    if set(bundle) != {"crds", "resources"} or len(bundle["crds"]) not in (24, 25) or len(bundle["resources"]) != 10:
        raise RuntimeError("candidate Ceph admission inventory changed")
    if len(bundle["crds"]) == 25 and hashlib.sha256(common.canonical(bundle)).hexdigest() != MINOR_BUNDLE_SHA256:
        raise RuntimeError("reviewed minor Ceph admission bundle changed")
    served = set()
    names = set()
    for crd in bundle["crds"]:
        spec = crd.get("spec", {})
        name = crd.get("metadata", {}).get("name")
        if (crd.get("apiVersion") != "apiextensions.k8s.io/v1" or
                crd.get("kind") != "CustomResourceDefinition" or spec.get("group") not in GROUPS or
                not name or name in names):
            raise RuntimeError("foreign or duplicate candidate CRD")
        names.add(name)
        served.update((spec["group"] + "/" + version["name"], spec["names"]["kind"])
                      for version in spec["versions"] if version.get("served"))
    identities = set()
    for resource in bundle["resources"]:
        meta = resource.get("metadata", {})
        identity = (resource.get("apiVersion"), resource.get("kind"), meta.get("namespace"), meta.get("name"))
        if (set(resource) != {"apiVersion", "kind", "metadata", "spec"} or
                set(meta) - {"name", "namespace"} or not meta.get("name") or identity in identities or
                identity[:2] not in served or not isinstance(resource["spec"], dict)):
            raise RuntimeError("foreign, duplicate or unsanitized resource")
        identities.add(identity)
    return names


def qualify(bundle, run_id):
    names = validate_bundle(bundle)

    def admission(_container, scratch, client, _run_id):
        def create(items, filename, dry_run=False):
            (scratch / filename).write_bytes(common.canonical({"apiVersion": "v1", "kind": "List", "items": items}))
            args = [*client, "create", "--validate=strict", "-f=/work/" + filename, "-o=json"]
            if dry_run:
                args.append("--dry-run=server")
            rows = command_objects(common.docker(*args).stdout)
            if len(rows) != len(items):
                raise RuntimeError("synthetic admission returned incomplete evidence")
            return rows

        create(bundle["crds"], "candidate-crds.json")
        common.docker(*client, "wait", "--for=condition=Established", "--timeout=180s",
                      *["crd/" + name for name in sorted(names)])
        namespaces = sorted({r["metadata"]["namespace"] for r in bundle["resources"] if "namespace" in r["metadata"]})
        create([{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}} for name in namespaces],
               "namespaces.json")
        result = create(bundle["resources"], "current-specifications.json", dry_run=True)
        for name in sorted(names):
            if json.loads(common.docker(*client, "get", name, "-A", "-o=json").stdout)["items"]:
                raise RuntimeError("dry-run unexpectedly persisted a custom resource")
        return {"accepted": True, "crds_established": len(names), "current_specs_server_dry_run": len(result),
                "bundle_sha256": hashlib.sha256(common.canonical(bundle)).hexdigest(),
                "measured_scratch_allocated_bytes": sum(p.lstat().st_blocks * 512 for p in scratch.rglob("*")),
                "production_writes": 0, "controllers_executed": 0,
                "limitation": "Kubernetes schema/CEL/defaulting only; no Rook/CSI webhook or daemon runtime"}

    return common.qualify(common.run_identifier(run_id), synthetic_check=admission)
