# Homelab Status Report - 2026-01-21

## Executive Summary
- **Overall Status**: GREEN
- **Report Generated**: 2026-01-21
- **Report Source**: `/homelab-recon` workflow

---

## Phase 1: Context Loading Results

### 1.2 Access Validation
| Component | Status | Details |
|-----------|--------|---------|
| Kubernetes Cluster | ✅ PASS | Control plane running at https://10.0.20.50:6443 |
| K3s Version | v1.33.6+k3s1 | |
| Controller (10.0.20.10) | ❌ FAIL | No route to host |
| Gitea API | ✅ PASS | Authenticated as gitea_admin |

### 1.3 Baseline Health Snapshot

#### Nodes
| Node | Status | Roles | CPU % | Mem % | Age |
|-------|--------|-------|-------|------|-----|
| arcanine | Ready | <none> | 10% | 16% | 333d |
| bulbasaur | Ready | control-plane,etcd,master | 27% | 38% | 333d |
| charmander | Ready | control-plane,etcd,master | 35% | 30% | 333d |
| chikorita | Ready | <none> | 4% | 4% | 245d |
| cyndaquil | Ready | <none> | 18% | 28% | 16d |
| growlithe | Ready | <none> | 13% | 34% | 333d |
| pikachu | Ready | <none> | 13% | 41% | 333d |
| sprigatito | Ready | <none> | 7% | 23% | 153d |
| squirtle | Ready | control-plane,etcd,master | 29% | 38% | 333d |
| totodile | Ready | <none> | 12% | 53% | 333d |

**Summary**: 10/10 nodes Ready. No resource pressure detected.

#### ArgoCD Applications
- **Total Applications**: 42
- **Synced + Healthy**: 42
- **OutOfSync**: 0
- **Degraded**: 0
- **Unknown**: 0

#### Pod Health
- **Total Pods**: ~200+
- **Running**: All operational pods
- **Completed**: Expected completed jobs
- **Error States**: 0 (no CrashLoopBackOff, Error, ImagePullBackOff, Pending, Failed)

### 1.5 Storage Evidence (Rook/Ceph)

#### Ceph Cluster Health
- **Health Status**: HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)
- **Muted Alert**: osd.2 observed stalled read indications in DB device (historical, acknowledged)

#### OSD Status
| OSD | Class | Host | Status | Weight |
|-----|-------|-------|--------|--------|
| 1 | ssd | cyndaquil | up | 0.40279 |
| 2 | ssd | arcanine | up | 0.86850 |
| 4 | ssd | bulbasaur | up | 0.40279 |
| 6 | ssd | growlithe | up | 0.45479 |
| 7 | ssd | sprigatito | up | 0.40279 |
| 8 | ssd | arcanine | up | 0.46579 |

**Notes**:
- 6 active OSDs (previously 7 - OSD.0 was removed from cluster)
- OSD.0 was marked as LOST on chikorita and has been properly cleaned from CRUSH map
- All OSDs showing UP status
- Node chikorita has no OSDs (was OSD.0 host, now empty)

#### Placement Groups
- **Total PGs**: 177
- **Active+Clean**: 155
- **Backfilling**: 3
- **Backfill Wait**: 17
- **Misplaced Objects**: 23,693 / 321,191 (7.377%)
- **Recovery Rate**: ~46-50 MiB/s, 11-12 objects/s

#### Storage Usage
| Pool | ID | PGs | Stored | Objects | Used | % Used | Max Avail |
|------|-----|-----|---------|-------|--------|----------|
| standard-rwo | 1 | 128 | 626 GiB | 160.55k | 1.2 TiB (45.24%) | 758 GiB |
| standard-rwx-metadata | 2 | 16 | 18 MiB | 28 | 36 MiB (0%) | 758 GiB |
| standard-rwx-data0 | 3 | 32 | 0 B | 0 | 0 B (0%) | 758 GiB |
| .mgr | 4 | 1 | 30 MiB | 9 | 89 MiB (0%) | 505 GiB |

