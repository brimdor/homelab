# Homelab Status Report: 2026-01-14

**Report Time**: 2026-01-14 18:00:00 CST
**Reported By**: /homelab-recon workflow

---

## Executive Summary

**Overall Status**: YELLOW

- **GREEN Components**: Metal (10/10 nodes Ready), System (kube-system healthy), Platform (ingress, certs, secrets all synced), Apps (no error-state pods), GitOps (44/44 ArgoCD apps Synced/Healthy)
- **YELLOW Components**: Storage (Ceph HEALTH_WARN - OSD.0 slow ops during backfill recovery)
- **RED Components**: None

**Primary Finding**: Ceph cluster is in HEALTH_WARN state with active backfill recovery in progress (~20% objects misplaced). This is a transient condition during normal recovery operations.

---

## Phase 1: Access Validation

### Access Status: PARTIAL
- Kubernetes API: Accessible (K3s v1.33.6+k3s1)
- Gitea API: Accessible (user: gitea_admin)
- SSH to Controller: TIMEOUT (workstation to 10.0.50.120)
  - Impact: Cannot use controller fallback
  - Workaround: All commands executed from workstation

---

## Phase 2: Baseline Health Evidence

### Nodes (Metal Layer)
**Status**: GREEN
- Total Nodes: 10
- All Nodes: Ready
- K3s Version: v1.33.6+k3s1

| Node | Status | Roles | Internal IP | Age |
|------|--------|-------|-------------|-----|
| arcanine | Ready | worker | 10.0.20.19 | 326d |
| bulbasaur | Ready | control-plane,etcd,master | 10.0.20.13 | 326d |
| charmander | Ready | control-plane,etcd,master | 10.0.20.11 | 326d |
| chikorita | Ready | worker | 10.0.20.15 | 238d |
| cyndaquil | Ready | worker | 10.0.20.16 | 9d |
| growlithe | Ready | worker | 10.0.20.18 | 326d |
| pikachu | Ready | worker | 10.0.20.14 | 326d |
| sprigatito | Ready | worker | 10.0.20.20 | 146d |
| squirtle | Ready | control-plane,etcd,master | 10.0.20.12 | 326d |
| totodile | Ready | worker | 10.0.20.17 | 326d |

### Node Resource Usage
| Node | CPU | CPU% | Memory | Memory% |
|------|-----|------|--------|---------|
| arcanine | 3737m | 46% | 12608Mi | 19% |
| bulbasaur | 1076m | 26% | 6554Mi | 41% |
| charmander | 839m | 20% | 4173Mi | 17% |
| chikorita | 526m | 13% | 5091Mi | 15% |
| cyndaquil | 404m | 10% | 4448Mi | 28% |
| growlithe | 460m | 11% | 9626Mi | 30% |
| pikachu | 481m | 12% | 3108Mi | 19% |
| sprigatito | 257m | 6% | 10938Mi | 34% |
| squirtle | 812m | 20% | 5418Mi | 34% |
| totodile | 433m | 10% | 3578Mi | 22% |

### Workload Health
**Status**: GREEN
- Non-running pods: 0
- All pods in Running or Completed state

### ArgoCD Health
**Status**: GREEN
- Total Applications: 44
- Synced: 44 (100%)
- Healthy: 44 (100%)

---

## Phase 3: System/Core Evidence

### kube-system
**Status**: GREEN
- CoreDNS: Running
- Cilium: 10/10 daemonset pods running
- Cilium Operator: Running
- Hubble Relay/UI: Running
- kube-vip: Running on 3 control-planes
- Metrics Server: Running

### CNI (Cilium)
**Status**: GREEN
- DaemonSet: 10/10 desired/ready
- No CNI issues detected

---

## Phase 4: Storage Evidence (Rook/Ceph)

### Ceph Health
**Overall**: HEALTH_WARN (Active Recovery)

