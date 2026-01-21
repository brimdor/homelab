# Homelab Status Report - 2025-12-09

## Executive Summary
**Overall Status**: **YELLOW**
**Summary**: Cluster is operationally healthy with all Kubernetes nodes Ready and all 32 ArgoCD applications Synced/Healthy. However, Ceph storage remains in HEALTH_WARN state with **629 daemon crashes** (primarily OSDs from Dec 8), **mon g low on disk space (16% avail)**, and 2 OSDs currently down. The noout flag is set as a protective measure. Immediate attention required on Ceph storage subsystem.

---

## Layer Status Overview

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | GREEN | - Controller (10.0.20.10) reachable via SSH<br>- All 10 nodes Ready<br>- CPU: 3-16%, Memory: 10-37%<br>- No disk pressure, no memory pressure |
| **System** | YELLOW | - k3s v1.28.3+k3s2 (5 versions behind current)<br>- Cilium CNI healthy on all 10 nodes<br>- Ceph HEALTH_WARN: 629 crashes, mon g low disk, noout set<br>- 7/9 OSDs up, 5 in cluster |
| **Platform** | GREEN | - 32/32 ArgoCD apps Synced & Healthy<br>- Ingress-nginx running (1 pod)<br>- All 17 certificates valid (until 2026)<br>- Monitoring stack operational |
| **Apps** | GREEN | - 183 pods total, all Running/Completed<br>- All user services responsive<br>- No failed or crashlooping pods |

---

## Service Status

| Service | Namespace | Status | Notes |
|---------|-----------|:------:|-------|
| ArgoCD | argocd | GREEN | 32 apps synced |
| Cert-Manager | cert-manager | GREEN | 3 pods healthy |
| Ingress-NGINX | ingress-nginx | GREEN | 1 controller pod |
| Grafana | grafana | GREEN | Recently restarted (18m ago) |
| Prometheus | monitoring-system | GREEN | AlertManager healthy |
| Kanidm | kanidm | GREEN | Identity provider running |
| Dex | dex | GREEN | OIDC provider running |
| External-DNS | external-dns | GREEN | DNS sync active |
| Gitea | gitea | GREEN | Full Valkey cluster (6 pods) |
| Emby | emby | GREEN | Media server running |
| Sonarr/Radarr | sonarr/radarr | GREEN | Automation running |
| OpenWebUI | openwebui | GREEN | AI interface running |
| Ollama | ollama | GREEN | LLM backend running |
| LocalAI | localai | GREEN | AI backend running |
| Rook-Ceph | rook-ceph | YELLOW | Storage with warnings |

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
- [ ] K3s v1.28.3 is 5 minor versions behind current (v1.33.x) - upgrade recommended
- [ ] kubectl v1.34.2 vs K3s v1.28.3 exceeds version skew policy

---

## Ceph Storage Status

### Current Health
```
HEALTH_WARN mon g is low on available space; noout flag(s) set; 629 daemons have recently crashed
```

### Storage Capacity
- **Total**: 2.5 TiB
- **Used**: 210 GiB (8.08%)
- **Available**: 2.3 TiB

### OSD Status
| OSD | Host | Status | Weight | Action |
|-----|------|--------|--------|--------|
| osd.0 | chikorita | UP | 1.0 | OK |
| osd.1 | unknown | DOWN | 0 | Investigate |
| osd.2 | arcanine | UP | 1.0 | OK |
| osd.3 | cyndaquil | UP | 1.0 | OK |
| osd.4 | bulbasaur | UP | 1.0 | OK |
| osd.5 | growlithe | DOWN | 0 | Investigate |
| osd.6 | growlithe | UP | 0 | Reweight |
| osd.7 | sprigatito | UP | 0 | Reweight |
| osd.8 | arcanine | UP | 1.0 | OK |

---

## Issues & Recommendations

### Critical (RED)
None

### Warnings (YELLOW)

- [ ] **Ceph OSD Crash History**: 629 crashes recorded (mostly from Dec 8)
  - **Impact**: Cluster stability, potential data availability risk
  - **Fix**: `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph crash archive-all`

- [ ] **Monitor g Low Disk**: 16% available on growlithe
  - **Impact**: Monitor could become unavailable
  - **Fix**: Clean up disk space on growlithe or migrate mon

- [ ] **OSDs Down/Zero-Weight**: osd.1, osd.5 down; osd.6, osd.7 weight=0
  - **Impact**: Reduced redundancy
  - **Fix**: Investigate disk status, reweight or remove OSDs

- [ ] **noout Flag Set**: Preventing OSD rebalancing
  - **Fix**: Clear after OSD issues resolved: `ceph osd unset noout`

- [ ] **K3s Version**: v1.28.3 is 5 versions behind
  - **Impact**: Missing security patches and features
  - **Fix**: Plan rolling upgrade through v1.29 -> v1.33

### Observations (GREEN)
- All 10 Kubernetes nodes healthy with no pressure conditions
- All 32 ArgoCD applications synced and healthy
- All 17 TLS certificates valid until 2026
- Storage capacity adequate at 8% utilization
- All user-facing applications operational

---

## Verification Data

| Metric | Value |
|--------|-------|
| Nodes | 10 / 10 Ready |
| Pods | 183 total |
| ArgoCD Apps | 32 / 32 Healthy |
| Certificates | 17 / 17 Valid |
| Ceph OSDs | 7 up / 9 total |
| Storage Used | 8.08% (210 GiB / 2.5 TiB) |
| PGs | 81 active+clean |

---

## Resource Utilization

| Node | CPU | Memory | Role |
|------|-----|--------|------|
| arcanine | 5% | 10% | worker |
| bulbasaur | 16% | 35% | control-plane |
| charmander | 15% | 37% | control-plane |
| chikorita | 7% | 11% | worker |
| cyndaquil | 6% | 24% | worker |
| growlithe | 7% | 14% | worker |
| pikachu | 8% | 26% | worker |
| sprigatito | 3% | 19% | worker |
| squirtle | 11% | 31% | control-plane |
| totodile | 8% | 29% | worker |

---

## Pending Updates

| Component | Current | Recommended | Priority | Notes |
|-----------|---------|-------------|:--------:|-------|
| K3s | v1.28.3+k3s2 | v1.33.x | HIGH | 5 versions behind |
| Cilium | v1.15.1 | Latest | MEDIUM | Check compatibility |

### Open PRs
- **PR #2**: Non-major dependency updates
- **PR #3**: Kong v3 update

---

*Generated by Homelab Recon Workflow*
*Last Updated: 2025-12-09 13:54 CST*
