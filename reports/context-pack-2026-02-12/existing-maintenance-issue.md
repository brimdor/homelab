# [Maintenance] 2026-01-31 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🔴 RED |
| **Last Updated** | 2026-01-31T13:03:31-06:00 |
| **Source Report** | reports/status-report-2026-01-31.md |
| **Assigned To** | gitea_admin |

## Context Pack

Context pack (this run): `reports/context-pack-2026-01-31`

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 41 total |
| Ceph Status | HEALTH_OK (7 OSDs up/in) |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 Ready; evidence: `reports/context-pack-2026-01-31/baseline-nodes.txt` |
| Node Versions | 🟢 | all nodes v1.33.6+k3s1; evidence: `reports/context-pack-2026-01-31/baseline-nodes.txt` |
| CNI (Cilium) | 🟢 | cilium DS 10/10, pods Running; evidence: `reports/context-pack-2026-01-31/system-core-kube-system.txt` |
| Kured | 🟢 | ArgoCD app `kured` Synced+Healthy; verify pods during action |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | `coredns` Running; evidence: `reports/context-pack-2026-01-31/system-core-kube-system.txt` |
| Metrics Server | 🟢 | `metrics-server` Running; evidence: `reports/context-pack-2026-01-31/system-core-kube-system.txt` |
| kube-vip | 🟢 | kube-vip pods Running (restarts observed but stable); evidence: `reports/context-pack-2026-01-31/system-core-kube-system.txt` |
| ArgoCD | 🟢 | 41/41 apps Synced+Healthy; evidence: `reports/context-pack-2026-01-31/baseline-argocd-apps.txt` |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟢 | HEALTH_OK; evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |
| OSDs | 🟢 | 7 up / 7 in; evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |
| Usage | 🟢 | 35% raw used (1.2TiB/3.4TiB); evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |
| Pools | 🟢 | 4 pools, 177 pgs active+clean; evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |
| Monitors | 🟢 | 3 mons in quorum; evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |
| MDS | 🟢 | 1/1 up + hot standby; evidence: `reports/context-pack-2026-01-31/storage-ceph.txt` |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | controller Running; LB 10.0.20.226; evidence: `reports/context-pack-2026-01-31/platform.txt` |
| Certificates | 🟢 | all certs Ready=True; evidence: `reports/context-pack-2026-01-31/platform.txt` |
| External Secrets | 🟢 | ExternalSecrets Ready=True, ClusterSecretStore Valid; evidence: `reports/context-pack-2026-01-31/platform.txt` |
| Cert-Manager | 🟢 | no pending challenges; evidence: `reports/context-pack-2026-01-31/platform.txt` |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟢 | no CrashLoopBackOff/Error/ImagePullBackOff/Pending found; evidence: `reports/context-pack-2026-01-31/apps-problem-pods.txt` |
| Gitea | 🟢 | ArgoCD app `gitea` Synced+Healthy; evidence: `reports/context-pack-2026-01-31/baseline-argocd-apps.txt` |
| Grafana | 🟢 | ArgoCD app `grafana` Synced+Healthy; evidence: `reports/context-pack-2026-01-31/baseline-argocd-apps.txt` |
| Kanidm | 🟢 | ArgoCD app `kanidm` Synced+Healthy; evidence: `reports/context-pack-2026-01-31/baseline-argocd-apps.txt` |

### Observations

#### 🔍 Node Activity
- No critical events identified in this recon; evidence: `reports/context-pack-2026-01-31/baseline-events-tail-200.txt`

#### 🔍 Renovate PRs
- Open PRs: #54, #55 (both mergeable); evidence: `reports/context-pack-2026-01-31/gitea-open-prs.json`
- Dependency Dashboard: Issue #4; evidence: `reports/context-pack-2026-01-31/dependency-dashboard.md`

