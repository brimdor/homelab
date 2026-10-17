#!/usr/bin/env python3
"""Check, or execute, one committed owner-authorized workload retirement plan."""

import sys

sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import socket
import stat
import subprocess
import tempfile
import textwrap
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path("/Users/chris/Documents/Github/homelab")
ORIGIN = "git@git.eaglepass.io:ops/homelab.git"
SERVER = "https://10.0.20.50:6443"
DRIVER = "rook-ceph.rbd.csi.ceph.com"
SOURCES = ("scripts/retire-workloads.py", "scripts/test_retire_workloads.py",
           "docs/how-to-guides/retire-workloads.md", "metal/scripts/ssh-trust.py",
           "system/argocd/values.yaml", ".agent/rules/foundational-rules.md")
RESOURCES = ("namespaces", "persistentvolumes", "persistentvolumeclaims", "pods",
             "deployments.apps", "statefulsets.apps", "daemonsets.apps", "replicasets.apps",
             "replicationcontrollers", "jobs.batch", "cronjobs.batch",
             "volumeattachments.storage.k8s.io", "applications.argoproj.io", "storageclasses.storage.k8s.io")
CLUSTER = {"namespaces", "persistentvolumes", "volumeattachments.storage.k8s.io", "storageclasses.storage.k8s.io"}
WORKLOADS = {"Pod": ("pods", "v1"), "Deployment": ("deployments.apps", "apps/v1"),
             "StatefulSet": ("statefulsets.apps", "apps/v1"), "DaemonSet": ("daemonsets.apps", "apps/v1"),
             "ReplicaSet": ("replicasets.apps", "apps/v1"), "ReplicationController": ("replicationcontrollers", "v1"),
             "Job": ("jobs.batch", "batch/v1"), "CronJob": ("cronjobs.batch", "batch/v1")}
NAMESPACE_KINDS = ({("v1", kind) for kind in (
    "Pod", "ReplicationController", "PersistentVolumeClaim", "ConfigMap", "Secret", "Service",
    "Endpoints", "ServiceAccount", "Event", "LimitRange", "ResourceQuota")} | {
    ("apps/v1", kind) for kind in ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "ControllerRevision")} | {
    ("batch/v1", "Job"), ("batch/v1", "CronJob"), ("networking.k8s.io/v1", "Ingress"),
    ("networking.k8s.io/v1", "NetworkPolicy"), ("discovery.k8s.io/v1", "EndpointSlice"),
    ("events.k8s.io/v1", "Event"), ("cert-manager.io/v1", "Certificate"),
    ("cert-manager.io/v1", "CertificateRequest"), ("cert-manager.io/v1", "Issuer"),
    ("acme.cert-manager.io/v1", "Order"), ("acme.cert-manager.io/v1", "Challenge"),
    ("cilium.io/v2", "CiliumEndpoint")})
METADATA_ACCEPT = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"
DNS = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,1023}\Z")
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
NAMESPACE_FIELD = re.compile(
    r"^[ \t]*(?:-[ \t]+)?(?:namespace|releaseNamespace)[ \t]*:[ \t]*(['\"]?)("
    + LABEL + r")\1[ \t]*(?:#.*)?$", re.MULTILINE)
SERVICE_FQDN = re.compile(
    r"(?<![A-Za-z0-9_.-])" + LABEL + r"\.(" + LABEL
    + r")\.svc(?:\.cluster\.local)?\.?(?![A-Za-z0-9_.-])")


