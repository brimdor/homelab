# [Maintenance] 2026-03-31 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🟡 YELLOW |
| **Last Updated** | 2026-04-03 13:42  |
| **Source Report** | reports/status-report-2026-04-03.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 48 total |
| Ceph Status | HEALTH_WARN |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 Ready (arcanine, bulbasaur, charmander, chikorita, cyndaquil, growlithe, pikachu, sprigatito, squirtle, totodile) |
| Node Versions | 🟢 | All nodes on v1.33.6+k3s1 |
| CNI (Cilium) | 🟢 | Cilium 10/10 Ready, operator 1/1 Running |
| Kured | 🟢 | ArgoCD app kured Synced+Healthy |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | CoreDNS 1/1 Running; cluster DNS reachable |
| Metrics Server | 🟢 | metrics-server 1/1 Running; node metrics available |
| kube-vip | 🟢 | kube-vip running on bulbasaur, charmander, and squirtle |
| ArgoCD | 🟡 | 46/48 apps Synced+Healthy; rook-ceph Degraded and scribe Progressing (scribe handled separately) |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟡 | HEALTH_WARN due 2 recent mgr module crashes (prometheus + rook) on Ceph v20.2.0; all data services active+clean |
| OSDs | 🟢 | 6 OSDs up, 6 in across 5 hosts |
| Usage | 🟡 | Approx. 1.4 TiB used of 3.0 TiB raw; standard-rwo pool about 55.17% used |
| Pools | 🟢 | 4 pools, 177 PGs, all active+clean |
| Monitors | 🟢 | 3 mons in quorum (h,k,l), leader h |
| MDS | 🟢 | 1 active MDS with 1 hot standby |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | Ingress-nginx healthy; 33 ingresses present |
| Certificates | 🟢 | 33/33 certificates Ready=True |
| External Secrets | 🟢 | 7/7 ExternalSecrets Ready=True; secret stores accessible |
| Cert-Manager | 🟢 | cert-manager flow healthy; no stuck orders/challenges at snapshot time |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟡 | No CrashLoopBackOff/Error/ImagePullBackOff pods; scribe rollout is Progressing under separate active remediation |
| Gitea | 🟢 | gitea, PostgreSQL, and Valkey pods all Running |
| Grafana | 🟢 | grafana pod 3/3 Running |
| Kanidm | 🟢 | kanidm-0 1/1 Running |

### Observations

#### 🔍 Node Activity
10 nodes stable. CPU usage ranges roughly 3-36%, memory 9-26%. No node pressure detected. Dedicated taints remain on arcanine and sprigatito.

#### 🔍 Renovate PRs
Open PRs: #80 chore(deps) non-major dependency bundle, #81 bitnamilegacy/postgresql tag to v17. Dependency Dashboard #4 also reports missing GitHub token/release-note coverage, docker lookup failures for podwave images, and blocked nextcloud v9 recreation (#74).

#### Network Evidence
- **Workstation → Cluster**: GREEN - direct kubectl access to https://10.0.20.50:6443 from workstation
- **Gitea API**: GREEN - API token authenticated as gitea_admin
- **NAS (10.0.40.3)**: GREEN - Unraid reachable on SMB/NFS/Web checks
- **Gateway (10.0.20.1)**: GREEN - all VLAN gateways reachable

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| B1 | Remediation | Storage | P0 | Low | None | Restore Ceph HEALTH_OK by validating mgr stability and archiving only historical crash records if no fresh crashes remain | None |
| B2 | Upgrade | Storage | P0 | Medium | Maintenance window | Upgrade Rook Ceph image off known-bad Ceph v20.2.0 to a fixed supported 20.2.x patch and validate chart compatibility | B1 |
| C1 | Configuration | Platform | P1 | Low | None | Re-enable rook-ceph monitoring once the Ceph patch is verified stable | B2 |
| C2 | Investigation | Storage | P1 | Medium | Host maintenance may be required | Investigate bulbasaur OSD hardware exclusion and recurring BlueFS stalled-read history | None |
| C3 | Investigation | Apps | P1 | Low | None | Investigate Woodpecker SQLite lock errors causing intermittent health probe failures | None |
| D1 | Review | Platform | P2 | Medium | None | Review and decide merge/close for PR #80 (non-major dependency bundle) with staged validation | None |
| D2 | Review | Apps | P2 | Medium | Possible app-specific restart | Review PR #81 (bitnamilegacy/postgresql v17) with release-note check, backup, and staged rollout plan | Database backup |
| D3 | Maintenance | System | P2 | Low | None | Fix Renovate Dependency Dashboard drift and token/registry lookup problems, then refresh issue #4 | None |
| D4 | Decision | Apps | P2 | Medium | Maintenance window if executed | Review blocked nextcloud v9 dashboard item and decide whether to recreate PR #74 | Release notes review |
| E1 | Monitoring | Storage | P3 | Low | None | Track Ceph raw and standard-rwo usage trends and plan capacity before they become urgent | None |

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

