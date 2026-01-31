# Maintenance Issue Template

> [!IMPORTANT]
> This template defines the **exact structure** for all maintenance issues.
> The AI Model MUST follow this template precisely when creating or updating maintenance issues.

---

## Issue Title

Format: `[Maintenance] YYYY-MM-DD - Homelab`
When resolved: `[RESOLVED] [Maintenance] YYYY-MM-DD - Homelab`

---

## Issue Body Template

```markdown
# [Maintenance] 2026-01-31 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🔴 RED |
| **Last Updated** | 2026-01-31 12:43  |
| **Source Report** | N/A |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | N/A |
| Node Count | N/A |
| ArgoCD Apps | N/A total |
| Ceph Status | N/A |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | ⚪ |  |
| Node Versions | ⚪ |  |
| CNI (Cilium) | ⚪ |  |
| Kured | ⚪ |  |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | ⚪ |  |
| Metrics Server | ⚪ |  |
| kube-vip | ⚪ |  |
| ArgoCD | ⚪ |  |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | ⚪ |  |
| OSDs | ⚪ |  |
| Usage | ⚪ |  |
| Pools | ⚪ |  |
| Monitors | ⚪ |  |
| MDS | ⚪ |  |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | ⚪ |  |
| Certificates | ⚪ |  |
| External Secrets | ⚪ |  |
| Cert-Manager | ⚪ |  |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | ⚪ |  |
| Gitea | ⚪ |  |
| Grafana | ⚪ |  |
| Kanidm | ⚪ |  |

### Observations

#### 🔍 Node Activity
None

#### 🔍 Renovate PRs
None

#### Network Evidence
- **Workstation → Cluster**: N/A
- **Gitea API**: N/A
- **NAS (10.0.40.3)**: N/A
- **Gateway (10.0.20.1)**: N/A

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| N1 | INVESTIGATE | Network | P2 | Low | None | Verify VLAN gateway ICMP reachability (confirm if blocked by intent) | None |
| S2 | INVESTIGATE | Storage | P2 | Medium | None | Verify NAS NFS exports (media, backups) | None |
| R1 | UPDATE | Apps | P2 | Low | None | Merge PR #54: Non-major dependency updates | None |
| R2 | UPDATE | Platform | P2 | Medium | None | Merge PR #55: Renovate to v46 (major) | None |

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

- [ ] **A1 P2**: Verify VLAN Gateway Reachability
  - **Goal**: Confirm if ICMP is intentionally blocked at the gateway level
  - **Commands**: `nc -zv 10.0.10.1 443; nc -zv 10.0.20.1 443`
  - **Expected**: Port 443 open
  - **If fails**: N/A
  - **Rollback**: N/A

- [ ] **A2 P2**: Verify NAS NFS Exports
  - **Goal**: Ensure NFS exports are mountable for services that require them
  - **Commands**: `showmount -e 10.0.40.3`
  - **Expected**: Exports for /mnt/user/media and /mnt/user/backups visible
  - **If fails**: N/A
  - **Rollback**: N/A

- [ ] **A3 P2**: Merge PR #54 - Non-major updates
  - **Goal**: Apply Renovate minor/patch updates
  - **Commands**: `curl -X POST 'https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/merge' -H 'Authorization: token $GITEA_TOKEN' -H 'Content-Type: application/json' -d '{"Do":"merge"}'`
  - **Expected**: PR merged, ArgoCD apps healthy
  - **If fails**: N/A
  - **Rollback**: git revert <commit>

- [ ] **A4 P2**: Merge PR #55 - Renovate v46
  - **Goal**: Update Renovate to v46
  - **Commands**: `curl -X POST 'https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/55/merge' -H 'Authorization: token $GITEA_TOKEN' -H 'Content-Type: application/json' -d '{"Do":"merge"}'`
  - **Expected**: PR merged, Renovate pod restarts
  - **If fails**: N/A
  - **Rollback**: git revert <commit>

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-01-31 12:43 | None | None | Recon update: Ceph stabilized at HEALTH_OK. Network RED (ICMP), NAS YELLOW (Shares). | Issue updated with current state | ⚪ |
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
```

