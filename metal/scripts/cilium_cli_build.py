#!/usr/bin/env python3
"""Build the pinned, isolated HA qualification CLI with its narrow Service overlay."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import tempfile


CLI_VERSION = "v0.20.1-homelab.103"
SOURCE_SHA256 = "3c9c6a261baa52ee3365c41e6501eef956d046133360685ab2b5fc00bad7b683"
SOURCE_URL = "https://github.com/cilium/cilium-cli/archive/refs/tags/v0.20.1.tar.gz"
GO_URL = "https://go.dev/dl/go1.27.3.darwin-arm64.tar.gz"
GO_SHA256 = "dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2"
PACKAGE = "github.com/cilium/cilium/cilium-cli/connectivity/tests"
OVERLAY = Path(__file__).with_name("cilium_cli_overlay")
OLD = '''\t\t\t\t\ta.ExecInPod(ctx, a.CurlCommand(svc))

\t\t\t\t\ta.ValidateFlows(ctx, pod, a.GetEgressRequirements(check.FlowParameters{
\t\t\t\t\t\tDNSRequired: true,
\t\t\t\t\t\tAltDstPort:  svc.Port(),
\t\t\t\t\t}))'''
NEW = '''\t\t\t\t\tparams, err := qualificationServiceFlowParameters(svc, ipFamily, ct.EchoPods(),
\t\t\t\t\t\tct.Features[features.KPRSocketLB].Enabled && !ct.Features[features.KPRSocketLBHostnsOnly].Enabled)
\t\t\t\t\tif err != nil {
\t\t\t\t\t\ta.Fatalf("Invalid qualification Service/backend: %s", err)
\t\t\t\t\t\treturn
\t\t\t\t\t}
\t\t\t\t\ta.ExecInPod(ctx, a.CurlCommand(svc))

\t\t\t\t\ta.ValidateFlows(ctx, pod, a.GetEgressRequirements(params))'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(archive, go, work, output):
    work = work.resolve(strict=True)
    if (not work.is_dir() or work.stat().st_uid != os.getuid() or work.stat().st_mode & 0o077 or
            output.exists() or not output.is_absolute() or output.parent.resolve(strict=True) != work or
            digest(archive) != SOURCE_SHA256):
        raise RuntimeError("private work directory, absent owned output and exact source archive required")
    scratch = Path(tempfile.mkdtemp(prefix="cli-build-", dir=work))
    evidence = work / "cli-build-evidence"
    evidence.mkdir(mode=0o700)
    env = {**os.environ, "GOCACHE": str(scratch / "cache"), "GOMODCACHE": str(scratch / "modules"),
           "GOPATH": str(scratch / "gopath"), "GOTMPDIR": str(scratch / "tmp"),
           "GOENV": "off", "GOTELEMETRY": "off", "GOTOOLCHAIN": "local", "GOPROXY": "off",
           "GOSUMDB": "off", "GOFLAGS": "-mod=vendor -p=4", "GOMAXPROCS": "4",
           "CGO_ENABLED": "0", "GOOS": "darwin", "GOARCH": "arm64"}
    (scratch / "tmp").mkdir()

    def run(args, name, cwd=None):
        child = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = child.communicate()
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            child.stdout.close()
            child.stderr.close()
        (evidence / (name + ".log.gz")).write_bytes(gzip.compress(out + err))
        if child.returncode:
            raise RuntimeError("qualification CLI " + name + " exited " + str(child.returncode))
        return out

    result = {"source_archive_sha256": SOURCE_SHA256, "version": CLI_VERSION, "production_change": False}
    try:
        version = run([str(go), "version"], "compiler").decode().strip()
        if version != "go version go1.27.3 darwin/arm64":
            raise RuntimeError("the reviewed Darwin ARM64 Go1.27.3 compiler is required")
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                if (not (member.name == "cilium-cli-0.20.1" or member.name.startswith("cilium-cli-0.20.1/")) or
                        ".." in Path(member.name).parts):
                    raise RuntimeError("unexpected source archive layout")
            source.extractall(scratch, filter="data")
        root = scratch / "cilium-cli-0.20.1"
        package = root / "vendor" / PACKAGE
        target = package / "service.go"
        original = target.read_text()
        start = original.index("func (s *podToService) Run(")
        end = original.index("// PodToIngress ", start)
        scenario = original[start:end]
        if scenario.count(OLD) != 1:
            raise RuntimeError("pinned Service scenario differs from the reviewed overlay target")
        target.write_text(original[:start] + scenario.replace(OLD, NEW) + original[end:])
        files = [OVERLAY / name for name in ("qualification_service.go", "qualification_service_test.go")]
        result["overlay_sha256"] = {p.name: digest(p) for p in files}
        for path in files:
            shutil.copyfile(path, package / path.name)
        run([str(go.with_name("gofmt")), "-w", str(target), *[str(package / p.name) for p in files]], "format")
        result["service_source_before_sha256"] = hashlib.sha256(original.encode()).hexdigest()
        result["service_source_after_sha256"] = digest(target)
        raw = run([str(go), "test", "-json", "-count=1", "-run=^TestQualificationService", PACKAGE], "guards", root)
        events = [json.loads(line) for line in raw.splitlines()]
        passed = [e["Test"] for e in events if e.get("Test") and e["Action"] == "pass"]
        if (any(e["Action"] in ("fail", "skip") for e in events) or
                not {"TestQualificationServiceExactBackend", "TestQualificationServiceRefusals"} <= set(passed)):
            raise RuntimeError("qualification CLI guard tests failed, skipped or did not execute")
        result.update(guard_tests_passed=passed, guard_tests_skipped=0, compiler=version)
        run([str(go), "build", "-trimpath", "-buildvcs=false", "-ldflags",
             "-s -w -X github.com/cilium/cilium/cilium-cli/defaults.CLIVersion=" + CLI_VERSION,
             "-o", str(output), "./cmd/cilium"], "build", root)
        client = run([str(output), "version", "--client"], "client").decode()
        if not client.startswith("cilium-cli: " + CLI_VERSION + " compiled with go1.27.3 on darwin/arm64\n"):
            raise RuntimeError("built qualification CLI identity differs")
        result["binary_sha256"] = digest(output)
        result["accepted"] = True
        return result
    finally:
        shutil.rmtree(scratch)
        result["scratch_removed"] = not scratch.exists()
        (evidence / "receipt.json").write_text(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "go", "work", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.go, args.work, args.output)))


if __name__ == "__main__":
    main()
