# Homelab Recon Status Report (2026-02-28)

Generated: 2026-02-28T20:00:00-06:00
Context Pack: reports/context-pack-2026-02-28

## Summary

| Layer | Status | Notes |
|-------|--------|-------|
| Metal | GREEN | 10/10 nodes Ready, all healthy |
| Network | GREEN | All VLANs, gateways, internet reachable |
| Storage (NAS) | GREEN | Unraid SMB/NFS/Web all accessible |
| Storage (Ceph) | GREEN | HEALTH_OK, 7/7 OSDs up, 39.87% used |
| System | GREEN | kube-system all Running, Cilium 10/10 |
| Platform | GREEN | Ingress, certs, secrets all healthy |
| Apps | GREEN | All pods Running, all 41 ArgoCD apps Synced+Healthy |
| Repo | YELLOW | 4 open Renovate PRs pending merge |

## Evidence Files

- `context-pack-2026-02-28/recon.json` - Full recon script output (JSON)
- `context-pack-2026-02-28/network.json` - Network health check (JSON)
- `context-pack-2026-02-28/nas.json` - NAS health check (JSON)
- `context-pack-2026-02-28/kube-system.txt` - kube-system pod inventory
- `context-pack-2026-02-28/ceph.txt` - Full Ceph status, df, osd tree
- `context-pack-2026-02-28/platform.txt` - Ingress, certs, secrets, monitoring
- `context-pack-2026-02-28/apps-errors.txt` - Error-focused pod scan + all services
- `context-pack-2026-02-28/repo.txt` - Open PRs and issues
- `context-pack-2026-02-28/prs.json` - PR details (JSON)
- `context-pack-2026-02-28/issues.json` - Open issues (JSON)
- `context-pack-2026-02-28/dependency-dashboard.md` - Dependency Dashboard body
- `context-pack-2026-02-28/node-top.txt` - Node resource usage
- `context-pack-2026-02-28/events-warnings.txt` - Recent warning events

## Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| kubectl Version | v1.35.1 (skew warning: +/-1 minor exceeded) |
| Node Count | 10 |
| ArgoCD Apps | 41 total, all Synced+Healthy |
| Ceph Status | HEALTH_OK |
| Ceph Usage | 1.4 TiB / 3.4 TiB (39.87%) |

## Nodes

| Node | CPU | Memory | Status |
|------|-----|--------|--------|
| arcanine | 8 cores, 64GB, GPU | 3% CPU, 15% MEM | Ready |
| bulbasaur | 4 cores, 16GB | 17% CPU, 36% MEM | Ready |
| charmander | 4 cores, 24GB | 25% CPU, 25% MEM | Ready |
| chikorita | 4 cores, 32GB | 5% CPU, 10% MEM | Ready |
| cyndaquil | 4 cores, 16GB | 7% CPU, 27% MEM | Ready |
| growlithe | 4 cores, 32GB | 12% CPU, 15% MEM | Ready |
| pikachu | 4 cores, 16GB | 9% CPU, 20% MEM | Ready |
| sprigatito | 4 cores, 32GB, GPU | 4% CPU, 29% MEM | Ready |
| squirtle | 4 cores, 16GB | 18% CPU, 23% MEM | Ready |
| totodile | 4 cores, 16GB | 6% CPU, 14% MEM | Ready |

## Open PRs (Renovate)

| PR | Title | Type | Mergeable | Age |
|----|-------|------|-----------|-----|
| #67 | fix(deps): update all non-major dependencies | minor/patch | Yes | 4 days |
| #68 | chore(deps): update bitnamilegacy/postgresql to v17 | major | Yes | 4 days |
| #69 | chore(deps): update debian to v13 | major | Yes | 4 days |
| #70 | chore(deps): update valkey/valkey to v9 | major | Yes | 3 days |

### PR #67 Details (Non-Major)
- argo-cd: 9.4.4 -> 9.4.5 (patch)
- bitnamilegacy/postgresql: 16.2.0 -> 16.6.0 (minor)
- cert-manager: v1.19.3 -> v1.19.4 (patch)
- kanidm/server: 1.9.0 -> 1.9.1 (patch)
- kagent tools: 0.0.15 -> 0.0.16 (patch, archived)
- k8s.io/api,apimachinery,client-go: v0.35.1 -> v0.35.2 (patch)
- kube-prometheus-stack: 82.2.1 -> 82.4.3 (minor)
- ollama: 1.45.0 -> 1.46.0 (minor)
- postgres: 18.2 -> 18.3 (patch)
- renovate: 46.31.4 -> 46.44.1 (minor)
- rook-ceph: v1.19.1 -> v1.19.2 (patch)
- rook-ceph-cluster: v1.19.1 -> v1.19.2 (patch)
- supabase components: various patches (archived)

### PR #68 Details (Major)
- bitnamilegacy/postgresql: 16.2.0 -> 17.6.0 (MAJOR - matrix app)

### PR #69 Details (Major)
- debian: 12-slim -> 13-slim (MAJOR - archived moltbot app)

### PR #70 Details (Major)
- valkey/valkey: 8.1-alpine -> 9.0-alpine (MAJOR - nextcloud app)

## Warning Events (Transient)

- cilium-operator: Liveness/readiness probe failures (16m ago, recovered)
- rook-ceph-mon-f: Liveness probe timeout (16m ago, recovered)
- woodpecker-server: Readiness probe failure (50m ago, transient)
- ollama-model-puller: BackOff during model creation (normal behavior, now running)
- grafana: Readiness probe failure during pod replacement (now running)

All warning events are transient and pods are currently healthy.

## Dependency Dashboard (Issue #4)

Repository problems noted:
- GitHub token not configured for release notes retrieval

Unchecked items map to open PRs #67-#70.

## Findings

1. **kubectl version skew**: Client v1.35 vs server v1.33 exceeds supported +/-1 minor skew. Low risk but should be noted.
2. **4 Renovate PRs pending**: All mergeable, covering system (argocd, cert-manager, rook-ceph, monitoring), platform (kanidm, renovate), and apps (ollama, postgres) updates.
3. **3 major version PRs**: PostgreSQL 16->17 (matrix), Debian 12->13 (archived), Valkey 8->9 (nextcloud) require careful review.
4. **Ceph usage at 39.87%**: Healthy but worth monitoring.
5. **All layers currently GREEN**: No immediate remediation needed.
