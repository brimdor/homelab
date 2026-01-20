# Homelab Status Report - 2026-01-16

## Summary
- **Overall Status**: 🟡 YELLOW
- **Generated**: 2026-01-16 08:35 CST
- **K3s Version**: v1.33.6+k3s1

## Layer Status

| Layer | Status | Notes |
|-------|:------:|-------|
| Metal | 🟡 YELLOW | Node `pikachu` is cordoned (SchedulingDisabled) with containerd issues |
| System | 🟢 GREEN | Ceph HEALTH_OK, kube-system healthy |
| Platform | 🟡 YELLOW | ArgoCD `kured` app Progressing (1/44) |
| Apps | 🟡 YELLOW | 2 pods in error state on `pikachu` |

---

## Metal Layer

### Nodes (10 total)
| Node | Status | Roles | CPU% | Memory% |
|------|:------:|-------|:----:|:-------:|
| arcanine | Ready | worker | 46% | 19% |
| bulbasaur | Ready | control-plane | 16% | 40% |
| charmander | Ready | control-plane | 34% | 37% |
| chikorita | Ready | worker | 14% | 21% |
| cyndaquil | Ready | worker | 11% | 26% |
| growlithe | Ready | worker | 12% | 32% |
| **pikachu** | **Ready,SchedulingDisabled** | worker | 5% | 10% |
| sprigatito | Ready | worker | 9% | 28% |
| squirtle | Ready | control-plane | 32% | 27% |
| totodile | Ready | worker | 12% | 42% |

### Issue: Node pikachu
- **Status**: Cordoned (SchedulingDisabled)
- **Problem**: `containerd-stargz-grpc.sock` connection refused
- **Impact**: Pods on this node cannot pull/inspect images
- **Affected pods**:
  - `kured/kured-rb9v6`: Status Unknown, ImagePullBackOff
  - `rook-ceph/rook-ceph.rbd.csi.ceph.com-nodeplugin-vpmlb`: Status ImageInspectError

---

## System Layer

### Ceph Storage
- **Health**: HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)
- **OSDs**: 7/7 up and in
- **Usage**: 1.2 TiB / 3.4 TiB (35%)
- **PGs**: 177 active+clean

### kube-system
- All pods Running ✓

---

## Platform Layer

### ArgoCD Applications (44 total)
| Status | Count |
|--------|:-----:|
| Synced + Healthy | 43 |
| Synced + Progressing | 1 (`kured`) |

### Issue: kured App Progressing
- **Cause**: DaemonSet pod on `pikachu` is failing
- **Pod**: `kured-rb9v6` stuck in ImagePullBackOff

### Ingress
- 27 ingresses configured, all healthy

### Certificates
- All certificates Ready ✓

### External Secrets
- All external secrets synced ✓

---

## Apps Layer

### Non-Running Pods
| Namespace | Pod | Status | Node | Issue |
|-----------|-----|:------:|------|-------|
| kured | kured-rb9v6 | Unknown | pikachu | containerd-stargz socket refused |
| rook-ceph | rook-ceph.rbd.csi.ceph.com-nodeplugin-vpmlb | ImageInspectError | pikachu | containerd-stargz socket refused |

---

## Repository Status

### Pull Requests
- Open PRs: 0

### Issues
| # | Title | Labels | Status |
|---|-------|--------|:------:|
| 44 | [Maintenance] 2026-01-15 - Homelab | maintenance | open |
| 4 | Dependency Dashboard | - | open |

---

## Recommendations

### P0 - Critical
1. **Investigate node `pikachu`**: The containerd-stargz-grpc service is down
   - Check containerd and stargz-snapshotter status
   - Review if node should be drained and removed, or repaired

### P1 - High
2. **Resolve failed pods on pikachu**:
   - Either repair the node or drain/delete it to allow DaemonSet pods to reschedule
   - `kured` and `rook-ceph-nodeplugin` pods need to be healthy

### P3 - Low
3. **Monitor Ceph muted alert**: DB_DEVICE_STALLED_READ_ALERT is muted but should be reviewed
