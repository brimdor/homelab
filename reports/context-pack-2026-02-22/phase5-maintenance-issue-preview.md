# [Maintenance] 2026-02-22 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🔴 RED |
| **Last Updated** | 2026-02-22 18:05  |
| **Source Report** | reports/status-report-2026-02-22.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 41 total |
| Ceph Status | HEALTH_ERR |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 Ready |
| Node Versions | 🟢 | All nodes on v1.33.6+k3s1 |
| CNI (Cilium) | 🟢 | Cilium daemonset 10/10 Ready |
| Kured | 🟢 | ArgoCD app kured Synced+Healthy |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | CoreDNS Running |
| Metrics Server | 🟢 | metrics-server Running; node metrics available |
| kube-vip | 🟢 | kube-vip running on all control-plane nodes |
| ArgoCD | 🔴 | emby OutOfSync (sync error), rook-ceph Synced+Degraded |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🔴 | HEALTH_ERR: prometheus mgr module crash loop (4 recent crashes) |
| OSDs | 🟢 | 7/7 OSDs up and in |
| Usage | 🟢 | 1.3 TiB used, 2.1 TiB available |
| Pools | 🟢 | 4 pools, 177 PGs active+clean |
| Monitors | 🟢 | 3 mons in quorum (f,h,j) |
| MDS | 🟢 | 1/1 MDS up, 1 hot standby |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | ingress-nginx controller Running, LB 10.0.20.226 |
| Certificates | 🟢 | 27/27 certificates Ready=True |
| External Secrets | 🟢 | 7/7 ExternalSecrets SecretSynced |
| Cert-Manager | 🟢 | All orders valid; no pending challenges |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟢 | No CrashLoopBackOff/Error/ImagePullBackOff/Pending pods |
| Gitea | 🟢 | Gitea API authenticated as gitea_admin |
| Grafana | 🟢 | grafana pod 3/3 Running |
| Kanidm | 🟢 | ArgoCD kanidm Synced+Healthy |

### Observations

#### Node Activity
No NotReady nodes and no kube-system non-running pods in snapshot.

#### Renovate PRs
Open PR #63 (non-major deps, mergeable), PR #65 (kube-prometheus-stack major v82, mergeable), Dependency Dashboard issue #4 has 4 unchecked items.

#### Network Evidence
- **Workstation -> Cluster**: Local default kubeconfig unauthenticated; recon used controller fallback via ssh with ~/homelab/metal/kubeconfig.yaml.
- **Gitea API**: Authenticated via API token.
- **NAS (10.0.40.3)**: YELLOW: web probe returned no content while NAS TCP ports are open.
- **Gateway (10.0.20.1)**: All VLAN gateways reachable (network script GREEN).

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| R1 | FIX | Storage | P0 | Medium | None | Recover Ceph from HEALTH_ERR caused by prometheus mgr module crashes and restore rook-ceph app health to GREEN. | None |
| R2 | FIX | Apps | P1 | Low | Rolling | Resolve emby ArgoCD OutOfSync sync error caused by invalid Deployment strategy rendering. | R1 |
| R3 | UPDATE | Platform | P1 | Medium | Low | Review/decision for PR #65 (kube-prometheus-stack 81.6.3 -> 82.2.0 major) with release-notes and breaking-change gate before merge. | R1 |
| R4 | UPDATE | Platform | P2 | Medium | Low | Review/decision for PR #63 (non-major dependency bundle) and validate post-merge app health. | R1, R2 |
| R5 | INVESTIGATE | Storage | P2 | Low | None | Confirm whether NAS web check YELLOW is expected auth behavior or a true service degradation. | None |
| R6 | MAINTENANCE | Apps | P3 | Low | None | Process all unchecked Renovate Dependency Dashboard items using scripted issue-body edits (no comments). | R3, R4 |

## Execution Plan

### Ordering Rules
1. Process P0 -> P1 -> P2 -> P3.
2. Within priority: Metal -> Network -> Storage -> System -> Platform -> Apps.
3. Databases are processed last within each priority.
4. Execute one change at a time and run validation gate after each change.

### Validation Gate (After Each Change)

```bash
ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get nodes --no-headers | grep -v ' Ready ' || true"
ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n kube-system --no-headers | grep -v 'Running\|Completed' || true"
ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true"
ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health"
ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -A --no-headers | grep -v 'Running\|Completed' || true"
~/.config/opencode/scripts/homelab-network-check.sh --json
~/.config/opencode/scripts/homelab-nas-check.sh --json
```

