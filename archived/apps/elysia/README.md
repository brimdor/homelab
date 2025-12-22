# Elysia Helm Chart (bjw-s app-template)

This chart deploys **Elysia** using the bjw-s `app-template` common library chart patterns used elsewhere in this repository.

## References
- Upstream Project: https://github.com/weaviate/elysia
- Product Docs: https://elysia.weaviate.io
- Blog Overview: https://weaviate.io/blog/elysia-agentic-rag
- Additional Docs: https://weaviate.github.io/elysia

## Features
- Configurable image repository/tag
- Kubernetes Service & Ingress (enabled by default) exposing HTTP (port 8080)
- Persistent storage (`persistence.data`) with 10Gi PVC by default (mount: `/data`)
- Optional ConfigMap (`configMaps.app-config`) for non-sensitive configuration
- 1Password Operator integration for secrets (no secrets stored in chart)
- Probes (liveness/readiness) pre-configured
- Resource requests for baseline stability
- Optional backups section (disabled by default) for future CronJob integration

## Secrets via 1Password Operator
A Secret named `secrets` is referenced but not populated here. Create a 1Password item and annotate a Secret manifest with:
```
operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
operator.1password.io/item-name: "secrets"
```
Environment variable examples (uncomment & adjust in `values.yaml`):
```
API_KEY -> api-key
WEAVIATE_ENDPOINT -> weaviate-endpoint
OLLAMA_URL -> ollama-url
DB_URL -> db-url
```
Each variable uses `valueFrom.secretKeyRef` to map to the corresponding 1Password item field.

Helper script to scaffold an item (created separately): `tools/elysia-op-create.sh`.

## Persistence
```
persistence:
  data:
    enabled: true
    size: 10Gi
    accessMode: ReadWriteOnce
    storageClass: ""
    existingClaim: "" # supply to reuse an existing PVC
```

## Ingress
Ingress enabled by default with host `elysia.eaglepass.io`. TLS section expects a certificate secret (e.g., via cert-manager). Disable by setting `app-template.ingress.main.enabled=false`.

## Backups (Planned)
`backups` block declares configuration for a CronJob (NFS target, schedule, retention). Actual CronJob template can be added by enabling and supplying logic; presently informational until implemented in templates.

Example values to enable in future:
```
backups:
  enabled: true
  schedule: "*/15 * * * *"
  nfs:
    server: 10.0.40.3
    path: /export/path/elysia
  retentionDays: 7
```

## ConfigMap
Enable `configMaps.app-config.enabled` and populate `data` with key/value entries. Mount or consume via env if needed (bjw-s advancedMounts pattern may be added similarly to other charts).

## Security Context
Default pod security context enforces non-root execution (UID/GID 1000) and `RuntimeDefault` seccomp.

## Customization Summary
Key sections in `values.yaml`:
- `app-template.controllers.main.containers.main.image`
- `app-template.service.main`
- `app-template.ingress.main`
- `app-template.persistence.data`
- `app-template.configMaps.app-config`
- `backups` (informational)
- `extraResources` (Secret placeholder)

## Testing
Commands (not executed automatically here):
```
helm dependency update apps/elysia
helm lint apps/elysia
helm template apps/elysia
```

## Disclaimer
No sensitive values are committed. Populate secrets exclusively through the 1Password Operator managed Secret named `secrets`.
