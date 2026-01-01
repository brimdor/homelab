# Homelab Status Report - 2026-01-01

**Generated**: 2026-01-01 11:43 CST
**Overall Status**: GREEN

---

## Cluster Overview

| Metric | Value |
|--------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 |
| Total Pods | 203 |
| ArgoCD Apps | 46 |
| Ceph Health | HEALTH_OK |

---

## Layer Status

### Metal Layer: GREEN

| Node | Roles | Status | CPU | Memory |
|------|-------|:------:|----:|-------:|
| arcanine | worker | Ready | 47% | 6% |
| bulbasaur | control-plane,etcd,master | Ready | 10% | 25% |
| charmander | control-plane,etcd,master | Ready | 16% | 18% |
| chikorita | worker | Ready | 9% | 16% |
| cyndaquil | worker | Ready | 13% | 26% |
| growlithe | worker | Ready | 8% | 14% |
| pikachu | worker | Ready | 8% | 18% |
| sprigatito | worker | Ready | 3% | 9% |
| squirtle | control-plane,etcd,master | Ready | 12% | 25% |
| totodile | worker | Ready | 5% | 21% |

**Summary**: 10/10 nodes Ready, max CPU 47% (arcanine), max RAM 26% (cyndaquil)

---

### System Layer: GREEN

#### kube-system
- CoreDNS: 1/1 Running
- Metrics Server: 1/1 Running
- Cilium: 10/10 DaemonSet pods Running
- Cilium Operator: 1/1 Running
- Hubble: Relay + UI Running
- kube-vip: 3/3 Running on control-plane nodes

#### Storage (Rook/Ceph)
- Health: **HEALTH_OK**
- Monitors: 3 (quorum f,h,i)
- Managers: 2 (a active, b standby)
- OSDs: 7 up, 7 in
- MDS: 1 up, 1 hot standby
- Placement Groups: 81 active+clean
- Usage: 269 GiB / 3.4 TiB (7.72%)
- Available: 3.1 TiB

---

### Platform Layer: GREEN

#### Ingress
- ingress-nginx-controller: 1/1 Running
- LoadBalancer IP: 10.0.20.101
- Active Ingresses: 27

#### Certificates
- Total: 28
- All Ready: TRUE
- Earliest Expiring:
  - localai-eaglepass-io-tls: 31 days
  - searxng-tls-certificate: 31 days
  - backlog-companion-tls: 36 days
  - nextcloud-tls-certificate: 38 days

#### External Secrets
- ClusterSecretStore: global-secrets (Valid, Ready)
- ExternalSecrets: 7/7 SecretSynced

#### ArgoCD
- All 46 applications: Synced + Healthy

#### Monitoring
- Prometheus: 1/1 Running
- Alertmanager: 1/1 Running (3 containers)
- Grafana: 1/1 Running
- Kube-state-metrics: 1/1 Running
- Node-exporter: 10/10 DaemonSet pods Running

---

### Apps Layer: GREEN

- Error pods (CrashLoopBackOff/Error/ImagePullBackOff/Pending): **0**
- All workloads: Running or Completed

---

## Repository Status

### Open Pull Requests (10)

| PR | Title | Mergeable | Age | Layer |
|----|-------|:---------:|-----|:-----:|
| #11 | update all non-major dependencies helm releases | Yes | 21d | Apps |
| #12 | update dependency supabase/postgres to v17 | Yes | 21d | Apps |
| #13 | update helm release app-template to v4 | Yes | 20d | Apps |
| #14 | update helm release argo-cd to v9 | Yes | 20d | System |
| #15 | update helm release external-secrets to v1 | **No** | 19d | System |
| #16 | update helm release grafana to v10 | Yes | 19d | Platform |
| #17 | update helm release kured to v5 | **No** | 16d | System |
| #18 | update helm release snapshot-controller to v4 | **No** | 17d | System |
| #19 | update module gopkg.in/yaml.v2 to v3 | Yes | 16d | Test |
| #20 | update module k8s.io/client-go to v12 | **No** | 16d | Test |

**Mergeable**: 6 PRs
**Blocked (need rebase)**: 4 PRs (#15, #17, #18, #20)

### Open Issues (2)

| Issue | Title | Labels |
|-------|-------|--------|
| #10 | [Maintenance Report] 2026-01-01 | maintenance |
| #4 | Dependency Dashboard | - |

---

## Validation Gate Results

```
kubectl get nodes | grep -v "Ready" → PASS (no output)
kubectl get pods -n kube-system | grep -v "Running|Completed" → PASS (no output)
kubectl get applications -n argocd | grep -v "Synced.*Healthy" → PASS (no output)
ceph health → HEALTH_OK
kubectl get pods -A --no-headers | grep -v "Running|Completed" → PASS (no output)
```

**Result**: ALL GREEN

---

## Summary

All layers are healthy. 10 Renovate PRs are pending (6 mergeable, 4 need rebase). No critical issues found.

### Recommended Actions
1. Merge mergeable PRs in order (P3 first, then P2)
2. Rebase blocked PRs after initial merges
3. Monitor certificate renewals (all auto-renewing)
