# [Maintenance] 2026-01-28 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🔴 RED |
| **Last Updated** | 2026-01-28 17:51  |
| **Source Report** | `reports/status-report-2026-01-28.md` |
| **Assigned To** | gitea_admin |

---

## Context Pack

### Cluster Identity
| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 39 total |
| Ceph Status | HEALTH_OK |

### Current Health Evidence (Snapshot)
| Layer | Status | Summary |
|-------|:------:|---------|
| **Metal** | 🟢 | 10/10 nodes Ready; no resource pressure in kubectl top |
| **Network** | 🟢 | Network check GREEN (VLAN gateways, OPNSense, internet, DNS) |
| **Storage (NAS)** | 🟢 | Unraid/NAS check GREEN (SMB/NFS ports open; web reachable) |
| **System** | 🟢 | kube-system pods Running; Cilium present; Ceph HEALTH_OK |
| **Platform** | 🔴 | ArgoCD app moltbot is Synced but Degraded |
| **Apps** | 🔴 | moltbot pod ImagePullBackOff (image not found) |

### Non-Running Pods
| Namespace | Pod | Status | Age |
|-----------|-----|--------|-----|
| moltbot | moltbot-59bcd567d6-gsqzk | ImagePullBackOff | ~35m |

### Repo Inventory (Actionable)
| Category | Count | Details |
|----------|:-----:|---------|
| Open Renovate PRs | 3 | #50, #51, #52 |
| Open User PRs | 0 | None |
| Open Non-Maintenance Issues | 1 | #4 |

---

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|:--:|------|:-----:|:--------:|:------:|:--------:|---------|:------------:|
| A1 | Fix | Apps | P0 | Service outage (moltbot) | None expected (rolling) | Restore moltbot by fixing image reference/publishing image to zot | None |
| B1 | Review | System | P1 | Storage platform major upgrade risk | Possible (maintenance window) | Process Renovate PR #51 (Ceph v19 -> v20) with staged upgrade plan | None |
| B2 | Review | Platform/System | P2 | Mixed dependency updates | Possible (some workloads) | Process Renovate PR #50 (non-major deps) with staged rollout; DB changes last | None |
| B3 | Review | Apps | P2 | Base image major update | None expected (rolling) | Process Renovate PR #52 (debian:12-slim -> 13-slim) and validate impacted workloads | None |
| C1 | Investigate | System/Storage | P2 | Potential stuck detach / PV cleanup | None | Investigate VolumeFailedDelete warnings for PVs still attached to charmander (if persists) | None |
| D1 | Fix | Tooling | P3 | Recon script reliability | N/A | Fix ~/.config/opencode/scripts/recon.sh jq 'Argument list too long' failure | None |

---

## Execution Plan

### Ordering Rules Applied
1. Priority: P0 → P1 → P2 → P3
2. Layer: Metal → Network → Storage → System → Platform → Apps
3. Dependencies: Complete prerequisites before dependent items
4. Databases: Always last within a priority level

### Validation Gate (Run After EVERY Change)
```bash
# Run comprehensive validation
~/homelab/scripts/recon.sh
~/homelab/scripts/homelab-network-check.sh --json
~/homelab/scripts/homelab-nas-check.sh --json
```

### Stop Conditions
- ❌ Any validation check fails
- ❌ Unknown rollback procedure
- ❌ Human escalation required

---

## Action Items (Tasks)


### Phase A: Preflight
- [ ] **A1 P0 Apps**: Capture current moltbot failure evidence
  - **Goal**: Confirm this is still an image-pull failure before making changes
  - **Commands**: `kubectl -n argocd get applications | grep -v 'Synced.*Healthy' || true; kubectl get pods -A --no-headers | grep -E 'CrashLoopBackOff|Error|ImagePullBackOff|Pending' || true; kubectl describe pod -n moltbot moltbot-59bcd567d6-gsqzk`
  - **Expected**: moltbot shows ImagePullBackOff and ArgoCD app health is Degraded
  - **If fails**: If failure mode differs (PVC, DNS, crash), capture describe+logs and adjust plan
  - **Rollback**: N/A