#### Network Evidence
- **Workstation → Cluster**: 🟢 (kubectl OK; evidence: `reports/context-pack-2026-01-31/kubectl-cluster-info.txt`)
- **Gitea API**: 🟢 (token validated; evidence: `reports/context-pack-2026-01-31/gitea-token-check.txt`)
- **NAS (10.0.40.3)**: 🟡 (NAS script warns on unauth share listing + legacy expectations; required NFS export exists: `/mnt/user/heartlib`; evidence: `reports/context-pack-2026-01-31/nas.json`, `reports/context-pack-2026-01-31/nas-showmount.txt`, `reports/context-pack-2026-01-31/storage-nfs-provisioner.txt`)
- **Gateway (10.0.20.1)**: 🟡 (all VLAN gateways respond on TCP 443; ICMP appears blocked -> network script reports RED; evidence: `reports/context-pack-2026-01-31/network.json`, `reports/context-pack-2026-01-31/network-gateway-tcp-443.txt`)

#### Tooling Notes (Workstation)
- `apt-get` unavailable; `pip --user` blocked by PEP 668. Remediated by venv at `~/.local/venvs/homelab-recon`.
- `nc` installed via brew (GNU netcat) at `/home/linuxbrew/.linuxbrew/bin/nc`.

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| N1 | INVESTIGATE | Network | P2 | Low | None | Confirm VLAN gateway ICMP policy (blocked by design vs regression) and decide whether to enable ICMP or adjust network health check to use TCP reachability | None |
| N2 | FIX | Network | P2 | Low | None | Make network gate GREEN by enabling ICMP to VLAN gateways OR updating the network check script to treat TCP 443 reachability as the gateway signal | N1 |
| S1 | INVESTIGATE | Storage | P2 | Low | None | Reconcile NAS check expectations (SMB share listing + NFS exports) vs actual Unraid exports; confirm required NFS path for cluster: `/mnt/user/heartlib` | None |
| S2 | FIX | Storage | P2 | Low | None | Update NAS gate to validate required exports (e.g., `/mnt/user/heartlib`) and avoid false YELLOW on unauthenticated SMB listing | S1 |
| P1 | REVIEW | Platform | P2 | Medium | None | [Renovate] Review PR #55 (Renovate v46 major): release notes + breaking-change checklist; decide merge/hold | None |
| P2 | UPDATE | Platform | P2 | Medium | None | [Renovate] Merge PR #55; verify renovate workload health; update Dependency Dashboard checkboxes | P1 |
| A1 | REVIEW | Apps | P2 | Medium | None | [Renovate] Review PR #54 non-major updates (identify DB-related changes + risk) and decide merge/hold | None |
| A2 | UPDATE | Apps | P2 | Medium | None | [Renovate] Merge PR #54; run full validation gate; update Dependency Dashboard checkboxes | A1 |
| R3 | INVESTIGATE | Platform | P3 | Low | None | Dependency Dashboard repo problem: add github.com token for Renovate release notes retrieval (secret + ExternalSecret update) | None |
| R4 | INVESTIGATE | Platform | P3 | Low | None | Dependency Dashboard blocked item: decide whether to recreate PR #52 (debian 13) or keep blocked | None |

## Execution Plan

### Ordering Rules
1. Process P0 → P1 → P2 → P3
2. Within priority: Metal → Network → Storage → System → Platform → Apps
3. One change at a time with validation
4. Databases always last within priority

### Validation Gate (After Each Change)

```bash
kubectl get nodes | grep -v "Ready" || true
kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true

# Network gate (exit code must be 0)
~/.config/opencode/scripts/homelab-network-check.sh --json > "reports/context-pack-2026-01-31/network-gate.json"

# NAS gate (exit code must be 0)
~/.config/opencode/scripts/homelab-nas-check.sh --json > "reports/context-pack-2026-01-31/nas-gate.json"
```

**PASS Criteria**: all greps empty + ceph health = HEALTH_OK + both scripts exit 0

### Stop Conditions
- Any non-GREEN validation result
- Node NotReady status
- Ceph health != HEALTH_OK
- Missing rollback information for a risky step

