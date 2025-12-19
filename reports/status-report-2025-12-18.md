# Homelab Status Report - 2025-12-18

## Executive Summary
**Overall Status**: GREEN
**Summary**: All 10 nodes healthy, all 34 ArgoCD applications synced and healthy. Ceph storage at 6% utilization with HEALTH_OK. 10 Renovate PRs pending for dependency updates.

---

## Layer Status Overview

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | GREEN | - All 10 nodes Ready (K3s v1.33.6)<br>- CPU: max 16% (squirtle), avg 9.5%<br>- Memory: max 25% (bulbasaur), avg 16%<br>- Fedora 39, kernel 6.11.9 |
| **System** | GREEN | - Ceph HEALTH_OK, 7 OSDs up<br>- Storage: 201 GiB used / 3.4 TiB (5.76%)<br>- Cilium CNI healthy, CoreDNS operational |
| **Platform** | GREEN | - ArgoCD: 34/34 Synced & Healthy<br>- All 18 certificates valid (earliest expiry: Jan 18, 2026)<br>- Ingress, Dex, Kanidm, Grafana operational |
| **Apps** | GREEN | - 179 pods running across 88 namespaces<br>- All critical apps (Emby, Gitea, OpenWebUI) healthy<br>- No CrashLoopBackOff or Error pods |

---

## Service Status

### Core Infrastructure
| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| ArgoCD | argocd | GREEN | - | 7 pods Running |
| Cert-Manager | cert-manager | GREEN | - | 3 pods Running |
| Ingress-NGINX | ingress-nginx | GREEN | - | 1 controller Running |
| External-DNS | external-dns | GREEN | - | Running (5 restarts, stable now) |
| Rook-Ceph | rook-ceph | GREEN | - | All operators and OSDs healthy |

### Platform Services
| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| Gitea | gitea | GREEN | - | Main + PostgreSQL + 6 Valkey nodes |
| Grafana | grafana | GREEN | - | 3/3 containers Ready |
| Kanidm | kanidm | GREEN | - | StatefulSet healthy |
| Dex | dex | GREEN | - | 1 pod Running |
| Woodpecker | woodpecker | GREEN | - | CI/CD operational |

### Applications
| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| Emby | emby | GREEN | - | Media server healthy |
| OpenWebUI | openwebui | GREEN | - | AI interface operational |
| Ollama | ollama | GREEN | - | LLM backend running |
| LocalAI | localai | GREEN | - | Running 5d2h |
| Radarr | radarr | GREEN | - | Movie automation |
| Sonarr | sonarr | GREEN | - | TV automation |
| Sabnzbd | sabnzbd | GREEN | - | Download manager (2 containers) |
| Explorers-Hub | explorers-hub | GREEN | - | Running (recent restart) |
| SearXNG | searxng | GREEN | - | Meta search engine |

---

## Security Findings

### Certificate Status
| Certificate | Namespace | Expires | Status |
|-------------|-----------|---------|:------:|
| kanidm-selfsigned | kanidm | 2026-01-18 | GREEN |
| searxng-tls-certificate | searxng | 2026-02-01 | GREEN |
| localai-eaglepass-io-tls | localai | 2026-02-01 | GREEN |
| gitea-tls-certificate | gitea | 2026-02-14 | GREEN |
| humbleai-tls | humbleai | 2026-02-28 | GREEN |
| humbleai-tls | humbleai-canary | 2026-03-01 | GREEN |
| open-tls-certificate | openwebui | 2026-03-12 | GREEN |
| (12 others) | various | 2026-03-19 | GREEN |

**All 18 certificates valid. Earliest expiry: 31+ days away.**

### Security Advisories
- None identified in current scan

### Configuration Concerns
- None identified

---

## Maintenance Order of Operations

### Execution Sequence

| Step | Priority | Item | Type | Est. Downtime | Dependencies | Rollback Plan |
|:----:|:--------:|------|------|:-------------:|--------------|---------------|
| 1 | P3 | PR #11 | Dep Bundle | 0 min | None | Revert commit |
| 2 | P2 | PR #18 | snapshot-controller v4 | 0 min | None | Revert commit |
| 3 | P2 | PR #17 | kured v5 | 0 min | None | Revert commit |
| 4 | P2 | PR #16 | grafana v10 | 0 min | None | Revert commit |
| 5 | P2 | PR #13 | app-template v4 | 0 min | None | Revert commit |
| 6 | P2 | PR #20 | k8s.io/client-go v12 | 0 min | None | Revert commit |
| 7 | P2 | PR #19 | gopkg.in/yaml.v2 v3 | 0 min | None | Revert commit |
| 8 | P2 | PR #15 | external-secrets v1 | 0 min | Sync stable | Revert commit |
| 9 | P2 | PR #14 | argo-cd v9 | 0-5 min | ArgoCD stable | Revert commit |
| 10 | P2 | PR #12 | supabase/postgres v17 | 0 min | Backups ready | Revert commit |

