# [Maintenance] 2026-03-31 - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | 🟡 YELLOW |
| **Last Updated** | 2026-03-31 17:30 |
| **Source Report** | reports/status-report-2026-03-31.md |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| ArgoCD Apps | 43 total |
| Ceph Status | HEALTH_OK |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | 🟢 | 10/10 Ready (arcanine, bulbasaur, charmander, chikorita, cyndaquil, growlithe, pikachu, sprigatito, squirtle, totodile) |
| Node Versions | 🟢 | All nodes v1.33.6+k3s1 (uniform) |
| CNI (Cilium) | 🟢 | Cilium 10/10 Ready + operator running |
| Kured | 🟢 | ArgoCD app kured Synced+Healthy |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | 🟢 | CoreDNS Running, DNS reachable |
| Metrics Server | 🟢 | metrics-server Running, node metrics available |
| kube-vip | 🟢 | kube-vip running on all 3 control-plane nodes |
| ArgoCD | 🟢 | 43/43 apps Synced+Healthy |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | 🟢 | HEALTH_OK |
| OSDs | 🟢 | 6 OSDs up, 6 in across 5 hosts |
| Usage | 🟡 | 46.82% raw used (1.4 TiB / 3.0 TiB); standard-rwo pool at 55.13% |
| Pools | 🟢 | 4 pools: standard-rwo, standard-rwx-metadata, standard-rwx-data0, .mgr |
| Monitors | 🟢 | 3 mons (h,k,l) in quorum, leader h |
| MDS | 🟢 | 1/1 daemons up + 1 hot standby (standard-rwx) |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | 🟢 | ingress-nginx-controller 1/1 Running, 30 ingresses configured |
| Certificates | 🟢 | All 29 certificates Ready=True; humbleai-canary just renewed |
| External Secrets | 🟢 | 7 ExternalSecrets all SecretSynced=True; global-secrets ClusterSecretStore Valid |
| Cert-Manager | 🟢 | cert-manager Running; no stuck orders/challenges |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | 🟡 | All Running/Completed; woodpecker-server-0 had liveness/readiness probe failures (HTTP 500) at 16m ago but recovered |
| Gitea | 🟢 | gitea pod Running, all apps Synced+Healthy |
| Grafana | 🟢 | grafana 3/3 Running |
| Kanidm | 🟢 | kanidm Running, auth.eaglepass.io TLS valid |

### Observations

#### 🔍 Node Activity
cyndaquil joined 85d ago, sprigatito joined 223d ago. All 10 nodes stable. CPU usage low (3-16%), memory usage moderate (11-29%). No nodes under pressure.

#### 🔍 Renovate PRs
PRs #72 (all non-major deps), #73 (postgresql v17), #74 (nextcloud v9), #76 (node v24) were all recently merged or closed today. Dependency Dashboard (#4) still lists them as open - needs refresh. No currently open PRs.

#### Network Evidence
- **Workstation → Cluster**: Direct kubectl access via kubeconfig (server: https://10.0.20.50:6443)
- **Gitea API**: Accessible from inside cluster via internal service (localhost:3000 in gitea pod)
- **NAS (10.0.40.3)**: SMB 445 open, NFS 2049 open, Web HTTP 302 - all GREEN
- **Gateway (10.0.20.1)**: All 7 VLAN gateways reachable on SSH port 22

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
| A1 | Investigation | Apps | P1 (HIGH) | Low | None | Investigate woodpecker-server SQLite database lock errors causing intermittent HTTP 500 health probe failures | None |
| B1 | Investigation | System | P2 (MEDIUM) | Low | None | Refresh Renovate Dependency Dashboard (#4) - all referenced PRs already merged/closed but dashboard stale | None |
| C1 | Maintenance | Storage | P3 (LOW) | Low | None | Monitor Ceph standard-rwo pool usage at 55.13% - plan capacity if needed | None |

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

- [ ] A1 P1 Investigate woodpecker-server SQLite database lock errors
  - **Goal**: Identify root cause of 'database is locked' errors causing intermittent HTTP 500 health probe failures on woodpecker-server-0
  - **Commands**:
    ```bash
    kubectl logs -n woodpecker woodpecker-server-0 --tail=200
    kubectl describe pod -n woodpecker woodpecker-server-0
    kubectl get pvc -n woodpecker
    kubectl get statefulset -n woodpecker woodpecker-server -o yaml | grep -A5 volumeClaimTemplates
    ```
  - **Expected**: Identify if SQLite is the bottleneck; determine if migration to PostgreSQL backend is needed
  - **If fails**: If SQLite confirmed as bottleneck, plan migration to PostgreSQL backend for woodpecker
  - **Rollback**: N/A - investigation only

- [ ] B1 P2 Refresh Renovate Dependency Dashboard (#4)
  - **Goal**: Update Dependency Dashboard to reflect current PR state (PRs #72, #73, #74, #76 all merged/closed)
  - **Commands**:
    ```bash
    # Trigger Renovate to re-run and update the dashboard
    kubectl exec -n renovate deploy/renovate -- renovate --force
    # Verify dashboard reflects actual PR states
    kubectl exec -n gitea deploy/gitea -- wget -qO- "http://localhost:3000/api/v1/repos/ops/homelab/issues/4" | jq '.body' | grep -E '\- \[ \]|\- \[x\]'
    ```
  - **Expected**: Dependency Dashboard reflects current state (merged PRs marked as completed or removed)
  - **If fails**: Manually edit issue #4 body to mark completed items as - [x]
  - **Rollback**: N/A - dashboard is informational

- [ ] C1 P3 Monitor Ceph standard-rwo pool usage at 55.13%
  - **Goal**: Document current Ceph usage trends and plan capacity management
  - **Commands**:
    ```bash
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph df detail
    kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df tree
    kubectl get pvc -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,SIZE:.spec.resources.requests.storage' | sort -k4 -h
    ```
  - **Expected**: Document current usage trends; no immediate action needed at 55%
  - **If fails**: If usage >70%, plan OSD expansion or data cleanup
  - **Rollback**: N/A - monitoring only

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
| 2026-03-31 17:30 | Recon | All | Evidence captured, maintenance issue created | Issue ready for /homelab-action | 🟡 YELLOW |
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

