# Spec: Jovo K8s Infrastructure — Canary Deployment Scaffolding

## Issue
Broville/jovo #2 — Set up the K8s manifests and ArgoCD application for Jovo canary deployment.

## Goal
Provide production-ready Helm charts (bjw-s app-template) for both canary and production Jovo deployments, following the established Broville app pattern. Production adds init/sidecar containers for NAS backups; canary uses PVC-only storage.

## Users
- **Pipeline agents** — deploy images via ArgoCD
- **Chris/Kaleb** — validate canary, approve production promotion
- **Operations** — monitor backups, rotate secrets

## Data Model / Resources

| Resource | Canary | Production | Notes |
|----------|--------|-----------|-------|
| Namespace | `jovo-canary` | `jovo` | Auto-created by ArgoCD syncPolicy |
| Chart type | Helm + app-template 4.6.2 | Helm + app-template 4.6.2 | Same dependency |
| Containers | `database` (MariaDB), `backend`, `frontend` | Same | Sidecar added in production |
| PVCs | `data` (10Gi DB), `audio` (50Gi) | Same + `covers` via NFS | Canary: no NAS backups |
| Ingress | `jovo-canary.eaglepass.io` | `jovo.eaglepass.io` | Cloudflare Access + nginx |
| Secrets | `jovo-canary-secrets` (1Password operator) | `jovo-secrets` (1Password operator) | Separate vault items |
| Auth | `JOVO_AUTH_REQUIRED=false` | `JOVO_AUTH_REQUIRED=true` | Prod requires Cloudflare Access |

## API / Data Flow
1. ArgoCD ApplicationSet watches `apps/jovo-canary` (and `apps/jovo`)
2. Helm renders Deployment + Services + Ingress + PVCs + ConfigMap (init-db)
3. 1Password operator injects secrets into pod
4. Cloudflare Access authenticates via `Cf-Access-Authenticated-User-Email` header
5. MariaDB init script creates DB on first boot

## Edge Cases
- **First boot**: MariaDB PVC is empty → init script runs `CREATE DATABASE` + `GRANT`
- **Rebuild with same tag**: Add `RESTART_AT` env var to force pod replacement
- **Auth disabled in canary**: `JOVO_AUTH_REQUIRED=false` bypasses Cloudflare requirement
- **Upload limit**: Ingress `proxy-body-size: 500m` for audio uploads
- **Recreate strategy**: Required because RWO PVCs cannot mount to multiple pods during RollingUpdate

## v1 Scope (IN)
- [x] `apps/jovo/` directory with `Chart.yaml` + `values.yaml`
- [x] `apps/jovo-canary/` refined with NetworkPolicy, updated tags, and prod parity
- [x] Init DB ConfigMap for MariaDB first-boot
- [x] PVCs: `data` (MariaDB) and `audio` (backend uploads)
- [x] Ingress with Cloudflare external-dns annotations + cert-manager TLS
- [x] 1Password secret operator annotations on pod
- [x] Production adds backup initContainer + backup sidecar

## Out of Scope (OUT)
- NAS restore initContainer (production-specific, to be added when promoting from canary)
- VolumeSnapshot / volsync (not configured for Jovo yet)
- Grafana dashboards / Prometheus rules (generic app-template metrics enabled by default)

## Open Questions
- What is the production image tag for backend/frontend? → Not yet built; values will use placeholder `latest` or same `issue-1-canary` for now; updated by pipeline

## Quality Checklist
- [ ] Helm template renders without errors
- [ ] No hardcoded passwords in values.yaml
- [ ] All secrets reference `secretKeyRef`
- [ ] NetworkPolicy restricts ingress to ingress-nginx only
- [ ] Init DB script is idempotent (`IF NOT EXISTS`)
