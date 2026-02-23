# [Maintenance] 2026-02-23 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🟢 GREEN |
| **Last Updated** | 2026-02-23 09:05  |
| **Source Report** | reports/status-report-2026-02-23.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 41 total |
| Ceph Status | HEALTH_OK |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 nodes Ready. |
| Node Versions | 🟢 | All nodes on v1.33.6+k3s1; kubectl client v1.35.1 reports minor skew warning only. |
| CNI (Cilium) | 🟢 | Cilium daemonset 10/10 Ready. |
| Kured | 🟢 | ArgoCD app kured is Synced and Healthy. |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | CoreDNS Running and cluster DNS reachable. |
| Metrics Server | 🟢 | metrics-server Running and node metrics available. |
| kube-vip | 🟢 | kube-vip pods Running on all control-plane nodes. |
| ArgoCD | 🟢 | ArgoCD apps snapshot shows Synced/Healthy. |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟢 | ceph health = HEALTH_OK. |
| OSDs | 🟢 | 7/7 OSDs up and in. |
| Usage | 🟢 | 1.3 TiB used, 2.1 TiB available (36.81% raw used). |
| Pools | 🟢 | 4 pools, 177 PGs active+clean. |
| Monitors | 🟢 | 3 mons in quorum (f,h,j). |
| MDS | 🟢 | 1/1 MDS up with 1 standby-replay. |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | ingress-nginx controller Running; LoadBalancer 10.0.20.226 present. |
| Certificates | 🟢 | Certificates Ready=True across active ingress namespaces. |
| External Secrets | 🟢 | ExternalSecrets SecretSynced and ClusterSecretStore global-secrets Ready=True. |
| Cert-Manager | 🟢 | Recent CertificateRequests approved/ready and ACME orders valid. |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟢 | No CrashLoopBackOff/Error/ImagePullBackOff/Pending pods detected. |
| Gitea | 🟢 | gitea namespace pods Running; Gitea API token auth succeeded as gitea_admin. |
| Grafana | 🟢 | grafana pod 3/3 Running. |
| Kanidm | 🟢 | kanidm pod 1/1 Running and ArgoCD app healthy. |

### Observations

#### Node Activity
No NotReady nodes and no non-running kube-system pods in this snapshot.

#### Renovate PRs
Open PR #65 (kube-prometheus-stack v82 major) and PR #63 (non-major bundle) are mergeable; Dependency Dashboard issue #4 has 4 unchecked items.

#### Network Evidence
- **Workstation -> Cluster**: Connected (workstation kubeconfig validated via kubectl cluster-info).
- **Gitea API**: Authenticated via API token as gitea_admin.
- **NAS (10.0.40.3)**: GREEN (NAS check script exit code 0).
- **Gateway (10.0.20.1)**: GREEN (all VLAN gateways reachable in network check).

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| R1 | VERIFY | System | P0 | Low | None | Run universal preflight gate and stop immediately on any non-GREEN signal before change execution. | None |
| R2 | UPDATE | Platform | P1 | Medium | Low | Review PR #65 (kube-prometheus-stack to v82) with release notes and breaking-change checklist, then execute merge/defer decision with staged validation. | R1 |
| R3 | UPDATE | Platform | P2 | Medium | Low | Review PR #63 (all non-major dependencies) and execute merge/defer decision with non-database-first validation. | R1 |
| R4 | DECISION | Storage | P2 | Low | None | Reconcile issue #66 against current Ceph HEALTH_OK evidence and decide close vs keep-open with updated evidence. | R1 |
| R5 | MAINTENANCE | Apps | P3 | Low | None | Process unchecked Dependency Dashboard items by editing issue body checkboxes (no comments). | R2, R3 |

## Execution Plan

### Ordering Rules
1. Process P0 -> P1 -> P2 -> P3.
2. Within priority: Metal -> Network -> Storage -> System -> Platform -> Apps.
3. Databases are processed last within each priority.
4. Execute one change at a time and run validation gate after each change.

### Validation Gate (After Each Change)

```bash
kubectl get nodes --no-headers | grep -v " Ready " || true
kubectl get pods -n kube-system --no-headers | grep -v "Running\|Completed" || true
kubectl get applications -n argocd --no-headers | grep -v "Synced.*Healthy" || true
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true

if [ -x ~/.config/opencode/scripts/homelab-network-check.sh ]; then
  ~/.config/opencode/scripts/homelab-network-check.sh --json > /tmp/network-gate.json
elif [ -x ~/.gemini/scripts/homelab-network-check.sh ]; then
  ~/.gemini/scripts/homelab-network-check.sh --json > /tmp/network-gate.json
else
  echo "ERROR: homelab-network-check.sh not found" >&2
  exit 1
fi

if [ -x ~/.config/opencode/scripts/homelab-nas-check.sh ]; then
  ~/.config/opencode/scripts/homelab-nas-check.sh --json > /tmp/nas-gate.json
elif [ -x ~/.gemini/scripts/homelab-nas-check.sh ]; then
  ~/.gemini/scripts/homelab-nas-check.sh --json > /tmp/nas-gate.json
else
  echo "ERROR: homelab-nas-check.sh not found" >&2
  exit 1
fi
```

