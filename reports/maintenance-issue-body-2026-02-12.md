# [Maintenance] 2026-02-12 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | :yellow_circle: YELLOW |
| **Last Updated** | 2026-02-12T15:45:00-06:00 |
| **Source Report** | reports/status-report-2026-02-12.md |
| **Assigned To** | gitea_admin |

## Context Pack

Context pack (this run): `reports/context-pack-2026-02-12`

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 41 total (41 Synced+Healthy) |
| Ceph Status | HEALTH_OK (7 OSDs up/in, 36.38% raw used) |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | :green_circle: | 10/10 Ready; evidence: `context-pack-2026-02-12/nodes.txt` |
| Node Versions | :green_circle: | All nodes v1.33.6+k3s1; evidence: `context-pack-2026-02-12/nodes.txt` |
| Node Disk | :yellow_circle: | arcanine 82% used (8.1GB free, image GC failing); sprigatito 78.5%; totodile 74.4%; evidence: `context-pack-2026-02-12/node-fs-summary.txt` |
| CNI (Cilium) | :green_circle: | Cilium DS running on all nodes; evidence: `context-pack-2026-02-12/kube-system-pods.txt` |
| Kured | :green_circle: | ArgoCD app `kured` Synced+Healthy; evidence: `context-pack-2026-02-12/argocd-apps.txt` |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | :green_circle: | Running; evidence: `context-pack-2026-02-12/kube-system-pods.txt` |
| Metrics Server | :green_circle: | Running; evidence: `context-pack-2026-02-12/kube-system-pods.txt` |
| kube-vip | :green_circle: | Running; evidence: `context-pack-2026-02-12/kube-system-pods.txt` |
| ArgoCD | :green_circle: | 41/41 apps Synced+Healthy; evidence: `context-pack-2026-02-12/argocd-apps.txt` |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | :green_circle: | HEALTH_OK; evidence: `context-pack-2026-02-12/ceph-health.txt` |
| OSDs | :green_circle: | 7 up / 7 in; evidence: `context-pack-2026-02-12/ceph-osd-tree.txt` |
| Usage | :green_circle: | 36.38% raw used (1.2TiB/3.4TiB); evidence: `context-pack-2026-02-12/ceph-df.txt` |
| Pools | :green_circle: | 4 pools, 177 pgs active+clean; evidence: `context-pack-2026-02-12/ceph-status.txt` |
| Monitors | :green_circle: | 3 mons in quorum (f,h,j); evidence: `context-pack-2026-02-12/ceph-status.txt` |
| MDS | :green_circle: | 1/1 up + hot standby; evidence: `context-pack-2026-02-12/ceph-status.txt` |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | :green_circle: | Controller Running; LB 10.0.20.226; 25 ingresses; evidence: `context-pack-2026-02-12/ingresses.txt` |
| Certificates | :green_circle: | 26/26 certs Ready=True; no pending challenges; evidence: `context-pack-2026-02-12/certificates.txt` |
| External Secrets | :green_circle: | 7/7 ExternalSecrets SecretSynced; ClusterSecretStore valid; evidence: `context-pack-2026-02-12/external-secrets.txt` |
| Cert-Manager | :green_circle: | No pending challenges or orders; evidence: `context-pack-2026-02-12/challenges.txt` |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | :green_circle: | Zero CrashLoopBackOff/Error/ImagePullBackOff/Pending; evidence: `context-pack-2026-02-12/problem-pods.txt` |
| Gitea | :green_circle: | ArgoCD app Synced+Healthy; evidence: `context-pack-2026-02-12/argocd-apps.txt` |
| Grafana | :green_circle: | ArgoCD app Synced+Healthy; evidence: `context-pack-2026-02-12/argocd-apps.txt` |
| Kanidm | :green_circle: | ArgoCD app Synced+Healthy; evidence: `context-pack-2026-02-12/argocd-apps.txt` |

### Observations

#### Node Activity
- growlithe kubelet "Starting" events every ~7s are normal K3s cert-monitor behavior (not actual restarts); node Ready since 2026-02-11T08:15:09Z
- arcanine FreeDiskSpaceFailed warning: image GC cannot free space (82% disk usage on GPU node)
- sprigatito (GPU node) at 78.5% disk, totodile at 74.4% - approaching caution thresholds

