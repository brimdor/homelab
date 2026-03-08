# [Maintenance] 2026-03-07 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🟡 YELLOW |
| **Last Updated** | 2026-03-07 17:14  |
| **Source Report** | reports/status-report-2026-03-07.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 42 total |
| Ceph Status | HEALTH_OK |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 nodes Ready |
| Node Versions | 🟡 | kubectl client v1.35.1 vs server v1.33.6+k3s1 (supported skew warning) |
| CNI (Cilium) | 🟢 | Cilium daemonset present and pods running |
| Kured | 🟢 | kured daemonset pods running |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | CoreDNS running from cluster-info and kube-system snapshot |
| Metrics Server | 🟢 | metrics-server running |
| kube-vip | 🟢 | kube-vip pods running on control-plane nodes |
| ArgoCD | 🟢 | All ArgoCD applications Synced and Healthy |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟢 | ceph health = HEALTH_OK |
| OSDs | 🟢 | 7/7 OSDs up/in |
| Usage | 🟢 | ~1.4 TiB used / ~3.4 TiB total |
| Pools | 🟢 | 4 pools, 177 pgs active+clean |
| Monitors | 🟢 | 3 mons in quorum (f,h,j) |
| MDS | 🟢 | 1 active + 1 standby-replay |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | ingress-nginx pods/services healthy |
| Certificates | 🟢 | certificate resources present, no active cert failures in snapshot |
| External Secrets | 🟢 | ExternalSecrets healthy in snapshot |
| Cert-Manager | 🟢 | cert-manager pods healthy |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟢 | No CrashLoopBackOff/Error/ImagePullBackOff/Pending pods |
| Gitea | 🟢 | gitea, postgres, and valkey pods running |
| Grafana | 🟢 | grafana pod running |
| Kanidm | 🟢 | kanidm pod running |

### Observations

#### 🔍 Node Activity
No NotReady nodes; no current resource pressure findings from recon snapshots.

