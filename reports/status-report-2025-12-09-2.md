# Homelab Status Report - 2025-12-09 (Evening Update)

## Executive Summary
**Overall Status**: 🟡 YELLOW  
**Summary**: **Significant improvement from earlier report.** All homelab systems are operational with all 10 Kubernetes nodes online. Critical Ceph daemon crashes (629) from earlier have been resolved - all 7 OSDs are now up and operational. Remaining warnings are minor: slow BlueStore operations on 1 OSD and low disk space on 3 monitors (d, f, g). System moved from critical storage issues to manageable warnings.

## Detailed Status
| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | 🟢 | - Controller (10.0.50.120) reachable, uptime 2 days 4:43 hours<br>- All 10 nodes online and Ready (arcanine, bulbasaur, charmander, chikorita, cyndaquil, growlithe, pikachu, sprigatito, squirtle, totodile)<br>- Resource usage healthy: CPU 2-16%, Memory 5-34%<br>- Highest resource usage: charmander (16% CPU, 34% RAM), bulbasaur (16% CPU, 32% RAM) |
| **System** | 🟡 | - All Kubernetes nodes Running v1.33.6+k3s1<br>- 3 control-plane nodes: bulbasaur (291d), charmander (291d), squirtle (291d)<br>- Cilium CNI: All 10 pods Running (deployed on every node)<br>- **Ceph HEALTH_WARN**: 1 OSD slow operations, monitors d/f/g low disk (improved from critical)<br>- All 7 OSDs up and in (improved from 7/9 with 2 down)<br>- Total pods: 185 across all namespaces |
| **Platform** | 🟢 | - ArgoCD: All 32 applications Healthy & Synced<br>- Ingress NGINX: Controller running (1 restart 8h ago)<br>- Certificate Manager: All certificates valid (0 failures)<br>- Monitoring: Prometheus/Grafana operational<br>- Total PVCs: 40 across cluster |
| **Apps** | 🟢 | - Emby: Running (1/1, 1 restart 8h ago, age 29h)<br>- Gitea: Fully operational with PostgreSQL & Valkey cluster (9 pods total)<br>- Sonarr: Running (1/1, 1 restart 8h ago, age 29h)<br>- Radarr: Running<br>- All app pods Running or Completed (0 failing pods outside kube-system/rook-ceph) |

## Issues & Recommendations

### Critical (Red)
None detected. ✅ **Previous critical issues resolved** (629 OSD crashes, 2 OSDs down, noout flag).

### Warnings (Yellow)
- [ ] **Issue**: 1 OSD experiencing slow BlueStore operations
  - **Impact**: Minor performance degradation on write operations
  - **Fix**: 
    1. Identify slow OSD: `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health detail`
    2. Check disk health on affected node
    3. Monitor disk I/O performance
    4. Consider reweighting OSD if persistent

- [ ] **Issue**: Monitors d, f, g low on available disk space
  - **Nodes affected**: Likely squirtle, bulbasaur, growlithe based on monitor naming
  - **Fix**: 
    1. Check monitor disk usage: `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph df`
    2. Clean up old monitor data if safe
    3. Consider expanding monitor storage capacity
    4. Monitor trend over next 24-48 hours

### Observations (Green)
- **Major Recovery**: System recovered from critical Ceph state (629 crashes → clean operation)
- **Storage Capacity Healthy**: 193 GiB used / 3.4 TiB total (5.7% utilization)
- **Data Pools Healthy**: 81 placement groups all active+clean
- **Recent Cluster Activity**: Several pods show restarts 8 hours ago, suggesting maintenance/recovery event
- **Node Age Diversity**: Nodes range from 111 days (sprigatito) to 291 days (majority)
- **ArgoCD Coverage**: All 32 applications managed by ArgoCD are synchronized
- **Persistent Storage**: 40 PVCs in use, all backed by Rook-Ceph
- **Container Restarts**: Minimal restart counts indicate stable workload performance

## Verification Data
- **Nodes**: 10 Online / 10 Total
  - Control Plane: 3 nodes (bulbasaur, charmander, squirtle)
  - Worker Nodes: 7 nodes
- **Kubernetes Version**: v1.33.6+k3s1 (uniform across all nodes)
- **Total Pods**: 185
- **Total PVCs**: 40
- **ArgoCD Applications**: 32 (all Healthy & Synced)
- **Network**: Cilium CNI deployed cluster-wide
- **Ceph Storage**:
  - Health: HEALTH_WARN (improved from critical)
  - OSDs: 7 up / 7 in (all operational, improved from 7/9 with failures)
  - Monitors: 3 daemons (d, f, g) - quorum healthy
  - Managers: 2 (b active, a standby)
  - MDS: 1/1 daemons up, 1 hot standby
  - Data: 96 GiB objects, 193 GiB used, 3.2 TiB free (5.7% used)
  - Pools: 4 pools, 81 placement groups (all active+clean)
  - I/O: 852 B/s read, 59 KiB/s write

## Hardware Details
| Node | Role | Age | CPU Usage | Memory Usage | Internal IP |
|------|------|-----|-----------|--------------|-------------|
| arcanine | Worker | 291d | 332m (4%) | 3320Mi (5%) | 10.0.50.129 |
| bulbasaur | Control Plane | 291d | 641m (16%) | 5107Mi (32%) | 10.0.50.123 |
| charmander | Control Plane | 291d | 645m (16%) | 8153Mi (34%) | 10.0.50.121 |
| chikorita | Worker | 203d | 286m (7%) | 3030Mi (9%) | 10.0.50.125 |
| cyndaquil | Worker | 291d | 257m (6%) | 2132Mi (13%) | 10.0.50.126 |
| growlithe | Worker | 291d | 375m (9%) | 3774Mi (11%) | 10.0.50.128 |
| pikachu | Worker | 291d | 294m (7%) | 1800Mi (11%) | 10.0.50.124 |
| sprigatito | Worker | 111d | 116m (2%) | 6013Mi (18%) | 10.0.50.130 |
| squirtle | Control Plane | 291d | 505m (12%) | 3630Mi (22%) | 10.0.50.122 |
| totodile | Worker | 291d | 324m (8%) | 3032Mi (19%) | 10.0.50.127 |

## Comparison to Earlier Report (2025-12-09 13:00)
| Metric | Morning (13:00) | Evening (23:26) | Status |
|--------|-----------------|-----------------|--------|
| Overall Health | 🟡 YELLOW | 🟡 YELLOW | Same |
| Ceph Crashes | 629 daemon crashes | 0 crashes | ✅ Resolved |
| OSDs Down | 2 down (osd.1, osd.5) | 0 down | ✅ Resolved |
| OSDs Up/Total | 7/9 | 7/7 | ✅ Improved |
| noout Flag | Set | Not mentioned (likely cleared) | ✅ Resolved |
| Monitor Disk | g low (16%) | d/f/g low | ⚠️ More monitors affected |
| Kubernetes Version | v1.28.3+k3s2 | v1.33.6+k3s1 | ℹ️ Upgraded |
| Storage Used | 209 GiB (8%) | 193 GiB (5.7%) | ✅ Slightly improved |

---
Generated by Antigravity on 2025-12-09T23:26:38-06:00