#### Renovate PRs
- 3 open PRs: #54 (non-major, 27 packages, 13 days old), #61 (external-secrets v2 MAJOR, 5 days old), #62 (doc2vec-mcp v2 MAJOR, 2 days old)
- Dependency Dashboard: Issue #4 (3 open items + 1 blocked)
- Renovate warns: missing GITHUB_COM_TOKEN (no release notes, package lookup failures)

#### Network Evidence
- **Workstation -> Cluster**: :green_circle: (kubectl OK)
- **Gitea API**: :green_circle: (token validated as gitea_admin)
- **NAS (10.0.40.3)**: :yellow_circle: (all ports open; SMB shares require auth; NFS exports not visible to showmount)
- **VLAN Gateways**: :yellow_circle: (ICMP blocked on VLAN10/20/30/40 by design; TCP 443 reachable; VLAN50 ICMP OK)
- **Internet**: :green_circle: (1.1.1.1, 8.8.8.8, DNS resolution all OK)

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| M1 | FIX | Metal | P1 | Medium | None | Investigate and remediate arcanine disk space (82% used, image GC failing) | None |
| M2 | INVESTIGATE | Metal | P2 | Low | None | Assess sprigatito (78.5%) and totodile (74.4%) disk usage; clean up if needed | M1 |
| N1 | FIX | Network | P2 | Low | None | Update network health check script to use TCP reachability for VLAN gateways (ICMP blocked by design) | None |
| S1 | FIX | Storage | P2 | Low | None | Update NAS health check script to validate required NFS exports and avoid false YELLOW on auth-required SMB shares | None |
| P1 | REVIEW | Platform | P2 | High | Possible | [Renovate] Review PR #61 external-secrets v1.3.1 -> v2.0.0 (MAJOR): check release notes, breaking changes, migration guide | None |
| P2 | REVIEW | Platform | P2 | Medium | None | [Renovate] Review PR #62 doc2vec-mcp v1.1.14 -> v2.0.0 (MAJOR): check breaking changes | None |
| P3 | REVIEW | Platform | P2 | Medium | None | [Renovate] Review PR #54 non-major deps (27 packages including rook-ceph, ingress-nginx, cert-manager, grafana, kube-prometheus-stack, ollama, redis, kanidm) | None |
| P4 | UPDATE | Platform | P2 | Medium | None | [Renovate] Merge PR #54 (non-major deps) after review; run validation gate | P3 |
| P5 | UPDATE | Platform | P2 | High | Possible | [Renovate] Merge PR #61 (external-secrets v2) if safe; staged rollout; run validation gate | P1 |
| P6 | UPDATE | Apps | P2 | Medium | None | [Renovate] Merge PR #62 (doc2vec-mcp v2) if safe; run validation gate | P2 |
| R1 | IMPROVE | Platform | P3 | Low | None | Add GITHUB_COM_TOKEN to Renovate ExternalSecret for release notes retrieval | None |
| R2 | INVESTIGATE | Platform | P3 | Low | None | Dependency Dashboard blocked item: decide whether to recreate PR #52 (debian 13 base image) or keep blocked | None |

## Execution Plan

### Ordering Rules
1. Process P0 -> P1 -> P2 -> P3
2. Within priority: Metal -> Network -> Storage -> System -> Platform -> Apps
3. One change at a time with validation
4. Databases always last within priority
5. MAJOR version PRs (P1, P5, P6) require release notes review before merge

### Validation Gate (After Each Change)

```bash
kubectl get nodes | grep -v "Ready" || true
kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true

# Network gate
~/.config/opencode/scripts/homelab-network-check.sh --json

# NAS gate
~/.config/opencode/scripts/homelab-nas-check.sh --json
```

**PASS Criteria**: All greps return empty + ceph health = HEALTH_OK + network/NAS scripts exit 0

### Stop Conditions
- Any non-GREEN validation result
- Node NotReady status
- Ceph health != HEALTH_OK
- Missing rollback information for a risky step

## Action Items (Tasks)

### P1 - Metal

