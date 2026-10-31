"""Focused Tsurreal private deployment and projected-identity checks."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "apps/tsurreal-canary"
import types
identity = types.ModuleType("prepare_identity")
values = yaml.safe_load((CHART / "values.yaml").read_text())["app-template"]
identity_source = values["configMaps"]["identity"]["data"]["prepare-identity.py"]
exec(compile(identity_source, str(CHART / "values.yaml"), "exec"), identity.__dict__)


def render(*overrides, namespace="tsurreal-canary", good=True):
    command = ["helm", "template", "tsurreal-canary", str(CHART), "--namespace", namespace]
    for value in overrides:
        command.extend(["--set-string", value])
    result = subprocess.run(command, text=True, capture_output=True)
    if good:
        if result.returncode:
            raise AssertionError(result.stderr)
        return [obj for obj in yaml.safe_load_all(result.stdout) if obj]
    if result.returncode == 0:
        raise AssertionError("Unsafe chart values were admitted")


class ChartTests(unittest.TestCase):
    def test_standard_chart_and_retained_private_resources(self):
        self.assertEqual(sorted(p.name for p in CHART.iterdir() if p.name != "charts" and p.name != "Chart.lock"), ["Chart.yaml", "values.yaml"])
        dependency = yaml.safe_load((CHART / "Chart.yaml").read_text())["dependencies"]
        self.assertEqual(dependency, [{"name": "app-template", "version": "5.3.0", "repository": "https://bjw-s-labs.github.io/helm-charts/"}])
        objects = render()
        self.assertEqual(len(objects), 11 + (1 if "preupgrade" in values["rawResources"] else 0) + (3 if "migration-proof" in values["controllers"] else 0))
        self.assertFalse(any(o["kind"] in ["Secret", "Job"] for o in objects))
        for obj in objects:
            self.assertNotIn("production", obj["metadata"]["name"])
            if obj["kind"] != "Namespace": self.assertEqual(obj["metadata"]["namespace"], "tsurreal-canary")
        service = next(o for o in objects if o["kind"] == "Service")
        self.assertEqual(service["metadata"]["name"], "tsurreal-canary")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        for field in ["allocateLoadBalancerNodePorts", "loadBalancerSourceRanges", "externalTrafficPolicy", "externalIPs"]:
            self.assertNotIn(field, service["spec"])
        self.assertEqual(service["spec"]["ports"], [{"name":"https", "port":443, "targetPort":8443, "protocol":"TCP"}])
        self.assertFalse(any(k.startswith("external-dns.") for k in service["metadata"].get("annotations", {})))
        ingress = next(o for o in objects if o["kind"] == "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "nginx")
        self.assertEqual(ingress["spec"]["rules"], [{"host":"tsurreal-canary.eaglepass.io", "http":{"paths":[{"path":"/", "pathType":"Prefix", "backend":{"service":{"name":"tsurreal-canary", "port":{"number":443}}}}]}}])
        self.assertEqual(ingress["spec"]["tls"], [{"hosts":["tsurreal-canary.eaglepass.io"], "secretName":"tsurreal-canary-tls"}])
        annotations = ingress["metadata"]["annotations"]
        self.assertEqual(annotations["nginx.ingress.kubernetes.io/ssl-passthrough"], "true")
        self.assertEqual(annotations["nginx.ingress.kubernetes.io/backend-protocol"], "HTTPS")
        self.assertEqual(annotations["nginx.ingress.kubernetes.io/whitelist-source-range"], "127.0.0.1/32,::1/128")
        self.assertFalse(any(k.startswith("cert-manager.io/") for k in annotations))
        certificate = next(o for o in objects if o["kind"] == "Certificate")
        self.assertEqual(certificate["metadata"]["name"], "tsurreal-canary")
        self.assertEqual(certificate["spec"]["secretName"], "tsurreal-canary-tls")
        self.assertEqual(certificate["spec"]["issuerRef"], {"name":"letsencrypt-prod", "kind":"ClusterIssuer"})
        policy = next(o for o in objects if o["kind"] == "NetworkPolicy")["spec"]
        self.assertFalse(policy.get("egress"))
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["ingress"][0]["ports"], [{"protocol":"TCP", "port":8443}])
        self.assertEqual(policy["ingress"][0]["from"], [{"namespaceSelector":{"matchLabels":{"kubernetes.io/metadata.name":"ingress-nginx"}}, "podSelector":{"matchLabels":{"app.kubernetes.io/name":"traefik", "app.kubernetes.io/instance":"ingress-nginx-ingress-nginx"}}}])
        claims = {o["metadata"]["name"]:o for o in objects if o["kind"] == "PersistentVolumeClaim"}
        self.assertEqual(set(claims), {"tsurreal-state", "tsurreal-recovery", "tsurreal-packages"} | ({"tsurreal-migration-proof"} if "migration-proof" in values["controllers"] else set()))
        for obj in [*[o for name,o in claims.items() if name != "tsurreal-migration-proof"], next(o for o in objects if o["kind"] == "Namespace")]:
            self.assertIn("Prune=false", obj["metadata"]["annotations"]["argocd.argoproj.io/sync-options"])
        config = json.loads(next(o for o in objects if o["metadata"]["name"] == "tsurreal-configuration")["data"]["hq.json"])
        self.assertEqual(config["tls_client_cidrs"], ["10.0.0.0/16", "127.0.0.1/32", "::1/128"])
        self.assertEqual(config["origin"], "https://tsurreal-canary.eaglepass.io")
        self.assertFalse(set(config).intersection(["native_file", "execution_file", "push_file", "email_file", "backup_file", "installation_id"]))

    def test_candidate_is_restricted(self):
        objects=render()
        deployment=next(o for o in objects if o["kind"]=="Deployment" and o["metadata"]["name"]=="tsurreal-canary")["spec"]
        phase = values["controllers"]["main"].get("annotations", {}).get("tsurreal.zuriel-labs.io/migration-phase")
        self.assertIn(phase, [None, "paused-v35"])
        self.assertEqual((deployment["replicas"],deployment["strategy"]["type"]),(0 if phase == "paused-v35" else 1,"Recreate"))
        pod=deployment["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"],65532)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"],"RuntimeDefault")
        self.assertNotIn("imagePullSecrets",pod)
        self.assertEqual(len(pod["initContainers"]),1)
        for container in pod["containers"]+pod["initContainers"]:
            security=container["securityContext"]
            self.assertTrue(security["readOnlyRootFilesystem"])
            self.assertFalse(security["allowPrivilegeEscalation"])
            self.assertEqual(security["capabilities"]["drop"],["ALL"])
            self.assertIn("@sha256:",container["image"])
        self.assertFalse(any("hostPath" in v for v in pod["volumes"]))
        self.assertFalse(pod.get("hostNetwork"))
        self.assertFalse(pod.get("hostPID"))
        service=next(o for o in objects if o["kind"]=="Service")
        self.assertEqual(service["spec"]["selector"],deployment["selector"]["matchLabels"])
        self.assertTrue(all(deployment["template"]["metadata"]["labels"][k]==v for k,v in service["spec"]["selector"].items()))
        for name,path in [("configuration","/etc/tsurreal"),("identity","/run/tsurreal")]:
            mounts=pod["containers"][0]["volumeMounts"]
            self.assertTrue(any(m["name"]==name and m["mountPath"]==path and m["readOnly"] for m in mounts))

    def test_retained_snapshot_and_isolated_proof(self):
        objects = render()
        snapshots = [o for o in objects if o["kind"] == "VolumeSnapshot"]
        if "preupgrade" not in values["rawResources"]:
            self.assertEqual(snapshots, [])
            return
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot["metadata"]["name"], "tsurreal-v35-pre-0d9e030a")
        self.assertEqual(snapshot["spec"], {"volumeSnapshotClassName":"ceph-block", "source":{"persistentVolumeClaimName":"tsurreal-state"}})
        self.assertEqual(snapshot["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false,Delete=false")
        self.assertEqual(snapshot["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        if "migration-proof" not in values["controllers"]:
            return
        proof = next(o for o in objects if o["kind"] == "Deployment" and o["metadata"]["name"] == "tsurreal-migration-proof")["spec"]
        self.assertEqual((proof["replicas"], proof["strategy"]["type"]), (1, "Recreate"))
        pod = proof["template"]["spec"]
        self.assertEqual(pod["securityContext"]["runAsUser"], 65532)
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual({c["name"] for c in pod["containers"]}, {"hq", "inspector"})
        claims = [vol["persistentVolumeClaim"]["claimName"] for vol in pod["volumes"] if "persistentVolumeClaim" in vol]
        self.assertEqual(claims, ["tsurreal-migration-proof"])
        for container in pod["containers"] + pod["initContainers"]:
            self.assertFalse(container.get("ports"))
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
            self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
            self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        for name in ["inspector"]:
            container = next(c for c in pod["containers"] + pod["initContainers"] if c["name"] == name)
            self.assertTrue(all(m["readOnly"] for m in container["volumeMounts"]))
        verifier = next(c for c in pod["initContainers"] if c["name"] == "verify-state")
        self.assertTrue(next(m for m in verifier["volumeMounts"] if m["mountPath"] == "/migration")["readOnly"])
        self.assertFalse(next(m for m in verifier["volumeMounts"] if m["mountPath"] == "/var/lib/tsurreal").get("readOnly", False))
        proof_config = json.loads(next(o for o in objects if o["metadata"]["name"] == "tsurreal-migration-configuration")["data"]["hq.json"])
        self.assertEqual(proof_config["listen"], "127.0.0.1:9443")
        self.assertFalse(set(proof_config).intersection(["native_file", "execution_file", "backup_file", "push_file", "email_file"]))

    def test_restored_database_verifier(self):
        if "migration-configuration" not in values["configMaps"]:
            return
        import sqlite3
        module = types.ModuleType("verify_migration")
        source = values["configMaps"]["migration-configuration"]["data"]["verify.py"]
        exec(compile(source, "verify.py", "exec"), module.__dict__)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hq.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, digest TEXT NOT NULL)")
            connection.executemany("INSERT INTO schema_migrations VALUES (?,?)", [(m["version"],m["sha256"]) for m in module.SCHEMA[:35]])
            connection.commit()
            self.assertEqual(len(module.verify(path, 35)["schema"]), 35)
            with self.assertRaises(ValueError): module.verify(path, 38)
            connection.execute("UPDATE schema_migrations SET digest='changed' WHERE version=35")
            connection.commit()
            with self.assertRaises(ValueError): module.verify(path, 35)
            connection.close()
            linked = Path(temporary) / "linked.sqlite"
            linked.symlink_to(path)
            with self.assertRaises(ValueError): module.verify(linked, 35)

    def test_invalid_identity_or_target_refused(self):
        render(namespace="tsurreal-production",good=False)
        for key,value in [("repository","public.example/hq"),("digest","sha256:invalid")]:
            render("app-template.controllers.main.containers.hq.image."+key+"="+value,good=False)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.generation = self.source / "generation-one"
        self.generation.mkdir()
        for name, value in [("tls.crt", b"synthetic certificate"), ("tls.key", b"synthetic key")]:
            (self.generation / name).write_bytes(value)
        (self.source / "..data").symlink_to(self.generation.name)
        self.output = self.root / "identity"

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_regular_outputs_and_replay_refusal(self):
        identity.stage(self.source, self.output)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        for name in ["tls.crt", "tls.key"]:
            path = self.output / name
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_bytes(), (self.generation / name).read_bytes())
        with self.assertRaises(FileExistsError):
            identity.stage(self.source, self.output)
        self.assertEqual((self.output / "tls.key").read_bytes(), b"synthetic key")

    def test_one_generation_even_during_rotation(self):
        next_generation = self.source / "generation-two"
        next_generation.mkdir()
        for name in ["tls.crt", "tls.key"]:
            (next_generation / name).write_bytes(b"changed")
        original = identity.os.open
        def rotating_open(path, flags, *args, **kwargs):
            fd = original(path, flags, *args, **kwargs)
            if Path(path).name == "..data":
                (self.source / "..data").unlink()
                (self.source / "..data").symlink_to(next_generation.name)
            return fd
        identity.os.open = rotating_open
        try:
            identity.stage(self.source, self.output)
        finally:
            identity.os.open = original
        self.assertEqual((self.output / "tls.key").read_bytes(), b"synthetic key")

    def test_missing_empty_oversize_link_fifo_refused(self):
        key = self.generation / "tls.key"
        for mode in ["missing", "empty", "oversize", "symlink", "fifo"]:
            with self.subTest(mode=mode):
                key.unlink(missing_ok=True)
                if mode == "empty": key.write_bytes(b"")
                if mode == "oversize": key.write_bytes(b"x" * (1024 * 1024 + 1))
                if mode == "symlink": key.symlink_to("tls.crt")
                if mode == "fifo": os.mkfifo(key)
                with self.assertRaises((OSError, ValueError)):
                    identity.stage(self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_destination_symlinks_refused(self):
        self.output.symlink_to(self.root / "absent")
        with self.assertRaises(FileExistsError): identity.stage(self.source, self.output)
        self.output.unlink()
        linked = self.root / "linked"
        linked.symlink_to(self.root)
        with self.assertRaises(ValueError): identity.stage(self.source, linked / "identity")


if __name__ == "__main__":
    unittest.main()