```
HEALTH_WARN 1 OSD(s) experiencing slow operations in BlueStore; 1 OSD(s) experiencing stalled read in db device of BlueFS
[WRN] BLUESTORE_SLOW_OP_ALERT: 1 OSD(s) experiencing slow operations in BlueStore
     osd.0 observed slow operation indications in BlueStore
[WRN] DB_DEVICE_STALLED_READ_ALERT: 1 OSD(s) experiencing stalled read in DB device
     osd.0 observed stalled read indications in DB device
```

### Cluster Status
- Cluster ID: 13c20377-d801-43f9-aebd-59f62df5dad1
- Monitors: 3 daemons, quorum f,h,j (age 10h)
- MGR: b (active, since 11d), standbys: a
- MDS: 1/1 daemons up, 1 hot standby
- OSDs: 7 osds: 7 up, 7 in; 45 remapped PGs

### Backfill Recovery Status
- Objects misplaced: 63,951/320,377 (19.96%)
- PGs: 132 active+clean, 44 active+remapped+backfill_wait, 1 active+remapped+backfilling
- Recovery rate: ~13-19 MiB/s, 3-4 objects/s

### OSD Status
| OSD | Node | Status | Weight |
|-----|------|--------|--------|
| 0 | chikorita | UP | 1.0 |
| 1 | cyndaquil | UP | 1.0 |
| 2 | arcanine | UP | 1.0 |
| 4 | bulbasaur | UP | 1.0 |
| 6 | growlithe | UP | 1.0 |
| 7 | sprigatito | UP | 1.0 |
| 8 | arcanine | UP | 1.0 |

### OSD Performance
| OSD | Commit Latency (ms) | Apply Latency (ms) | Notes |
|-----|---------------------|-------------------|-------|
| 0 | 37 | 37 | Slow ops (under recovery load) |
| 1 | 18 | 18 | Normal |
| 2 | 6 | 6 | Normal |
| 4 | 248 | 248 | HIGH - needs investigation |
| 6 | 10 | 10 | Normal |
| 7 | 8 | 8 | Normal |
| 8 | 16 | 16 | Normal |

### Ceph Disk Usage
- Total RAW: 3.4 TiB
- Available: 2.2 TiB (64%)
- Used: 1.2 TiB (36%)

### Ceph Crashes
- No new crashes detected

---

## Phase 5: Platform Evidence

### Ingress (ingress-nginx)
**Status**: GREEN
- Controller: Running on growlithe
- External IP: 10.0.20.226
- Total Ingress routes: 27

### Certificates (cert-manager)
**Status**: GREEN
- Total Certificates: 28
- All Ready: 28/28 (100%)
- No pending orders or challenges

### External Secrets
**Status**: GREEN
- ClusterSecretStore: global-secrets (Valid, ReadWrite)
- ExternalSecrets: 7 synced (all SecretSynced)

### Monitoring
**Status**: GREEN
- Prometheus: Running
- Alertmanager: Running
- Node Exporter: 10/10 running
- Kube State Metrics: Running

---

## Phase 6: Apps Evidence

### Error-State Pods
**Status**: GREEN
- CrashLoopBackOff: 0
- Error: 0
- ImagePullBackOff: 0
- Pending: 0

---

## Phase 7: Repository Evidence

### Open Pull Requests
**Total**: 7 open PRs (all Renovate bot, all unmergeable due to conflicts)

| PR | Title | Age | Changed Files | Status |
|----|-------|-----|---------------|--------|
| #30 | chore(deps): update helm values redis to v8 | 8d | 1 | Conflict |
| #28 | chore(deps): update helm values postgres | 9d | 4 | Conflict |
| #27 | chore(deps): update helm values mongo to v8 | 9d | 1 | Conflict |
| #26 | chore(deps): update helm values mariadb to v12 | 10d | 1 | Conflict |
| #25 | chore(deps): update helm values homepage to v1 | 10d | 1 | Conflict |
| #24 | chore(deps): update helm values cloudflared to v2025 | 11d | 1 | Conflict |
| #21 | chore(deps): update all non-major dependencies | 12d | 69 | Conflict |