- [ ] **A1 P1 Metal**: Investigate and remediate arcanine disk space pressure
  - **Goal**: Free disk space on arcanine to below 75% usage (currently 82%, 8.1GB free) and resolve image GC failures
  - **Commands**:
    ```bash
    # Check what is consuming disk space on arcanine
    kubectl get --raw "/api/v1/nodes/arcanine/proxy/stats/summary" | jq '.node.fs'

    # List pods running on arcanine to identify large workloads
    kubectl get pods -A --field-selector spec.nodeName=arcanine -o wide

    # Check container image sizes on arcanine (via controller SSH)
    ssh brimdor@10.0.20.10 "ssh arcanine 'sudo crictl images --no-trunc 2>/dev/null | sort -k4 -h | tail -20'"

    # Option 1: Prune unused images via crictl
    ssh brimdor@10.0.20.10 "ssh arcanine 'sudo crictl rmi --prune 2>/dev/null'"

    # Option 2: If SSH unavailable, cordon + drain stale workloads or adjust kubelet image GC thresholds
    # Verify after cleanup
    kubectl get --raw "/api/v1/nodes/arcanine/proxy/stats/summary" | jq '.node.fs'
    ```
  - **Expected**: Disk usage below 75%; FreeDiskSpaceFailed events stop
  - **If fails**: Check if Ceph OSD data on arcanine (1.33 TiB across osd.2 + osd.8) is consuming ephemeral storage; consider moving workloads off arcanine or expanding disk
  - **Rollback**: N/A (disk cleanup is non-destructive; only unused images are pruned)

### P2 - Metal

- [ ] **B1 P2 Metal**: Assess and clean up disk on sprigatito (78.5%) and totodile (74.4%)
  - **Goal**: Ensure GPU and worker nodes have adequate free space (target: below 75%)
  - **Commands**:
    ```bash
    # Check filesystem usage
    for node in sprigatito totodile; do
      echo "=== $node ==="
      kubectl get --raw "/api/v1/nodes/$node/proxy/stats/summary" | jq '.node.fs'
      kubectl get pods -A --field-selector spec.nodeName=$node --no-headers | wc -l
    done

    # Prune unused images if accessible
    ssh brimdor@10.0.20.10 "ssh sprigatito 'sudo crictl rmi --prune 2>/dev/null'" || true
    ssh brimdor@10.0.20.10 "ssh totodile 'sudo crictl rmi --prune 2>/dev/null'" || true

    # Verify
    for node in sprigatito totodile; do
      kubectl get --raw "/api/v1/nodes/$node/proxy/stats/summary" | jq ".node.fs"
    done
    ```
  - **Expected**: Both nodes below 75% usage
  - **If fails**: Identify large images/workloads; consider rescheduling non-GPU workloads
  - **Rollback**: N/A (image prune is non-destructive)

### P2 - Network

- [ ] **C1 P2 Network**: Update network health check script for TCP-based VLAN gateway checks
  - **Goal**: Eliminate false RED from ICMP-blocked VLAN gateways; script should exit 0 when TCP reachability confirms gateway health
  - **Commands**:
    ```bash
    # Backup existing script
    cp ~/.config/opencode/scripts/homelab-network-check.sh ~/.config/opencode/scripts/homelab-network-check.sh.bak

    # Update script to use TCP 443 for VLAN gateway checks instead of ICMP
    # (edit VLAN gateway check section to use nc -zw2 $ip 443 instead of ping)

    # Test updated script
    ~/.config/opencode/scripts/homelab-network-check.sh --json
    echo "exit code: $?"
    ```
  - **Expected**: Script overall_status=GREEN, exit code 0; all VLAN gateways show GREEN via TCP
  - **If fails**: Verify OPNSense is listening on 443 for all VLAN gateways; check for firewall rules blocking TCP from workstation VLAN
  - **Rollback**: `cp ~/.config/opencode/scripts/homelab-network-check.sh.bak ~/.config/opencode/scripts/homelab-network-check.sh`

### P2 - Storage (NAS)

