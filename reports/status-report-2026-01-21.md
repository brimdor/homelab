# Homelab Status Report - 2026-01-21

## Cluster Identity
- K3s version: v1.33.6+k3s1
- Node count: 10 (3 control-plane, 7 worker)
- ArgoCD apps: 39 total (37 Synced+Healthy, 2 Degraded)
- Ceph: HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)

## Current Health Evidence

### Nodes
```
NAME         STATUS   ROLES                       AGE    VERSION
arcanine     Ready    <none>                      333d   v1.33.6+k3s1
bulbasaur    Ready    control-plane,etcd,master   333d   v1.33.6+k3s1
charmander   Ready    control-plane,etcd,master   333d   v1.33.6+k3s1
chikorita    Ready    <none>                      245d   v1.33.6+k3s1
cyndaquil    Ready    <none>                      16d    v1.33.6+k3s1
growlithe    Ready    <none>                      333d   v1.33.6+k3s1
pikachu      Ready    <none>                      333d   v1.33.6+k3s1
sprigatito   Ready    <none>                      153d   v1.33.6+k3s1
squirtle     Ready    control-plane,etcd,master   333d   v1.33.6+k3s1
totodile     Ready    <none>                      333d   v1.33.6+k3s1
```

### Non-Running Pods
| Namespace | Pod | Status | Age | Issue |
|-----------|------|--------|-------|
| grafana | grafana-769d5c5fb5-6cvpm | ImageInspectError | 23m | containerd-stargz-grpc.sock connection refused on chikorita |
| heartlib | heartlib-7444579677-wd4hw | CreateContainerError | 17h | stale NFS file handle on arcanine |
| kube-system | nfs-client-provisioner-nfs-subdir-external-provisioner-854hlqsv | ImageInspectError | 14h | containerd-stargz-grpc.sock connection refused on chikorita |

### ArgoCD Non-Healthy Apps
| App | Sync Status | Health Status | Notes |
|------|-------------|---------------|--------|
| grafana | Synced | Degraded | 1/2 pods running (ImageInspectError) |
| heartlib | Synced | Degraded | 0/1 pods running (NFS stale handle) |

### Ceph Health
```
HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)

  services:
    mon: 3 daemons, quorum f,h,j (age 19h)
    mgr: a(active, since 5d), standbys: b
    mds: 1/1 daemons up, 1 hot standby
    osd: 7 osds: 6 up (since 19h), 6 in (since 20h)

  data:
    volumes: 1/1 healthy
    pools:   4 pools, 177 pgs
    objects: 160.59k objects, 621 GiB
    usage:   1.2 TiB used, 1.8 TiB / 3.0 TiB avail
    pgs:     177 active+clean
```

**OSD Status:**
- OSD.0 on chikorita: down (host chikorita)
- All other OSDs (1,2,4,6,7,8): up

**Muted Warning:**
- DB_DEVICE_STALLED_READ_ALERT: osd.2 experiencing stalled read in DB device

### Certificates
- Total: 26
- Ready: 26
- All certificates valid and operational

### External Secrets
| Namespace | Name | Store | Status |
|-----------|------|--------|--------|
| connect | op-credentials | global-secrets | SecretSynced |
| dex | dex-secrets | global-secrets | SecretSynced |
| gitea | gitea-admin-secret | global-secrets | SecretSynced |
| grafana | grafana-secrets | global-secrets | SecretSynced |
| renovate | renovate-secret | global-secrets | SecretSynced |
| woodpecker | woodpecker-secret | global-secrets | SecretSynced |
| zot | registry-admin-secret | global-secrets | SecretSynced |

### Ingress
- Controller: 1 pod running on growlithe
- LoadBalancer: 10.0.20.226
- 27 ingress resources configured across namespaces

### Platform/Infrastructure
| Component | Namespace | Status |
|------------|-----------|--------|
| Cilium | kube-system | 10/10 daemonset pods Running |
| CoreDNS | kube-system | 1/1 pods Running |
| Kube-VIP | kube-system | 3/3 pods Running |
| Metrics Server | kube-system | 1/1 pods Running |
| Hubble | kube-system | 2/2 pods Running |
| Monitoring System | monitoring-system | All pods Running |
| Cert Manager | cert-manager | All pods Running |
| External DNS | external-dns | 1/1 pods Running |

### Ceph Details
- Cluster usage: 1.2 TiB / 3.0 TiB (40.54%)
- 177 PGs all active+clean
- IO: 16 KiB/s rd, 46 KiB/s wr

## Failing Pod Details

### grafana-769d5c5fb5-6cvpm (grafana namespace)
**Error:** ImageInspectError
**Age:** 23m
**Node:** chikorita (10.0.20.15)
**Containers affected:**
- grafana-sc-dashboard (quay.io/kiwigrid/k8s-sidecar:2.2.1)
- grafana-sc-datasources (quay.io/kiwigrid/k8s-sidecar:2.2.1)
- grafana (docker.io/grafana/grafana:12.3.1)

**Root Cause:**
```
Failed to inspect image "": rpc error: code = Unavailable desc = connection error:
desc = "transport: Error while dialing: dial unix /run/containerd-stargz-grpc/containerd-stargz-grpc.sock: connect: connection refused"
```