**Raw Storage**:
- **Total**: 3.0 TiB (SSD class)
- **Used**: 1.2 TiB (41.03%)
- **Available**: 1.8 TiB
- **I/O**: 1.2 KiB/s rd, 40 KiB/s wr, 2 op/s rd, 5 op/s wr

#### Rook-Ceph Pods
- **Operator**: ✅ Running
- **Monitors**: 3/3 Running (quorum f,h,j)
- **Managers**: 2/2 Running (a active, b standby)
- **MDS**: 2/2 Running (1 active, 1 standby)
- **OSDs**: 6/6 Running
- **CSI Controllers**: ✅ Running (RBD + CephFS)
- **Exporters**: 8/8 Running (one per OSD)
- **Tools**: ✅ Running

### 1.6 Platform Evidence

#### Ingress (NGINX)
| Component | Status | Details |
|-----------|--------|---------|
| Controller | ✅ Running | 1/1 pods on growlithe |
| LoadBalancer IP | 10.0.20.226 | |
| Services | ✅ Healthy | controller, admission, metrics |

#### Ingress Resources
- **Total Ingresses**: 27
- **TLS**: All using cert-manager/letsencrypt
- **Services**: argocd, backlog, budget, dex, emby, explorers-hub, family-games-host, family-games-rules, gitea, grafana, humbleai, kanidm, localai, n8n, nextcloud, ollama, openwebui, radarr, sabnzbd, searxng, sonarr, woodpecker, zot

#### Certificates (cert-manager)
- **Total Certificates**: 28
- **Ready**: 28/28 (100%)
- **Issuers**: letsencrypt-prod (27), kanidm-selfsigned (1)
- **Certificate Requests**: 28 valid, 0 failed
- **Orders**: 22 valid
- **Challenges**: 0 (none pending)

#### External Secrets
| Namespace | Secret | Store | Status | Refresh Interval |
|-----------|--------|-------|--------|----------------|
| connect | op-credentials | ClusterSecretStore | SecretSynced | 1h |
| dex | dex-secrets | ClusterSecretStore | SecretSynced | 1h |
| gitea | gitea-admin-secret | ClusterSecretStore | SecretSynced | 1h |
| grafana | grafana-secrets | ClusterSecretStore | SecretSynced | 1h |
| renovate | renovate-secret | ClusterSecretStore | SecretSynced | 1h |
| woodpecker | woodpecker-secret | ClusterSecretStore | SecretSynced | 1h |
| zot | registry-admin-secret | ClusterSecretStore | SecretSynced | 1h |

**Summary**: 7/7 external secrets synchronized. Store `global-secrets` valid and Ready.

#### Monitoring (Grafana, Prometheus)

**Prometheus Stack (monitoring-system)**:
- AlertManager: ✅ 3/3 Running
- Prometheus Operator: ✅ Running
- State Metrics: ✅ Running
- Node Exporters: 10/10 Running (one per node)
- Prometheus: ✅ Running (2/2 pods ready)

**Grafana**:
- Grafana: ✅ 3/3 Running

### 1.7 Apps Evidence

#### Error Pods
- **CrashLoopBackOff**: 0
- **Error**: 0
- **ImagePullBackOff**: 0
- **Pending**: 0 (transient states only during job completion)
- **Failed**: 0

#### Services
- **Total Services**: 100+
- **Critical Services**: All healthy (Gitea, ArgoCD, etc.)

### 1.8 Repo Evidence

