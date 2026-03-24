# Homelab Recon Status Report (2026-03-23)

Generated: 2026-03-23T17:10:00Z
Context Pack: reports/context-pack-2026-03-23

## Executive Summary

**Overall Status: RED**

### Key Findings

| Layer | Status | Critical Issues |
|-------|--------|-----------------|
| Metal | 🟢 GREEN | All 10 nodes Ready |
| Network | 🟢 GREEN | All VLANs reachable, NAS accessible |
| Storage | 🔴 RED | Ceph HEALTH_ERR (prometheus mgr crash + 2 OSDs DOWN) |
| System | 🟡 YELLOW | rook-ceph ArgoCD app Degraded |
| Platform | 🟢 GREEN | All certificates, ingress, secrets healthy |
| Apps | 🟢 GREEN | All pods Running/Completed |

### Immediate Actions Required

1. **P0**: Investigate Ceph prometheus mgr module crash (TypeError in string formatting)
2. **P0**: Recover 2 DOWN OSDs (osd.0 on chikorita, osd.4 on bulbasaur)
3. **P0**: Archive Ceph crash report after fix
4. **P1**: Merge PR #72 (non-major dependencies - mergeable)

## Evidence References

### Context Pack Contents
- `reports/context-pack-2026-03-23/recon.json` - Comprehensive cluster health
- `reports/context-pack-2026-03-23/network.json` - Network health check (GREEN, exit 0)
- `reports/context-pack-2026-03-23/nas.json` - NAS health check (GREEN, exit 0)
- `reports/context-pack-2026-03-23/events.txt` - Recent cluster events
- `reports/context-pack-2026-03-23/dependency-dashboard.md` - Dependency Dashboard issue #4
- `reports/context-pack-2026-03-23/dependency-dashboard-unchecked.txt` - Unchecked dashboard items

### Cluster Identity
- **K3s Version**: v1.33.6+k3s1
- **Nodes**: 10 total (3 control-plane, 7 workers)
- **ArgoCD Apps**: 42 total (41 synced, 1 degraded)
- **Ceph Status**: HEALTH_ERR

### Ceph Details
```
cluster:
  id:     13c20377-d801-43f9-aebd-59f62df5dad1
  health: HEALTH_ERR
    Module 'prometheus' has failed: not all arguments converted during string formatting
    1 mgr modules have recently crashed

services:
  mon: 3 daemons, quorum h,j,k (age 15h)
  mgr: a(active, since 15h), standbys: b
  mds: 1/1 daemons up, 1 hot standby
  osd: 7 osds: 5 up (since 15h), 5 in (since 4d)

data:
  volumes: 1/1 healthy
  pools:   4 pools, 177 pgs
  objects: 174.97k objects, 678 GiB
  usage:   1.3 TiB used, 1.3 TiB / 2.6 TiB avail
  pgs:     177 active+clean
```

### OSD Tree (2 DOWN)
```
ID   CLASS  WEIGHT   TYPE NAME            STATUS  REWEIGHT
 -1         3.40022  root default
 -5         1.33429      host arcanine
  2    ssd  0.86850          osd.2            up   1.00000
  8    ssd  0.46579          osd.8            up   1.00000
 -7         0.40279      host bulbasaur
  4    ssd  0.40279          osd.4          down         0
 -3         0.40279      host chikorita
  0    ssd  0.40279          osd.0          down         0
 -9         0.40279      host cyndaquil
  1    ssd  0.40279          osd.1            up   1.00000
-11         0.45479      host growlithe
  6    ssd  0.45479          osd.6            up   1.00000
-13         0.40279      host sprigatito
  7    ssd  0.40279          osd.7            up   1.00000
```

### Ceph Crash Report
```
crash_id: 2026-03-23T07:47:15.516238Z_d8275c2c-ca6a-489c-8822-3aa41b2cc4f1
entity_name: mgr.a
mgr_module: prometheus
mgr_module_caller: PyModuleRunner::serve
mgr_python_exception: TypeError
timestamp: 2026-03-23T07:47:15.516238Z

backtrace:
  File "/usr/share/ceph/mgr/prometheus/module.py", line 1889, in configure
    security_config = json.loads(out)
  ...
  json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

During handling of the above exception, another exception occurred:
  File "/usr/share/ceph/mgr/prometheus/module.py", line 1894, in configure
    self.log.exception(f'Failed to setup cephadm based secure monitoring stack: {e}\n',
  ...
  TypeError: not all arguments converted during string formatting
```

### Open Renovate PRs
| PR | Title | Mergeable | Risk |
|----|-------|-----------|------|
| #72 | fix(deps): update all non-major dependencies | ✅ Yes | Medium |
| #73 | chore(deps): update bitnamilegacy/postgresql to v17 | ❌ No | High (major) |
| #74 | chore(deps): update helm release nextcloud to v9 | ❌ No | High (major) |

### Maintenance Issue
**Issue #75**: https://git.eaglepass.io/ops/homelab/issues/75
- **Status**: Updated with 2026-03-23 evidence
- **Overall**: RED
- **Created**: 2026-03-09
- **Updated**: 2026-03-23

## Validation Gate Status

### Network Check (GREEN)
```
~/.config/opencode/scripts/homelab-network-check.sh --json
Exit: 0 (GREEN)
```

### NAS Check (GREEN)
```
~/.config/opencode/scripts/homelab-nas-check.sh --json
Exit: 0 (GREEN)
```

### ArgoCD Health (YELLOW)
```
rook-ceph: Synced, Degraded
All others: Synced, Healthy
```

### Ceph Health (RED)
```
HEALTH_ERR: Module 'prometheus' has failed; 1 mgr modules have recently crashed
```

## Completion Criteria for GREEN Status

1. ✅ Ceph prometheus module issue resolved
2. ✅ 2 DOWN OSDs recovered
3. ✅ Ceph crash report archived
4. ✅ PR #72 merged
5. ✅ Ceph HEALTH_OK achieved