**PASS Criteria**: All greps return empty, `ceph health` reports `HEALTH_OK`, network script exits `0`, and NAS script exits `0`.

### Stop Conditions
- Any non-GREEN validation result.
- Missing rollback information for a risky step.
- Any action that requires unapproved destructive behavior.

## Action Items (Tasks)

### Preflight

- [ ] **A1 P0 System**: Run preflight universal validation snapshot
  - **Goal**: Establish current baseline and block all execution if any non-GREEN condition appears.
  - **Commands**: `kubectl get nodes --no-headers | grep -v ' Ready ' || true; kubectl get pods -n kube-system --no-headers | grep -v 'Running\|Completed' || true; kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; kubectl get pods -A --no-headers | grep -v 'Running\|Completed' || true; ~/.config/opencode/scripts/homelab-network-check.sh --json > /tmp/network-preflight.json; ~/.config/opencode/scripts/homelab-nas-check.sh --json > /tmp/nas-preflight.json`
  - **Expected**: No non-ready node/pod/app output, ceph health HEALTH_OK, network/NAS scripts exit 0.
  - **If fails**: Stop immediately and open a new blocking recon item for the failing layer before any PR actions.
  - **Rollback**: N/A

### High (P1)

- [ ] **C1 P1 Platform**: PR #65 release-notes and breaking-change gate
  - **Goal**: Gather evidence for kube-prometheus-stack v82 risk and make the merge/defer decision explicit.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/65" -H "Authorization: token $GITEA_TOKEN" | jq -r '.title,.mergeable,.body' > /tmp/pr65-review.txt; curl -fsSL "https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/UPGRADE.md" > /tmp/kube-prometheus-stack-UPGRADE.md`
  - **Expected**: Release notes and breaking-change checklist documented, with go/no-go decision captured.
  - **If fails**: If release notes or checklist cannot be completed, defer PR #65 and keep it open.
  - **Rollback**: N/A

- [ ] **C2 P1 Platform**: Execute PR #65 merge/defer decision with backup
  - **Goal**: Only merge after C1 passes; preserve rollback artifacts before any major monitoring update.
  - **Commands**: `kubectl get application -n argocd monitoring-system -o yaml > /tmp/monitoring-system-app-pre-pr65.yaml; kubectl get pods -n monitoring-system -o wide > /tmp/monitoring-system-pods-pre-pr65.txt; set -a; source ~/.config/gitea/.env; set +a; curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/65/merge" -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" -d '{"Do":"merge"}'`
  - **Expected**: Pre-merge backups exist and PR #65 is either merged successfully or explicitly deferred with rationale.
  - **If fails**: If merge fails or decision is defer, leave PR open and record blocker in maintenance issue body.
  - **Rollback**: git revert <merge-commit-for-pr65> && git push

- [ ] **C3 P1 Platform**: Staged validation after PR #65 (if merged)
  - **Goal**: Verify observability stack remains healthy after major chart update.
  - **Commands**: `kubectl get applications -n argocd monitoring-system -o wide; kubectl get pods -n monitoring-system -o wide; kubectl get pods -n grafana -o wide; kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true`
  - **Expected**: monitoring-system and grafana remain healthy/running with no new ArgoCD drift.
  - **If fails**: Stop at P1 and execute rollback for PR #65 before continuing.
  - **Rollback**: git revert <merge-commit-for-pr65> && git push

### Medium (P2)

- [ ] **D1 P2 Storage**: Reconcile issue #66 with current Ceph state
  - **Goal**: Confirm whether Ceph mgr crash issue is still active and decide close vs keep-open for issue #66.
  - **Commands**: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail > /tmp/ceph-health-detail-D1.txt; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash ls-new > /tmp/ceph-crash-ls-new-D1.txt; set -a; source ~/.config/gitea/.env; set +a; curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/66" -H "Authorization: token $GITEA_TOKEN" > /tmp/issue66.json`
  - **Expected**: Issue #66 decision recorded from fresh evidence (close if resolved, keep-open if reproducible).
  - **If fails**: If diagnostics conflict, keep issue #66 open and add explicit blocking note in maintenance issue.
  - **Rollback**: N/A

- [ ] **D2 P2 Platform**: PR #63 review and risk decision
  - **Goal**: Evaluate bundled non-major updates before merge to avoid broad blast radius.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/63" -H "Authorization: token $GITEA_TOKEN" | jq -r '.title,.mergeable,.body' > /tmp/pr63-review.txt`
  - **Expected**: Merge/defer decision recorded with risk rationale.
  - **If fails**: If review cannot be completed, defer PR #63 and leave open.
  - **Rollback**: N/A

