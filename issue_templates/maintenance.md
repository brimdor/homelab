# [Maintenance] 2026-01-21 - Homelab

## Status
- **Overall**: **GREEN**
- **Last Updated**: 2026-01-21 11:05 UTC 
- **Source**: reports/status-report-2026-01-21.md

---

## Context Pack

### Current Findings & Diagnostics
**Core Systems Status**:
- **Nodes**: All healthy, 10 nodes. Minimal resource utilization at thresholds, CPU: < 50% and 
  Memory: < 50%.
- **Cluster Version**: Kubernetes `V1.33.6+k3s1`
- **ArgoCD**: 28/28 apps synced and healthy.
- **Ceph Status**: 
  - `HEALTH_OK` but DB stalls observed: 
    - [Stalled OSDs](ceph
ds) - Investigate and resolve as needed.
    - `1 OSD observed stalled read` 
  - Check `ceph pg stat`, `osd tree`, `ceph -s`.

### Storage & Infrastructure
- **Observed Issues**: 
    - One Ceph OSD stall in DB device.
    - Ceph stalls muted and logged for diagnostics.

**Platform Status**:
- **Certificates, Ingresses and Secret Stores**: 
  - 19/19 certificates ready/issued (via cert-manager).
  - No certificate errors.
- **External Secrets**: All secrets synced properly.
- **Ingress-NGINX**: No errors.

### Actionable Repository Items
- **PRs**: No currently open conflicts or blockages from Renovate.
- **Current Open Issues**: Narrowly scoped to stalls/non-CRITICAL OSD maintenance.

---

## Proposed Changes (Spec)
| Item                            | Type             | Layer         | Priority | Risk | Summary                              | Notes                                                  |
|----------------------------------|-----------------|---------------|----------|-------|-------------------------------------|--------------------------------------------------------|
| Ceph DB Device Stalled OSD Read | Remediation     | Storage       | P0 P0-HIGH| HIGH  | Resolve stalled OSD stall       | Requires storage health assessment.
---

---

## Execution Plan
- Ordering: `P0 -> P3`, layer-wise (all layers)
- **Validation Gate**: Run checks after changes; recheck OSDs (and clusters).

**Stop Conditions**: 
- Non-healthy OSD or cluster instability.
- Incompleteness in rollback.

---

## Action Items (Tasks)

### Phase A: Preflight
- [ ] **A00**: Pre-flight: Verify access (kubectl/SSH/Gitea)

### Phase B: Remediate Findings
- [ ] B00 P**0**: System Health Check: Reassess storage issues.
  - **Goal**: Resolve stalled OSD read event(s) in DB device.
  - **Commands**: 
    ```bash
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd stat \
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree -f json
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph pg stat \
    
    ```
  
  - **If Fails**: Analyze logs with:
    ```bash
    kubectl logs -n rook-ceph deploy/rook-ceph-tools -c rook-ceph-tools -l name=rook-ceph-tools
    
    ```
---
**Rollback Plan (N/A if OSD stability confirmed) or: 
`ceph osd out osd.<id>` if required for rollback.

---
## Closure (Filled by homelab-action)
---
---
## Change Log

| Timestamp            | Summary Event                         | Notes                                  |
|:---------------------|--------------------------------------|:------|
| 2026-01-21 11:05:00 | Initial health findings capture       | Ceph stall recorded as maintenance.   |

---
