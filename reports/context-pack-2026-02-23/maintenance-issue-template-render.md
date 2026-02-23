# [Maintenance] {{ date }} - Homelab

## Status

| Field | Value |
|-------|-------|
| **Overall Status** | {{ status_emoji }} {{ status_text }} |
| **Last Updated** | {{ timestamp }} |
| **Source Report** | {{ source_report }} |
| **Assigned To** | gitea_admin |

## Context Pack

### Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | {{ k3s_version }} |
| Node Count | {{ node_count }} |
| ArgoCD Apps | {{ app_count }} total |
| Ceph Status | {{ ceph_status }} |

### Current Health Evidence (Snapshot)

#### Metal Layer
| Check | Status | Details |
|-------|--------|---------|
| Nodes | {{ metal_nodes_status }} | {{ metal_nodes_details }} |
| Node Versions | {{ metal_versions_status }} | {{ metal_versions_details }} |
| CNI (Cilium) | {{ metal_cni_status }} | {{ metal_cni_details }} |
| Kured | {{ metal_kured_status }} | {{ metal_kured_details }} |

#### System Layer
| Check | Status | Details |
|-------|--------|---------|
| CoreDNS | {{ system_coredns_status }} | {{ system_coredns_details }} |
| Metrics Server | {{ system_metrics_status }} | {{ system_metrics_details }} |
| kube-vip | {{ system_kubevip_status }} | {{ system_kubevip_details }} |
| ArgoCD | {{ system_argocd_status }} | {{ system_argocd_details }} |

#### Storage Layer
| Check | Status | Details |
|-------|--------|---------|
| Ceph Health | {{ storage_ceph_status }} | {{ storage_ceph_details }} |
| OSDs | {{ storage_osd_status }} | {{ storage_osds_details }} |
| Usage | {{ storage_usage_status }} | {{ storage_usage_details }} |
| Pools | {{ storage_pools_status }} | {{ storage_pools_details }} |
| Monitors | {{ storage_mons_status }} | {{ storage_mons_details }} |
| MDS | {{ storage_mds_status }} | {{ storage_mds_details }} |

#### Platform Layer
| Check | Status | Details |
|-------|--------|---------|
| Ingress-Nginx | {{ platform_ingress_status }} | {{ platform_ingress_details }} |
| Certificates | {{ platform_certs_status }} | {{ platform_certs_details }} |
| External Secrets | {{ platform_secrets_status }} | {{ platform_secrets_details }} |
| Cert-Manager | {{ platform_certmgr_status }} | {{ platform_certmgr_details }} |

#### Apps Layer
| Check | Status | Details |
|-------|--------|---------|
| All Pods | {{ apps_pods_status }} | {{ apps_pods_details }} |
| Gitea | {{ apps_gitea_status }} | {{ apps_gitea_details }} |
| Grafana | {{ apps_grafana_status }} | {{ apps_grafana_details }} |
| Kanidm | {{ apps_kanidm_status }} | {{ apps_kanidm_details }} |

### Observations

#### Node Activity
{{ observations_node_activity }}

#### Renovate PRs
{{ observations_renovate }}

#### Network Evidence
- **Workstation -> Cluster**: {{ net_workstation_status }}
- **Gitea API**: {{ net_gitea_status }}
- **NAS (10.0.40.3)**: {{ net_nas_status }}
- **Gateway (10.0.20.1)**: {{ net_gateway_status }}

## Proposed Changes (Spec)

| ID | Type | Layer | Priority | Impact | Downtime | Summary | Dependencies |
|----|------|-------|----------|--------|----------|---------|--------------|
{{ proposed_changes_rows }}

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

{{ action_items_list }}

## Change Log

| Timestamp | Phase | Item | Action | Result | Status After |
|-----------|:-----:|------|--------|--------|:------------:|
<!-- markdownlint-disable MD055 MD056 -->
{{ change_log_rows }}
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
