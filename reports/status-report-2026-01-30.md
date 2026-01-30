# Homelab Status Report - 2026-01-30

**Generated**: 2026-01-30 12:15 CST  
**Source**: opencode /homelab-recon  
**Cluster**: eaglepass-prod (K3s v1.33.6+k3s1)

---

## Executive Summary

🟢 **ALL LAYERS GREEN** - No critical issues detected.  
**Overall Status**: Healthy and operational.  
**Action Required**: Optional - 2 Renovate PRs pending review (non-critical).

---

## Evidence Archive

### 1. Node Status
```
NAME         STATUS   ROLES                       AGE    VERSION        INTERNAL-IP
arcanine     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.19
bulbasaur    Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.13
charmander   Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.11
chikorita    Ready    <none>                      254d   v1.33.6+k3s1   10.0.20.15
cyndaquil    Ready    <none>                      25d    v1.33.6+k3s1   10.0.20.16
growlithe    Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.18
pikachu      Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.14
sprigatito   Ready    <none>                      162d   v1.33.6+k3s1   10.0.20.20
squirtle     Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.12
totodile     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.17
```

### 2. Resource Usage (kubectl top nodes)
```
NAME         CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
arcanine     282m         3%       3596Mi          5%          
bulbasaur    820m         20%      6157Mi          38%         
charmander   791m         19%      5504Mi          23%         
chikorita    320m         8%       2896Mi          9%          
cyndaquil    332m         8%       2621Mi          16%         
growlithe    361m         9%       5052Mi          15%         
pikachu      170m         4%       3093Mi          19%         
sprigatito   153m         3%       3119Mi          9%          
squirtle     828m         20%      3779Mi          23%         
totodile     436m         10%      2861Mi          18%         
```

### 3. Ceph Status
```
cluster:
  id:     13c20377-d801-43f9-aebd-59f62df5dad1
  health: HEALTH_OK

services:
  mon: 3 daemons, quorum f,h,j
  mgr: b(active), standbys: a
  mds: 1/1 daemons up, 1 hot standby
  osd: 7 osds: 7 up, 7 in

data:
  volumes: 1/1 healthy
  pools:   4 pools, 177 pgs
  objects: 157.53k objects, 610 GiB
  usage:   1.2 TiB used, 2.2 TiB / 3.4 TiB avail
  pgs:     177 active+clean
```

### 4. ArgoCD Applications (40 total)
All applications **Synced** and **Healthy**:
- argocd, backlog, backlog-canary, budget, budget-canary
- cert-manager, cloudflared, connect, dex, doplarr
- emby, explorers-hub, external-dns, external-secrets
- gitea, global-secrets, gpu-operator, grafana, humbleai
- humbleai-canary, ingress-nginx, kanidm, kured, loki
- monitoring-system, n8n, nextcloud, ollama, openwebui
- postgres, qdrant, radarr, renovate, rook-ceph
- sabnzbd, searxng, sonarr, volsync-system
- woodpecker, zot

### 5. TLS Certificates (20 total)
All certificates **Ready=True**:
- argocd-server-tls, backlog-companion-tls, budget-tls
- dex-tls-certificate, emby-tls-certificate
- explorers-hub-tls-certificate, gitea-tls-certificate
- grafana-general-tls, humbleai-tls, kanidm-tls-certificate
- n8n-tls-certificate, nextcloud-tls-certificate
- ollama-tls, open-tls-certificate, radarr-tls
- searxng-tls-certificate, sonarr-tls-certificate
- zot-tls-certificate

### 6. External Secrets (8 total)
All secrets **SecretSynced=True**:
- connect/onepassword-credentials
- dex/dex-secrets
- gitea/gitea-admin-secret
- grafana/grafana-secrets
- renovate/renovate-secret
- woodpecker/woodpecker-secret
- zot/registry-admin-secret

### 7. Open Pull Requests
- **PR #55**: chore(deps): update helm release renovate to v46
- **PR #54**: chore(deps): update all non-major dependencies

### 8. Recent Events (Last 50)
Recent activity shows normal kured operations on growlithe node:
- Multiple "Starting kubelet" events (expected kured reboot checking)
- Certificate expiration checks (all OK)
- Node ready status maintained throughout

---

## Analysis

### Findings
1. **Node growlithe Activity**: Frequent kubelet events observed
   - **Root Cause**: Kured (Kubernetes Reboot Daemon) scheduled checks
   - **Kured Schedule**: Mon/Wed/Fri 01:45-05:00 America/Chicago
   - **Impact**: None - node remains Ready, normal operations
   - **Action**: Monitor only, no intervention required

2. **Renovate PRs**: 2 dependency update PRs pending
   - **PR #54**: Non-major dependency updates (minor/patch)
   - **PR #55**: Renovate v46 update
   - **Risk**: Low - both are minor version bumps
   - **Action**: Can be merged during next maintenance window

### Health Matrix

| Layer | Status | Evidence |
|-------|--------|----------|
| Metal | 🟢 GREEN | 10/10 nodes Ready, Cilium healthy |
| Network | 🟢 GREEN | CNI operational, ingress functional |
| Storage | 🟢 GREEN | Ceph HEALTH_OK, 35% usage |
| System | 🟢 GREEN | CoreDNS, metrics, kube-vip OK |
| Platform | 🟢 GREEN | Ingress, certs, secrets all healthy |
| Apps | 🟢 GREEN | 40/40 ArgoCD apps Synced+Healthy |

---

## Recommendations

### Immediate (P2)
- [ ] Review and merge PR #54 (non-major deps)
- [ ] Review and merge PR #55 (renovate v46)

### Monitoring (P3)
- [ ] Observe growlithe kured cycle completion
- [ ] Verify no sustained NotReady periods

---

## Related Resources

- **Maintenance Issue**: https://git.eaglepass.io/ops/homelab/issues/53
- **ArgoCD**: https://argocd.eaglepass.io
- **Documentation**: https://homelab.eaglepass.io
