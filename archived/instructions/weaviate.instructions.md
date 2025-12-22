---
applyTo: '**'
---
Plan/Instructions: Weaviate Helm Chart (Sub-Chart)

Chart Type
Selection: Sub-Chart
Justification (per determination logic): A well-maintained existing chart for Weaviate exists → select Sub-Chart

Authoritative References
Project entry (read-only): /home/coder/homelab/plan_create/projects.yaml
Weaviate Documentation:
- https://docs.weaviate.io/academy/deployment/k8s/setup_weaviate
- https://docs.weaviate.io/deploy/installation-guides/k8s-installation
- https://github.com/weaviate/weaviate-helm
Chart Files location in this repo: apps/weaviate
Helm References:
- Charts and values/schema behavior: https://helm.sh/docs/topics/charts/
- Best practices: https://helm.sh/docs/chart_best_practices/

Hard Constraints
- Never modify anything under plan_create
- Do not propose a directory structure and do not add “things to investigate”
- No sensitive values hardcoded in charts or values.yaml
- Host environment: ZSH shell, Kubernetes managed by Argo CD, Helm CLI, 1Password CLI
- Domain default: eaglepass.io
- Follow homelab conventions and Sub-Chart approach for remote chart usage

Kubernetes Objects (create/configure per conditions)
Secrets (required if app needs credentials or tokens)
- All secrets must be sourced via 1Password Operator
- Workloads must reference env via valueFrom.secretKeyRef (no literals in values.yaml)
- Required annotations on Kubernetes Secret or target object receiving secrets:
  operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  operator.1password.io/item-name: "secrets"
- Secret key naming convention:
  Environment variable: ROOT_PASSWORD
  1Password field: root-password
- Do not embed credentials in values.yaml; only references and annotations are allowed

ConfigMaps (optional)
- Use only for non-sensitive configuration, if needed

Service (internal access only)
- Expose Weaviate’s service ports as needed
- Make parameters configurable in values.yaml:
  service.enabled
  service.type (ClusterIP, NodePort, LoadBalancer)
  service.ports (list with name, port, targetPort, protocol)
  service.annotations (map)

Ingress (external access only)
- Use networking.k8s.io/v1 with host-based rules and pathType
- Domain: eaglepass.io (configurable)
- Make parameters configurable in values.yaml:
  ingress.enabled
  ingress.className
  ingress.annotations
    Public DNS annotations (when public):
      external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"
      external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
      cert-manager.io/cluster-issuer: letsencrypt-prod
    Private DNS annotation:
      cert-manager.io/cluster-issuer: letsencrypt-prod
  ingress.hosts:
    host: weaviate.eaglepass.io (configurable)
    paths:
      path: /
      pathType: Prefix
  ingress.tls:
    secretName (configurable)
    hosts list

Persistence (if Weaviate requires persistent data)
- Create a PVC named "data"
- Configure via values.yaml:
  persistence.enabled
  persistence.data.existingClaim (optional)
  persistence.data.storageClass
  persistence.data.accessModes (e.g., ["ReadWriteOnce"])
  persistence.data.size (e.g., 20Gi)

Backups (CronJobs)
- Implement CronJobs to back up the "data" PVC to NFS
- NFS server: 10.0.40.3
- Placeholder path in values.yaml for user customization (e.g., /mnt/nfs/backups/weaviate)
- Default schedule: every 15 minutes (*/15 * * * *)
- Default retention: 7 days
- Make configurable in values.yaml:
  backups.enabled
  backups.schedule (default "*/15 * * * *")
  backups.retentionDays (default 7)
  backups.nfs.server (default "10.0.40.3")
  backups.nfs.path (default "/path/to/backups/weaviate", placeholder)
  backups.labels, backups.annotations (optional)
  backups.podResources (optional)
- Ensure safe operation and compatibility with rollouts

Image Handling
- External image exists → Use the official Weaviate image
- Configure via values.yaml:
  image.repository
  image.tag
  image.pullPolicy
  imagePullSecrets (optional)
- If a custom image is needed:
  Use tools/build_push.sh to build and push to docker.io/brimdor/weaviate:<tag> (default "latest")
  Update image fields in values.yaml accordingly

1Password Operator Integration Steps
- Create tools/weaviate-op-create.sh based on tools/example-op-create.sh
  Use 1Password item category: Database
  Include field key: root-password (mapped to env var ROOT_PASSWORD)
  Script must output JSON including:
    {
      "id": "<item-id>",
      "title": "Weaviate Secrets",
      "version": 1,
      "vault": {
        "id": "<vault-id>",
        "name": "Server"
      }
    }
- Make the script executable:
  chmod +x tools/weaviate-op-create.sh
- Run the script and capture the JSON output
- Add the vault.id and item.id to values.yaml annotations:
  operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  operator.1password.io/item-name: "secrets"
- Reference secrets in workloads via env.valueFrom.secretKeyRef:
  name: ROOT_PASSWORD
  valueFrom.secretKeyRef.name: <k8s-secret-name>
  valueFrom.secretKeyRef.key: ROOT_PASSWORD
- Note: Operator updates may trigger restarts; ensure rollout settings allow safe restarts

Values.yaml Expectations (configurable; schema-validated)
- image:
  repository, tag, pullPolicy, imagePullSecrets
- env:
  only non-sensitive defaults; ROOT_PASSWORD must use valueFrom.secretKeyRef
- secret annotations:
  operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  operator.1password.io/item-name: "secrets"
- service:
  enabled, type, ports[], annotations
- ingress:
  enabled, className, annotations
  hosts[].host (default weaviate.eaglepass.io), hosts[].paths[].path="/", pathType="Prefix"
  tls[].secretName, tls[].hosts[]
- persistence:
  enabled
  data.existingClaim, data.storageClass, data.accessModes, data.size
- backups:
  enabled, schedule (default "*/15 * * * *"), retentionDays (default 7)
  nfs.server="10.0.40.3", nfs.path="/path/to/backups/weaviate" (placeholder)
- optional:
  resources, nodeSelector, tolerations, affinity
- Conform to Helm values/schema behavior:
  https://helm.sh/docs/topics/charts/
  https://helm.sh/docs/chart_best_practices/

Validation and Rollout
- Use Helm template/lint to validate schema and values
- Verify Service and Ingress behavior; ensure TLS if enabled
- Confirm PVC binds and data persists
- Confirm CronJobs execute and write to NFS path on schedule; retention behavior is applied
- Confirm secrets are injected via 1Password Operator (annotations present, env wired via secretKeyRef)
- Argo CD will reconcile the release as configured

Activity Logging
- Append human-readable action notes to: reports/weaviate/action-log.txt
- Store test artifacts and logs under: reports/weaviate/tests/
- Example notes (with timestamps):
  Created tools/weaviate-op-create.sh and set executable
  Updated values.yaml with 1Password annotations (vault=<vault-id>, item=<item-id>)
  Deployed chart; verified Service and Ingress
  Validated backup CronJob executed and wrote to NFS

Constraints Reminder
- Do not modify anything in plan_create
- Do not propose directory structures
- Do not add “things to investigate”
- No sensitive values in repository or values.yaml