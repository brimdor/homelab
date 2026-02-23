# [Maintenance] 2026-02-13 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🟡 YELLOW |
| **Last Updated** | 2026-02-13 09:10  |
| **Source Report** | reports/status-report-2026-02-13.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 40 total |
| Ceph Status | HEALTH_WARN |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 Ready |
| Node Versions | 🟢 | All nodes v1.33.6+k3s1 |
| CNI (Cilium) | 🟢 | Cilium 10/10 desired, 10/10 ready |
| Kured | 🟢 | Running, ArgoCD Synced+Healthy |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | 1/1 Running |
| Metrics Server | 🟢 | 1/1 Running |
| kube-vip | 🟢 | 3/3 Running on control-plane nodes |
| ArgoCD | 🟢 | 40/40 apps Synced+Healthy |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟡 | HEALTH_WARN - 1 mgr module (prometheus) recently crashed on mgr.a |
| OSDs | 🟢 | 7/7 up, 7/7 in |
| Usage | 🟢 | 36.25% raw (1.2 TiB / 3.4 TiB) |
| Pools | 🟢 | 4 pools, 177 PGs active+clean |
| Monitors | 🟢 | 3 mons quorum f,h,j |
| MDS | 🟢 | 1/1 up, 1 hot standby |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | 1/1 Running, LB at 10.0.20.226 |
| Certificates | 🟢 | 27/27 Ready=True, 0 pending challenges |
| External Secrets | 🟢 | 7/7 SecretSynced, ClusterSecretStore Valid+Ready |
| Cert-Manager | 🟢 | All orders valid, no pending challenges |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟢 | No CrashLoopBackOff/Error/Pending pods |
| Gitea | 🟢 | Running, API authenticated |
| Grafana | 🟢 | 3/3 containers Running |
| Kanidm | 🟢 | Running, ArgoCD Synced+Healthy |

### Observations

#### 🔍 Node Activity
Growlithe kubelet restarting every ~7s with InvalidDiskCapacity warning ('invalid capacity 0 on image filesystem'). Node is Ready and workloads are healthy. Likely a transient disk reporting issue after recent reboot (~7h ago).

#### 🔍 Renovate PRs
PR #63 open: 'chore(deps): update all non-major dependencies' - updates argo-cd 9.4.1->9.4.2, kube-prometheus-stack 81.6.3->81.6.7, mariadb 12.1->12.2, postgres 18.1->18.2-bookworm, renovate 46.10.1->46.11.1, supabase/logflare 1.31.0->1.31.2, supabase/postgres 17.6.1.083->17.6.1.084, supabase/realtime v2.76.4->v2.76.5. Mergeable.

#### Network Evidence
- **Workstation → Cluster**: Connected (kubectl at 10.0.20.50:6443)
- **Gitea API**: Authenticated as gitea_admin
- **NAS (10.0.40.3)**: ALL GREEN - SMB/NFS/HTTP accessible at 10.0.40.3
- **Gateway (10.0.20.1)**: Pingable - all VLANs reachable, 0% packet loss

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| R1 | FIX | Storage | P1 | None | None | Archive Ceph mgr crash to clear HEALTH_WARN | None |
| R2 | INVESTIGATE | Metal | P2 | None | None | Investigate growlithe InvalidDiskCapacity event spam | None |
| R3 | UPDATE | Apps | P2 | Low | Rolling | Review and merge PR #63 (non-major dep updates) | R1 |

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

### High (P1)

- [ ] **A1 P1 Storage**: Archive Ceph mgr crash to clear HEALTH_WARN
  - **Goal**: Clear HEALTH_WARN by archiving the prometheus mgr module crash (known Ceph v20.2.0 bug)
  - **Commands**: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash archive-all && kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health`
  - **Expected**: HEALTH_OK
  - **If fails**: Check crash details with 'ceph crash ls' and 'ceph crash info <id>'. If crash recurs, investigate prometheus mgr module config.
  - **Rollback**: No rollback needed - archiving crashes is safe and non-destructive

### Medium (P2)

- [ ] **A2 P2 Metal**: Investigate growlithe InvalidDiskCapacity event spam
  - **Goal**: Determine root cause of kubelet restart loop and InvalidDiskCapacity warning on growlithe
  - **Commands**: `ssh brimdor@10.0.20.18 'journalctl -u k3s --since "1 hour ago" --no-pager | tail -50' && kubectl describe node growlithe | grep -A5 Conditions`
  - **Expected**: Identify root cause - likely transient disk reporting issue after reboot. If kubelet is stable and node is Ready, may be cosmetic.
  - **If fails**: Check disk health: ssh brimdor@10.0.20.18 'df -h && lsblk && dmesg | tail -20'. Consider draining node and restarting k3s service.
  - **Rollback**: No changes made - investigation only

- [ ] **A3 P2 Apps**: Review and merge PR #63 (non-major dependency updates)
  - **Goal**: Apply Renovate non-major updates: argo-cd, kube-prometheus-stack, mariadb, postgres, renovate, supabase components
  - **Commands**: `Review PR #63 diff at https://git.eaglepass.io/ops/homelab/pulls/63, then merge via Gitea UI or API`
  - **Expected**: PR merges cleanly, ArgoCD auto-syncs, all apps return to Synced+Healthy
  - **If fails**: If ArgoCD apps degrade after merge, identify failing app and revert the specific chart version bump in a new commit
  - **Rollback**: git revert <merge-commit> && git push

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-02-13 09:02 | Recon | Full recon | Executed homelab-recon workflow (Phases 1-5) | 3 action items identified | 🟡 |
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