- [ ] **A2 P0 Platform**: Confirm zot registry service is healthy and note access path
  - **Goal**: Ensure the registry backing 10.0.20.11:32309 is up
  - **Commands**: `kubectl -n zot get pods -o wide; kubectl -n zot get svc -o wide`
  - **Expected**: zot pod Running; svc exposes NodePort 32309
  - **If fails**: Describe zot pod and check events/logs in zot namespace
  - **Rollback**: N/A

- [ ] **A3 P0 Apps**: Verify whether moltbot image exists in zot/registry
  - **Goal**: Determine if this is a publish/missing-tag problem vs wrong image reference
  - **Commands**: `(If registry allows anonymous) curl -s http://10.0.20.11:32309/v2/_catalog; curl -s http://10.0.20.11:32309/v2/moltbot/tags/list. (If auth required) retrieve registry creds from 1Password/ExternalSecret and repeat with basic auth.`
  - **Expected**: moltbot repo exists and includes the referenced tag/digest (or it is confirmed missing)
  - **If fails**: If registry unreachable: test NodePort from the node and check ingress/Firewall; if auth issues: confirm credentials and registry config
  - **Rollback**: N/A


### Phase B: Critical (P0)
- [ ] **B1 P0 Apps**: Publish moltbot image to zot (if missing)
  - **Goal**: Make the referenced image available so pulls succeed
  - **Commands**: `Trigger the build/publish pipeline for moltbot to push to zot (10.0.20.11:32309) and re-check tags/list. If pipeline does not exist, build/push manually from the moltbot source repo.`
  - **Expected**: Registry lists moltbot image tag/digest and nodes can pull it
  - **If fails**: Check zot auth, push permissions, and image naming (repo/tag). Confirm the node can resolve and reach 10.0.20.11:32309
  - **Rollback**: N/A

- [ ] **B2 P0 Apps**: Update apps/moltbot to reference a valid image (prefer digest)
  - **Goal**: Ensure GitOps deploys a valid image reference
  - **Commands**: `In ops/homelab repo, update apps/moltbot to use the correct image repo/tag (or digest). Open PR and merge. Then sync ArgoCD application moltbot.`
  - **Expected**: moltbot deployment uses a valid image reference and rollout succeeds
  - **If fails**: Describe pod; confirm imagePullSecrets (if needed) and registry auth
  - **Rollback**: Revert the PR (new PR) to restore prior image reference

- [ ] **B3 P0 Apps/Platform**: Validate moltbot returns to GREEN
  - **Goal**: Restore Apps + Platform layer GREEN
  - **Commands**: `kubectl get pods -n moltbot -o wide; kubectl -n argocd get application moltbot; kubectl logs -n moltbot deploy/moltbot --tail=200 || true`
  - **Expected**: moltbot pod Running and ArgoCD app Synced+Healthy
  - **If fails**: Collect describe/logs; if still image pull, re-check registry contents and credentials
  - **Rollback**: Roll back ArgoCD to previous revision or revert the most recent moltbot change


### Phase C: High (P1)
- [ ] **C1 P1 System**: Review PR #51 (Ceph v20 major) release notes and decide
  - **Goal**: Decide merge/defer/close with clear criteria
  - **Commands**: `Review PR #51 + upstream Ceph v20 release notes; identify breaking changes; define maintenance window + rollback plan`
  - **Expected**: Decision recorded in issue (merge now / defer / close) with rationale
  - **If fails**: If notes indicate high risk, defer and split into smaller staged upgrades
  - **Rollback**: N/A

- [ ] **C2 P1 System**: If approved, merge PR #51 and validate Ceph health
  - **Goal**: Apply the change and keep Ceph HEALTH_OK
  - **Commands**: `Merge PR #51; wait for ArgoCD sync; validate: kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status`
  - **Expected**: ceph health returns HEALTH_OK and no rook-ceph pods are failing
  - **If fails**: Capture ceph health detail + rook-ceph-operator logs; stop further changes
  - **Rollback**: Revert the ceph image tag change (new PR) and resync


### Phase D: Medium (P2)
- [ ] **D1 P2 Platform/System**: Review PR #50 (bulk non-major deps) and decide split/merge plan
  - **Goal**: Avoid high-blast-radius upgrades; plan ordering and downtime
  - **Commands**: `Review PR #50; list components; decide if PR should be split; schedule DB-related updates last`
  - **Expected**: Plan recorded (split or merge) with ordering and validation gates
  - **If fails**: If scope is too broad, create follow-up PRs to split by layer
  - **Rollback**: N/A

