# Homelab Status Report - 2025-12-10

## Executive Summary
**Overall Status**: **GREEN**
**Summary**: Cluster is fully operational with all 10 Kubernetes nodes Ready, all 32 ArgoCD applications Synced/Healthy, and Ceph storage reporting HEALTH_OK. All pods are healthy with no CrashLoopBackOff issues. All core infrastructure and user applications are running smoothly.

---

## Layer Status Overview

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | GREEN | - All 10 nodes Ready<br>- CPU: 2-27%, Memory: 5-24%<br>- No resource pressure<br>- Fedora 39, kernel 6.11.9 |
| **System** | GREEN | - K3s v1.33.6+k3s1<br>- Cilium CNI healthy on all 10 nodes<br>- Ceph HEALTH_OK<br>- 7 OSDs up, 192 GiB used of 3.4 TiB |
| **Platform** | GREEN | - 32/32 ArgoCD apps Synced & Healthy<br>- Ingress-nginx running (1 pod)<br>- All 17 certificates valid (until 2026)<br>- Monitoring stack operational |
| **Apps** | GREEN | - 180 pods total, 167 Running + 13 Completed<br>- All user services responsive<br>- No failing pods |

---

## Service Status

| Service | Namespace | Status | Version | Notes |
|---------|-----------|:------:|---------|-------|
| ArgoCD | argocd | GREEN | v2.14.11 | 32 apps synced |
| Cert-Manager | cert-manager | GREEN | - | 3 pods healthy |
| Ingress-NGINX | ingress-nginx | GREEN | - | 1 controller pod |
| Grafana | grafana | GREEN | v10.4.3 | 3/3 containers running |
| Prometheus | monitoring-system | GREEN | - | AlertManager healthy |
| Kanidm | kanidm | GREEN | v1.8.4 | Identity provider running |
| Dex | dex | GREEN | - | OIDC provider running |
| External-Secrets | external-secrets | GREEN | - | 7 secrets synced |
| Gitea | gitea | GREEN | v1.24.6 | Full Valkey cluster (6 pods) |
| Emby | emby | GREEN | - | Media server running |
| Sonarr/Radarr | sonarr/radarr | GREEN | - | Automation running |
| OpenWebUI | openwebui | GREEN | latest | AI interface running |
| Ollama | ollama | GREEN | latest | LLM backend running |
| LocalAI | localai | GREEN | - | AI backend running |
| Rook-Ceph | rook-ceph | GREEN | - | HEALTH_OK, all PGs clean |
| Woodpecker | woodpecker | GREEN | - | CI/CD operational |

---

## Security Findings

### Certificate Status
| Certificate | Namespace | Expires | Status |
|-------------|-----------|---------|:------:|
| argocd-server-tls | argocd | 2026-01-18 | GREEN |
| dex-tls-certificate | dex | 2026-01-18 | GREEN |
| emby-tls-certificate | emby | 2026-01-18 | GREEN |
| gitea-tls-certificate | gitea | 2026-02-14 | GREEN |
| grafana-general-tls | grafana | 2026-01-18 | GREEN |
| kanidm-tls-certificate | kanidm | 2026-01-18 | GREEN |
| openwebui-tls | openwebui | 2026-01-11 | GREEN |
| All 17 certificates | Various | 2026+ | GREEN |

### Configuration Concerns
- [x] K3s updated to v1.33.6 (current)
- [x] Orphaned pods resolved - default namespace now healthy

---

## Ceph Storage Status

### Current Health
```
HEALTH_OK
```

### Storage Capacity
- **Total**: 3.4 TiB
- **Used**: 192 GiB (5.6%)
- **Available**: 3.2 TiB

### OSD Status
- **OSDs**: 7 up, 7 in
- **Monitors**: 3 (d, f, g)
- **MGRs**: 2 (b active, a standby)
- **MDS**: 1 up, 1 hot standby
- **PGs**: 81 active+clean

---

## Issues & Recommendations

### Critical (RED)
None

### Warnings (YELLOW)
None - all previous issues resolved

### Observations (GREEN)
- K3s running v1.33.6+k3s1 - fully current
- Ceph storage healthy at HEALTH_OK
- All 10 Kubernetes nodes healthy with low resource utilization
- All 32 ArgoCD applications synced and healthy
- All 17 TLS certificates valid until 2026
- Storage capacity healthy at 5.6% utilization
- All user-facing applications operational and responsive
- Previous orphaned pods in default namespace now healthy

---

## Verification Data

| Metric | Value |
|--------|-------|
| Nodes | 10 / 10 Ready |
| Pods | 167 Running + 13 Completed |
| ArgoCD Apps | 32 / 32 Healthy |
| Certificates | 17 / 17 Valid |
| Ceph OSDs | 7 up / 7 in |
| Storage Used | 5.6% (192 GiB / 3.4 TiB) |
| PGs | 81 active+clean |

---

## Resource Utilization

| Node | CPU | Memory | Role |
|------|-----|--------|------|
| arcanine | 5% | 5% | worker (64GB) |
| bulbasaur | 12% | 24% | control-plane (16GB) |
| charmander | 24% | 16% | control-plane (24GB) |
| chikorita | 8% | 8% | worker (32GB) |
| cyndaquil | 5% | 13% | worker (16GB) |
| growlithe | 27% | 17% | worker (32GB) |
| pikachu | 6% | 12% | worker (16GB) |
| sprigatito | 2% | 13% | worker (32GB) |
| squirtle | 14% | 20% | control-plane (16GB) |
| totodile | 11% | 18% | worker (16GB) |

**Top Resource Consumers:**
1. emby (2793Mi memory)
2. prometheus (1603Mi memory)
3. rook-ceph-osd-2 (790Mi memory)

---

## Pending Updates

### Open Pull Requests
None - All PRs merged

### Recently Merged PRs (2025-12-10)
| PR | Title | Merged |
|----|-------|--------|
| #7 | Non-major dependencies (cert-manager, kanidm 1.8.4, k8s libs, supabase) | 16:03 UTC |
| #8 | Postgrest v13 (major version update) | 16:03 UTC |

### Rate-Limited Updates (Dependency Dashboard #4)
- **Helm**: app-template v4, argo-cd v9, external-secrets v1, grafana v10, kube-prometheus-stack v80
- **Images**: cloudflared 2025.x, homepage v1, postgres v18
- **Terraform**: cloudflare v5, kubernetes v3

---

## Recent Events Summary
Recent warning events observed during recon (all transient):
- Grafana readiness probes during pod restarts (resolved)
- Kanidm volume multi-attach during rescheduling (resolved)
- Global-secrets job backoff (newer job completed successfully)

All warnings are from normal Kubernetes operations during recent maintenance window.

---

## Improvements Since Last Report
1. **Orphaned Pods**: CrashLoopBackOff pods in default namespace now healthy/resolved
2. **Grafana**: Restarted successfully after brief unavailability
3. **Kanidm**: Volume attachment resolved after pod migration

---

## Gitea Repository State

### Open Pull Requests (Non-Maintenance)
None - All PRs have been merged

### Open Issues (Non-Maintenance)
| Issue | Title | Labels | Age | Priority | Action Needed |
|-------|-------|--------|-----|----------|---------------|
| #4 | Dependency Dashboard | - | 1d | Low | None (Renovate managed) |

### Summary
- **Open PRs requiring action**: 0
- **Open Issues requiring action**: 0 (Issue #4 is Renovate-managed)
- **Previous maintenance issues**: All resolved (Issues #1, #5, #6, #9)

---

*Generated by Homelab Recon Workflow*
*Last Updated: 2025-12-10 15:18 CST*