- [ ] **D1 P2 Storage**: Update NAS health check script to fix false YELLOW
  - **Goal**: NAS script exits 0 (GREEN) when ports are open and required NFS exports exist; SMB share visibility without auth should not trigger YELLOW
  - **Commands**:
    ```bash
    # Backup existing script
    cp ~/.config/opencode/scripts/homelab-nas-check.sh ~/.config/opencode/scripts/homelab-nas-check.sh.bak

    # Check actual NFS exports
    showmount -e 10.0.40.3 2>&1 || true

    # Update script: make SMB share checks informational (not YELLOW), validate NFS via port check only

    # Test updated script
    ~/.config/opencode/scripts/homelab-nas-check.sh --json
    echo "exit code: $?"
    ```
  - **Expected**: Script overall_status=GREEN, exit code 0
  - **If fails**: Verify NFS port 2049 actually serves exports; check Unraid NFS settings
  - **Rollback**: `cp ~/.config/opencode/scripts/homelab-nas-check.sh.bak ~/.config/opencode/scripts/homelab-nas-check.sh`

### P2 - Platform (Renovate PRs)

- [ ] **E1 P2 Platform**: Review PR #54 non-major dependency updates
  - **Goal**: Assess risk of 27-package non-major update bundle; identify database-related or breaking changes
  - **Commands**:
    ```bash
    source ~/.config/gitea/.env
    # Get PR diff summary
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/files" \
      -H "Authorization: token $GITEA_TOKEN" | jq '.[].filename'

    # Key packages to verify:
    # - rook-ceph v1.19.0 -> v1.19.1 (storage operator - patch, low risk)
    # - rook-ceph-cluster v1.19.0 -> v1.19.1 (storage cluster - patch, low risk)
    # - ingress-nginx 4.14.2 -> 4.14.3 (ingress - patch, low risk)
    # - cert-manager v1.19.2 -> v1.19.3 (cert mgmt - patch, low risk)
    # - kube-prometheus-stack 81.3.0 -> 81.6.3 (monitoring - minor, medium risk)
    # - external-secrets 1.3.1 -> 1.3.2 (secrets - patch, low risk)
    # - redis 8.4 -> 8.6 (DB! - minor, needs care)
    # - ollama 1.39.0 -> 1.42.0 (AI - minor)
    # - kanidm 1.8.5 -> 1.8.6 (auth - patch)
    # - grafana 10.5.14 -> 10.5.15 (observability - patch)
    # - argo-cd 9.3.7 -> 9.4.1 (GitOps - minor)
    ```
  - **Expected**: All changes assessed; redis update flagged for DB-last ordering
  - **If fails**: N/A (review only)
  - **Rollback**: N/A

- [ ] **E2 P2 Platform**: Merge PR #54 non-major dependencies
  - **Goal**: Apply non-major dependency updates; validate all services remain healthy
  - **Commands**:
    ```bash
    source ~/.config/gitea/.env
    # Merge PR
    curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/54/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do": "merge", "merge_message_field": "chore: merge non-major dependency updates (PR #54)"}'

    # Wait for ArgoCD to sync (up to 5 min)
    sleep 60

    # Run validation gate
    kubectl get nodes | grep -v "Ready" || true
    kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
    kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
    kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true

    # Check Dependency Dashboard and mark item as done
    ```
  - **Expected**: All ArgoCD apps re-sync to Healthy; zero problem pods; Ceph HEALTH_OK
  - **If fails**: Check ArgoCD app sync status; investigate failing apps; if critical, revert via git revert + force push
  - **Rollback**: `git revert <merge-commit-sha> && git push origin master`

- [ ] **E3 P2 Platform**: Review PR #61 external-secrets v1.3.1 -> v2.0.0 (MAJOR)
  - **Goal**: Assess external-secrets v2 breaking changes, migration requirements, and impact on 7 ExternalSecrets + ClusterSecretStore
  - **Commands**:
    ```bash
    # Review external-secrets v2 release notes
    # https://github.com/external-secrets/external-secrets/releases/tag/v2.0.0

    # Check current ESO CRD versions and resources
    kubectl get crd | grep external-secrets
    kubectl get externalsecret -A
    kubectl get clustersecretstore -A

    # Review PR diff
    source ~/.config/gitea/.env
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/61/files" \
      -H "Authorization: token $GITEA_TOKEN" | jq '.[].filename'
    ```
  - **Expected**: Clear understanding of migration path, CRD changes, and whether existing ExternalSecrets/ClusterSecretStores need modification
  - **If fails**: N/A (review only)
  - **Rollback**: N/A

