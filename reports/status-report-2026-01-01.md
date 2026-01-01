# Homelab Status Report - 2026-01-01

## Executive Summary
**Overall Status**: GREEN
**Summary**: All systems are operating nominally. 10 nodes online with healthy resource utilization. Ceph storage at HEALTH_OK with 92.3% available capacity. All 46 ArgoCD applications are Synced and Healthy. 10 Renovate PRs pending for dependency updates.

---

## Layer Status Overview

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | GREEN | - 10/10 nodes Ready<br>- CPU: max 48% (arcanine)<br>- RAM: max 26% (cyndaquil)<br>- All on Fedora 39, kernel 6.11.9 |
| **System** | GREEN | - K3s v1.33.6+k3s1 running<br>- Cilium CNI healthy<br>- Ceph HEALTH_OK, 3.1 TiB available (92.3%) |
| **Platform** | GREEN | - ArgoCD: 46/46 apps Synced/Healthy<br>- All certificates valid<br>- Ingress-nginx operational |
| **Apps** | GREEN | - All user applications running<br>- No CrashLoopBackOff<br>- Renovate job completing successfully |

---

## Node Status

| Node | Role | CPU% | RAM% | Version | GPU |
|------|------|:----:|:----:|---------|-----|
| arcanine | worker | 48% | 5% | v1.33.6+k3s1 | RTX 3090 (24GB) |
| bulbasaur | control-plane | 10% | 23% | v1.33.6+k3s1 | - |
| charmander | control-plane | 17% | 18% | v1.33.6+k3s1 | - |
| chikorita | worker | 12% | 15% | v1.33.6+k3s1 | - |
| cyndaquil | worker | 11% | 26% | v1.33.6+k3s1 | - |
| growlithe | worker | 8% | 12% | v1.33.6+k3s1 | - |
| pikachu | worker | 10% | 18% | v1.33.6+k3s1 | - |
| sprigatito | worker | 3% | 9% | v1.33.6+k3s1 | GTX 1650 (4GB) |
| squirtle | control-plane | 13% | 24% | v1.33.6+k3s1 | - |
| totodile | worker | 15% | 21% | v1.33.6+k3s1 | - |

---

## Storage Status (Ceph)

| Metric | Value | Status |
|--------|-------|:------:|
| Cluster Health | HEALTH_OK | GREEN |
| Total Capacity | 3.4 TiB | - |
| Available | 3.1 TiB (92.3%) | GREEN |
| Used | 269 GiB (7.7%) | - |
| OSDs | 7 up / 7 in | GREEN |
| MONs | 3 (quorum) | GREEN |
| MGRs | 2 (1 active, 1 standby) | GREEN |
| MDS | 2 (1 active, 1 standby) | GREEN |

---

## Service Status

| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| ArgoCD | argocd | GREEN | v2.14.11 | All apps synced |
| Gitea | gitea | GREEN | 1.24.6 | PostgreSQL + Valkey cluster |
| Grafana | grafana | GREEN | - | Monitoring operational |
| Prometheus | monitoring-system | GREEN | v2.50.1 | Metrics collection active |
| Loki | loki | GREEN | - | Log aggregation working |
| Ingress-NGINX | ingress-nginx | GREEN | 1.14.1 | Traffic routing normal |
| Cert-Manager | cert-manager | GREEN | v1.19.2 | All certs valid |
| External-Secrets | external-secrets | GREEN | v0.20.4 | 1Password integration working |
| Ollama | ollama | GREEN | 0.13.0 | AI inference ready |
| LocalAI | localai | GREEN | - | Running on arcanine GPU |
| Emby | emby | GREEN | - | Media serving operational |
| Rook-Ceph | rook-ceph | GREEN | v1.18.8 | Storage healthy |
| Kanidm | kanidm | GREEN | - | Identity management |
| Woodpecker | woodpecker | GREEN | - | CI/CD operational |

---

## Certificate Status

All certificates are valid. Earliest expiring certificates:

| Certificate | Namespace | Expires | Days Left | Status |
|-------------|-----------|---------|:---------:|:------:|
| localai-eaglepass-io-tls | localai | 2026-02-01 | 31 | GREEN |
| searxng-tls-certificate | searxng | 2026-02-01 | 31 | GREEN |
| backlog-companion-tls | backlog-companion | 2026-02-07 | 37 | GREEN |
| nextcloud-tls-certificate | nextcloud | 2026-02-08 | 38 | GREEN |
| gitea-tls-certificate | gitea | 2026-02-14 | 44 | GREEN |
| humbleai-tls | humbleai | 2026-02-28 | 58 | GREEN |

---