**Note:** A healthy grafana pod (grafana-7d664c6f5-zmfv9) is running on bulbasaur.

### heartlib-7444579677-wd4hw (heartlib namespace)
**Error:** CreateContainerError
**Age:** 17h
**Node:** arcanine (10.0.20.19)

**Root Cause:**
```
Error: failed to generate container spec: failed to stat
"/var/lib/kubelet/pods/5d798cb3-4965-44a8-b5ca-df493ac5b638/volumes/kubernetes.io~nfs/models":
stat /var/lib/kubelet/pods/.../volumes/kubernetes.io~nfs/models: stale NFS file handle
```

**NFS Details:**
- Server: 10.0.40.3
- Paths: /mnt/user/heartlib/models, /mnt/user/heartlib/output

### nfs-client-provisioner-nfs-subdir-external-provisioner-854hlqsv (kube-system namespace)
**Error:** ImageInspectError
**Age:** 14h
**Node:** chikorita (10.0.20.15)

**Root Cause:** Same as grafana - containerd-stargz-grpc.sock connection refused

## Repo Inventory

### Open Pull Requests

#### PR #45: chore(deps): update all non-major dependencies
**Type:** Renovate (patch/minor)
**Created:** 2026-01-16 15:03:39Z
**Updated:** 2026-01-20 15:02:01Z
**State:** Open

**Updates:**
| Package | Type | Change |
|----------|------|--------|
| app-template | patch | 4.6.0 → 4.6.2 |
| ghcr.io/gethomepage/homepage | minor | v1.8.0 → v1.9.0 |
| ollama | minor | 1.37.0 → 1.38.0 |
| renovate | minor | 45.74.12 → 45.78.6 |
| snapshot-controller | patch | 5.0.0 → 5.0.2 |
| supabase/postgres | patch | 17.6.1.071 → 17.6.1.072 |
| supabase/realtime | minor | v2.70.0 → v2.71.2 |

**Risk:** Low (patch/minor updates)
**Automerge:** Disabled

#### PR #46: chore(deps): update helm release kube-prometheus-stack to v81
**Type:** Renovate (MAJOR)
**Created:** 2026-01-17 15:02:41Z
**Updated:** 2026-01-20 20:23:04Z
**State:** Open

**Updates:**
| Package | Type | Change |
|----------|------|--------|
| kube-prometheus-stack | major | 80.14.4 → 81.1.0 |

**Risk:** Medium (major version)
**Automerge:** Disabled

#### PR #47: chore(deps): update docker.io/cloudflare/cloudflared docker tag to v2026
**Type:** Renovate (MAJOR - year bump)
**Created:** 2026-01-20 15:02:05Z
**Updated:** 2026-01-20 20:23:04Z
**State:** Open

**Updates:**
| Package | Type | Change |
|----------|------|--------|
| docker.io/cloudflare/cloudflared | major | 2025.11.1 → 2026.1.1 |

**Risk:** Medium (year bump major)
**Automerge:** Disabled

### Open Non-Maintenance Issues

#### Issue #4: Dependency Dashboard
**Type:** Renovate tracking
**Created:** 2025-12-09 15:01:32Z
**Updated:** 2026-01-20 15:02:12Z
**Purpose:** Tracks all dependency updates via Renovate bot

**Repository Problems:**
- WARN: GitHub token is required for some dependencies
- WARN: No github.com token has been configured. Skipping release notes retrieval

**Open Updates (via PRs):**
- PR #45: all non-major dependencies
- PR #46: kube-prometheus-stack v81
- PR #47: cloudflared v2026

## Events Summary

### Recent Critical Events
1. **ImageInspectError (chikorita)** - 23m ago (grafana), 14h ago (nfs-provisioner)
   - Cause: containerd-stargz-grpc service not running
   - Affects: Any new pods on chikorita

2. **CreateContainerError (heartlib)** - 17h ago (continuous restarts)
   - Cause: stale NFS file handle on arcanine
   - Affects: heartlib pod startup

### Normal Events
- Multiple CertificateExpirationOK events for all nodes
- Repeated kubelet starting events (normal for cluster operation)

## Summary

### Overall Status: YELLOW

### Issues Requiring Attention
1. **P0**: Fix containerd-stargz-grpc on chikorita (blocks grafana, nfs provisioner)
2. **P0**: Resolve NFS stale file handle on arcanine (blocks heartlib)
3. **P2**: Review and merge dependency updates (PRs #45, #46, #47)

### Healthy Components
- All 10 nodes Ready
- Ceph HEALTH_OK with 177 active+clean PGs
- 37/39 ArgoCD apps Synced+Healthy
- All 26 certificates Ready
- All 7 external secrets synced
- Core infrastructure (Cilium, DNS, ingress, monitoring) operational

### Previous Maintenance
- Issue #44: [Maintenance] 2026-01-20 - Homelab (open, in progress)
  - Contains tasks from previous recon
  - Some issues resolved (evicted pods, emby sync)
  - Some issues persist (chikorita cordoned, heartlib)