## Action Items (Tasks)

### P2 - Network

- [ ] **A1 P2**: Confirm VLAN gateway health signal (ICMP vs TCP)
  - **Goal**: Decide whether to enable ICMP or update health checks to use TCP reachability
  - **Commands**:

    ```bash
    ~/.config/opencode/scripts/homelab-network-check.sh --verbose || true

    for ip in 10.0.10.1 10.0.20.1 10.0.30.1 10.0.40.1 10.0.50.1; do
      nc -zv -w 2 "$ip" 443 || true
    done

    ping -c 2 10.0.20.1 || true
    ```

  - **Expected**: Gateways reachable via TCP; ICMP policy confirmed as intended or regression
  - **If fails**: Validate inter-VLAN routing/firewall in OPNSense; re-run verbose network check and capture output
  - **Rollback**: N/A

- [ ] **A2 P2**: Make network gate GREEN (fix infra or fix script)
  - **Goal**: Ensure `homelab-network-check.sh` returns GREEN (exit 0) for the intended gateway policy
  - **Commands**:

    ```bash
    # Option 1: enable ICMP to VLAN gateways from the workstation VLAN (OPNSense)
    # Option 2: update the script to use TCP 443 checks for VLAN gateways (preferred if ICMP is intentionally blocked)

    cp ~/.config/opencode/scripts/homelab-network-check.sh ~/.config/opencode/scripts/homelab-network-check.sh.bak
    # edit script

    ~/.config/opencode/scripts/homelab-network-check.sh --json
    echo "exit=$?"
    ```

  - **Expected**: Script overall_status=GREEN and exit code 0
  - **If fails**: Capture stderr + verbose output; validate DNS/internet checks remain GREEN
  - **Rollback**: `cp ~/.config/opencode/scripts/homelab-network-check.sh.bak ~/.config/opencode/scripts/homelab-network-check.sh`

### P2 - Storage (NAS)

- [ ] **B1 P2**: Validate NAS exports required by cluster
  - **Goal**: Confirm NAS warnings are false positives vs real missing shares
  - **Commands**:

    ```bash
    kubectl -n kube-system get deploy nfs-client-provisioner-nfs-subdir-external-provisioner \
      -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}'

    showmount -e 10.0.40.3

    ~/.config/opencode/scripts/homelab-nas-check.sh --verbose || true
    ```

  - **Expected**: NFS export for `NFS_PATH` exists (currently `/mnt/user/heartlib`)
  - **If fails**: Verify Unraid NFS export settings + host access list; confirm the export name/path matches `NFS_PATH`
  - **Rollback**: N/A

- [ ] **B2 P2**: Make NAS gate GREEN (fix script expectations)
  - **Goal**: Ensure NAS check script validates required exports and avoids false YELLOW on unauth SMB listing
  - **Commands**:

    ```bash
    cp ~/.config/opencode/scripts/homelab-nas-check.sh ~/.config/opencode/scripts/homelab-nas-check.sh.bak
    # edit script

    ~/.config/opencode/scripts/homelab-nas-check.sh --json
    echo "exit=$?"
    ```

  - **Expected**: Script overall_status=GREEN and exit code 0
  - **If fails**: Validate ports 445/2049 are open; capture `showmount -e 10.0.40.3`
  - **Rollback**: `cp ~/.config/opencode/scripts/homelab-nas-check.sh.bak ~/.config/opencode/scripts/homelab-nas-check.sh`

### P2 - Platform (Renovate)

- [ ] **C1 P2**: [Renovate] Review PR #55 (Renovate v46 major)
  - **Goal**: Confirm upgrade risk (release notes, breaking changes, config changes)
  - **Commands**:

    ```bash
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/55" \
      -H "Authorization: token $GITEA_TOKEN" \
      | jq '{number,title,mergeable,base,head,created_at}'

    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/55/files" \
      -H "Authorization: token $GITEA_TOKEN" \
      | jq -r '.[].filename'
    ```

  - **Expected**: Release notes / breaking-change checklist captured; merge decision recorded in Change Log
  - **If fails**: Use web UI diff; ensure `mergeable=true` before proceeding
  - **Rollback**: N/A