**PASS Criteria**: All filters return empty, ceph health is HEALTH_OK, network check exits 0, NAS check exits 0.

### Stop Conditions
- Any non-GREEN validation result.
- Missing rollback information for a risky step.
- Any action that requires unapproved destructive behavior.

## Action Items (Tasks)

### Preflight

- [ ] **A1 P0 System**: Run preflight validation snapshot before executing changes
  - **Goal**: Establish pre-change baseline and stop immediately if additional RED findings appear.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get nodes --no-headers | grep -v ' Ready ' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n kube-system --no-headers | grep -v 'Running\|Completed' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health" && ~/.config/opencode/scripts/homelab-network-check.sh --json && ~/.config/opencode/scripts/homelab-nas-check.sh --json`
  - **Expected**: No NotReady nodes, no kube-system failures, known app drift only (emby/rook-ceph), and baseline evidence captured.
  - **If fails**: If new RED findings appear, halt and create a dedicated blocking task before any change actions.
  - **Rollback**: N/A

### Critical (P0)

- [ ] **B1 P0 Storage**: Diagnose Ceph prometheus mgr module HEALTH_ERR
  - **Goal**: Confirm current failure mode and crash scope before remediation.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash ls-new && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr module ls"`
  - **Expected**: Crash list and module state captured; root cause remains limited to prometheus mgr module formatting exception.
  - **If fails**: If diagnostics cannot run, gather rook-ceph-operator logs and block all downstream tasks.
  - **Rollback**: N/A

- [ ] **B2 P0 Storage**: Apply low-risk Ceph remediation (archive crashes and restart mgr-a)
  - **Goal**: Capture pre-change Ceph status backup, then clear stale crash records and restart mgr process to recover module health without data-plane disruption.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status -f json > /tmp/ceph-status-pre-B2.json && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash archive-all && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph rollout restart deploy/rook-ceph-mgr-a && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph rollout status deploy/rook-ceph-mgr-a --timeout=300s"`
  - **Expected**: Pre-change backup /tmp/ceph-status-pre-B2.json exists, mgr-a rollout completes, and no new immediate prometheus crash appears.
  - **If fails**: If rollout or crash behavior worsens, stop and escalate for manual Ceph maintainer review before disabling modules.
  - **Rollback**: ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph rollout undo deploy/rook-ceph-mgr-a"

- [ ] **B3 P0 Storage**: Validate Ceph and ArgoCD storage layer return to GREEN
  - **Goal**: Prove storage remediation success before any update work.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph crash ls-new && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd --no-headers | grep 'rook-ceph'"`
  - **Expected**: ceph health reports HEALTH_OK, ceph crash ls-new is empty, and rook-ceph app is Synced+Healthy.
  - **If fails**: If HEALTH_ERR persists, add follow-up hotfix task for Ceph image/module patch and block PR merges.
  - **Rollback**: N/A

### High (P1)

- [ ] **C1 P1 Platform**: Review PR #65 major update with release notes and breaking-change checklist
  - **Goal**: Capture upgrade risk for kube-prometheus-stack 82.x before merge decision.
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/65" -H "Authorization: token $GITEA_TOKEN" | jq -r '.body' > /tmp/pr65-body.md; curl -fsSL "https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/UPGRADE.md" > /tmp/kube-prometheus-stack-UPGRADE.md`
  - **Expected**: Documented release notes, explicit breaking-change checklist, and a go/no-go decision captured in task execution notes.
  - **If fails**: If release notes cannot be retrieved, mark PR #65 as deferred and do not merge.
  - **Rollback**: N/A