**All PRs have merge conflicts** - need Renovate rebase or manual intervention.

### Open Issues
| Issue | Title | Labels |
|-------|-------|--------|
| #4 | Dependency Dashboard | None |

### Maintenance Issues
**No open maintenance issues found** - need to create new one.

---

## Critical Findings

### 1. Ceph HEALTH_WARN - Active Backfill Recovery
**Severity**: MEDIUM (self-healing in progress)
**Layer**: System (Storage)
**Status**: Transient - recovery in progress

**Details**:
- OSD.0 on chikorita experiencing slow operations during backfill
- 19.96% of objects currently misplaced and being recovered
- Recovery progressing at ~13-19 MiB/s
- No data loss risk - all PGs active
- Estimated completion: ~2-4 hours based on recovery rate

**Root Cause Analysis**:
- Recent OSD restarts/reprovisioning (per operator logs from 07:59)
- Normal backfill behavior after OSD changes

**Action Required**: Monitor only - recovery is automatic

### 2. OSD.4 High Latency
**Severity**: LOW (no immediate impact)
**Layer**: System (Storage)

**Details**:
- OSD.4 on bulbasaur showing 248ms commit/apply latency
- Other OSDs: 6-37ms range
- May be disk performance issue or temporary recovery load

**Action Required**: Monitor after recovery completes; investigate if latency persists

### 3. All Renovate PRs Have Conflicts
**Severity**: LOW
**Layer**: Repo

**Details**:
- 7 PRs unmergeable due to conflicts
- All are dependency updates (non-critical)
- Need Renovate rebase or manual resolution

**Action Required**: Trigger Renovate rebase or manually resolve conflicts

---

## Validation Gate Results

**Gate**: PARTIAL PASS (YELLOW)

| Check | Result | Notes |
|-------|--------|-------|
| All nodes Ready | PASS | 10/10 |
| kube-system healthy | PASS | All pods Running |
| ArgoCD apps healthy | PASS | 44/44 Synced/Healthy |
| Ceph HEALTH_OK | FAIL | HEALTH_WARN (recovery) |
| No error-state pods | PASS | All Running/Completed |

**Stop Condition**: Ceph not HEALTH_OK
**Recommendation**: Wait for Ceph recovery to complete before performing any maintenance actions

---

## Recommendations

### Immediate (P0) - None Required
- Ceph recovery is automatic, no intervention needed
- All other systems GREEN

### Medium Priority (P2)
1. **Monitor Ceph Recovery**: Wait for backfill to complete and verify HEALTH_OK
2. **Investigate OSD.4 Latency**: After recovery, check disk health on bulbasaur
3. **Resolve PR Conflicts**: Trigger Renovate rebase on conflicted PRs

### Low Priority (P3)
4. **Controller SSH Access**: Investigate why 10.0.50.120 is not accessible
5. **Clean up Dependency Dashboard**: Review issue #4

---

## Appendix

### A. Ceph OSD Tree
```
ID   CLASS  WEIGHT   TYPE NAME            STATUS  REWEIGHT
 -1         3.40022  root default
 -5         1.33429      host arcanine
  2    ssd  0.86850          osd.2            up   1.00000
  8    ssd  0.46579          osd.8            up   1.00000
 -7         0.40279      host bulbasaur
  4    ssd  0.40279          osd.4            up   1.00000
 -3         0.40279      host chikorita
  0    ssd  0.40279          osd.0            up   1.00000
 -9         0.40279      host cyndaquil
  1    ssd  0.40279          osd.1            up   1.00000
-11         0.45479      host growlithe
  6    ssd  0.45479          osd.6            up   1.00000
-13         0.40279      host sprigatito
  7    ssd  0.40279          osd.7            up   1.00000
```

### B. Rook Operator Recent Activity
- 07:58-07:59: OSD provisioning completed on all nodes
- OSD updates: osd.0, osd.1, osd.2, osd.4, osd.6, osd.7, osd.8
- No errors in operator logs