class Refusal(Exception):
    """Public, deliberately non-secret diagnostic."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def name(value, namespace=False):
    require(isinstance(value, str) and len(value) <= (63 if namespace else 253)
            and DNS.fullmatch(value) and all(re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) for part in value.split("."))
            and (not namespace or "." not in value), "Invalid DNS resource name")
    return value


def identity(value):
    require(isinstance(value, str) and IDENTITY.fullmatch(value), "Invalid metadata identity")
    return value


def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected.split()),
            "Unknown or missing plan fields")


def validate_plan(plan):
    fields(plan, "version reason namespaces volumes historical_jobs retired_workloads")
    require(type(plan["version"]) is int and plan["version"] == 1, "Unsupported plan version")
    require(isinstance(plan["reason"], str) and plan["reason"].strip()
            and len(plan["reason"]) <= 4096, "Owner instruction is required")
    for key in ("namespaces", "volumes", "historical_jobs", "retired_workloads"):
        require(isinstance(plan[key], list), "Plan resource collections must be lists")
    namespaces, pvs, claims = set(), set(), set()
    for item in plan["namespaces"]:
        fields(item, "name uid archived_path")
        name(item["name"], True)
        identity(item["uid"])
        path = item["archived_path"]
        require(isinstance(path, str) and re.fullmatch(r"archived/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+", path),
                "Archive path must be a directory below archived")
        require(item["name"] not in namespaces, "Duplicate namespace goal")
        namespaces.add(item["name"])
    workload_keys, workload_uids = set(), set()
    for item in plan["retired_workloads"]:
        fields(item, "kind namespace name uid")
        require(item["kind"] in WORKLOADS, "Unsupported retired workload kind")
        name(item["namespace"], True)
        name(item["name"])
        identity(item["uid"])
        require(item["namespace"] in namespaces, "Retired workload requires an explicit archived namespace")
        key = (item["kind"], item["namespace"], item["name"])
        require(key not in workload_keys and item["uid"] not in workload_uids, "Duplicate retired workload identity")
        workload_keys.add(key)
        workload_uids.add(item["uid"])
    for item in plan["volumes"]:
        fields(item, "name uid claim_namespace claim_name claim_uid driver volume_handle disposition")
        name(item["name"])
        name(item["claim_namespace"], True)
        name(item["claim_name"])
        for key in ("uid", "claim_uid", "driver", "volume_handle"):
            identity(item[key])
        require(item["disposition"] in ("archived", "deleted-unarchived"), "Unknown volume disposition")
        require((item["claim_namespace"] in namespaces) == (item["disposition"] == "archived"),
                "Archived volumes require an explicit namespace goal; orphan scope cannot delete namespaces")
        pair = (item["claim_namespace"], item["claim_name"])
        require(item["name"] not in pvs and pair not in claims, "Duplicate PV or claim goal")
        pvs.add(item["name"])
        claims.add(pair)
    require(len(plan["historical_jobs"]) <= 1, "Only the specified historical Renovate Job is supported")
    for item in plan["historical_jobs"]:
        fields(item, "namespace name uid cronjob_name cronjob_uid cronjob_timezone disposition")
        require(item["namespace"] == "renovate" and item["name"] == "renovate-29837640"
                and item["cronjob_name"] == "renovate"
                and item["disposition"] == "owner-closed-historical", "Unsupported historical Job goal")
        identity(item["uid"])
        identity(item["cronjob_uid"])
        cron_timezone(item["cronjob_timezone"])
        require("renovate" not in namespaces, "The active Renovate namespace must stay")
    return plan


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON plan field")
        result[key] = value
    return result


def decode_plan(raw):
    try:
        return validate_plan(json.loads(raw, object_pairs_hook=unique_object))
    except (ValueError, UnicodeError):
        raise Refusal("Plan must be valid version-1 JSON") from None


def git(*args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    require(bool(env.get("GIT_SSH_COMMAND")), "Parent-approved GIT_SSH_COMMAND is required")
    forbidden = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_SSH",
                 "GIT_PROXY_COMMAND", "GIT_CONFIG", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
                 "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_NAMESPACE"}
    require(not any(key in env for key in forbidden)
            and not any(key.startswith("GIT_CONFIG_") for key in env), "Git environment override refused")
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), *args],
                                capture_output=True, check=False, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("Git read failed or timed out; diagnostics withheld") from None
    require(result.returncode == 0, "Git read failed; diagnostics withheld")
    return result.stdout


def committed_files(paths, read_git=git):
    """Check content and index separately, including staged-only and mode changes."""
    require(not read_git("status", "--porcelain=v1", "--untracked-files=all", "--", *paths),
            "Source or plan is dirty or untracked")
    for path in paths:
        target = ROOT / path
        require(target.resolve() == target.absolute() and target.is_file(), "Symlink or missing source/plan")
        entry = read_git("ls-tree", "HEAD", "--", path).decode().split()
        require(len(entry) == 4 and entry[0] in ("100644", "100755") and entry[3] == path,
                "Source or plan is not a tracked regular file")
        require(target.read_bytes() == read_git("show", "HEAD:" + path),
                "Source or plan differs from committed HEAD")


def tree_files(raw):
    """Keep exact blob lengths so batched git show output cannot merge file boundaries."""
    require(not raw or raw.endswith(b"\0"), "Invalid committed file inventory")
    result = {}
    try:
        for record in raw.split(b"\0"):
            if not record:
                continue
            details, path = record.split(b"\t", 1)
            _mode, kind, _oid, size = details.split()
            if kind == b"commit":
                continue
            require(kind == b"blob" and size.isdigit(), "Invalid committed blob metadata")
            path = path.decode()
            require(path not in result, "Duplicate committed file")
            result[path] = int(size)
    except (ValueError, UnicodeError):
        raise Refusal("Invalid committed file inventory") from None
    return result


def committed_texts(paths, sizes, read_git=git):
    paths = sorted(set(paths))
    result = {}
    for start in range(0, len(paths), 64):
        chunk = paths[start:start + 64]
        raw = read_git("show", *("HEAD:" + path for path in chunk))
        require(len(raw) == sum(sizes[path] for path in chunk), "Batched source byte lengths changed")
        offset = 0
        for path in chunk:
            end = offset + sizes[path]
            result[path] = raw[offset:end].decode()
            offset = end
    return result


def strip_source_comments(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def namespace_source(text):
    """An egress permission is not evidence that a workload consumes its destination."""
    lines = []
    egress_indent = None
    policy_indent = None
    policy_resource = False
    for line in strip_source_comments(text).splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if line.strip() in ("---", "..."):
            egress_indent = policy_indent = None
            policy_resource = False
        if egress_indent is not None:
            if indent > egress_indent or (indent == egress_indent and line.lstrip().startswith("-")):
                continue
            egress_indent = None
        if policy_indent is not None and (indent < policy_indent or
                (indent == policy_indent and not line.lstrip().startswith("-"))):
            policy_indent = None
        if re.match(r"^kind[ \t]*:", line):
            policy_resource = bool(re.fullmatch(
                r"kind[ \t]*:[ \t]*(['\"]?)(?:NetworkPolicy|CiliumNetworkPolicy|CiliumClusterwideNetworkPolicy)\1[ \t]*(?:#.*)?", line))
        if re.match(r"^[ \t]*(?:networkPolicy|networkPolicies)[ \t]*:", line):
            policy_indent = indent
        if (policy_resource or policy_indent is not None) and re.match(r"^[ \t]*(?:egress|egressDeny)[ \t]*:", line):
            egress_indent = indent
            continue
        lines.append(line)
    return "\n".join(lines)


def endpoint_key(key):
    return isinstance(key, str) and bool(
        re.search(r"(?:^|[_-])(?:host|hostname|url|uri|endpoint)s?$", key, re.IGNORECASE)
        or re.search(r"[a-z0-9](?:Host|Hostname|Url|URL|Uri|URI|Endpoint)s?$", key)
        or key.lower() in ("pghost", "pgurl", "dbhost", "dburl", "databasehost", "databaseurl", "baseurl"))


def endpoint_references(key, value):
    if not endpoint_key(key) or not isinstance(value, str):
        return set()
    if value.lstrip().startswith("["):
        import yaml

        try:
            endpoints = yaml.safe_load(value)
        except yaml.YAMLError:
            raise Refusal("Invalid endpoint syntax; values withheld") from None
        require(isinstance(endpoints, list) and all(isinstance(item, str) for item in endpoints),
                "Invalid endpoint list; values withheld")
        return set().union(*(endpoint_references(key, item) for item in endpoints))
    value = value.split(" #", 1)[0].strip().strip("'\"")
    if not value or any(char.isspace() for char in value):
        return set()
    try:
        host = urlsplit(value if "://" in value else "//" + value).hostname or ""
    except ValueError:
        raise Refusal("Invalid endpoint syntax; values withheld") from None
    short = re.fullmatch(LABEL + r"\.(" + LABEL + r")\.?", host)
    return set(SERVICE_FQDN.findall(host)) | ({short.group(1)} if short else set())


def env_references(obj):
    """Inspect literal endpoint env values, never resolve or print Secret/valueFrom data."""
    result = set()
    if isinstance(obj, dict):
        env = obj.get("env")
        require("{{" not in str(env), "Unresolved inline env syntax; values withheld")
        if isinstance(env, list):
            for item in env:
                if isinstance(item, dict):
                    result.update(endpoint_references(item.get("name"), item.get("value")))
        elif isinstance(env, dict):
            for key, value in env.items():
                result.update(endpoint_references(key, value.get("value") if isinstance(value, dict) else value))
        for key, value in obj.items():
            if key not in ("env", "metadata", "status", "egress", "egressDeny"):
                result.update(env_references(value))
    elif isinstance(obj, list):
        for value in obj:
            result.update(env_references(value))
    return result


def resolve_env_templates(text, values_text):
    import yaml

    lines, scalar_indent, values = text.splitlines(keepends=True), None, None
    for index, line in enumerate(lines):
        depth = len(line) - len(line.lstrip())
        if scalar_indent is not None:
            if not line.strip() or depth > scalar_indent:
                continue
            scalar_indent = None
        if re.match(r"^[ \t]*[^#\n]+:[ \t]*[|>](?:[1-9][+-]?|[+-][1-9]?)?[ \t]*(?:#.*)?$", line):
            scalar_indent = depth
            continue
        header = re.fullmatch(r"([ \t]*)env:[ \t]*(.*)", line.rstrip("\r\n"))
        if not header or "{{" not in header.group(2):
            continue
        match = re.fullmatch(
            r"\{\{[ \t]*toYaml[ \t]+\.Values\.([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)"
            r"[ \t]*\|[ \t]*nindent[ \t]+[0-9]+[ \t]*\}\}[ \t]*", header.group(2))
        require(match is not None, "Unsupported env template; values withheld")
        if values is None:
            require(isinstance(values_text, str), "Missing chart values for env template; values withheld")
            try:
                values = yaml.safe_load(values_text)
            except yaml.YAMLError:
                raise Refusal("Invalid chart values for env template; values withheld") from None
        value = values
        for part in match.group(1).split("."):
            require(isinstance(value, dict) and part in value, "Missing env template path; values withheld")
            value = value[part]
        require(value is None or isinstance(value, (list, dict)), "Unsupported env template value; values withheld")
        try:
            literal = json.dumps(value, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise Refusal("Invalid env template value; values withheld") from None
        lines[index] = header.group(1) + "env: " + literal + ("\n" if line.endswith("\n") else "")
    return "".join(lines)


def source_env_references(text):
    import yaml

    result = set()
    try:
        for document in yaml.safe_load_all(text):
            result.update(env_references(document))
        return result
    except yaml.YAMLError:
        pass
    # Raw Helm can invalidate the document. Only inspect bounded, literal env blocks.
    lines, scalar_indent = text.splitlines(), None
    for index, line in enumerate(lines):
        depth = len(line) - len(line.lstrip())
        if scalar_indent is not None:
            if not line.strip() or depth > scalar_indent:
                continue
            scalar_indent = None
        if re.match(r"^[ \t]*[^#\n]+:[ \t]*[|>](?:[1-9][+-]?|[+-][1-9]?)?[ \t]*(?:#.*)?$", line):
            scalar_indent = depth
            continue
        header = re.fullmatch(r"([ \t]*)env:[ \t]*(.*)", line)
        if not header:
            continue
        indent, end = len(header.group(1)), index + 1
        while end < len(lines):
            current = lines[end]
            depth = len(current) - len(current.lstrip())
            if current.strip() and not (depth > indent or (depth == indent and current.lstrip().startswith("-"))):
                break
            end += 1
        block = textwrap.dedent("\n".join(lines[index:end]))
        require("{{" not in block, "Unresolved inline env syntax; values withheld")
        try:
            result.update(env_references(yaml.safe_load(block)))
            continue
        except yaml.YAMLError:
            pass
        require(not header.group(2).strip() or header.group(2).lstrip().startswith("#"),
                "Unresolved inline env syntax; values withheld")
        literal_lines = [item for item in lines[index + 1:end] if item.strip()]
        entries = [item for item in literal_lines if re.fullmatch(
            r"[ \t]*(?:-[ \t]+name:[ \t]*['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?|[A-Za-z_][A-Za-z0-9_]*:)[ \t]*", item)]
        if not entries:
            continue
        entry_depth = min(len(item) - len(item.lstrip()) for item in entries)
        for first, second in zip(literal_lines, literal_lines[1:]):
            native = re.fullmatch(r"([ \t]*)-[ \t]+name:[ \t]*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[ \t]*", first)
            wrapped = re.fullmatch(r"([ \t]*)([A-Za-z_][A-Za-z0-9_]*):[ \t]*", first)
            declaration = native or wrapped
            value = re.fullmatch(r"([ \t]*)value:[ \t]*(.+)", second)
            if declaration and value and len(declaration.group(1)) == entry_depth and len(value.group(1)) > entry_depth:
                result.update(endpoint_references(declaration.group(2), value.group(2)))
    return result


def namespace_references(text):
    text = namespace_source(text)
    references = ({match.group(2) for match in NAMESPACE_FIELD.finditer(text)}
                  | set(SERVICE_FQDN.findall(text)) | source_env_references(text))
    for line in text.splitlines():
        field = re.match(r"^[ \t]*(?:-[ \t]+)?(['\"]?)([A-Za-z_][A-Za-z0-9_.-]*)\1[ \t]*[:=][ \t]*(.*)$", line)
        if field:
            references.update(endpoint_references(field.group(2), field.group(3)))
    return references


def archive_aliases(directories, texts):
    aliases = {path: {PurePosixPath(path).name} for path in directories if path.startswith("archived/")}
    for path, text in texts.items():
        directory = str(PurePosixPath(path).parent)
        if PurePosixPath(path).name != "Chart.yaml" or directory not in aliases:
            continue
        matches = re.findall(r"^name[ \t]*:[ \t]*(['\"]?)(" + LABEL + r")\1[ \t]*(?:#.*)?$",
                             strip_source_comments(text), re.MULTILINE)
        declarations = re.findall(r"^name[ \t]*:", strip_source_comments(text), re.MULTILINE)
        if len(declarations) == len(matches) == 1:
            aliases[directory].add(matches[0][1])
    return aliases


def source_gate(plan_path, read_git=git):
    require(Path(__file__).resolve().parents[1] == ROOT
            and ROOT.resolve() == ROOT, "Executor must run from the canonical checkout")
    require(isinstance(plan_path, str) and re.fullmatch(r"scripts/retirements/[a-z0-9][a-z0-9-]*\.json", plan_path),
            "Plan must be a canonical scripts/retirements/<run>.json source path")
    require(read_git("rev-parse", "--show-toplevel").decode().strip() == str(ROOT), "Foreign Git checkout")
    require(read_git("symbolic-ref", "--short", "HEAD").strip() == b"master", "Deployment branch must be master")
    require(read_git("config", "--get-all", "remote.origin.url").decode().splitlines() == [ORIGIN]
            and read_git("remote", "get-url", "origin").decode().strip() == ORIGIN,
            "Canonical Gitea origin required; URL rewrites are not allowed")
    head = read_git("rev-parse", "HEAD").decode().strip()
    require(re.fullmatch(r"[0-9a-f]{40}", head), "Invalid Git HEAD")
    committed_files((*SOURCES, plan_path), read_git)
    require(read_git("ls-remote", "origin", "refs/heads/master").decode().splitlines()
            == [head + "\trefs/heads/master"], "Gitea master does not match local HEAD")
    files = tree_files(read_git("ls-tree", "-r", "--long", "-z", "HEAD"))
    charts = {str(PurePosixPath(path).parent) for path in files
              if re.fullmatch(r"(?:system|platform|apps)/[^/]+/Chart\.yaml", path)}
    # Uncommitted active charts protect data even though they cannot authorize destruction.
    charts.update(str(path.parent.relative_to(ROOT)) for area in ("system", "platform", "apps")
                  for path in (ROOT / area).glob("*/Chart.yaml"))
    active = {PurePosixPath(chart).name for chart in charts}
    paths = {path for path in files if PurePosixPath(path).suffix in (".yaml", ".yml", ".json", ".tpl")
             and "/".join(PurePosixPath(path).parts[:2]) in charts}
    paths.update(path for path in files if path.startswith("archived/") and PurePosixPath(path).name == "Chart.yaml")
    committed = committed_texts(paths, files, read_git)
    texts = [strip_source_comments(resolve_env_templates(
        text, committed.get("/".join(PurePosixPath(path).parts[:2]) + "/values.yaml")))
        for path, text in committed.items() if not path.startswith("archived/")]
    for chart in sorted(charts):
        values_path = ROOT / chart / "values.yaml"
        values_text = values_path.read_text() if values_path.is_file() else None
        for path in (ROOT / chart).rglob("*"):
            if path.is_file() and path.suffix in (".yaml", ".yml", ".json", ".tpl"):
                texts.append(strip_source_comments(resolve_env_templates(path.read_text(), values_text)))
    for text in texts:
        active.update(match.group(2) for match in NAMESPACE_FIELD.finditer(namespace_source(text)))
    directories = {str(parent) for path in files for parent in PurePosixPath(path).parents}
    aliases = archive_aliases(directories, committed)
    require(read_git("rev-parse", "HEAD").decode().strip() == head, "HEAD changed during source inspection")
    return {"head": head, "active": active, "directories": directories, "texts": texts, "archive_aliases": aliases}


def load_api():
    """Import only the API, never the enrollment entry point or trust publication helpers."""
    spec = importlib.util.spec_from_file_location("retirement_ssh_trust", ROOT / "metal/scripts/ssh-trust.py")
    trust = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trust)
    trust.Refusal = Refusal

    def bounded_run(*args, **kwargs):
        kwargs["timeout"] = 20
        return subprocess.run(*args, **kwargs)

    # Keep API.establish/run/json, but tighten its process timeout as well as its API timeout.
    trust.subprocess = SimpleNamespace(run=bounded_run, TimeoutExpired=subprocess.TimeoutExpired)
    return trust.API()


@contextmanager
def metadata_deadline():
    """Bound one GET, including slow headers/bodies, in this single-threaded CLI."""
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "Existing process timer prevents isolated metadata timeout")

    def expired(_signum, _frame):
        raise Refusal("Metadata GET exceeded 20 seconds")

    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, 20)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class UnixHTTPConnection(HTTPConnection):
    def __init__(self, directory):
        super().__init__("localhost", timeout=20)
        self.directory = directory

    def connect(self):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous = None
        try:
            connection.settimeout(20)
            previous = os.open(".", os.O_RDONLY)
            try:
                os.chdir(self.directory)
                connection.connect("s")
            finally:
                os.fchdir(previous)
            self.sock = connection
        except BaseException:
            connection.close()
            raise
        finally:
            if previous is not None:
                os.close(previous)


def metadata_identity(api_version, kind, metadata):
    require(isinstance(metadata, dict), "Missing partial object metadata")
    namespace, resource_name, uid = (metadata.get(key) for key in ("namespace", "name", "uid"))
    name(namespace, True)
    require(isinstance(resource_name, str) and len(resource_name) <= 1024
            and re.fullmatch(r"[^\x00-\x1f\x7f/]+", resource_name), "Invalid metadata resource name")
    identity(uid)
    return {"apiVersion": api_version, "kind": kind,
            "metadata": {"namespace": namespace, "name": resource_name, "uid": uid}}


class MetadataAPI:
    """Existing API for governed operations; private GET-only metadata negotiation."""

    def __init__(self, api, directory):
        self.api, self.directory = api, directory
        self._discovery_paths = {"/api/v1", "/apis"}
        self._list_paths = set()
        self._resources = None

    def __getattr__(self, key):
        return getattr(self.api, key)

    def _read(self, path, partial=False, continuation=""):
        require(path in (self._list_paths if partial else self._discovery_paths), "Metadata route is not an approved GET")
        require(isinstance(continuation, str) and (partial or not continuation), "Invalid metadata pagination")
        query = {"limit": "500"} if partial else {}
        if continuation:
            query["continue"] = continuation
        route = path + ("?" + urlencode(query) if query else "")
        connection = UnixHTTPConnection(self.directory)
        try:
            with metadata_deadline():
                connection.request("GET", route, headers={"Accept": METADATA_ACCEPT if partial else "application/json"})
                response = connection.getresponse()
                require(response.status == 200, f"Metadata HTTP GET refused for {path} (HTTP {response.status}); no full-object fallback")
                result = json.loads(response.read())
                require(isinstance(result, dict), "Invalid metadata HTTP response")
                return result
        except (OSError, HTTPException, ValueError):
            raise Refusal("Metadata GET failed; diagnostics withheld, no fallback") from None
        finally:
            connection.close()

    def metadata_resources(self):
        if self._resources is not None:
            return [dict(resource) for resource in self._resources]
        groups = self._read("/apis")
        require(groups.get("kind") == "APIGroupList" and isinstance(groups.get("groups"), list), "Invalid API group discovery")
        versions = [("v1", "/api/v1")]
        for group in groups["groups"]:
            group_name = name(group["name"])
            preferred = group["preferredVersion"]
            version = preferred["version"]
            require(isinstance(version, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*", version)
                    and preferred.get("groupVersion") == group_name + "/" + version, "Invalid preferred API version")
            path = "/apis/" + group_name + "/" + version
            require(path not in self._discovery_paths, "Duplicate API group discovery")
            self._discovery_paths.add(path)
            versions.append((preferred["groupVersion"], path))
        resources, seen = [], set()
        for api_version, path in versions:
            document = self._read(path)
            require(document.get("kind") == "APIResourceList" and document.get("groupVersion") == api_version
                    and isinstance(document.get("resources"), list), "Invalid API resource discovery")
            for resource in document["resources"]:
                resource_name = resource["name"]
                require(isinstance(resource_name, str) and type(resource.get("namespaced")) is bool,
                        "Malformed API resource scope discovery")
                if "/" in resource_name or not resource["namespaced"]:
                    continue
                name(resource_name)
                verbs = resource.get("verbs")
                require(isinstance(verbs, list), "Missing API resource verbs")
                if not {"list", "delete"} <= set(verbs) or api_version.split("/")[0].endswith("metrics.k8s.io"):
                    continue
                kind = resource["kind"]
                require(isinstance(kind, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", kind), "Invalid API resource kind")
                qualified = resource_name + ("." + api_version.split("/")[0] if "/" in api_version else "")
                require(qualified not in seen, "Duplicate deletable resource discovery")
                seen.add(qualified)
                list_path = path + "/" + resource_name
                self._list_paths.add(list_path)
                resources.append({"resource": qualified, "apiVersion": api_version, "kind": kind, "path": list_path})
        self._resources = resources
        return [dict(resource) for resource in resources]

    def metadata_list(self, resource):
        expected = {item["resource"]: item for item in self.metadata_resources()}
        require(resource.get("resource") in expected and resource == expected[resource["resource"]], "Unregistered metadata list route")
        result, continuation, seen = [], "", set()
        while True:
            document = self._read(resource["path"], partial=True, continuation=continuation)
            require(document.get("apiVersion") == "meta.k8s.io/v1" and document.get("kind") == "PartialObjectMetadataList"
                    and set(document) <= {"apiVersion", "kind", "metadata", "items"}
                    and "items" in document and (document["items"] is None or isinstance(document["items"], list))
                    and isinstance(document.get("metadata"), dict),
                    f"Server did not return a metadata-only list for {resource['resource']}; no fallback")
            for obj in document["items"] or []:
                require(isinstance(obj, dict) and obj.get("apiVersion", "meta.k8s.io/v1") == "meta.k8s.io/v1"
                        and obj.get("kind", "PartialObjectMetadata") == "PartialObjectMetadata"
                        and set(obj) <= {"apiVersion", "kind", "metadata"},
                        "Server returned a full or malformed object; no fallback")
                result.append(metadata_identity(resource["apiVersion"], resource["kind"], obj.get("metadata")))
            continuation = document["metadata"].get("continue", "")
            require(isinstance(continuation, str), "Invalid metadata continuation token")
            if not continuation:
                return result
            require(continuation not in seen, "Repeated metadata continuation token")
            seen.add(continuation)


def stop_metadata_proxy(process):
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=20)


@contextmanager
def metadata_api(api):
    temporary, cache = os.environ.get("TMPDIR"), os.environ.get("KUBECACHEDIR")
    require(temporary and cache and Path(temporary).is_absolute() and Path(temporary).is_dir()
            and Path(cache).is_absolute() and Path(cache).is_dir(), "Parent-provided TMPDIR and KUBECACHEDIR directories are required")
    with tempfile.TemporaryDirectory(prefix="retire-metadata-", dir=temporary) as directory:
        os.chmod(directory, 0o700)
        process = None
        try:
            process = subprocess.Popen([*api.base, "--server", SERVER, "--request-timeout=20s", "proxy",
                "--unix-socket=s", "--reject-methods=POST,PUT,PATCH,DELETE,CONNECT"],
                cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            end = time.monotonic() + 20
            socket_path = Path(directory) / "s"
            while True:
                require(time.monotonic() < end, "Metadata proxy startup exceeded 20 seconds")
                require(process.poll() is None, "Owned metadata proxy exited during startup")
                try:
                    info = socket_path.lstat()
                except FileNotFoundError:
                    info = None
                if info is not None:
                    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), "Unsafe metadata proxy socket")
                    os.chmod(socket_path, 0o600)
                    require(time.monotonic() < end, "Metadata proxy startup exceeded 20 seconds")
                    break
                time.sleep(0.05)
            yield MetadataAPI(api, directory)
        finally:
            if process is not None:
                stop_metadata_proxy(process)


def namespace_metadata(api):
    resources = api.metadata_resources()
    require({value[0] for value in WORKLOADS.values()} | {"persistentvolumeclaims"}
            <= {resource["resource"] for resource in resources}, "Metadata discovery lacks required built-in resources")
    result, seen = [], set()
    for resource in resources:
        for obj in api.metadata_list(resource):
            obj = metadata_identity(obj["apiVersion"], obj["kind"], obj.get("metadata"))
            key = (obj["apiVersion"], obj["kind"], obj["metadata"]["namespace"], obj["metadata"]["name"])
            require(key not in seen, "Duplicate namespace metadata identity")
            seen.add(key)
            result.append(obj)
    return result


def collect(api, namespaces=()):
    result = {}
    for resource in RESOURCES:
        args = ["get", resource] + ([] if resource in CLUSTER else ["-A"]) + ["-o", "json"]
        try:
            document = api.json(args)
        except Refusal:
            raise Refusal(f"Resource evidence read failed for {resource}; command diagnostics withheld") from None
        require(isinstance(document, dict) and isinstance(document.get("items"), list), "Invalid resource list")
        entries = {}
        for obj in document["items"]:
            metadata = obj["metadata"]
            key = (metadata.get("namespace", ""), name(metadata["name"], namespace=resource == "namespaces"))
            identity(metadata["uid"])
            identity(metadata["resourceVersion"])
            for kind, (workload_resource, api_version) in WORKLOADS.items():
                if resource == workload_resource:
                    require(obj.get("kind") == kind and obj.get("apiVersion") == api_version, "Unexpected workload API kind")
            require(key not in entries, "Duplicate resource identity")
            entries[key] = obj
        result[resource] = entries
    result["namespace_metadata"] = namespace_metadata(api) if namespaces else []
    return result


def workload_objects(snapshot):
    return {(kind, namespace, resource_name): obj for kind, (resource, _) in WORKLOADS.items()
            for (namespace, resource_name), obj in snapshot[resource].items()}


def retired_ownership(plan, snapshot, active):
    known = workload_objects(snapshot)
    planned = {(item["kind"], item["namespace"], item["name"]): item["uid"] for item in plan["retired_workloads"]}
    retired = {item["name"] for item in plan["namespaces"]}
    for key, uid in planned.items():
        same_uid(known.get(key), uid)
    approved = {}

    def visit(key, trail):
        require(key not in trail, "Retired workload ownerReference cycle")
        if key in approved:
            return approved[key]
        obj = known[key]
        require(not active_owner(obj, active), "Active workload ownership overrides retirement plan")
        owners = obj["metadata"].get("ownerReferences", [])
        parent_anchor = False
        if owners:
            require(len(owners) == 1 and owners[0].get("controller") is True, "Ambiguous retired workload ownership")
            owner = owners[0]
            owner_key = (owner.get("kind"), key[1], owner.get("name"))
            require(owner.get("kind") in WORKLOADS and owner.get("apiVersion") == WORKLOADS[owner["kind"]][1]
                    and owner_key in known, "Unknown retired workload owner")
            same_uid(known[owner_key], owner.get("uid"))
            _, parent_anchor = visit(owner_key, trail | {key})
        direct = planned.get(key) == obj["metadata"]["uid"]
        result = (direct or parent_anchor, (direct and key[0] != "Pod") or parent_anchor)
        approved[key] = result
        return result

    for key in known:
        if key[1] in retired:
            require(visit(key, set())[0], "Unplanned or foreign workload in archived namespace")
    return known


def namespace_effects_check(plan, snapshot, known):
    retired = {item["name"] for item in plan["namespaces"]}
    projected = set()
    for obj in snapshot["namespace_metadata"]:
        metadata = obj["metadata"]
        if metadata["namespace"] not in retired:
            continue
        require((obj["apiVersion"], obj["kind"]) in NAMESPACE_KINDS, "Namespace has an unapproved deletion-effect resource")
        key = (obj["kind"], metadata["namespace"], metadata["name"])
        if obj["kind"] in WORKLOADS:
            require(key in known and same_uid(known[key], metadata["uid"]), "Workload changed during namespace metadata discovery")
        elif obj["kind"] == "PersistentVolumeClaim":
            pvc = snapshot["persistentvolumeclaims"].get((metadata["namespace"], metadata["name"]))
            require(pvc is not None and same_uid(pvc, metadata["uid"]), "PVC changed during namespace metadata discovery")
        projected.add((*key, metadata["uid"]))
    for (kind, namespace, resource_name), obj in known.items():
        if namespace in retired:
            require((kind, namespace, resource_name, obj["metadata"]["uid"]) in projected, "Workload missing from metadata inventory")
    for (namespace, resource_name), pvc in snapshot["persistentvolumeclaims"].items():
        if namespace in retired:
            require(("PersistentVolumeClaim", namespace, resource_name, pvc["metadata"]["uid"]) in projected,
                    "PVC missing from namespace metadata inventory")


def same_uid(obj, uid):
    if obj is not None:
        require(obj["metadata"]["uid"] == uid, "Replacement UID refused")
    return obj


def nfs(pv):
    spec = pv.get("spec", {})
    return ("nfs" in spec or spec.get("storageClassName") == "nfs-rwx"
            or "nfs" in spec.get("csi", {}).get("driver", "").lower())


def is_rbd(pv):
    spec = pv.get("spec", {})
    csi = spec.get("csi", {})
    attrs = csi.get("volumeAttributes", {})
    driver = csi.get("driver", "").lower()
    return ("rbd" in spec or "rbd" in driver or "imageName" in attrs
            or ("clusterID" in attrs and "pool" in attrs and not driver.endswith("cephfs.csi.ceph.com")))


def rbd_identity(pv, storageclasses):
    spec = pv.get("spec", {})
    csi = spec.get("csi", {})
    attrs = csi.get("volumeAttributes", {})
    require(isinstance(attrs, dict), "Unresolved RBD physical identity")
    cluster, pool = attrs.get("clusterID"), attrs.get("pool")
    require(cluster and pool, "RBD clusterID and pool are required")
    identity(cluster)
    identity(pool)
    require(not attrs.get("radosNamespace"), "RBD namespace identity is unsupported")
    if "imageName" in attrs:
        return cluster, pool, identity(attrs["imageName"])
    require(str(attrs.get("staticVolume", "false")).lower() == "false", "Static RBD image identity is unresolved")
    sc = storageclasses.get(("", spec.get("storageClassName")))
    require(spec.get("storageClassName") == "standard-rwo" and sc is not None
            and sc.get("provisioner") == csi.get("driver"), "Default RBD derivation requires matching standard-rwo provisioner")
    parameters = sc.get("parameters", {})
    require(isinstance(parameters, dict)
            and parameters.get("clusterID") == cluster and parameters.get("pool") == pool
            and not parameters.get("radosNamespace")
            and str(parameters.get("staticVolume", "false")).lower() == "false" and "imageName" not in parameters
            and not any("prefix" in key.lower() for source in (parameters, attrs) for key in source),
            "Custom or inconsistent RBD parameters prevent image derivation")
    handle = csi.get("volumeHandle", "")
    prefix = re.match(r"0001-([0-9a-f]{4})-", handle)
    require(prefix is not None, "Unknown RBD volumeHandle format")
    length = int(prefix.group(1), 16)
    rest = handle[prefix.end():]
    require(length == len(cluster) and rest[:length] == cluster, "RBD handle clusterID mismatch")
    suffix = re.fullmatch(r"-[0-9a-f]{16}-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", rest[length:])
    require(suffix is not None, "Unknown RBD pool/image handle format")
    return cluster, pool, "csi-vol-" + suffix.group(1)


def inline_csi(spec):
    if isinstance(spec, dict):
        if isinstance(spec.get("csi"), dict):
            yield spec["csi"]
        for key, value in spec.items():
            if key not in ("metadata", "status", "env", "envFrom"):
                yield from inline_csi(value)
    elif isinstance(spec, list):
        for value in spec:
            yield from inline_csi(value)


def rbd_alias_check(plan, snapshot, skipped, workloads):
    targets = {item["name"]: snapshot["persistentvolumes"][("", item["name"])] for item in plan["volumes"]
               if item["name"] not in skipped and ("", item["name"]) in snapshot["persistentvolumes"]}
    if not targets:
        return
    classes = snapshot["storageclasses.storage.k8s.io"]
    physical = {pv["metadata"]["name"]: rbd_identity(pv, classes)
                for pv in snapshot["persistentvolumes"].values() if is_rbd(pv)}
    for target, pv in targets.items():
        require(target in physical, "Planned RBD image identity is unresolved")
        require(all(image[0] == physical[target][0] for image in physical.values()),
                "Different CSI clusterIDs have unproven physical disjointness")
        require(not any(other != target and image == physical[target] for other, image in physical.items()),
                "Another PV aliases the same physical RBD image")
        for obj in workloads:
            for csi in inline_csi(obj.get("spec", {})):
                require(csi.get("volumeHandle") != pv["spec"]["csi"]["volumeHandle"], "Inline shared backend handle is protected")
                candidate = {"spec": {"csi": csi}}
                if is_rbd(candidate):
                    inline_image = rbd_identity(candidate, classes)
                    require(inline_image[0] == physical[target][0], "Inline CSI clusterID has unproven physical disjointness")
                    require(inline_image != physical[target], "Inline CSI aliases a planned physical RBD image")


def retained(obj):
    if not obj:
        return False
    if obj.get("spec", {}).get("persistentVolumeReclaimPolicy") == "Retain":
        return True
    metadata = obj.get("metadata", {})
    for category in ("labels", "annotations"):
        for key, value in metadata.get(category, {}).items():
            key, value = key.lower(), str(value).lower().strip()
            if key == "helm.sh/resource-policy" and value == "keep":
                return True
            if key == "argocd.argoproj.io/sync-options" and any(
                    re.sub(r"\s", "", option) in ("prune=false", "delete=false", "prune=confirm", "delete=confirm")
                    for option in value.split(",")):
                return True
            if any(word in key for word in ("retain", "persist", "keep", "protect")) and value in (
                    "true", "yes", "1", "keep", "retain", "retained", "enabled", "always"):
                return True
    # Native PVC/CSI protection finalizers are lifecycle coordination, not owner retention flags.
    return False


def claim_references(obj):
    """Read pod templates recursively without inspecting or emitting environment values."""
    result = set()
    if isinstance(obj, dict):
        claim = obj.get("persistentVolumeClaim")
        if isinstance(claim, dict) and claim.get("claimName"):
            result.add(claim["claimName"])
        for key, value in obj.items():
            if key not in ("metadata", "env", "envFrom", "status"):
                result.update(claim_references(value))
    elif isinstance(obj, list):
        for value in obj:
            result.update(claim_references(value))
    return result


def inline_nfs(obj):
    if isinstance(obj, dict):
        if "nfs" in obj or "nfs" in obj.get("csi", {}).get("driver", "").lower():
            return True
        return any(inline_nfs(value) for key, value in obj.items()
                   if key not in ("metadata", "env", "envFrom", "status"))
    return isinstance(obj, list) and any(inline_nfs(value) for value in obj)


def active_owner(obj, active):
    metadata = obj.get("metadata", {})
    for category in ("labels", "annotations"):
        values = metadata.get(category, {})
        if any(values.get(key) in active for key in (
                "app.kubernetes.io/instance", "app.kubernetes.io/name", "argocd.argoproj.io/instance",
                "meta.helm.sh/release-name", "meta.helm.sh/release-namespace")):
            return True
        if values.get("argocd.argoproj.io/tracking-id", "").split(":")[0] in active:
            return True
    return False


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.utcoffset() == timedelta(0), "Job evidence must use UTC timestamps")
        return parsed
    except (AttributeError, TypeError, ValueError):
        raise Refusal("Missing or invalid Job time evidence") from None


def condition(obj, kind):
    return any(item.get("type") == kind and item.get("status") == "True"
               for item in obj.get("status", {}).get("conditions", []))


def cron_timezone(value):
    require(isinstance(value, str) and len(value) <= 255
            and re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", value)
            and value not in ("localtime", "posixrules") and not value.startswith(("posix/", "right/")),
            "Verified IANA cronjob_timezone is required")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise Refusal("IANA cronjob_timezone is unavailable; no timezone fallback") from None


def daily_fields(schedule):
    require(isinstance(schedule, str), "Only a fixed daily Renovate cron expression is supported")
    match = re.fullmatch(r"([0-9]{1,2})[ \t]+([0-9]{1,2})[ \t]+\*[ \t]+\*[ \t]+\*", schedule)
    require(match is not None, "Only minute hour * * * daily Renovate scheduling is supported")
    minute, hour = map(int, match.groups())
    require(0 <= minute < 60 and 0 <= hour < 24, "Invalid fixed daily Renovate time")
    return minute, hour


def latest_daily_due(schedule, timezone_name, now):
    minute, hour = daily_fields(schedule)
    zone = cron_timezone(timezone_name)
    require(now.utcoffset() is not None, "Current scheduling evidence needs an aware timestamp")
    cutoff = now.astimezone(timezone.utc) - timedelta(minutes=5)
    candidates = set()
    for days in range(3):
        date = cutoff.astimezone(zone).date() - timedelta(days=days)
        for fold in (0, 1):
            local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone, fold=fold)
            utc = local.astimezone(timezone.utc)
            roundtrip = utc.astimezone(zone)
            if (roundtrip.date(), roundtrip.hour, roundtrip.minute, roundtrip.fold) == (date, hour, minute, fold) and utc <= cutoff:
                candidates.add(utc)
    require(candidates, "Cannot resolve a supported daily Renovate occurrence")
    return max(candidates)


def owned_job(job, goal):
    owners = [owner for owner in job["metadata"].get("ownerReferences", []) if owner.get("controller") is True]
    return (len(owners) == 1 and owners[0].get("kind") == "CronJob"
            and owners[0].get("apiVersion") == "batch/v1"
            and owners[0].get("name") == goal["cronjob_name"]
            and owners[0].get("uid") == goal["cronjob_uid"])


def renovate_pods_check(snapshot, job, complete, now):
    pods = [pod for (ns, _), pod in snapshot["pods"].items() if ns == "renovate" and any(
        owner.get("uid") == job["metadata"]["uid"] for owner in pod["metadata"].get("ownerReferences", []))]
    for pod in pods:
        owners = pod["metadata"].get("ownerReferences", [])
        require(len(owners) == 1 and owners[0].get("controller") is True
                and owners[0].get("kind") == "Job" and owners[0].get("apiVersion") == "batch/v1"
                and owners[0].get("name") == job["metadata"]["name"], "Renovate Pod owner evidence is inconsistent")
        status = pod.get("status", {})
        require(status.get("phase") in ("Pending", "Running", "Succeeded"), "A newer Renovate Pod has failed or unknown state")
        require(not any(condition.get("type") == "PodScheduled" and condition.get("status") == "False"
                        for condition in status.get("conditions", [])), "A newer Renovate Pod cannot be scheduled")
        for container in status.get("containerStatuses", []) + status.get("initContainerStatuses", []) + status.get("ephemeralContainerStatuses", []):
            require(not container.get("restartCount", 0), "A newer Renovate Pod is retrying")
            for state in (container.get("state", {}), container.get("lastState", {})):
                if "terminated" in state:
                    require(type(state["terminated"].get("exitCode")) is int and state["terminated"]["exitCode"] == 0,
                            "A newer Renovate container exited unsuccessfully")
                if "waiting" in state:
                    require(state["waiting"].get("reason") in ("ContainerCreating", "PodInitializing"),
                            "A newer Renovate container has an unhealthy waiting reason")
    if not complete:
        require(pods and job.get("status", {}).get("active", 0) > 0, "Current Renovate execution lacks active Pod evidence")
        require(sum(pod.get("status", {}).get("phase") in ("Running", "Pending")
                    and not pod["metadata"].get("deletionTimestamp") for pod in pods) >= job["status"]["active"],
                "Current Renovate execution lacks its reported active Pods")
        for pod in pods:
            created = instant(pod["metadata"].get("creationTimestamp"))
            require(instant(job["metadata"].get("creationTimestamp")) <= created <= now, "Invalid current Renovate Pod time")
            status = pod.get("status", {})
            if status.get("phase") in ("Running", "Pending"):
                containers = status.get("containerStatuses", [])
                require(containers, "Current Renovate container state is unknown")
                if status["phase"] == "Running":
                    require(all(container.get("ready") is True and "running" in container.get("state", {})
                                for container in containers), "Current Renovate containers are not ready")
                else:
                    require(all(container.get("state", {}).get("waiting", {}).get("reason") in (
                        "ContainerCreating", "PodInitializing") or (container.get("ready") is True
                        and "running" in container.get("state", {})) for container in containers),
                        "Current Renovate initialization state is unknown")


def historical_check(snapshot, goal, now):
    cron = same_uid(snapshot["cronjobs.batch"].get(("renovate", "renovate")), goal["cronjob_uid"])
    require(cron is not None and not cron["metadata"].get("deletionTimestamp")
            and not cron.get("spec", {}).get("suspend"), "Healthy owning Renovate CronJob required")
    success = instant(cron.get("status", {}).get("lastSuccessfulTime"))
    require(now - timedelta(hours=36) <= success <= now, "Renovate last success must be within 36 hours")
    scheduled = instant(cron.get("status", {}).get("lastScheduleTime"))
    require(now - timedelta(hours=36) <= scheduled <= now, "Renovate last schedule must be within 36 hours")
    spec = cron.get("spec", {})
    zone_name = goal["cronjob_timezone"]
    require("timeZone" not in spec or spec["timeZone"] == zone_name, "CronJob timeZone differs from committed plan")
    schedule = spec.get("schedule")
    require(scheduled >= latest_daily_due(schedule, zone_name, now), "Latest due daily Renovate schedule was missed beyond five-minute grace")
    minute, hour = daily_fields(schedule)
    local_scheduled = scheduled.astimezone(cron_timezone(zone_name))
    require((local_scheduled.hour, local_scheduled.minute, local_scheduled.second, local_scheduled.microsecond)
            == (hour, minute, 0, 0), "Renovate lastScheduleTime does not match the fixed daily schedule")
    job = same_uid(snapshot["jobs.batch"].get(("renovate", goal["name"])), goal["uid"])
    if job:
        require(owned_job(job, goal) and condition(job, "Failed") and not condition(job, "Complete")
                and not job.get("status", {}).get("active"), "Historical Job must be terminal Failed with exact owner")
    owned = [item for (ns, _), item in snapshot["jobs.batch"].items()
             if ns == "renovate" and owned_job(item, goal) and item["metadata"]["uid"] != goal["uid"]]
    healthy = [item for item in owned if condition(item, "Complete") and not item.get("status", {}).get("active")
               and not item["metadata"].get("deletionTimestamp")
               and (job is None or instant(item["metadata"].get("creationTimestamp"))
                    > instant(job["metadata"].get("creationTimestamp")))
               and now - timedelta(hours=36) <= instant(item["metadata"].get("creationTimestamp")) <= now
               and instant(item.get("status", {}).get("completionTime")) == success]
    require(healthy, "A healthy newer Completed Job must corroborate the latest CronJob success")
    # On resume, the deleted Job has no creation time. Use the corroborated successful run as the floor.
    floor = (instant(job["metadata"].get("creationTimestamp")) if job else
             max(instant(item["metadata"].get("creationTimestamp")) for item in healthy))
    newer = [item for item in owned if instant(item["metadata"].get("creationTimestamp")) >= floor
             or (job is None and not condition(item, "Complete") and (
                 item.get("status", {}).get("active", 0) > 0
                 or instant(item["metadata"].get("creationTimestamp")) >= now - timedelta(hours=36)))]
    represented = False
    for item in newer:
        created = instant(item["metadata"].get("creationTimestamp"))
        require(created <= now and not item["metadata"].get("deletionTimestamp"), "Newer Renovate Job time/state is invalid")
        require(not condition(item, "Failed") and not condition(item, "FailureTarget"), "A newer Renovate failure remains unresolved")
        complete = condition(item, "Complete")
        if complete:
            require(not item.get("status", {}).get("active")
                    and created <= instant(item.get("status", {}).get("completionTime")) <= now, "Completed Renovate evidence is invalid")
        else:
            require(not item.get("status", {}).get("failed", 0), "A newer Renovate Job is retrying failed Pods")
            require(now - created <= timedelta(minutes=30), "Current Renovate execution exceeds its 30-minute runtime window")
        renovate_pods_check(snapshot, item, complete, now)
        source_time = item["metadata"].get("annotations", {}).get("batch.kubernetes.io/cronjob-scheduled-timestamp")
        if source_time:
            matched = instant(source_time) == scheduled and scheduled <= created <= scheduled + timedelta(minutes=2)
        else:
            matched = scheduled <= created <= scheduled + timedelta(minutes=2)
        represented = represented or matched
    require(represented, "Latest Renovate schedule lacks a completed or healthy recent owned Job")
    newer_uids = {item["metadata"]["uid"] for item in newer}
    require(all(ref.get("uid") in newer_uids for ref in cron.get("status", {}).get("active", [])),
            "Renovate CronJob references unverified active work")


def preflight(plan, source, snapshot, now):
    validate_plan(plan)
    retired = {item["name"] for item in plan["namespaces"]}
    scopes = retired | {item["claim_namespace"] for item in plan["volumes"]}
    require(not scopes.intersection(source["active"]), "Active chart or release namespace is protected")
    for app in snapshot["applications.argoproj.io"].values():
        require(app.get("spec", {}).get("destination", {}).get("namespace") not in scopes,
                "Live Argo Application still targets retirement scope, including Terminating Applications")
    for item in plan["namespaces"]:
        require(item["archived_path"] in source["directories"], "Archive directory is not committed in HEAD")
        aliases = source["archive_aliases"].get(item["archived_path"], set())
        require(item["name"] in aliases, "Namespace does not match archive basename or explicit Chart name")
        require(not aliases.intersection(source["active"]), "Active replacement basename or archive alias is protected")
        same_uid(snapshot["namespaces"].get(("", item["name"])), item["uid"])
    needles = {item[key] for item in plan["volumes"] for key in ("name", "volume_handle")}
    for text in source["texts"]:
        text = strip_source_comments(text)
        require(not any(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", text)
                         for value in needles), "Active chart source references retirement identity")
        require(not scopes.intersection(namespace_references(text)), "Active chart has a direct retirement namespace reference")
    goals = {(item["claim_namespace"], item["claim_name"]): item for item in plan["volumes"]}
    for (ns, claim), pvc in snapshot["persistentvolumeclaims"].items():
        if ns in retired:
            require((ns, claim) in goals, "Namespace contains an unplanned protected PVC")
    planned_pvs = {item["name"] for item in plan["volumes"]}
    for pv in snapshot["persistentvolumes"].values():
        if pv.get("spec", {}).get("claimRef", {}).get("namespace") in retired:
            require(not nfs(pv), "Namespace has protected NFS PV ownership, even without a live PVC")
            require(pv["metadata"]["name"] in planned_pvs, "Namespace has an unplanned PV claimRef, even without a live PVC")
    known = retired_ownership(plan, snapshot, source["active"])
    namespace_effects_check(plan, snapshot, known)
    workloads = list(known.values())
    require(not any(obj["metadata"].get("namespace") not in retired
                    and scopes.intersection(env_references(obj.get("spec", {}))) for obj in workloads),
            "Live workload endpoint env references retirement namespace; values withheld")
    require(not any(obj["metadata"].get("namespace") in retired and inline_nfs(obj.get("spec", {}))
                    for obj in workloads), "Namespace contains protected inline NFS storage")
    require(not any(obj["metadata"].get("namespace") in retired and any(inline_csi(obj.get("spec", {})))
                    for obj in workloads), "Namespace contains unsupported inline CSI deletion effects")
    require(not any(obj["metadata"].get("namespace") in retired and active_owner(obj, source["active"])
                    for obj in workloads), "Active chart workload in retired namespace is protected")
    skipped = set()
    for item in plan["volumes"]:
        pair = (item["claim_namespace"], item["claim_name"])
        pv = same_uid(snapshot["persistentvolumes"].get(("", item["name"])), item["uid"])
        pvc = same_uid(snapshot["persistentvolumeclaims"].get(pair), item["claim_uid"])
        require(not any(active_owner(obj, source["active"]) for obj in (pv, pvc) if obj),
                "Active chart storage ownership is protected")
        require(item["driver"] == DRIVER, "Unknown or NFS planned backend refused")
        if pvc:
            require(item["disposition"] != "deleted-unarchived" or not pvc["metadata"].get("ownerReferences"),
                    "Orphan PVC ownerReferences are unresolved or still present")
            if item["disposition"] == "archived":
                owners = pvc["metadata"].get("ownerReferences", [])
                require(isinstance(owners, list) and all(isinstance(owner, dict) for owner in owners),
                        "Malformed archived PVC ownerReferences")
                seen_owners = set()
                require(sum(owner.get("controller") is True for owner in owners) <= 1,
                        "Ambiguous archived PVC ownership")
                for owner in owners:
                    owner_key = (owner.get("kind"), pair[0], owner.get("name"))
                    require(owner.get("kind") in WORKLOADS
                            and owner.get("apiVersion") == WORKLOADS[owner["kind"]][1]
                            and owner.get("namespace", pair[0]) == pair[0] and owner_key in known,
                            "Unknown or cross-scope archived PVC owner")
                    same_uid(known[owner_key], owner.get("uid"))
                    require(owner["uid"] not in seen_owners, "Ambiguous archived PVC ownership")
                    seen_owners.add(owner["uid"])
            require(pvc.get("spec", {}).get("volumeName") == item["name"] and pv is not None,
                    "Claim is unbound, changed, or has no corresponding PV")
            require(pvc.get("spec", {}).get("storageClassName") == "standard-rwo", "Unknown or NFS claim class refused")
        if pv:
            spec = pv.get("spec", {})
            require(not nfs(pv), "NFS PV and its namespace are always protected")
            require(spec.get("storageClassName") == "standard-rwo" and spec.get("csi", {}).get("driver") == DRIVER
                    and spec["csi"].get("volumeHandle") == item["volume_handle"], "Unknown or changed PV backend")
            require(spec.get("persistentVolumeReclaimPolicy") in ("Retain", "Delete"), "Unknown reclaim policy")
            claim = spec.get("claimRef")
            if claim:
                require((claim.get("namespace"), claim.get("name"), claim.get("uid"))
                        == (*pair, item["claim_uid"]), "PV claim identity changed")
            else:
                require(pvc is None and pv.get("status", {}).get("phase") in ("Available", "Released"),
                        "PV lacks trustworthy claim ownership evidence")
        for other in snapshot["persistentvolumes"].values():
            if other["metadata"]["name"] != item["name"]:
                require(other.get("spec", {}).get("csi", {}).get("volumeHandle") != item["volume_handle"],
                        "Shared backend volumeHandle is protected")
        for other_pair, other in snapshot["persistentvolumeclaims"].items():
            require(other_pair == pair or other.get("spec", {}).get("volumeName") != item["name"],
                    "Another PVC references the planned PV")
        for obj in workloads:
            ns = obj["metadata"].get("namespace")
            refs = claim_references(obj.get("spec", {}))
            refs.update(obj["metadata"]["name"] + "-" + volume["name"]
                        for volume in obj.get("spec", {}).get("volumes", []) if "ephemeral" in volume)
            # StatefulSet claim templates also represent future consumers at zero replicas.
            templates = obj.get("spec", {}).get("volumeClaimTemplates", [])
            referenced = item["claim_name"] in refs or any(
                item["claim_name"].startswith(template.get("metadata", {}).get("name", "")
                                              + "-" + obj["metadata"]["name"] + "-")
                for template in templates)
            owned = pvc is not None and any(owner.get("uid") == obj["metadata"]["uid"]
                                           for owner in pvc["metadata"].get("ownerReferences", []))
            if (ns == pair[0] and referenced) or owned:
                require(item["disposition"] == "archived" and ns in retired,
                        "Orphan PVC still has a Pod or controller consumer")
            # Inline CSI aliases may expose the same RBD without a PVC.
            require(not any(csi.get("volumeHandle") == item["volume_handle"] for csi in inline_csi(obj.get("spec", {}))),
                    "Inline shared backend reference is protected")
        attachments = [obj for obj in snapshot["volumeattachments.storage.k8s.io"].values()
                       if obj.get("spec", {}).get("source", {}).get("persistentVolumeName") == item["name"]]
        if item["disposition"] == "deleted-unarchived":
            if retained(pv) or retained(pvc):
                skipped.add(item["name"])
            else:
                require(not attachments, "Orphan PV still has a VolumeAttachment")
    rbd_alias_check(plan, snapshot, skipped, workloads)
    for goal in plan["historical_jobs"]:
        historical_check(snapshot, goal, now)
    return skipped


def resource_args(resource, resource_name, namespace=""):
    require(resource in ("namespaces", "persistentvolumes", "persistentvolumeclaims", "jobs.batch"),
            "Unsupported exact resource read")
    name(resource_name, resource == "namespaces")
    if namespace:
        name(namespace, True)
    return ["get", resource, resource_name] + (["-n", namespace] if namespace else []) + ["--ignore-not-found", "-o", "json"]


def get_goal(api, resource, resource_name, uid, namespace=""):
    text = api.run(resource_args(resource, resource_name, namespace))
    try:
        obj = json.loads(text) if text.strip() else None
    except ValueError:
        raise Refusal("Invalid exact-resource GET response") from None
    if text.strip():
        require(isinstance(obj, dict) and isinstance(obj.get("metadata"), dict), "Invalid exact-resource GET response")
        require(obj["metadata"]["name"] == resource_name
                and obj["metadata"].get("namespace", "") == namespace, "GET resource identity mismatch")
        identity(obj["metadata"]["resourceVersion"])
    return same_uid(obj, uid)


def delete_path(resource, resource_name, namespace=""):
    require(resource in ("namespaces", "persistentvolumeclaims", "jobs.batch"), "Direct PV deletion is not supported")
    resource_args(resource, resource_name, namespace)
    require(bool(namespace) == (resource != "namespaces"), "Delete resource scope mismatch")
    if resource == "jobs.batch":
        return f"/apis/batch/v1/namespaces/{namespace}/jobs/{resource_name}"
    if resource == "persistentvolumeclaims":
        return f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{resource_name}"
    return f"/api/v1/{resource}/{resource_name}"


def reclaim_patch(pv, item):
    return [{"op": "test", "path": path, "value": value} for path, value in (
        ("/metadata/uid", item["uid"]), ("/metadata/resourceVersion", pv["metadata"]["resourceVersion"]),
        ("/spec/csi/driver", DRIVER), ("/spec/csi/volumeHandle", item["volume_handle"]),
        ("/spec/storageClassName", "standard-rwo"), ("/spec/persistentVolumeReclaimPolicy", "Retain"))] + [
            {"op": "replace", "path": "/spec/persistentVolumeReclaimPolicy", "value": "Delete"}]


def mutate(api, resource, obj, item=None):
    metadata = obj["metadata"]
    resource_name, uid = metadata["name"], metadata["uid"]
    namespace = metadata.get("namespace", "")
    if item is None:
        options = {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground",
                   "preconditions": {"uid": uid, "resourceVersion": metadata["resourceVersion"]}}
        args = ["delete", "--raw", delete_path(resource, resource_name, namespace), "-f", "-"]
        payload = json.dumps(options)
    else:
        require(resource == "persistentvolumes" and item["disposition"] == "archived" and not nfs(obj),
                "Only archived RBD reclaim policy can be patched")
        args = ["patch", "persistentvolumes", name(resource_name), "--type=json", "-p", json.dumps(reclaim_patch(obj, item))]
        payload = None
    try:
        api.run(args, payload)
    except Exception:
        # Never retry a write. Resolve UID identity before returning an uncertain outcome.
        current = get_goal(api, resource, resource_name, uid, namespace)
        raise Refusal("Mutation failed or outcome unknown; exact UID GET shows "
                      + ("absence" if current is None else "same UID still present")
                      + "; rerun check before resuming") from None


def wait_absent(api, resource, resource_name, uid, namespace="", clock=time.monotonic, sleep=time.sleep, end=None):
    end = clock() + 600 if end is None else end
    while get_goal(api, resource, resource_name, uid, namespace) is not None:
        require(clock() < end, "Timed out waiting for owning-controller deletion; finalizers remain untouched")
        sleep(min(2, max(0, end - clock())))


def wait_detached(api, item, end, clock, sleep):
    while True:
        get_goal(api, "persistentvolumes", item["name"], item["uid"])
        document = api.json(["get", "volumeattachments.storage.k8s.io", "-o", "json"])
        require(isinstance(document, dict) and isinstance(document.get("items"), list), "Invalid attachment evidence")
        if not any(obj.get("spec", {}).get("source", {}).get("persistentVolumeName") == item["name"]
                   for obj in document["items"]):
            return
        require(clock() < end, "Timed out waiting for CSI detach; VolumeAttachments remain untouched")
        sleep(min(2, max(0, end - clock())))


def execute(api, plan, gate, apply=False, emit=lambda receipt: None,
            clock=time.monotonic, sleep=time.sleep, now=lambda: datetime.now(timezone.utc)):
    """All evidence gates finish before the first write; refresh them before every write."""
    first_source = gate()
    expected_head = first_source["head"]
    namespaces = [item["name"] for item in plan["namespaces"]]

    def checked():
        source = gate()
        require(source["head"] == expected_head, "Committed retirement revision changed during execution")
        snapshot = collect(api, namespaces)
        skips = preflight(plan, source, snapshot, now())
        return snapshot, skips

    initial = collect(api, namespaces)
    protected = preflight(plan, first_source, initial, now())
    emit({"event": "checked", "head": expected_head, "apply": apply, "protected_pvs": sorted(protected),
          "namespace_objects_checked": sum(obj["metadata"]["namespace"] in namespaces for obj in initial["namespace_metadata"])})
    if not apply:
        return
    for goal in plan["namespaces"]:
        snapshot, skips = checked()
        require(skips == protected, "Protection flags changed during execution")
        obj = snapshot["namespaces"].get(("", goal["name"]))
        if obj is not None and not obj["metadata"].get("deletionTimestamp"):
            mutate(api, "namespaces", obj)
            emit({"event": "namespace-delete-requested", "name": goal["name"], "uid": goal["uid"]})
        wait_absent(api, "namespaces", goal["name"], goal["uid"], clock=clock, sleep=sleep)
    for item in plan["volumes"]:
        if item["name"] in protected:
            emit({"event": "protected-storage-skipped", "name": item["name"], "uid": item["uid"]})
            continue
        end = clock() + 600
        snapshot, skips = checked()
        require(skips == protected, "Protection flags changed during execution")
        pv = snapshot["persistentvolumes"].get(("", item["name"]))
        pvc = snapshot["persistentvolumeclaims"].get((item["claim_namespace"], item["claim_name"]))
        if item["disposition"] == "deleted-unarchived" and pvc and not pvc["metadata"].get("deletionTimestamp"):
            mutate(api, "persistentvolumeclaims", pvc)
            emit({"event": "pvc-delete-requested", "name": item["claim_name"], "namespace": item["claim_namespace"],
                  "uid": item["claim_uid"]})
        wait_absent(api, "persistentvolumeclaims", item["claim_name"], item["claim_uid"],
                    item["claim_namespace"], clock, sleep, end)
        wait_detached(api, item, end, clock, sleep)
        if pv and pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain":
            require(item["disposition"] == "archived", "Retained orphan must stay")
            snapshot, skips = checked()
            require(skips == protected, "Protection flags changed during execution")
            require(not any(obj.get("spec", {}).get("source", {}).get("persistentVolumeName") == item["name"]
                            for obj in snapshot["volumeattachments.storage.k8s.io"].values()),
                    "VolumeAttachment remains; wait for CSI before resuming")
            current = snapshot["persistentvolumes"].get(("", item["name"]))
            if current and current["spec"]["persistentVolumeReclaimPolicy"] == "Retain":
                mutate(api, "persistentvolumes", current, item)
                emit({"event": "archived-reclaim-delete-requested", "name": item["name"], "uid": item["uid"]})
        wait_absent(api, "persistentvolumes", item["name"], item["uid"], clock=clock, sleep=sleep, end=end)
    for goal in plan["historical_jobs"]:
        snapshot, skips = checked()
        require(skips == protected, "Protection flags changed during execution")
        obj = snapshot["jobs.batch"].get(("renovate", goal["name"]))
        if obj and not obj["metadata"].get("deletionTimestamp"):
            mutate(api, "jobs.batch", obj)
        wait_absent(api, "jobs.batch", goal["name"], goal["uid"], "renovate", clock, sleep)
        emit({"event": "owner-closed-historical", "namespace": "renovate", "name": goal["name"],
              "uid": goal["uid"], "root_cause_repaired": False})
    final, skips = checked()
    require(skips == protected, "Protected storage changed during execution")
    for goal in plan["namespaces"]:
        require(("", goal["name"]) not in final["namespaces"], "Namespace absence not verified")
    for item in plan["volumes"]:
        pair = (item["claim_namespace"], item["claim_name"])
        for resource, key in (("persistentvolumes", ("", item["name"])), ("persistentvolumeclaims", pair)):
            if item["name"] in protected:
                before = initial[resource].get(key)
                after = final[resource].get(key)
                require((before is None) == (after is None), "Protected storage presence changed")
            else:
                require(key not in final[resource], "Planned storage absence not verified")
        require(item["name"] in protected or not any(
            obj.get("spec", {}).get("source", {}).get("persistentVolumeName") == item["name"]
            for obj in final["volumeattachments.storage.k8s.io"].values()), "VolumeAttachment absence not verified")
    for goal in plan["historical_jobs"]:
        require(("renovate", goal["name"]) not in final["jobs.batch"], "Historical Job absence not verified")
    emit({"event": "planned-absence-verified", "head": expected_head,
          "protected_pvs": sorted(protected), "physical_bytes_reclaimed": "not-measured"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Committed repository-relative scripts/retirements/<run>.json")
    parser.add_argument("--apply", action="store_true", help="Execute the already-authorized exact plan, without prompts")
    args = parser.parse_args(argv)
    try:
        source = source_gate(args.plan)
        raw = (ROOT / args.plan).read_bytes()
        plan = decode_plan(raw)

        def gate():
            current = source_gate(args.plan)
            require(current["head"] == source["head"] and (ROOT / args.plan).read_bytes() == raw,
                    "Approved source or plan changed")
            return current

        cache = os.environ.get("KUBECACHEDIR")
        require(cache and Path(cache).is_absolute() and Path(cache).resolve() == Path(cache),
                "Parent-provided absolute, non-symlink KUBECACHEDIR is required")
        Path(cache).mkdir(mode=0o700, exist_ok=True)
        require(Path(cache).is_dir() and Path(cache).resolve() == Path(cache), "Unsafe kubectl cache directory")
        api = load_api()
        api.base.extend(["--cache-dir", cache])
        cluster_uid = api.establish()

        def live_gate():
            current = gate()
            require(api.cluster_uid() == cluster_uid, "Cluster UID changed")
            return current

        print(json.dumps({"event": "identity", "head": source["head"], "cluster_uid": cluster_uid}), flush=True)
        with metadata_api(api) as client:
            execute(client, plan, live_gate, args.apply, lambda receipt: print(json.dumps(receipt, sort_keys=True), flush=True))
        return 0
    except Refusal as error:
        print("Retirement blocked: " + str(error), file=sys.stderr)
    except KeyboardInterrupt:
        print("Retirement interrupted; rerun check against the same committed plan before resuming", file=sys.stderr)
    except Exception:
        print("Retirement blocked: inaccessible or malformed evidence; diagnostics withheld", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