- [ ] **C2 P1 Platform**: Execute merge/close decision for PR #65 and run staged monitoring validation
  - **Goal**: Capture pre-merge monitoring backup, then apply major monitoring stack update only when risk gate passes and verify observability stack stability.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get application -n argocd monitoring-system -o yaml > /tmp/monitoring-system-app-pre-C2.yaml && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n monitoring-system -o wide > /tmp/monitoring-system-pods-pre-C2.txt" && set -a; source ~/.config/gitea/.env; set +a; curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/65/merge" -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" -d '{"Do":"merge"}' && ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd monitoring-system -o wide && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n monitoring-system -o wide && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n grafana -o wide"`
  - **Expected**: Pre-merge backups exist (/tmp/monitoring-system-app-pre-C2.yaml, /tmp/monitoring-system-pods-pre-C2.txt), PR #65 merges cleanly, and monitoring-system remains Synced+Healthy with Prometheus/Alertmanager/Grafana pods Running.
  - **If fails**: If merge fails or monitoring degrades, close/defer PR #65 and open rollback PR immediately.
  - **Rollback**: git revert <merge-commit-for-pr65> && git push

- [ ] **C3 P1 Apps**: Fix emby ArgoCD sync error in repo (invalid deployment strategy rendering)
  - **Goal**: Make emby manifests apply cleanly so app returns to Synced state.
  - **Commands**: `git checkout -b fix/emby-sync-strategy && python3 -c "from pathlib import Path; p=Path('apps/emby/values.yaml'); t=p.read_text(); t=t.replace('# strategy: RollingUpdate','strategy: RollingUpdate',1) if '# strategy: RollingUpdate' in t else t; p.write_text(t)" && git add apps/emby/values.yaml && git commit -m "fix(emby): set valid deployment strategy for argocd sync" && git push -u origin fix/emby-sync-strategy`
  - **Expected**: A fix PR is created with explicit strategy config change and no invalid rollingUpdate/recreate combination.
  - **If fails**: If this exact change does not fix render output, generate rendered manifests and adjust values/template in follow-up fix PR.
  - **Rollback**: git switch master && git branch -D fix/emby-sync-strategy

- [ ] **C4 P1 Apps**: Validate emby app returns to Synced+Healthy after fix merge
  - **Goal**: Confirm application drift is resolved and runtime remains healthy.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n argocd get application emby -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}' && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n emby get deploy emby -o jsonpath='{.spec.strategy.type}{"\n"}'"`
  - **Expected**: emby shows Synced Healthy and deployment strategy type is valid (RollingUpdate or Recreate without forbidden rollingUpdate block).
  - **If fails**: If still OutOfSync, inspect argocd application operationState message and update fix PR with exact manifest correction.
  - **Rollback**: git revert <merge-commit-for-emby-fix> && git push

### Medium (P2)

- [ ] **D1 P2 Storage**: Investigate NAS YELLOW web probe and classify as expected or incident
  - **Goal**: Eliminate ambiguity in NAS health gate so Storage layer can be GREEN with clear criteria.
  - **Commands**: `~/.config/opencode/scripts/homelab-nas-check.sh --json > /tmp/nas-check.json && curl -sk -o /dev/null -w "%{http_code}\n" http://10.0.40.3 && curl -sk -o /dev/null -w "%{http_code}\n" https://10.0.40.3`
  - **Expected**: Either HTTP response confirms service reachable (200/30x/401/403 accepted) or a concrete incident is identified with owner.
  - **If fails**: If endpoint remains ambiguous, capture tcpdump/reverse-proxy logs and keep NAS gate as YELLOW with documented exception.
  - **Rollback**: N/A

- [ ] **D2 P2 Platform**: Execute merge/close decision for PR #63 (non-major dependency bundle)
  - **Goal**: Capture pre-merge app/database baseline backup, then apply non-major updates only if mergeable and post-merge validation remains GREEN.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd -o wide > /tmp/argocd-apps-pre-D2.txt && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' > /tmp/db-pods-pre-D2.txt" && set -a; source ~/.config/gitea/.env; set +a; curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/63" -H "Authorization: token $GITEA_TOKEN" | jq -r '.mergeable, .body' && curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/63/merge" -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" -d '{"Do":"merge"}'`
  - **Expected**: Pre-merge backups exist (/tmp/argocd-apps-pre-D2.txt, /tmp/db-pods-pre-D2.txt), and PR #63 is either merged successfully or explicitly deferred/closed with risk rationale.
  - **If fails**: If merge fails or creates immediate drift, defer PR #63 and open a narrowed-scope replacement PR.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

- [ ] **D3 P2 Platform**: Run non-database post-merge validation for PR #63
  - **Goal**: Verify system/platform/app layers stay healthy before database checks.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n monitoring-system --no-headers | grep -v 'Running\|Completed' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n external-secrets --no-headers | grep -v 'Running\|Completed' || true"`
  - **Expected**: No new non-healthy ArgoCD apps and no non-running pods in monitoring-system or external-secrets.
  - **If fails**: If failures appear, stop and revert the exact dependency update causing regression.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

- [ ] **D4 P2 Apps**: Run database workload validation last for PR #63
  - **Goal**: Validate postgres/mariadb/supabase workloads after all other P2 checks complete.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' && KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -A --no-headers | grep -E 'postgres|mariadb|supabase' | grep -v 'Running\|Completed' || true"`
  - **Expected**: All database-related pods are Running/Completed with no crash loops or pending state.
  - **If fails**: If database workloads fail, immediately revert PR #63 and restore previous image/chart versions.
  - **Rollback**: git revert <merge-commit-for-pr63> && git push