## Gitea Repository State

### Open Pull Requests - Renovate (Automated)

| PR | Title | Age | Mergeable | Priority |
|----|-------|:---:|:---------:|:--------:|
| #20 | fix(deps): update module k8s.io/client-go to v12 | 16d | No | P3 |
| #19 | fix(deps): update module gopkg.in/yaml.v2 to v3 | 16d | Yes | P3 |
| #18 | chore(deps): update helm release snapshot-controller to v4 | 17d | No | P2 |
| #17 | chore(deps): update helm release kured to v5 | 17d | No | P2 |
| #16 | chore(deps): update helm release grafana to v10 | 19d | Yes | P2 |
| #15 | chore(deps): update helm release external-secrets to v1 | 19d | No | P2 |
| #14 | chore(deps): update helm release argo-cd to v9 | 20d | Yes | P2 |
| #13 | chore(deps): update helm release app-template to v4 | 20d | Yes | P2 |
| #12 | chore(deps): update dependency supabase/postgres to v17 | 21d | Yes | P2 |
| #11 | chore(deps): update all non-major dependencies helm releases | 21d | Yes | P3 |

### Open Issues (Non-Maintenance)

| Issue | Title | Labels | Age | Priority |
|-------|-------|--------|:---:|:--------:|
| #4 | Dependency Dashboard | - | 23d | Info |

### Summary
- **Renovate PRs**: 10 (6 mergeable, 4 have conflicts)
- **Maintenance Issues**: 1 (#10)
- **Oldest unresolved PR**: #11 (21 days)

---

## Maintenance Order of Operations

> **Execute in sequence.** Validate GREEN status after each change.

### Pre-Maintenance Checklist
- [x] Backup verification: Ceph healthy
- [x] ArgoCD sync status: All Synced/Healthy
- [x] Health status: GREEN across all layers
- [x] Rollback procedures: Git revert available

### Execution Sequence

| Step | Priority | Item | Type | Est. Downtime | Dependencies |
|:----:|:--------:|------|------|:-------------:|--------------|
| 1 | P3 | PR #11 | Non-major deps bundle | 0 min | None |
| 2 | P3 | PR #19 | Fix: yaml v2->v3 | 0 min | None |
| 3 | P2 | PR #16 | Grafana v10 | 0 min | None |
| 4 | P2 | PR #14 | ArgoCD v9 | 0 min | None |
| 5 | P2 | PR #13 | App-template v4 | 0 min | Step 4 |
| 6 | P2 | PR #12 | Postgres v17 | 0 min | LAST |

**Note**: PRs #15, #17, #18, #20 have merge conflicts and require rebasing before merge.

---

## Issues & Recommendations

### Critical (RED)
- None

### Warnings (YELLOW)
- None

### Observations (GREEN)
- All systems nominal
- 10 Renovate PRs pending review (some with conflicts)
- Storage utilization healthy at 7.7%
- GPU nodes (arcanine, sprigatito) operational
- Certificate renewals on track

### Recommendations
1. **Process mergeable PRs**: #11, #19, #16, #14, #13, #12 can be merged via `/homelab-action`
2. **Resolve PR conflicts**: PRs #15, #17, #18, #20 need rebasing
3. **Monitor certificates**: Earliest expiry Feb 1 (localai, searxng) - auto-renewal expected

---

## Verification Data

- **Nodes**: 10 Online / 10 Total
- **Control Planes**: 3 (bulbasaur, charmander, squirtle)
- **Workers**: 7 (arcanine, chikorita, cyndaquil, growlithe, pikachu, sprigatito, totodile)
- **GPU Nodes**: 2 (arcanine: RTX 3090, sprigatito: GTX 1650)
- **Storage**: 7.7% Used (269 GiB / 3.4 TiB)
- **ArgoCD Apps**: 46 Synced / 46 Total
- **Certificates**: 28 Valid / 28 Total
- **Namespaces**: 97 Active
- **Top CPU Consumer**: arcanine (48% - GPU workloads)
- **Top RAM Consumer**: cyndaquil (26%)

---

## Risk Assessment

| Update/Change | Impact | Dependencies | Mitigation |
|---------------|:------:|--------------|------------|
| ArgoCD v9 (PR #14) | Medium | Core GitOps | Staged rollout, verify sync |
| Grafana v10 (PR #16) | Low | Monitoring | Dashboard backup |
| Postgres v17 (PR #12) | Medium | Databases | Data backup, test migration |
| App-template v4 (PR #13) | Low | App charts | Review breaking changes |

---

*Generated by Homelab Recon Workflow*
*Last Updated: 2026-01-01 09:58 CST*