- [ ] **D3 P2 Platform**: Execute PR #63 merge/defer decision with backup
  - **Goal**: Apply non-major bundle only after D2 passes and preserve rollback evidence.
  - **Commands**: `kubectl get applications -n argocd -o wide > /tmp/argocd-apps-pre-pr63.txt; kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' > /tmp/db-pods-pre-pr63.txt || true; set -a; source ~/.config/gitea/.env; set +a; curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/63/merge" -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" -d '{"Do":"merge"}'`
  - **Expected**: PR #63 is merged or explicitly deferred, and backup snapshots exist.
  - **If fails**: If merge fails or introduces drift, defer and open narrowed follow-up update plan.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

- [ ] **D4 P2 Platform**: Post-merge non-database validation for PR #63
  - **Goal**: Validate core platform and app health before touching database checks.
  - **Commands**: `kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; kubectl get pods -n monitoring-system --no-headers | grep -v 'Running\|Completed' || true; kubectl get pods -n external-secrets --no-headers | grep -v 'Running\|Completed' || true`
  - **Expected**: No new non-healthy ArgoCD apps and no failed pods in monitoring-system/external-secrets.
  - **If fails**: Stop and rollback PR #63 before proceeding to database validation.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

- [ ] **D5 P2 Apps**: Database validation last for PR #63
  - **Goal**: Enforce database-last rule and confirm postgres/mariadb/supabase workloads remain stable.
  - **Commands**: `kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' > /tmp/db-pods-post-pr63.txt || true; kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' | grep -v 'Running\|Completed' || true`
  - **Expected**: Database-related pods are Running/Completed with no new failures.
  - **If fails**: Rollback PR #63 and restore previous stable dependency set.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

### Low (P3)

- [ ] **E1 P3 Apps**: [Renovate] Mark dashboard item for renovate/all-minor-patch
  - **Goal**: Check off Dependency Dashboard item in issue #4 (https://git.eaglepass.io/ops/homelab/issues/4) after decision on PR #63.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/all-minor-patch' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dashboard checkbox for renovate/all-minor-patch is checked in issue body.
  - **If fails**: Refresh dashboard body and re-run update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/all-minor-patch' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E2 P3 Apps**: [Renovate] Mark dashboard item for renovate/kube-prometheus-stack-82.x
  - **Goal**: Check off Dependency Dashboard item in issue #4 (https://git.eaglepass.io/ops/homelab/issues/4) after decision on PR #65.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/kube-prometheus-stack-82.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dashboard checkbox for renovate/kube-prometheus-stack-82.x is checked in issue body.
  - **If fails**: Refresh dashboard body and re-run update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/kube-prometheus-stack-82.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E3 P3 Apps**: [Renovate] Mark dashboard bulk rebase item
  - **Goal**: Check off Dependency Dashboard bulk rebase item in issue #4 (https://git.eaglepass.io/ops/homelab/issues/4).
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-all-open-prs' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dashboard checkbox for bulk rebase is checked in issue body.
  - **If fails**: Refresh dashboard body and re-run update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-all-open-prs' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E4 P3 Apps**: [Renovate] Mark dashboard blocked PR recreate item
  - **Goal**: Check off Dependency Dashboard recreate item in issue #4 (https://git.eaglepass.io/ops/homelab/issues/4) for blocked debian v13 PR.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='recreate-branch=renovate/docker.io-library-debian-13.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dashboard recreate checkbox is checked and Renovate re-queues PR creation.
  - **If fails**: Refresh dashboard body and re-run update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='recreate-branch=renovate/docker.io-library-debian-13.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

### Final Validation

- [ ] **F1 P0 System**: Run final universal validation gate
  - **Goal**: Confirm all layers are GREEN after all accepted decisions/changes.
  - **Commands**: `kubectl get nodes --no-headers | grep -v ' Ready ' || true; kubectl get pods -n kube-system --no-headers | grep -v 'Running\|Completed' || true; kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; kubectl get pods -A --no-headers | grep -v 'Running\|Completed' || true; ~/.config/opencode/scripts/homelab-network-check.sh --json > /tmp/network-final.json; ~/.config/opencode/scripts/homelab-nas-check.sh --json > /tmp/nas-final.json`
  - **Expected**: No non-ready output, ceph health HEALTH_OK, network/NAS checks GREEN (exit 0).
  - **If fails**: Any non-GREEN result is a hard stop and triggers new recon evidence capture.
  - **Rollback**: N/A

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-02-23 08:54 | Recon | Phase 1 | Executed exhaustive evidence capture | Captured cluster, network, NAS, Ceph, platform, apps, and repo evidence under context pack | 🟢 |
| 2026-02-23 09:12 | Spec | Phase 2-6 | Regenerated maintenance spec for GREEN baseline | Converted to PR/dependency-focused action plan with explicit decision gates and rollback | 🟢 |
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