- [ ] **A1 P0 System**: Refresh cluster baseline before maintenance starts
  - **Goal**: Confirm the live starting point for nodes, ArgoCD apps, Ceph, network, and NAS before making any changes
  - **Commands**: `kubectl get nodes -o wide; kubectl get applications -n argocd; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail; ~/.config/opencode/scripts/homelab-network-check.sh --verbose; ~/.config/opencode/scripts/homelab-nas-check.sh --verbose`
  - **Expected**: Live baseline captured and any drift from this recon identified before action work begins
  - **If fails**: Stop and rerun /homelab-recon if the starting state materially differs from this report
  - **Rollback**: N/A

### Critical (P0)

- [ ] **B1 P0 Storage**: Clear current Ceph HEALTH_WARN state if only historical mgr crashes remain
  - **Goal**: Return Ceph and the rook-ceph ArgoCD app to GREEN if current warnings are only retained historical crash records
  - **Commands**: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash ls-new; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr services; kubectl get application rook-ceph -n argocd; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash archive-all`
  - **Expected**: ceph health becomes HEALTH_OK and ArgoCD rook-ceph becomes Healthy without any new mgr crashes appearing
  - **If fails**: If fresh mgr crashes continue or services disappear, stop and continue with B2 as the durable fix path
  - **Rollback**: N/A

- [ ] **B2 P0 Storage**: Upgrade Ceph off v20.2.0 and validate Rook compatibility
  - **Goal**: Eliminate the known Ceph v20.2.0 mgr/orchestrator bug that is causing recurring rook-ceph instability
  - **Commands**: `grep -n "cephVersion\|image:" system/rook-ceph/values.yaml; grep -n "version:" system/rook-ceph/Chart.yaml; helm dependency update system/rook-ceph; kubectl get application rook-ceph -n argocd; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health`
  - **Expected**: Repo pinned to a fixed supported Ceph patch, sync completes cleanly, ceph health is HEALTH_OK, and rook-ceph becomes Synced+Healthy
  - **If fails**: Review upstream Rook/Ceph compatibility notes, hold the rollout, and revert to the previous known-good chart/image combination before retrying
  - **Rollback**: Revert the Ceph image/chart bump commit, resync rook-ceph, and verify ceph health plus ArgoCD health return to the pre-change state

### High (P1)

- [ ] **C1 P1 Platform**: Re-enable rook-ceph monitoring after the Ceph patch is stable
  - **Goal**: Restore native Ceph monitoring once the mgr crash bug is no longer present
  - **Commands**: `grep -n "monitoring:\|enabled:" system/rook-ceph/values.yaml; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr services; kubectl get prometheusrule -n rook-ceph; kubectl get application rook-ceph -n argocd`
  - **Expected**: rook-ceph monitoring is enabled in GitOps and the mgr prometheus endpoint remains stable without new crashes
  - **If fails**: Disable monitoring again and capture mgr logs/crash info before proceeding
  - **Rollback**: Set rook-ceph-cluster.monitoring.enabled back to false, resync rook-ceph, and confirm mgr stability

- [ ] **C2 P1 Storage**: Investigate the excluded bulbasaur OSD device and decide repair vs permanent removal
  - **Goal**: Resolve the long-running BlueFS stalled-read risk that already forced bulbasaur out of OSD placement
  - **Commands**: `grep -n "bulbasaur excluded\|BlueFS" system/rook-ceph/values.yaml; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail; kubectl -n rook-ceph logs deploy/rook-ceph-operator --tail=200`
  - **Expected**: Documented decision to repair/reintroduce the device or keep it permanently excluded with clear rationale
  - **If fails**: Escalate to host-level disk diagnostics and schedule node maintenance before making cluster storage changes
  - **Rollback**: N/A - investigation and planning only

- [ ] **C3 P1 Apps**: Investigate woodpecker-server SQLite database lock errors
  - **Goal**: Determine whether Woodpecker needs backend changes or workload tuning to avoid intermittent probe failures
  - **Commands**: `kubectl logs -n woodpecker woodpecker-server-0 --tail=200; kubectl describe pod -n woodpecker woodpecker-server-0; kubectl get pvc -n woodpecker; kubectl get statefulset -n woodpecker woodpecker-server -o yaml`
  - **Expected**: Root cause documented and a clear remediation path chosen (tuning, storage change, or PostgreSQL migration)
  - **If fails**: Capture previous logs and create a dedicated follow-up task for PostgreSQL migration planning
  - **Rollback**: N/A - investigation only

### Medium (P2)

- [ ] **D1 P2 Platform**: Review and decide PR #80 (all non-major dependencies)
  - **Goal**: Safely move routine dependency updates that are already prepared by Renovate
  - **Commands**: `curl -s https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/80; git log --oneline --decorate -n 20; pre-commit run --all-files`
  - **Expected**: PR #80 is either merged after validation or closed with documented reason
  - **If fails**: Split high-risk updates out of the bundle or defer the PR with explicit blockers
  - **Rollback**: Revert the merged dependency commit/PR and resync affected apps if regressions appear

- [ ] **D2 P2 Apps**: Review and stage PR #81 (bitnamilegacy/postgresql v17)
  - **Goal**: Handle the PostgreSQL major image change with release-note review, backup, and staged validation
  - **Commands**: `curl -s https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/81; grep -R "bitnamilegacy/postgresql" -n apps platform; kubectl get pvc -A | rg postgresql; kubectl get pods -A | rg -i postgres`
  - **Expected**: PR #81 has a documented merge/close decision with backup and validation steps before rollout
  - **If fails**: Defer the PR, capture release-note blockers, and schedule app-specific migration testing
  - **Rollback**: Restore the previous PostgreSQL image tag, revert the merged change, and validate database pods recover cleanly

- [ ] **D3 P2 System**: Fix Renovate dashboard drift and lookup failures
  - **Goal**: Get Dependency Dashboard #4 back into a trustworthy state and restore release-note/package lookup coverage
  - **Commands**: `curl -s https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4; kubectl exec -n renovate deploy/renovate -- printenv | rg 'GITHUB|TOKEN'; kubectl logs -n renovate deploy/renovate --tail=200`
  - **Expected**: Dependency Dashboard reflects real PR state and Renovate warnings about GitHub token/docker lookups are either fixed or explicitly documented
  - **If fails**: Document the exact credential or registry lookup failure and keep dashboard refresh as a separate follow-up
  - **Rollback**: N/A

- [ ] **D4 P2 Apps**: Decide whether to recreate blocked nextcloud v9 PR #74
  - **Goal**: Make an explicit maintenance decision on the blocked major Nextcloud update instead of leaving it ambiguous in the dashboard
  - **Commands**: `curl -s https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4; grep -R "nextcloud" -n apps/nextcloud; kubectl get pods -n nextcloud -o wide`
  - **Expected**: Issue #4 and the maintenance issue both record a clear recreate/defer decision with rationale
  - **If fails**: Defer with documented blockers and required release-note testing steps
  - **Rollback**: N/A - decision gate only

### Low (P3)

- [ ] **E1 P3 Storage**: Track Ceph capacity and pool usage trends
  - **Goal**: Prevent current 55% standard-rwo usage from becoming an urgent storage event later
  - **Commands**: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph df detail; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df tree; kubectl get pvc -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,SIZE:.spec.resources.requests.storage'`
  - **Expected**: Capacity trend documented with thresholds for expansion or cleanup before health degrades
  - **If fails**: If usage is accelerating or any pool nears a warning threshold, promote storage expansion planning to P1
  - **Rollback**: N/A - monitoring and planning only

### Final Validation

- [ ] **F1 P0 System**: Run full post-maintenance validation gate
  - **Goal**: Confirm the homelab returns to GREEN across all layers after each significant maintenance change
  - **Commands**: `kubectl get nodes; kubectl get pods -n kube-system; kubectl get applications -n argocd; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; kubectl get pods -A; ~/.config/opencode/scripts/homelab-network-check.sh --verbose; ~/.config/opencode/scripts/homelab-nas-check.sh --verbose`
  - **Expected**: All nodes Ready, Ceph HEALTH_OK, ArgoCD apps Synced+Healthy, no bad pod states, network GREEN, NAS GREEN
  - **If fails**: Stop immediately on the first non-GREEN layer and return to targeted diagnostics before proceeding
  - **Rollback**: Undo the most recent change before continuing

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-03-31 17:30 | Recon | Issue #79 | Initial maintenance issue created | Baseline maintenance backlog captured | 🟡 |
| 2026-04-03 18:35 | Recon | Issue #79 | Evidence refreshed and Ceph/Rook maintenance plan expanded | Issue updated with live storage warnings, open PRs, and Renovate backlog | 🟡 |
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