### Low (P3)

- [ ] **E1 P3 Apps**: [Renovate] Process Dependency Dashboard item: rebase renovate/all-minor-patch
  - **Goal**: Tick the dashboard checkbox for PR #63 rebase via API body edit (no comments) in Dependency Dashboard issue #4 (https://git.eaglepass.io/ops/homelab/issues/4).
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/all-minor-patch' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dependency Dashboard item for renovate/all-minor-patch is checked off.
  - **If fails**: If marker not found, refresh latest issue body and apply update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/all-minor-patch' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E2 P3 Apps**: [Renovate] Process Dependency Dashboard item: rebase renovate/kube-prometheus-stack-82.x
  - **Goal**: Tick the dashboard checkbox for PR #65 rebase via API body edit (no comments) in Dependency Dashboard issue #4 (https://git.eaglepass.io/ops/homelab/issues/4).
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/kube-prometheus-stack-82.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dependency Dashboard item for renovate/kube-prometheus-stack-82.x is checked off.
  - **If fails**: If marker not found, refresh latest issue body and apply update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-branch=renovate/kube-prometheus-stack-82.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E3 P3 Apps**: [Renovate] Process Dependency Dashboard item: rebase all open PRs
  - **Goal**: Tick the dashboard checkbox for rebase-all-open-prs via API body edit (no comments) in Dependency Dashboard issue #4 (https://git.eaglepass.io/ops/homelab/issues/4).
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-all-open-prs' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dependency Dashboard bulk rebase item is checked off.
  - **If fails**: If marker not found, refresh latest issue body and apply update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='rebase-all-open-prs' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

- [ ] **E4 P3 Apps**: [Renovate] Process Dependency Dashboard item: recreate blocked PR for debian v13
  - **Goal**: Tick the dashboard checkbox for recreate-branch=renovate/docker.io-library-debian-13.x via API body edit (no comments) in Dependency Dashboard issue #4 (https://git.eaglepass.io/ops/homelab/issues/4).
  - **Commands**: `set -a; source ~/.config/gitea/.env; set +a; MARKER='recreate-branch=renovate/docker.io-library-debian-13.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [ ] '+m,'- [x] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"`
  - **Expected**: Dependency Dashboard recreate item is checked off and Renovate re-queues PR creation.
  - **If fails**: If marker not found, refresh latest issue body and apply update with exact marker string.
  - **Rollback**: set -a; source ~/.config/gitea/.env; set +a; MARKER='recreate-branch=renovate/docker.io-library-debian-13.x' python3 -c "import os,requests;u='https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4';h={'Authorization':'token '+os.environ['GITEA_TOKEN']};m='<!-- '+os.environ['MARKER']+' -->';b=requests.get(u,headers=h,timeout=30).json()['body'];b=b.replace('- [x] '+m,'- [ ] '+m,1);requests.patch(u,headers={**h,'Content-Type':'application/json'},json={'body':b},timeout=30).raise_for_status()"

### Final Validation

- [ ] **F1 P0 System**: Run final universal validation gate
  - **Goal**: Confirm all layers are GREEN after all accepted changes and decisions.
  - **Commands**: `ssh brimdor@10.0.20.10 "KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get nodes --no-headers | grep -v ' Ready ' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -n kube-system --no-headers | grep -v 'Running\|Completed' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get applications -n argocd --no-headers | grep -v 'Synced.*Healthy' || true; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health; KUBECONFIG=~/homelab/metal/kubeconfig.yaml kubectl get pods -A --no-headers | grep -v 'Running\|Completed' || true" && ~/.config/opencode/scripts/homelab-network-check.sh --json && ~/.config/opencode/scripts/homelab-nas-check.sh --json`
  - **Expected**: No non-ready node/pod/app output, ceph health HEALTH_OK, network gate exit 0, nas gate exit 0.
  - **If fails**: Any non-GREEN result is a hard stop and requires a new recon cycle with updated evidence.
  - **Rollback**: N/A

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-02-22 17:41 | Recon | Phase 1 | Executed exhaustive evidence capture | Captured cluster, network, NAS, Ceph, ArgoCD, PR, and Dependency Dashboard evidence | 🔴 |
| 2026-02-22 23:55 | Spec | Phase 2-5 | Generated maintenance spec and atomic action plan | Prioritized tasks for Ceph HEALTH_ERR, emby OutOfSync, Renovate PR decisions, and dashboard backlog | 🔴 |
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