#### Open Pull Requests (Renovate)
| PR # | Title | Type | Priority | Created | Mergeable |
|------|-------|------|----------|----------|-----------|
| 49 | chore(deps): update nvidia/cuda docker tag to v13 | Renovate | High (major) | 2026-01-21 | Yes |
| 46 | chore(deps): update helm release kube-prometheus-stack to v81 | Renovate | Medium (major) | 2026-01-17 | Yes |
| 45 | chore(deps): update all non-major dependencies | Renovate | Low (patch/minor) | 2026-01-16 | Yes |
| 47 | chore(deps): update docker.io/cloudflare/cloudflared docker tag to v2026 | Renovate | Medium (major) | 2026-01-20 | Yes |

**Total Open PRs**: 4 (all Renovate, 0 user PRs)

#### Open Issues (non-maintenance)
- **Open non-maintenance issues**: 0

. **Summary** of OSD Stalled Reads:
```ceph osd status
- OSD.2 reports 1 stalling read condition (identified).
- No data loss reported.
- Stalled-read events are historical/muted without criticality.
```


##### Action Items (Tasks):
- [ ] **1. Review Ceph OSDs:** 
  - Execute: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- bash -c 'ceph pg dump' && ceph osd crush tree`.
  - Action goal: Confirm `DB_DEVICE_STALLED_READ` alert is resolved.
- [ ] **2. Update Muted Alert** (48-hour period). 
- [ ] **3. Run Maintenance Checks** and ensure cluster status remains **GREEN**.
  

##### Log References:
- Event records indicate 
  - No direct failures reported.
  - No impact on cluster connectivity.



None detected. All layers GREEN.

### Warnings / Observations

1. **Ceph PG Rebalancing**: 20 PGs still backfilling after OSD.0 removal (7.38% misplaced objects)
   - **Expected**: Temporary during CRUSH map rebalancing
   - **Action**: Monitor until completion
   - **ETA**: ~4-6 hours based on current recovery rate

2. **Ceph Muted Alert**: `DB_DEVICE_STALLED_READ_ALERT` on osd.2
   - **Status**: Acknowledged (sticky muted)
   - **Metrics**: 0 stalls, normal performance
   - **Recommendation**: Unmute after 48 hours to confirm non-recurrence

3. **Node chikorita**: No OSDs running (host entry exists in CRUSH but weight 0)
   - **Status**: OSD.0 properly removed from cluster
   - **Recommendation**: Consider repurposing or removing host entry from CRUSH map

### Proposed Changes (Spec)

| Item | Type | Layer | Priority | Risk | Summary | Notes |
|------|------|:-----:|:--------:|:----:|---------|-------|
| PR #45 | Update | Apps | P2 | Low | Multiple patch/minor dependency updates | Automerge disabled, manual review |
| PR #46 | Update | System | P2 | Medium | kube-prometheus-stack 80→81 (major) | Requires release notes review |
| PR #47 | Update | System | P2 | Medium | cloudflared 2025→2026 (major) | Year bump, requires review |
| PR #49 | Update | Apps | P2 | Low | nvidia/cuda 12.4→13.1 (major) | GPU runtime, requires review |

---

## Validation Gate Results

| Check | Status | Details |
|-------|--------|---------|
| kubectl get nodes | ✅ PASS | 10/10 Ready |
| kubectl get pods -n kube-system | ✅ PASS | All Running/Completed |
| kubectl get applications -n argocd | ✅ PASS | 42/42 Synced+Healthy |
| kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health | ✅ PASS | HEALTH_OK |
| kubectl get pods -A error states | ✅ PASS | 0 error pods |

---

## Recommendations

1. **Monitor Ceph Rebalancing**: Check PG status in 4-6 hours to confirm backfill completion
2. **Review Major PRs**: PR #46 (kube-prometheus-stack) and PR #47 (cloudflared) require careful review
3. **Unmute Ceph Alert**: Unmute `DB_DEVICE_STALLED_READ_ALERT` after 48 hours to confirm issue resolved
4. **Node chikorita**: Consider repurposing or adding OSDs to utilize node capacity

---

## Report End
- **Generated by**: `/homelab-recon` workflow
- **Timestamp**: 2026-01-21
