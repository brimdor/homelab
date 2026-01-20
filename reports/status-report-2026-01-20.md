# Homelab Status Report - 2026-01-20

**Generated**: 2026-01-20 14:25 CST
**Overall Status**: YELLOW (degraded apps, storage warning)

---

## Executive Summary

| Layer | Status | Issues |
|-------|:------:|--------|
| Metal | YELLOW | chikorita SchedulingDisabled, OSD.0 down |
| System | GREEN | kube-system healthy, Cilium 10/10 |
| Platform | YELLOW | emby OutOfSync, heartlib Degraded |
| Apps | YELLOW | wolf Error (evicted), localai unknown |

---

## Cluster Identity

- **K3s Version**: v1.33.6+k3s1
- **Client Version**: v1.35.0 (version skew warning)
- **Control Plane**: https://10.0.20.50:6443
- **Nodes**: 10 total (3 control-plane, 7 worker)
- **ArgoCD Apps**: 45 total (2 non-healthy)
- **Ceph**: HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)

---

## Node Status

| Node | Role | Status | CPU | Memory |
|------|------|:------:|----:|-------:|
| arcanine | worker | Ready | 42% | 14% |
| bulbasaur | control-plane | Ready | 19% | 29% |
| charmander | control-plane | Ready | 49% | 30% |
| chikorita | worker | **SchedulingDisabled** | 19% | 9% |
| cyndaquil | worker | Ready | 10% | 27% |
| growlithe | worker | Ready | 25% | 32% |
| pikachu | worker | Ready | 12% | 38% |
| sprigatito | worker | Ready | 9% | 24% |
| squirtle | control-plane | Ready | 25% | 44% |
| totodile | worker | Ready | 12% | 45% |

**Finding**: chikorita is cordoned (SchedulingDisabled) - likely intentional maintenance or OSD issue.

---

## Storage (Rook/Ceph)

### Health
```
HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)
```

### Capacity
- **Total**: 3.0 TiB
- **Used**: 1.2 TiB (40.50%)
- **Available**: 1.8 TiB

### OSD Status
| OSD | Host | Status | Weight |
|-----|------|:------:|-------:|
| osd.0 | chikorita | **DOWN** | 0 |
| osd.1 | cyndaquil | up | 1.0 |
| osd.2 | arcanine | up | 1.0 |
| osd.4 | bulbasaur | up | 1.0 |
| osd.6 | growlithe | up | 1.0 |
| osd.7 | sprigatito | up | 1.0 |
| osd.8 | arcanine | up | 1.0 |

**Finding**: OSD.0 on chikorita is DOWN with weight 0. Cluster still healthy due to replication.

### Services
- MON: 3 daemons (f, h, j)
- MGR: a (active), b (standby)
- MDS: 1/1 up, 1 hot standby
- OSD: 7 total, 6 up, 6 in

---

## ArgoCD Applications

### Non-Healthy Apps

| App | Sync | Health | Issue |
|-----|:----:|:------:|-------|
| emby | OutOfSync | Healthy | Deployment SyncFailed |
| heartlib | Synced | Degraded | Pod startup probe failing |

### App Details

**emby** - OutOfSync
- Deployment resource is OutOfSync
- SyncFailed on sync attempt
- May need manual intervention

**heartlib** - Degraded
- Pod startup probe failing on port 7860
- Logs show: `TypeError: expected token to be a str, received NoneType instead`
- **Root cause**: Discord token secret is missing/empty

---

## Non-Running Pods

| Namespace | Pod | Status | Reason |
|-----------|-----|:------:|--------|
| localai | localai-local-ai-565b69c969-qrhhz | ContainerStatusUnknown | Evicted - ephemeral-storage pressure |
| wolf | wolf-5f5cbb95dd-8tms9 | Error | Evicted - ephemeral-storage pressure |

### Eviction Details

Both pods were evicted from **arcanine** due to ephemeral-storage pressure:
- localai: using 2.5GB ephemeral storage
- wolf: using 4MB ephemeral storage

Note: arcanine currently shows `DiskPressure=False` (recovered ~20 minutes ago).

---

## Platform Components

### Certificates
- **Total**: 29
- **Ready**: 29/29

### External Secrets
- **Total**: 7
- **Synced**: 7/7

### Ingress
- nginx-controller: Running on growlithe

---

## Repository Status

### Open PRs (3 Renovate)

| PR | Title | Type | Change | Age | Mergeable |
|----|-------|:----:|--------|----:|:---------:|
| #45 | update all non-major dependencies | patch/minor | app-template 4.6.0->4.6.2, ollama 1.37.0->1.38.0, renovate 45.74.12->45.78.6, etc | 4d | Yes |
| #46 | update helm release kube-prometheus-stack to v81 | **MAJOR** | 80.14.4->81.1.0 | 3d | Yes |
| #47 | update cloudflared docker tag to v2026 | **MAJOR** | 2025.11.1->2026.1.1 | 5h | Yes |

### Open Issues (2)

| # | Title | Type | Labels |
|---|-------|:----:|--------|
| #44 | [Maintenance] 2026-01-16 - Homelab | Maintenance | maintenance |
| #4 | Dependency Dashboard | Renovate | - |

---

## Findings Summary

### P0 - Critical
1. **heartlib Degraded**: Missing Discord token secret - app cannot start

### P1 - High
1. **chikorita SchedulingDisabled**: Node cordoned, OSD.0 down
2. **emby OutOfSync**: ArgoCD sync failing on Deployment
3. **Evicted pods**: wolf and localai evicted due to storage pressure (resolved)

### P2 - Medium
1. **PR #45**: Non-major dependency updates ready to merge
2. **PR #46**: kube-prometheus-stack major update (requires release notes review)
3. **PR #47**: cloudflared major update (requires release notes review)

### P3 - Low
1. **kubectl version skew**: Client 1.35 vs Server 1.33 (minor warning)
2. **Muted Ceph alert**: DB_DEVICE_STALLED_READ_ALERT

---

## Recommended Actions

1. Fix heartlib Discord token secret
2. Investigate chikorita/OSD.0 status - determine if intentional maintenance
3. Sync emby app manually or investigate SyncFailed
4. Delete evicted pods (wolf and localai already have replacements running)
5. Review and merge PR #45 (low risk - patch/minor updates)
6. Review release notes for PRs #46 and #47 before merging (major updates)