#### 🔍 Renovate PRs
4 open Renovate PRs (#67-#70), all mergeable=true, plus 5 unchecked Dependency Dashboard items (issue #4).

#### Network Evidence
- **Workstation → Cluster**: GREEN (cluster API reachable)
- **Gitea API**: GREEN (API token validated as gitea_admin)
- **NAS (10.0.40.3)**: GREEN (NAS script status GREEN; required ports reachable)
- **Gateway (10.0.20.1)**: GREEN (VLAN gateway checks all passed)

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| CHG-001 | Dependency Review | Platform | P1 | Medium | None expected | Triage PR #67 (non-major dependency bundle) with staged validation and rollback gate | Validation Gate, Dependency Dashboard #4 |
| CHG-002 | Major Dependency | Apps | P1 | High | Possible app restart | Review PR #68 (bitnamilegacy/postgresql v17) with release-note and backup-first checklist | Backup completed, Validation Gate |
| CHG-003 | Major Base Image | System | P1 | Medium | Possible workload restart | Review PR #69 (debian v13) for breaking package/runtime changes | Release notes reviewed, Validation Gate |
| CHG-004 | Major Dependency | Platform | P1 | High | Possible Redis-like service restart | Review PR #70 (valkey v9) with compatibility checks and staged rollout | Backup completed, Validation Gate |
| CHG-005 | Governance | Platform | P2 | Low | None | Reconcile unchecked Dependency Dashboard items after merge/defer decisions | PR decisions complete |

## Execution Plan

### Ordering Rules
1. Process P0 → P1 → P2 → P3
2. Within priority: Metal → System → Platform → Apps
3. One change at a time with validation

### Validation Gate (After Each Change)

```bash
kubectl get nodes | grep -v "Ready" || true
kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true
```

**PASS Criteria**: All greps return empty + ceph health = HEALTH_OK

### Stop Conditions
- Any non-GREEN validation result
- Node NotReady status
- Ceph health ≠ HEALTH_OK

## Action Items (Tasks)

### Preflight

- [ ] **A1 P0 Metal**: Preflight cluster and repo token validation
  - **Goal**: Guarantee safe execution context before any maintenance change
  - **Commands**: `kubectl cluster-info && kubectl get nodes && set -a && source ~/.config/gitea/.env && set +a && curl -sf https://git.eaglepass.io/api/v1/user -H "Authorization: token $GITEA_TOKEN" | jq -r .login`
  - **Expected**: Cluster reachable, all nodes Ready, Gitea API auth returns gitea_admin
  - **If fails**: Stop execution, restore access/auth first, and re-run recon
  - **Rollback**: N/A

### High (P1)

- [ ] **C3 P1 System**: [Renovate] Review PR #69 (debian major v13) for runtime compatibility
  - **Goal**: Prevent base-image compatibility regressions
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/69" -H "Authorization: token $GITEA_TOKEN" | jq '{number,title,mergeable,head:{ref:.head.ref}}' && echo 'Validate glibc/runtime impact from Debian 12 -> 13'`
  - **Expected**: Compatibility checklist complete with clear merge/defer decision
  - **If fails**: Pin current image and open follow-up compatibility issue
  - **Rollback**: Revert merge commit to restore Debian 12 image

- [ ] **C1 P1 Platform**: [Renovate] Decide merge/defer for PR #67 (non-major bundle)
  - **Goal**: Resolve broad non-major update batch with explicit merge or defer decision
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/67" -H "Authorization: token $GITEA_TOKEN" | jq '{number,title,mergeable,head:{ref:.head.ref},base:{ref:.base.ref}}' && kubectl get applications -n argocd`
  - **Expected**: Decision recorded in issue and validation gate defined before merge
  - **If fails**: Split into smaller dependency groups and defer risky components
  - **Rollback**: git revert <merge_commit_sha> followed by full validation gate

- [ ] **C4 P1 Platform**: [Renovate] Review PR #70 (valkey major v9) with staged rollout
  - **Goal**: Upgrade Valkey safely with compatibility and data protection gates
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/70" -H "Authorization: token $GITEA_TOKEN" | jq '{number,title,mergeable,head:{ref:.head.ref}}' && echo 'Take backup/snapshot and stage rollout per namespace'`
  - **Expected**: Major-upgrade checklist complete; merge only after backup + validation gate
  - **If fails**: Defer PR and open dedicated migration task with app compatibility matrix
  - **Rollback**: Restore Valkey data from snapshot and revert merge commit

- [ ] **C2 P1 Apps**: [Renovate] Review PR #68 (postgresql major v17) with breaking-change checklist
  - **Goal**: Protect data-plane workloads while evaluating major PostgreSQL container jump
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/68" -H "Authorization: token $GITEA_TOKEN" | jq '{number,title,mergeable,head:{ref:.head.ref}}' && echo 'Review upstream release notes and run backup before merge'`
  - **Expected**: Release notes reviewed, backup procedure confirmed, decision merge/defer documented
  - **If fails**: Defer PR and create dedicated migration plan with canary test namespace
  - **Rollback**: Restore database from pre-change backup and revert merged commit

### Medium (P2)

- [ ] **D1 P2 Platform**: [Renovate] Track Dependency Dashboard item for PR #67
  - **Goal**: Resolve unchecked dashboard entry tied to pulls/67
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' | rg 'pulls/67'`
  - **Expected**: Dashboard entry for pulls/67 is checked or explicitly deferred with rationale
  - **If fails**: Keep maintenance issue open and align dashboard state with PR decision
  - **Rollback**: N/A

- [ ] **D2 P2 Platform**: [Renovate] Track Dependency Dashboard item for PR #68
  - **Goal**: Resolve unchecked dashboard entry tied to pulls/68
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' | rg 'pulls/68'`
  - **Expected**: Dashboard entry for pulls/68 is checked or explicitly deferred with rationale
  - **If fails**: Leave item open and add migration prerequisite tasks before merge
  - **Rollback**: N/A

- [ ] **D3 P2 Platform**: [Renovate] Track Dependency Dashboard item for PR #69
  - **Goal**: Resolve unchecked dashboard entry tied to pulls/69
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' | rg 'pulls/69'`
  - **Expected**: Dashboard entry for pulls/69 is checked or explicitly deferred with rationale
  - **If fails**: Document blockers and keep item open until compatibility is confirmed
  - **Rollback**: N/A

- [ ] **D4 P2 Platform**: [Renovate] Track Dependency Dashboard item for PR #70
  - **Goal**: Resolve unchecked dashboard entry tied to pulls/70
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' | rg 'pulls/70'`
  - **Expected**: Dashboard entry for pulls/70 is checked or explicitly deferred with rationale
  - **If fails**: Do not merge until compatibility and backup gates are complete
  - **Rollback**: N/A

- [ ] **D5 P2 Platform**: [Renovate] Reconcile 'rebase all open PRs' dashboard control
  - **Goal**: Apply rebase-all checkbox only when synchronized rebase is required
  - **Commands**: `curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' | rg 'rebase-all-open-prs'`
  - **Expected**: Rebase-all control handled intentionally and reflected in dashboard state
  - **If fails**: Rebase PRs individually and track outcomes per PR
  - **Rollback**: N/A

### Final Validation

- [ ] **F1 P0 System**: Universal validation gate after each approved change
  - **Goal**: Enforce GREEN status across Metal/Network/Storage/System/Platform/Apps
  - **Commands**: `kubectl get nodes | grep -v Ready || true && kubectl get pods -n kube-system | grep -v "Running\|Completed" || true && kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true && kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health && kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true && ~/.config/opencode/scripts/homelab-network-check.sh --json > reports/context-pack-2026-03-07/network-gate.json && ~/.config/opencode/scripts/homelab-nas-check.sh --json > reports/context-pack-2026-03-07/nas-gate.json`
  - **Expected**: All grep checks empty; ceph health HEALTH_OK; network/nas gate exit code 0
  - **If fails**: Stop immediately, triage failing layer, and rollback latest change
  - **Rollback**: Rollback latest merged PR via git revert and re-sync ArgoCD

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-03-07T22:43:00Z | 1 | Evidence Capture | Collected script-first context pack and cluster snapshots | Context pack complete for Metal/Network/Storage/System/Platform/Apps/Repo | 🟢 |
| 2026-03-07T22:50:00Z | 5 | Maintenance Spec | Prepared ordered action plan for open Renovate PRs and dashboard | Issue body ready for update | 🟡 |
<!-- markdownlint-enable MD055 MD056 -->

## Closure (Filled by homelab-action)

### Completion Criteria:
- [ ] All action items completed or explicitly deferred
- [ ] All validation gates passed
- [ ] No regressions in cluster health
- [ ] Maintenance issue closed

**Final Status**: PENDING

**Closed By**: PENDING
**Closed Date**: PENDING