- [ ] **D2 P2 Platform/System**: If approved, merge PR #50 and validate cluster health
  - **Goal**: Apply non-major updates safely
  - **Commands**: `Merge PR #50; wait for ArgoCD sync; run universal validation gate`
  - **Expected**: All layers remain GREEN
  - **If fails**: Identify failing app/pod and roll back the merge
  - **Rollback**: Revert the merge (new PR) and resync

- [ ] **D3 P2 Apps**: Review PR #52 (debian 13-slim major) and decide
  - **Goal**: Ensure base image major bump is safe
  - **Commands**: `Review PR #52; identify impacted workloads; check upstream Debian 13 changes; plan rollback`
  - **Expected**: Decision recorded (merge/defer/close) with risk assessment
  - **If fails**: If risk uncertain, defer until tested in non-prod namespace
  - **Rollback**: N/A

- [ ] **D4 P2 Apps**: If approved, merge PR #52 and validate impacted workloads
  - **Goal**: Apply the major base-image update without regressions
  - **Commands**: `Merge PR #52; wait for ArgoCD sync; run universal validation gate; spot-check workloads affected by debian base image`
  - **Expected**: No new non-running pods appear
  - **If fails**: Roll back the merge and capture failure logs
  - **Rollback**: Revert the merge (new PR) and resync

- [ ] **D5 P2 System/Storage**: Confirm whether VolumeFailedDelete warnings are recurring
  - **Goal**: Decide whether detach remediation is needed
  - **Commands**: `kubectl get events -A --sort-by=.lastTimestamp | tail -200 | grep -E 'VolumeFailedDelete|still attached' || true`
  - **Expected**: Either no recurring warnings or the exact PV/node is identified
  - **If fails**: If grep errors, rerun without filter and manually identify storage warnings
  - **Rollback**: N/A

- [ ] **D6 P2 System/Storage**: If recurring, identify stuck VolumeAttachment and remediate safely
  - **Goal**: Unblock PV deletion without data loss
  - **Commands**: `kubectl get volumeattachments.storage.k8s.io -o wide; identify the VolumeAttachment referencing the PV; confirm the consuming pod/workload is gone; follow CSI detach remediation procedure`
  - **Expected**: PV deletion completes and no CSI errors remain
  - **If fails**: Describe VolumeAttachment + check rook-ceph csi nodeplugin logs on implicated node
  - **Rollback**: N/A


### Phase E: Low (P3)
- [ ] **E1 P3 Tooling**: Fix recon.sh jq argument overflow
  - **Goal**: Make ~/.config/opencode/scripts/recon.sh usable again
  - **Commands**: `Fix ~/.config/opencode/scripts/recon.sh failing jq invocation; rerun ~/.config/opencode/scripts/recon.sh --json`
  - **Expected**: Script exits 0 and produces JSON
  - **If fails**: Run with bash -x to identify failing line; capture stdout/stderr
  - **Rollback**: N/A


### Phase F: Final Validation
- [ ] **F1 P0 All**: Universal validation gate
  - **Goal**: Confirm all layers return to GREEN
  - **Commands**: `kubectl get nodes | grep -v Ready || true; kubectl get pods -n kube-system | grep -Ev 'Running|Completed' || true; kubectl get applications -n argocd | grep -Ev 'Synced.*Healthy' || true; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; kubectl get pods -A --no-headers | grep -Ev 'Running|Completed' || true`
  - **Expected**: All greps produce no output; ceph health returns HEALTH_OK
  - **If fails**: Stop and troubleshoot the failing layer before proceeding
  - **Rollback**: N/A

---

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
| - | - | - | No actions yet | - | - |

---

## Closure (Filled by homelab-action on completion)

### Resolution Summary
| Field | Value |
|-------|-------|
| **Status** | PENDING |
| **Started** | - |
| **Completed** | - |
| **Duration** | - |
| **Resolved By** | - |

---

*Created/Updated by homelab-recon workflow*
*Last modified: 2026-01-28 17:51 *