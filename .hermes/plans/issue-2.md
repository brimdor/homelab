# Plan: Jovo K8s Infrastructure — Canary Deployment Scaffolding

## Summary
Create `apps/jovo/` (production) and update `apps/jovo-canary/` (canary) in the homelab GitOps repo. Both use bjw-s app-template Helm chart with MariaDB + FastAPI backend + Next.js frontend.

## Files to Change

### New Files (Production)
| File | What it does |
|------|--------------|
| `apps/jovo/Chart.yaml` | Helm chart metadata; depends on app-template 4.6.2 |
| `apps/jovo/values.yaml` | Full production values: 3 containers, ingress, PVCs, secrets, NetworkPolicy |

### Modified Files (Canary)
| File | What changes |
|------|--------------|
| `apps/jovo-canary/Chart.yaml` | No change (already exists and correct) |
| `apps/jovo-canary/values.yaml` | Minor refinements: add NetworkPolicy, align probe/resource conventions |

### No Changes Needed
- `system/argocd/values.yaml` — ApplicationSet already auto-discovers `apps/*`; new `jovo/` dir is picked up automatically
- `system/cloudflared/values.yaml` — Wildcard `*.eaglepass.io` already routes to ingress-nginx

## Data Flow
1. **PR merged** → ArgoCD ApplicationSet creates `jovo` Application
2. **ArgoCD sync** → Helm template renders Deployment, Services, PVCs, Ingress, ConfigMap
3. **1Password operator** → Injects secrets into pod env vars
4. **MariaDB init** → ConfigMap SQL runs on first boot, creating DB + user
5. **Ingress** → Cloudflare Access + nginx routes `jovo.eaglepass.io` to frontend service, `/api/*` and `/health` to backend service
6. **Production backup** → initContainer restores from NFS (if sentinel missing), sidecar rsyncs to NAS every 24h

## Component Diagram
```
[Cloudflare Access] → [Ingress nginx] → [Service: main:3000] → [frontend container]
                                    → [Service: backend:8000] → [backend container]
                                    → [Service: mariadb:3306]  → [database container]
[1Password] → [Secret: jovo-secrets] → [pod env vars]
[ConfigMap] → [init-db: 01-init.sql] → [MariaDB /docker-entrypoint-initdb.d/]
```

## Helm Template Validation
- `cd homelab && helm dependency build apps/jovo/`
- `helm template jovo apps/jovo/ --namespace jovo`
- `helm dependency update` (if chart.lock changes)