- [ ] **C2 P2**: [Renovate] Merge PR #55 and verify renovate stays healthy
  - **Goal**: Upgrade Renovate helm release to v46 and confirm platform remains GREEN
  - **Commands**:

    ```bash
    curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/55/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do":"merge"}'

    kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
    kubectl get pods -n renovate -o wide || true

    # Dependency Dashboard (Issue #4): check off the PR #55 checkbox (edit issue body; no comments)
    ```

  - **Expected**: PR merged; renovate Running; ArgoCD apps Synced+Healthy
  - **If fails**: Check renovate pod logs + ArgoCD app status; rollback via git revert on merge commit
  - **Rollback**: `git revert <merge_commit_sha>`

### P2 - Apps (Renovate)

- [ ] **D1 P2**: [Renovate] Review PR #54 non-major updates (risk + DB awareness)
  - **Goal**: Ensure safe ordering and confirm no breaking changes slipped in
  - **Commands**:

    ```bash
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54" \
      -H "Authorization: token $GITEA_TOKEN" \
      | jq '{number,title,mergeable,base,head,created_at}'

    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/files" \
      -H "Authorization: token $GITEA_TOKEN" \
      | jq -r '.[].filename'
    ```

  - **Expected**: DB-related changes (if any) identified; merge decision recorded
  - **If fails**: Use web UI diff; split work into follow-up PRs if required
  - **Rollback**: N/A

- [ ] **D2 P2**: [Renovate] Merge PR #54 and run full validation gate
  - **Goal**: Apply non-major dependency updates and confirm ALL layers stay GREEN
  - **Commands**:

    ```bash
    curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do":"merge"}'

    kubectl get nodes | grep -v "Ready" || true
    kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
    kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
    kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true

    ~/.config/opencode/scripts/homelab-network-check.sh --json
    ~/.config/opencode/scripts/homelab-nas-check.sh --json

    # Dependency Dashboard (Issue #4): check off the PR #54 checkbox (edit issue body; no comments)
    ```

  - **Expected**: PR merged; all validations pass; both scripts exit 0
  - **If fails**: Identify failing ArgoCD app, then use describe/logs to isolate
  - **Rollback**: `git revert <merge_commit_sha>`

### P3 - Renovate Dashboard Problems

- [ ] **E1 P3**: [Renovate] Resolve Dependency Dashboard repo problem (GitHub token)
  - **Goal**: Enable Renovate to fetch release notes for GitHub-hosted dependencies
  - **Commands**:

    ```bash
    # Evidence
    sed -n '1,80p' "reports/context-pack-2026-01-31/dependency-dashboard.md"

    # Implement: add GitHub token as a secret via 1Password + ExternalSecrets, then redeploy renovate
    ```

  - **Expected**: Dashboard no longer shows missing github.com token warning; Renovate retrieves release notes
  - **If fails**: Verify token scope and secret injection into renovate
  - **Rollback**: Remove token secret and revert related manifests

- [ ] **E2 P3**: [Renovate] Decide whether to recreate blocked PR #52 (debian 13)
  - **Goal**: Ensure the upgrade is tracked explicitly (recreate or defer)
  - **Commands**:

    ```bash
    grep -n "pulls/52" "reports/context-pack-2026-01-31/dependency-dashboard.md" || true

    # If proceeding: tick the "recreate" checkbox in Issue #4 for PR #52 (edit issue body; no comments)
    ```

  - **Expected**: Clear decision recorded and tracked
  - **If fails**: N/A
  - **Rollback**: N/A

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-01-31T13:03:31-06:00 | Recon | Issue #53 | Normalized issue body to contract + updated with current evidence (cluster GREEN; network gate RED due to ICMP; NAS gate YELLOW due to script expectations) | Issue body updated (no comments) | 🔴 |
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
