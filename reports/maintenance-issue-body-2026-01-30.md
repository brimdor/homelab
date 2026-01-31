# [Maintenance] 2026-01-30 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | GREEN |
| **Last Updated** | 2026-01-30 19:15 CST |
| **Source Report** | reports/status-report-2026-01-30.md |
| **Assigned To** | gitea_admin |

---

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Client Version | v1.35.0 |
| Node Count | 10 (3 masters, 7 workers) |
| ArgoCD Apps | 40 total |
| Ceph Status | HEALTH_OK (7 OSDs, 3.4 TiB total) |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | GREEN | 10/10 Ready |
| Node Versions | GREEN | All v1.33.6+k3s1 |
| CNI (Cilium) | GREEN | 10/10 pods Running |
| Kured | GREEN | 10/10 pods Running |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | GREEN | 1/1 Running |
| Metrics Server | GREEN | 1/1 Running |
| kube-vip | GREEN | 3/3 Running (HA masters) |
| ArgoCD | GREEN | 7/7 pods Running, 40 apps Synced+Healthy |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | GREEN | HEALTH_OK |
| OSDs | GREEN | 7/7 up, 7/7 in |
| Usage | GREEN | 35.10% (1.2 TiB used / 3.4 TiB total) |
| Pools | GREEN | 4 pools, 177 pgs active+clean |
| Monitors | GREEN | 3 daemons, quorum f,h,j |
| MDS | GREEN | 1/1 up, 1 hot standby |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | GREEN | 1/1 Running |
| Certificates | GREEN | 25/25 Ready=True |
| External Secrets | GREEN | 7/7 SecretSynced |
| Cert-Manager | GREEN | 3/3 Running |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | GREEN | All Running or Completed |
| Gitea | GREEN | 6 pods Running |
| Grafana | GREEN | 3/3 Running |
| Kanidm | GREEN | 1/1 Running |

### Observations

#### Node Activity
- **growlithe** (10.0.20.18): Showing frequent kubelet start events and InvalidDiskCapacity warnings
  - **Analysis**: InvalidDiskCapacity is a metrics collection issue (image filesystem capacity=0)
  - **Status**: Node Ready=True, all conditions healthy (no DiskPressure)
  - **Conclusion**: Informational warning, monitor but no immediate action required

#### Renovate PRs
- **PR #54**: chore(deps): update all non-major dependencies (renovate/all-minor-patch → master)
  - grafana: 10.5.14 → 10.5.15
  - kube-prometheus-stack: 81.3.0 → 81.3.2
  - ollama: 1.39.0 → 1.40.0
  - supabase deps: various patch/minor updates
- **PR #55**: chore(deps): update helm release renovate to v46 (renovate/renovate-46.x → master)
  - renovate: 45.88.1 → 46.0.3 (MAJOR update)

#### Open Issues
- **Issue #4**: Dependency Dashboard (Renovate tracking issue - permanent)

### Network Evidence
- **Workstation → Cluster**: Connected (kubectl functional)
- **Gitea API**: Accessible (read access, token needed for writes)
- **NAS (10.0.40.3)**: SMB/NFS ports open, web accessible
- **Gateways**: ICMP blocked (expected firewall behavior)

---

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| R1 | UPDATE | Apps | P2 | Low | None | Merge PR #54: Non-major dependency updates | PR review |
| R2 | UPDATE | Platform | P2 | Medium | Possible restart | Merge PR #55: Renovate to v46 (major) | PR review, R1 |
| M1 | MONITOR | Metal | P3 | None | None | Monitor growlithe InvalidDiskCapacity warning | None |

---

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
- Ceph health not HEALTH_OK

---

## Action Items (Tasks)

- [ ] **A1 P2**: Review and merge PR #54 - Non-major dependency updates
  - **Goal**: Apply minor/patch dependency updates (grafana, kube-prometheus-stack, ollama, supabase)
  - **Commands**: 
    ```bash
    # Via Gitea UI: https://git.eaglepass.io/ops/homelab/pulls/54
    # Or via API with token:
    curl -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do":"merge"}'
    ```
  - **Expected**: ArgoCD syncs successfully, affected apps remain Healthy
  - **If fails**: Check ArgoCD sync errors, rollback via Git revert
  - **Rollback**: `git revert <commit>` + ArgoCD sync

- [ ] **A2 P2**: Review and merge PR #55 - Renovate to v46
  - **Goal**: Update Renovate bot to v46 (major version)
  - **Commands**: 
    ```bash
    # Via Gitea UI: https://git.eaglepass.io/ops/homelab/pulls/55
    # Or via API with token:
    curl -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/55/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do":"merge"}'
    ```
  - **Expected**: ArgoCD syncs successfully, Renovate pod restarts with v46
  - **If fails**: Check Renovate pod logs, rollback via Git revert
  - **Rollback**: `git revert <commit>` + ArgoCD sync

- [ ] **A3 P3**: Monitor growlithe InvalidDiskCapacity warning
  - **Goal**: Verify warning resolves or escalate if persistent
  - **Commands**: 
    ```bash
    kubectl describe node growlithe | grep -A5 Conditions
    kubectl get events -A --field-selector involvedObject.name=growlithe | grep InvalidDiskCapacity
    ```
  - **Expected**: No recurring InvalidDiskCapacity events, node remains Ready
  - **If fails**: SSH to growlithe, check disk usage with `df -h`, check containerd storage
  - **Rollback**: N/A (monitoring task)

---

## Change Log

| Timestamp | Action | User | Result |
|-----------|--------|------|--------|
| 2026-01-30 05:07 | Initial maintenance issue created | opencode | GREEN status confirmed |
| 2026-01-30 12:15 | Recon update executed | opencode | GREEN status confirmed |
| 2026-01-30 13:48 | Recon update executed | opencode | Added InvalidDiskCapacity observation |
| 2026-01-30 19:15 | Evening recon update | opencode | GREEN status confirmed, PRs still pending |

---

## Closure (Filled by homelab-action)

### Completion Criteria:
- [ ] All action items completed or explicitly deferred
- [ ] All validation gates passed
- [ ] No regressions in cluster health
- [ ] Maintenance issue closed

**Final Status**: PENDING

**Closed By**: PENDING
**Closed Date**: PENDING