- [ ] **E4 P2 Platform**: Merge PR #61 external-secrets v2 (if review passes)
  - **Goal**: Upgrade external-secrets to v2; verify all 7 ExternalSecrets continue to sync
  - **Commands**:
    ```bash
    # Pre-merge: backup current ExternalSecret state
    kubectl get externalsecret -A -o yaml > /tmp/externalsecrets-backup.yaml
    kubectl get clustersecretstore -A -o yaml > /tmp/clustersecretstore-backup.yaml

    source ~/.config/gitea/.env
    curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/61/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do": "merge", "merge_message_field": "chore: upgrade external-secrets to v2.0.0 (PR #61)"}'

    # Wait for ArgoCD sync
    sleep 120

    # Validate ExternalSecrets
    kubectl get externalsecret -A
    kubectl get clustersecretstore -A
    kubectl get pods -n external-secrets -o wide

    # Run full validation gate
    kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
    ```
  - **Expected**: All 7 ExternalSecrets show SecretSynced; ClusterSecretStore valid; external-secrets ArgoCD app Synced+Healthy
  - **If fails**: Check external-secrets operator logs; verify CRD compatibility; if secrets broken, revert merge
  - **Rollback**: `git revert <merge-commit-sha> && git push origin master; kubectl apply -f /tmp/externalsecrets-backup.yaml; kubectl apply -f /tmp/clustersecretstore-backup.yaml`

### P2 - Apps

- [ ] **F1 P2 Apps**: Review and merge PR #62 doc2vec-mcp v1.1.14 -> v2.0.0 (MAJOR)
  - **Goal**: Upgrade doc2vec-mcp container image; verify workload health
  - **Commands**:
    ```bash
    # Review PR diff
    source ~/.config/gitea/.env
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/62/files" \
      -H "Authorization: token $GITEA_TOKEN" | jq '.[].filename'

    # Merge if review passes
    curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/62/merge" \
      -H "Authorization: token $GITEA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"Do": "merge", "merge_message_field": "chore: upgrade doc2vec-mcp to v2.0.0 (PR #62)"}'

    # Wait and validate
    sleep 60
    kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
    kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true
    ```
  - **Expected**: ArgoCD app syncs healthy; no problem pods
  - **If fails**: Check pod logs for the affected deployment; revert if service broken
  - **Rollback**: `git revert <merge-commit-sha> && git push origin master`

### P3 - Platform (Improvements)

- [ ] **G1 P3 Platform**: Add GITHUB_COM_TOKEN to Renovate configuration
  - **Goal**: Enable Renovate to fetch release notes and resolve package lookup failures
  - **Commands**:
    ```bash
    # 1. Add GITHUB_COM_TOKEN to 1Password vault (manual step or via 1Password CLI)
    # 2. Update Renovate ExternalSecret to include the new secret key
    # 3. Update Renovate deployment to pass GITHUB_COM_TOKEN env var

    # Verify after deployment
    kubectl get externalsecret -n renovate renovate-secret -o yaml
    kubectl get pods -n renovate
    ```
  - **Expected**: Renovate logs show no github.com token warnings; release notes appear in PRs
  - **If fails**: Check 1Password item mapping; verify ExternalSecret sync
  - **Rollback**: Remove GITHUB_COM_TOKEN env var from Renovate deployment; ExternalSecret will stop syncing that key

- [ ] **G2 P3 Platform**: Assess blocked PR #52 (debian 13 base image)
  - **Goal**: Decide whether to recreate PR #52 or keep it blocked
  - **Commands**:
    ```bash
    source ~/.config/gitea/.env
    # Check what PR #52 was about
    curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/52" \
      -H "Authorization: token $GITEA_TOKEN" | jq '.title, .state'

    # If useful: tick the checkbox in Dependency Dashboard to recreate
    # If not: document decision and close
    ```
  - **Expected**: Decision documented (recreate or dismiss)
  - **If fails**: N/A
  - **Rollback**: N/A

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
| 2026-02-12T15:45:00-06:00 | Recon | All | Evidence capture + issue update | Spec complete | YELLOW |

## Closure (Filled by homelab-action)

### Completion Criteria:
- [ ] All action items completed or explicitly deferred
- [ ] All validation gates passed
- [ ] No regressions in cluster health
- [ ] Maintenance issue closed

**Final Status**: PENDING

**Closed By**: PENDING
**Closed Date**: PENDING
