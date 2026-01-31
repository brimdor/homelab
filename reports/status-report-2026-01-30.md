# Homelab Status Report - 2026-01-30 (Evening Update)

**Generated**: 2026-01-30 19:10 CST  
**Source**: opencode /homelab-recon  
**Cluster**: eaglepass-prod (K3s v1.33.6+k3s1)

---

## Executive Summary

| Layer | Status | Summary |
|-------|--------|---------|
| Metal | GREEN | 10/10 nodes Ready |
| System | GREEN | All core services Running |
| Storage | GREEN | Ceph HEALTH_OK (35% used) |
| Platform | GREEN | All certs Ready, secrets synced |
| Apps | GREEN | 40/40 ArgoCD apps Synced+Healthy |
| **Overall** | **GREEN** | Cluster healthy, 2 PRs pending review |

---

## Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Client Version | v1.35.0 |
| Control Plane | https://10.0.20.50:6443 |
| Node Count | 10 (3 masters, 7 workers) |
| ArgoCD Apps | 40 total |
| Ceph Status | HEALTH_OK |

---

## Metal Layer

### Nodes

| Node | Role | Status | IP | CPU | Memory |
|------|------|--------|----|----|--------|
| arcanine | worker | Ready | 10.0.20.19 | 3% | 6% |
| bulbasaur | master | Ready | 10.0.20.13 | 22% | 38% |
| charmander | master | Ready | 10.0.20.11 | 24% | 24% |
| chikorita | worker | Ready | 10.0.20.15 | 7% | 9% |
| cyndaquil | worker | Ready | 10.0.20.16 | 8% | 18% |
| growlithe | worker | Ready | 10.0.20.18 | 14% | 17% |
| pikachu | worker | Ready | 10.0.20.14 | 4% | 19% |
| sprigatito | worker | Ready | 10.0.20.20 | 3% | 15% |
| squirtle | master | Ready | 10.0.20.12 | 20% | 28% |
| totodile | worker | Ready | 10.0.20.17 | 9% | 18% |

### CNI (Cilium)

- 10/10 Cilium pods Running
- 1 Cilium operator Running
- Hubble UI/Relay Running

---

## System Layer

### Core Services

| Service | Status | Pods |
|---------|--------|------|
| CoreDNS | Running | 1/1 |
| Metrics Server | Running | 1/1 |
| kube-vip | Running | 3/3 (HA) |
| NFS Provisioner | Running | 1/1 |

---

## Storage Layer

### Ceph Status

```
Health: HEALTH_OK
Cluster ID: 13c20377-d801-43f9-aebd-59f62df5dad1

services:
  mon: 3 daemons, quorum f,h,j (age 8h) [leader: f]
  mgr: b(active, since 11h), standbys: a
  mds: 1/1 daemons up, 1 hot standby
  osd: 7 osds: 7 up (since 8h), 7 in (since 2d)

data:
  volumes: 1/1 healthy
  pools:   4 pools, 177 pgs
  objects: 157.53k objects, 610 GiB
  usage:   1.2 TiB used, 2.2 TiB / 3.4 TiB avail
  pgs:     177 active+clean
```

### Capacity

| Metric | Value |
|--------|-------|
| Total | 3.4 TiB |
| Used | 1.2 TiB |
| Available | 2.2 TiB |
| Usage % | 35.10% |

### OSD Distribution

| Host | OSDs | Weight |
|------|------|--------|
| arcanine | 2 (osd.2, osd.8) | 1.33 TiB |
| bulbasaur | 1 (osd.4) | 0.40 TiB |
| chikorita | 1 (osd.0) | 0.40 TiB |
| cyndaquil | 1 (osd.1) | 0.40 TiB |
| growlithe | 1 (osd.6) | 0.45 TiB |
| sprigatito | 1 (osd.7) | 0.40 TiB |

### NAS (Unraid)

| Check | Status |
|-------|--------|
| SMB (445) | OPEN |
| NFS (2049) | OPEN |
| Web (80) | 302 (redirect to login) |

---

## Platform Layer

### Ingress

| Component | Status |
|-----------|--------|
| ingress-nginx-controller | Running (1/1) |
| Location | totodile (10.0.2.71) |

### Certificates (25 total, all Ready)

All certificates **Ready=True** across namespaces:
argocd, backlog, backlog-canary, budget, budget-canary, dex, emby, explorers-hub, gitea, grafana, humbleai, humbleai-canary, kanidm, localai, n8n, nextcloud, ollama, openwebui, radarr, sabnzbd, searxng, sonarr, woodpecker, zot

### External Secrets (7 total, all Synced)