### Zero-Downtime Guidelines

**Safe Update Order**:
1. Non-major dependency patches (PR #11)
2. Platform services (kured, snapshot-controller)
3. Monitoring stack (grafana)
4. App template libraries (app-template)
5. Go module updates (client-go, yaml.v3)
6. Core infrastructure (external-secrets, argo-cd)
7. Database updates (postgres) - **ALWAYS LAST**

### Pre-Maintenance Checklist
- [x] Backup verification complete (Ceph healthy)
- [x] ArgoCD sync status: All Synced/Healthy
- [x] Health status: GREEN across all layers
- [ ] Rollback procedures documented for risky items
- [ ] Maintenance window communicated (if applicable)

---

## Issues & Recommendations

### Critical (RED)
- None

### Warnings (YELLOW)
- None

### Observations (GREEN)
- Cluster underwent maintenance/restart ~43h ago; all services recovered successfully
- External-DNS had 5 restarts but is now stable
- Node exporter pods show high restart counts (accumulated over 10d) but functioning correctly
- Storage utilization low (5.76%) - healthy capacity headroom

---

## Verification Data

- **Nodes**: 10 Online / 10 Total
- **Storage**: 5.76% Used (3.2 TiB free of 3.4 TiB)
- **Top Resource Consumer**: squirtle (16% CPU), bulbasaur (25% RAM)
- **ArgoCD Apps**: 34 Synced / 34 Total
- **Certificates**: 18 Valid / 18 Total
- **Running Pods**: 179
- **Namespaces**: 88

---

## Risk Assessment

| Update/Change | Impact | Dependencies | Mitigation |
|---------------|--------|--------------|------------|
| PR #14 (argo-cd v9) | HIGH | All GitOps | Test in staging, backup manifests |
| PR #15 (external-secrets v1) | MEDIUM | Secrets sync | Verify secret stores after |
| PR #12 (postgres v17) | MEDIUM | Gitea data | Backup database first |
| PR #13 (app-template v4) | LOW | App deployments | Incremental rollout |
| Other PRs | LOW | Minimal | Standard rollback |

---

## Gitea Repository State

### Open Pull Requests - Renovate (Automated)
| PR | Title | Age | Status | Action Needed |
|----|-------|-----|--------|---------------|
| #11 | chore(deps): update all non-major dependencies | 7d | mergeable | Merge via /homelab-action |
| #12 | chore(deps): update supabase/postgres to v17 | 7d | mergeable | Merge via /homelab-action |
| #13 | chore(deps): update app-template to v4 | 6d | mergeable | Merge via /homelab-action |
| #14 | chore(deps): update argo-cd to v9 | 6d | mergeable | Merge via /homelab-action |
| #15 | chore(deps): update external-secrets to v1 | 5d | mergeable | Merge via /homelab-action |
| #16 | chore(deps): update grafana to v10 | 5d | mergeable | Merge via /homelab-action |
| #17 | chore(deps): update kured to v5 | 3d | mergeable | Merge via /homelab-action |
| #18 | chore(deps): update snapshot-controller to v4 | 3d | mergeable | Merge via /homelab-action |
| #19 | fix(deps): update gopkg.in/yaml.v2 to v3 | 2d | mergeable | Merge via /homelab-action |
| #20 | fix(deps): update k8s.io/client-go to v12 | 2d | mergeable | Merge via /homelab-action |

### Open Pull Requests - User (Manual)
None

### Open Issues (Non-Maintenance)
| Issue | Title | Labels | Age | Priority | Action Needed |
|-------|-------|--------|-----|----------|---------------|
| #4 | Dependency Dashboard | - | 9d | P3 | Info only - auto-managed by Renovate |

### Summary
- **Renovate PRs**: 10 (process via /homelab-action)
- **User PRs**: 0
- **Open Issues**: 1 (Dependency Dashboard - informational)
- **Oldest unresolved PR**: #11 (7 days)

---

*Generated by Homelab Recon Workflow*
*Last Updated: 2025-12-18 19:45 UTC*
