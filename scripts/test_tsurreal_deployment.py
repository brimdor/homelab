"""Focused Tsurreal private deployment and projected-identity checks."""
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "apps/tsurreal-canary"


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
        self.assertEqual(len(objects), 11)
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
        self.assertEqual(set(claims), {"tsurreal-state", "tsurreal-recovery", "tsurreal-packages"})
        for obj in [*claims.values(), next(o for o in objects if o["kind"] == "Namespace")]:
            self.assertIn("Prune=false", obj["metadata"]["annotations"]["argocd.argoproj.io/sync-options"])
        config = json.loads(next(o for o in objects if o["metadata"]["name"] == "tsurreal-configuration")["data"]["hq.json"])
        self.assertEqual(config["tls_client_cidrs"], ["10.0.0.0/16", "127.0.0.1/32", "::1/128"])
        self.assertEqual(config["origin"], "https://tsurreal-canary.eaglepass.io")
        self.assertFalse(set(config).intersection(["native_file", "execution_file", "push_file", "email_file", "backup_file", "installation_id"]))

    def test_candidate_is_restricted(self):
        objects=render()
        deployment=next(o for o in objects if o["kind"]=="Deployment")["spec"]
        self.assertEqual((deployment["replicas"],deployment["strategy"]["type"]),(1,"Recreate"))
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
        init=pod["initContainers"][0]
        self.assertEqual(init["image"],pod["containers"][0]["image"])
        self.assertEqual(init["command"],["/opt/tsurreal/package/hq","--stage-identity-source","/projected-tls","--stage-identity-output","/run/tsurreal/identity"])
        self.assertEqual(init["resources"]["limits"]["memory"],"64Mi")
        self.assertEqual({m["name"] for m in init["volumeMounts"]},{"projected-tls","identity"})
        self.assertTrue(any(m["name"]=="projected-tls" and m["mountPath"]=="/projected-tls" and m["readOnly"] for m in init["volumeMounts"]))
        self.assertFalse(any(v["name"]=="identity-script" for v in pod["volumes"]))
        self.assertEqual([o["metadata"]["name"] for o in objects if o["kind"]=="ConfigMap"],["tsurreal-configuration"])
        self.assertFalse(any("hostPath" in v for v in pod["volumes"]))
        self.assertFalse(pod.get("hostNetwork"))
        self.assertFalse(pod.get("hostPID"))
        service=next(o for o in objects if o["kind"]=="Service")
        self.assertEqual(service["spec"]["selector"],deployment["selector"]["matchLabels"])
        self.assertTrue(all(deployment["template"]["metadata"]["labels"][k]==v for k,v in service["spec"]["selector"].items()))
        for name,path in [("configuration","/etc/tsurreal"),("identity","/run/tsurreal")]:
            mounts=pod["containers"][0]["volumeMounts"]
            self.assertTrue(any(m["name"]==name and m["mountPath"]==path and m["readOnly"] for m in mounts))

    def test_preupgrade_snapshot_retained_and_proof_removed(self):
        objects = render()
        snapshot = next(o for o in objects if o["kind"] == "VolumeSnapshot")
        self.assertEqual(snapshot["metadata"]["name"], "tsurreal-v35-pre-0d9e030a")
        self.assertEqual(snapshot["spec"], {"volumeSnapshotClassName":"ceph-block", "source":{"persistentVolumeClaimName":"tsurreal-state"}})
        annotations = snapshot["metadata"]["annotations"]
        self.assertEqual(annotations["argocd.argoproj.io/sync-options"], "Prune=false,Delete=false")
        self.assertEqual(annotations["helm.sh/resource-policy"], "keep")
        self.assertEqual(annotations["tsurreal.zuriel-labs.io/source-pvc-uid"], "bbd5ca78-93b1-4a0e-9062-35a79b8103ce")
        self.assertEqual(len([o for o in objects if o["kind"] == "Deployment"]), 1)
        self.assertFalse(any(o["metadata"]["name"] == "tsurreal-migration-proof" for o in objects))
        self.assertFalse(any("migration-proof" in vol.get("persistentVolumeClaim", {}).get("claimName", "") for o in objects if o["kind"] == "Deployment" for vol in o["spec"]["template"]["spec"]["volumes"]))

    def test_invalid_identity_or_target_refused(self):
        render(namespace="tsurreal-production",good=False)
        for key,value in [("repository","public.example/hq"),("digest","sha256:invalid")]:
            render("app-template.controllers.main.containers.hq.image."+key+"="+value,good=False)
            render("app-template.controllers.main.initContainers.prepare-identity.image."+key+"="+value,good=False)
        render("app-template.controllers.main.initContainers.prepare-identity.image.digest=sha256:"+"a"*64,good=False)


if __name__ == "__main__":
    unittest.main()
