#!/usr/bin/env python3
"""Qualify reviewed GPU schemas without running controllers or GPU operands."""

import hashlib
import json

import etcd_recovery as common


BUNDLE_SHA256 = "45f36ea81302f5ff66b4b1738f3eb6141a728110be921a6e3adcba823369678c"
CANDIDATE_BUNDLE_SHA256 = "849baea132da32f5c52cb76c91440234d49ccc5d0b0023c0772e0291012ebe3f"
VERSIONS = ("24.9.2", "25.3.4", "25.10.1", "26.3.3", "26.7.2")
BASE = {"clusterpolicies.nvidia.com", "nvidiadrivers.nvidia.com"}
ADDED = {"gpuclusters.nvidia.com", "computedomains.resource.nvidia.com",
         "computedomaincliques.resource.nvidia.com"}


def validate_bundle(bundle):
    digest = hashlib.sha256(common.canonical(bundle)).hexdigest()
    if digest not in {BUNDLE_SHA256, CANDIDATE_BUNDLE_SHA256}:
        raise RuntimeError("reviewed GPU admission bundle changed")
    validate_resources(bundle)
    return digest


def validate_resources(bundle):
    """Check resource boundaries after the caller verifies its exact public bundle hash."""
    if (set(bundle) != {"values_sha256", "stages"} or
            tuple(stage["version"] for stage in bundle["stages"]) != VERSIONS):
        raise RuntimeError("GPU family sequence changed")
    for index, stage in enumerate(bundle["stages"]):
        expected = BASE | (ADDED if index == 4 else set())
        names = set()
        for crd in stage["crds"]:
            name = crd.get("metadata", {}).get("name")
            spec = crd.get("spec", {})
            if (set(crd) != {"apiVersion", "kind", "metadata", "spec"} or
                    crd["apiVersion"] != "apiextensions.k8s.io/v1" or
                    crd["kind"] != "CustomResourceDefinition" or
                    crd["metadata"] != {"name": name} or name not in expected or name in names or
                    spec.get("group") not in {"nvidia.com", "resource.nvidia.com"} or
                    spec.get("conversion", {}).get("strategy", "None") != "None"):
                raise RuntimeError("foreign, duplicate or webhook GPU schema")
            names.add(name)
        policy = stage["policy"]
        if (names != expected or set(policy) != {"apiVersion", "kind", "metadata", "spec"} or
                policy["apiVersion"] != "nvidia.com/v1" or policy["kind"] != "ClusterPolicy" or
                policy["metadata"] != {"name": "cluster-policy"} or not isinstance(policy["spec"], dict)):
            raise RuntimeError("GPU policy or schema inventory changed")


def qualify(bundle, run_id):
    digest = validate_bundle(bundle)

    def admission(_container, scratch, client, _run_id):
        evidence = {"accepted": False, "stages": [], "production_writes": 0,
                    "controllers_executed": 0, "gpu_devices_used": 0,
                    "bundle_sha256": digest}
        identities = {}

        def api(*args):
            result = common.docker(*client, *args, check=False)
            if result.returncode:
                evidence["native_failure"] = {
                    "exit": result.returncode,
                    "stderr_bytes": len(result.stderr),
                    "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                    # Inputs contain only public vendor schemas and rendered policy.
                    "public_schema_diagnostic": result.stderr.decode(errors="replace")[:16384]}
                raise RuntimeError("native GPU schema admission failed")
            return json.loads(result.stdout)

        def empty_resources(names):
            for name in sorted(names):
                if api("get", name, "-A", "-o=json")["items"]:
                    raise RuntimeError("GPU dry-run persisted a custom resource")
            if api("get", "nodes", "-o=json")["items"]:
                raise RuntimeError("GPU admission fixture has a node")

        def submit(resource, operation, dry_run=False):
            (scratch / "gpu-schema.json").write_bytes(common.canonical(resource))
            args = [operation, "--validate=strict", "-f=/work/gpu-schema.json", "-o=json"]
            if dry_run:
                args.append("--dry-run=server")
            return api(*args)

        try:
            for stage in bundle["stages"]:
                record = {"version": stage["version"], "archive_sha256": stage["archive_sha256"],
                          "accepted": False}
                evidence["stages"].append(record)
                for crd in stage["crds"]:
                    name = crd["metadata"]["name"]
                    desired = json.loads(common.canonical(crd))
                    operation = "create"
                    if name in identities:
                        current = api("get", "crd", name, "-o=json")
                        meta = current["metadata"]
                        if meta["uid"] != identities[name] or not meta.get("resourceVersion") or meta.get("deletionTimestamp"):
                            raise RuntimeError("owned GPU schema identity changed")
                        desired["metadata"].update(uid=meta["uid"], resourceVersion=meta["resourceVersion"])
                        operation = "replace"
                    result = submit(desired, operation)
                    uid = result["metadata"].get("uid")
                    if (result["metadata"]["name"] != name or not uid or
                            (name in identities and identities[name] != uid)):
                        raise RuntimeError("GPU schema write returned another identity")
                    identities[name] = uid
                common.docker(*client, "wait", "--for=condition=Established", "--timeout=180s",
                              *["crd/" + name for name in sorted(identities)])
                empty_resources(identities)
                policy = submit(stage["policy"], "create", dry_run=True)
                if (policy.get("apiVersion") != "nvidia.com/v1" or policy.get("kind") != "ClusterPolicy" or
                        policy.get("metadata", {}).get("name") != "cluster-policy"):
                    raise RuntimeError("GPU dry-run policy identity changed")
                empty_resources(identities)
                record.update(accepted=True, schemas_established=len(identities),
                              schema_uids=dict(identities), strict_server_dry_run=True,
                              persisted_custom_resources=0, nodes=0,
                              defaulted_spec_sha256=hashlib.sha256(common.canonical(policy["spec"])).hexdigest())
            evidence.update(accepted=True, limitation="Schema, defaulting and adjacent CRD replacement only; "
                            "no operator, NFD, operand, device, host driver, CUDA, NVENC or application qualification")
        except RuntimeError as error:
            evidence["error"] = str(error)
        return evidence

    return common.qualify(common.run_identifier(run_id), synthetic_check=admission)
