---
mode: agent
---
Initial Prompt to the AI (Autonomous Execution)

Objective
Implement a Weaviate Helm Sub-Chart for the homelab, fully autonomously, without modifying plan_create and without proposing directory structures.

Chart Type and Reason
Use a Sub-Chart because a well-maintained upstream Weaviate chart exists.

Authoritative References (read-only)
- /home/coder/homelab/plan_create/projects.yaml → Weaviate
  Documentation:
  - https://docs.weaviate.io/academy/deployment/k8s/setup_weaviate
  - https://docs.weaviate.io/deploy/installation-guides/k8s-installation
  - https://github.com/weaviate/weaviate-helm
  Chart Files: apps/weaviate
- Helm:
  - https://helm.sh/docs/topics/charts/
  - https://helm.sh/docs/chart_best_practices/

Tasks (perform all steps without asking questions)
1) Sub-Chart Implementation
- Implement Weaviate as a Helm Sub-Chart in apps/weaviate using the upstream weaviate chart and homelab conventions.
- Do not print or propose directory structures; just implement.

2) Image Handling
- Use official external Weaviate image.
- Make image.repository, image.tag, image.pullPolicy configurable via values.yaml.
- If a custom build is needed, build and push using tools/build_push.sh to docker.io/brimdor/weaviate:<tag> (default "latest") and update values.yaml.

3) Secrets via 1Password Operator
- Do not embed secrets in values.yaml.
- Create tools/weaviate-op-create.sh based on tools/example-op-create.sh (1Password item category: Database).
- Key mapping: 1Password field root-password → environment variable ROOT_PASSWORD.
- Make executable: chmod +x tools/weaviate-op-create.sh.
- Run it; capture JSON with vault.id and item.id:
  {
    "id": "<item-id>",
    "title": "Weaviate Secrets",
    "version": 1,
    "vault": { "id": "<vault-id>", "name": "Server" }
  }
- Add annotations in values.yaml with captured IDs:
  operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  operator.1password.io/item-name: "secrets"
- Reference the secret in workloads via env.valueFrom.secretKeyRef:
  name: ROOT_PASSWORD
  valueFrom.secretKeyRef.name: <k8s-secret-name>
  valueFrom.secretKeyRef.key: ROOT_PASSWORD
- Ensure rollout strategy tolerates operator-triggered restarts.

4) Service (internal access)
- Configure values.yaml:
  service.enabled
  service.type (ClusterIP, NodePort, or LoadBalancer)
  service.ports[] (name, port, targetPort, protocol)
  service.annotations (map)

5) Ingress (external access as needed)
- Use networking.k8s.io/v1 with host-based rules for eaglepass.io and pathType: Prefix.
- Configure values.yaml:
  ingress.enabled
  ingress.className
  ingress.annotations
    Public:
      external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"
      external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
      cert-manager.io/cluster-issuer: letsencrypt-prod
    Private:
      cert-manager.io/cluster-issuer: letsencrypt-prod
  ingress.hosts:
    host: weaviate.eaglepass.io (configurable)
    paths: [ { path: "/", pathType: "Prefix" } ]
  ingress.tls:
    secretName (configurable)
    hosts list

6) Persistence
- Provide a PVC named "data" for persistence.
- Configure values.yaml:
  persistence.enabled
  persistence.data.existingClaim (optional)
  persistence.data.storageClass
  persistence.data.accessModes
  persistence.data.size

7) Backups (CronJobs)
- Implement CronJobs that back up the "data" PVC to NFS.
- Defaults:
  backups.enabled=true
  backups.schedule="*/15 * * * *"
  backups.retentionDays=7
  backups.nfs.server="10.0.40.3"
  backups.nfs.path="/path/to/backups/weaviate" (placeholder; make configurable)
- Ensure safe operation and compatibility with rollouts.

8) Validation
- Ensure values.yaml contains only configurable fields and secret references (no plaintext secrets).
- Validate with Helm template/lint per Helm docs.
- Confirm Service/Ingress behavior, TLS provisioning when enabled.
- Confirm PVC binding and data persistence.
- Confirm CronJobs execute on schedule and write to NFS path; retention enforced.
- Confirm 1Password Operator injects secrets via annotations and secretKeyRef.

9) Activity Logging
- Append human-readable action notes to reports/weaviate/action-log.txt.
- Save any test artifacts/logs under reports/weaviate/tests/.
- Keep appending notes throughout changes and tests.

Constraints
- Do not edit folder plan_create.
- Do not propose directory structures.
- Do not add “things to investigate”.
- Do not embed sensitive values anywhere.
- Follow homelab conventions and Sub-Chart usage.

Success Criteria
- The Sub-Chart deploys via Argo CD.
- Service and optional Ingress function with TLS when configured.
- Data persists via PVC "data".
- Backups run to NFS 10.0.40.3 at the configured path on schedule with retention applied.
- All secrets are injected via 1Password Operator using the specified annotations