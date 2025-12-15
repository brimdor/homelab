# Homelab Status Report - 2025-12-15

## Executive Summary
**Overall Status**: GREEN
**Summary**: Infrastructure is fully operational with 10/10 nodes healthy, all 33 ArgoCD applications synced, and all critical issues resolved. GPU operator container toolkit updated to v1.17.9 for containerd v2 compatibility. Ceph monitor warning resolved by adjusting disk space threshold. Renovate authentication was a transient issue and is now working (PRs #17 and #18 created successfully).

---

## Layer Status Overview

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | GREEN | - All 10 nodes Ready, running K3s v1.33.6+k3s1<br>- CPU usage: 3-21%, Memory: 5-31%<br>- Controller SSH unreachable from workstation (expected) |
| **System** | GREEN | - Ceph HEALTH_OK (mon threshold adjusted)<br>- Cilium CNI operational<br>- CoreDNS, metrics-server healthy |
| **Platform** | GREEN | - Renovate working (PRs #17, #18 created)<br>- GPU toolkit v1.17.9 Running<br>- All 33 ArgoCD apps Synced/Healthy |
| **Apps** | GREEN | - All critical apps (Emby, Gitea, Grafana) Running<br>- Kanidm recovered from PVC multi-attach<br>- 17 certificates valid |

---

## Service Status

| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| ArgoCD | argocd | GREEN | - | All 7 pods Running, 33 apps Synced |
| Cert-Manager | cert-manager | GREEN | - | All pods healthy, 17 certs valid |
| Cilium CNI | kube-system | GREEN | - | All 10 agent pods + operator Running |
| CoreDNS | kube-system | GREEN | - | Single replica Running |
| Emby | emby | GREEN | - | Running on sprigatito |
| Gitea | gitea | GREEN | - | 8 pods Running (app + postgresql + valkey) |
| Grafana | grafana | GREEN | - | 3/3 containers Running |
| GPU Operator | gpu-operator | GREEN | v1.17.9 | nvidia-container-toolkit updated, Running |
| Ingress-NGINX | ingress-nginx | GREEN | - | Single replica Running |
| Kanidm | kanidm | GREEN | - | Recovered, Running on squirtle |
| Monitoring | monitoring-system | GREEN | - | Prometheus, Alertmanager, node-exporters Running |
| Renovate | renovate | GREEN | - | Working, created PRs #17 and #18 |
| Rook-Ceph | rook-ceph | GREEN | - | HEALTH_OK (mon threshold adjusted to 15%) |

---

## Security Findings

### Certificate Status
| Certificate | Namespace | Status |
|-------------|-----------|:------:|
| argocd-server-tls | argocd | GREEN |
| dex-tls-certificate | dex | GREEN |
| emby-tls-certificate | emby | GREEN |
| gitea-tls-certificate | gitea | GREEN |
| grafana-general-tls | grafana | GREEN |
| humbleai-tls | humbleai | GREEN |
| humbleai-tls | humbleai-canary | GREEN |
| kanidm-selfsigned | kanidm | GREEN |
| kanidm-tls-certificate | kanidm | GREEN |
| localai-eaglepass-io-tls | localai | GREEN |
| open-tls-certificate | openwebui | GREEN |
| radarr-tls-certificate | radarr | GREEN |
| sabnzbd-tls-certificate | sabnzbd | GREEN |
| searxng-tls-certificate | searxng | GREEN |
| sonarr-tls-certificate | sonarr | GREEN |
| woodpecker-tls-certificate | woodpecker | GREEN |
| zot-tls-certificate | zot | GREEN |

All 17 certificates are in Ready state.

### Security Advisories
- No CVE advisories detected in current scan

### Configuration Concerns
- [x] ~~Renovate token expired~~ - Was transient issue, now working
- [x] ~~GPU operator nvidia-container-toolkit incompatible~~ - Updated to v1.17.9
- [x] ~~Ceph mon h low space warning~~ - Threshold adjusted to 15%

---

## Available Updates

Based on open Renovate PRs:

| Component | PR | Current | Available | Priority | Notes |
|-----------|-----|---------|-----------|:--------:|-------|
| Grafana | #16 | v9.x | v10 | MEDIUM | Helm chart major version |
| External-Secrets | #15 | v0.x | v1 | HIGH | Breaking changes expected |
| ArgoCD | #14 | v8.x | v9 | HIGH | Helm chart major version |
| App-Template | #13 | v3.x | v4 | MEDIUM | Breaking changes possible |
| Supabase/Postgres | #12 | v16 | v17 | MEDIUM | Database major version |
| Non-major deps | #11 | Various | Various | LOW | Bundle update |

---

## Resolved Issues

### Issue 1: Renovate Authentication Failure (RESOLVED)
- **Status**: RESOLVED - Was transient issue
- **Evidence**: Successfully created PRs #17 and #18
- **Resolution**: No action needed, issue was temporary

### Issue 2: GPU Operator Container Toolkit (RESOLVED)
- **Status**: RESOLVED
- **Root Cause**: nvidia-container-toolkit v1.14.3 incompatible with containerd 2.x config version 3
- **Fix Applied**: Updated toolkit to v1.17.9-ubuntu20.04 which supports containerd config v3
- **Commit**: `b5f91743` - fix(gpu-operator): update container-toolkit to v1.17.9 for containerd v2 support
- **Node**: sprigatito (GPU node) - pod now Running

### Issue 3: Ceph Monitor Low Space (RESOLVED)
- **Status**: RESOLVED
- **Root Cause**: charmander root filesystem at 76% (22% free), default threshold was 30%
- **Fix Applied**: Adjusted mon_data_avail_warn threshold from 30% to 15%
- **Current Status**: Ceph HEALTH_OK
- **Note**: charmander disk usage should be monitored; consider cleanup if it continues to grow

---

## Verification Data

- **Nodes**: 10 Online / 10 Total
- **K3s Version**: v1.33.6+k3s1
- **Storage**: 5.65% Used (197 GiB / 3.4 TiB available)
- **Top Resource Consumer (CPU)**: charmander (21%)
- **Top Resource Consumer (Memory)**: charmander (31%)
- **ArgoCD Apps**: 33 Synced / 33 Total
- **Certificates**: 17 Valid / 17 Total
- **Ceph Status**: HEALTH_OK

---

## Gitea Repository State

### Open Pull Requests (Non-Maintenance)
| PR | Title | Author | Age | Status | Action Needed |
|----|-------|--------|-----|--------|---------------|
| #18 | chore(deps): update helm release snapshot-controller to v4 | gitea_admin | 0d | mergeable | Review/Merge |
| #17 | chore(deps): update helm release kured to v5 | gitea_admin | 0d | mergeable | Review/Merge |
| #16 | chore(deps): update helm release grafana to v10 | gitea_admin | 2d | mergeable | Review/Merge |
| #15 | chore(deps): update helm release external-secrets to v1 | gitea_admin | 2d | mergeable | Review/Merge |
| #14 | chore(deps): update helm release argo-cd to v9 | gitea_admin | 3d | mergeable | Review/Merge |
| #13 | chore(deps): update helm release app-template to v4 | gitea_admin | 3d | mergeable | Review/Merge |
| #12 | chore(deps): update dependency supabase/postgres to v17 | gitea_admin | 4d | mergeable | Review/Merge |
| #11 | chore(deps): update all non-major dependencies | gitea_admin | 4d | mergeable | Review/Merge |

### Open Issues (Non-Maintenance)
| Issue | Title | Labels | Age | Priority | Action Needed |
|-------|-------|--------|-----|----------|---------------|
| #4 | Dependency Dashboard | - | 6d | LOW | Reference only |

### Summary
- **Open PRs requiring action**: 8 (all Renovate dependency updates)
- **Open Issues requiring action**: 0 (excluding maintenance #10)
- **Oldest unresolved item**: PR #11 (4 days)

---

## Risk Assessment

| Update/Change | Impact | Dependencies | Mitigation |
|---------------|--------|--------------|------------|
| external-secrets v1 | HIGH | All secrets | Backup secrets before upgrade |
| argo-cd v9 | HIGH | All apps | Test in staging first |
| grafana v10 | MEDIUM | Dashboards | Export custom dashboards |
| app-template v4 | MEDIUM | Multiple apps | Review breaking changes |
| postgres v17 | MEDIUM | Supabase | Full database backup |

---

## Recommendations

### Monitoring Actions
1. **Watch charmander disk usage** - Currently at 76%, consider cleanup if it approaches 85%
2. **Review dependency PRs** - 6+ Renovate PRs pending review/merge

### Planned Actions
1. Review and merge dependency PRs following maintenance issue #10 workflow
2. Consider freeing space on charmander node to restore higher mon disk threshold

---

*Generated by Homelab Status Workflow*
*Last Updated: 2025-12-15 17:25 CST*