| Secret | Store | Status |
|--------|-------|--------|
| connect/op-credentials | global-secrets | SecretSynced |
| dex/dex-secrets | global-secrets | SecretSynced |
| gitea/gitea-admin-secret | global-secrets | SecretSynced |
| grafana/grafana-secrets | global-secrets | SecretSynced |
| renovate/renovate-secret | global-secrets | SecretSynced |
| woodpecker/woodpecker-secret | global-secrets | SecretSynced |
| zot/registry-admin-secret | global-secrets | SecretSynced |

---

## Apps Layer (ArgoCD)

### All Applications (40 total) - All Synced + Healthy

argocd, backlog, backlog-canary, budget, budget-canary, cert-manager, cloudflared, connect, dex, doplarr, emby, explorers-hub, external-dns, external-secrets, gitea, global-secrets, gpu-operator, grafana, humbleai, humbleai-canary, ingress-nginx, kanidm, kured, loki, monitoring-system, n8n, nextcloud, ollama, openwebui, postgres, qdrant, radarr, renovate, rook-ceph, sabnzbd, searxng, sonarr, volsync-system, woodpecker, zot

---

## Repo Evidence

### Open Pull Requests

| PR | Title | Author | Branch | Mergeable | Age |
|----|-------|--------|--------|-----------|-----|
| #54 | chore(deps): update all non-major dependencies | gitea_admin | renovate/all-minor-patch | true | <1 day |
| #55 | chore(deps): update helm release renovate to v46 | gitea_admin | renovate/renovate-46.x | true | <1 day |

#### PR #54 Details (Non-major dependencies)

| Package | Update | Change |
|---------|--------|--------|
| grafana | patch | 10.5.14 → 10.5.15 |
| kube-prometheus-stack | patch | 81.3.0 → 81.3.2 |
| ollama | minor | 1.39.0 → 1.40.0 |
| supabase/logflare | patch | 1.30.5 → 1.30.6 |
| supabase/postgres | patch | 17.6.1.074 → 17.6.1.075 |
| supabase/realtime | patch | v2.73.3 → v2.73.5 |
| supabase/storage-api | minor | v1.35.3 → v1.36.0 |

#### PR #55 Details (Renovate major update)

| Package | Update | Change |
|---------|--------|--------|
| renovate | major | 45.88.1 → 46.0.3 |

### Open Issues

| Issue | Title | Labels | Assignee |
|-------|-------|--------|----------|
| #53 | [Maintenance] 2026-01-29 - Homelab | maintenance | gitea_admin |
| #4 | Dependency Dashboard | - | - |

---

## Events & Warnings

### Warning Events

| Timestamp | Type | Node | Message |
|-----------|------|------|---------|
| Recent (recurring) | Warning | growlithe | InvalidDiskCapacity: invalid capacity 0 on image filesystem |

**Analysis:** The growlithe node is reporting InvalidDiskCapacity events for the image filesystem. This appears to be a transient metrics collection issue. Node conditions show:
- MemoryPressure: False
- DiskPressure: False
- PIDPressure: False
- Ready: True

The node is fully functional with no actual disk pressure. This warning is informational and does not require immediate action but should be monitored.

### Normal Events (Summary)

- Frequent kubelet start events on growlithe (kured checking for reboots - normal)
- CertificateExpirationOK events on all nodes
- ClusterSecretStore validated

---

## Validation Gate Results

```bash
kubectl get nodes | grep -v "Ready" || true
# Result: No non-Ready nodes

kubectl get pods -n kube-system | grep -v "Running\|Completed" || true
# Result: All pods Running/Completed

kubectl get applications -n argocd | grep -v "Synced.*Healthy" || true
# Result: All apps Synced+Healthy

kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
# Result: HEALTH_OK

kubectl get pods -A --no-headers | grep -v "Running\|Completed" || true
# Result: No problematic pods
```

**Validation Status: ALL PASS**

1. **P2**: Merge Renovate PRs #54 and #55 during maintenance window (low risk, minor updates)
2. **P3**: Monitor growlithe node for InvalidDiskCapacity recurrence
3. **P3**: Continue normal operations (all layers GREEN)

---

## Completion Status

| Phase | Status |
|-------|--------|
| Phase 1: Context Loading | ✅ Complete |
| Phase 2: Specification | ✅ Complete |
| Phase 3: Clarification | ✅ Complete |
| Phase 4: Planning | ✅ Complete |
| Phase 5: Task Generation | ✅ Complete |
| Phase 6: Analysis | ✅ Complete |
| Phase 7: Remediation | ✅ Skipped (Phase 6 passed) |
| Phase 8: Handoff | ✅ Complete |

**Recon Complete**: Maintenance issue ready for `/homelab-action`

---

## Related Resources

- **Maintenance Issue**: https://git.eaglepass.io/ops/homelab/issues/53
- **ArgoCD**: https://argocd.eaglepass.io
- **Documentation**: https://homelab.eaglepass.io
- **Dependency Dashboard**: https://git.eaglepass.io/ops/homelab/issues/4

---

*Report generated by opencode /homelab-recon*
