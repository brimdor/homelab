# Homelab Recon Status Report (2026-03-06)

Generated: 2026-03-06T22:35:00-06:00
Context Pack: reports/context-pack-2026-03-06

## Overall Status: GREEN

All four layers are GREEN. No critical issues found.

## Layer Summary

| Layer | Status | Notes |
|-------|--------|-------|
| Metal | GREEN | 10/10 nodes Ready, all v1.33.6+k3s1, low resource usage |
| Network | GREEN | All VLANs reachable, 0 errors, 0 warnings |
| Storage | GREEN | Ceph HEALTH_OK, 7 OSDs up, 40.3% raw used (1.4 TiB / 3.4 TiB) |
| System | GREEN | All kube-system pods Running |
| Platform | GREEN | 42/42 ArgoCD apps Synced+Healthy, all certs valid, all external secrets synced |
| Apps | GREEN | Zero non-running pods |
| NAS | GREEN | Unraid reachable, all ports open (SMB/NFS/HTTP/HTTPS) |

## Evidence Files

- `context-pack-2026-03-06/recon.json` - Full cluster recon (nodes, pods, apps)
- `context-pack-2026-03-06/network.json` - Network health check results
- `context-pack-2026-03-06/nas.json` - NAS health check results
- `context-pack-2026-03-06/dependency-dashboard.md` - Dependency Dashboard body

## Node Resource Usage

| Node | CPU | CPU% | Memory | Memory% |
|------|-----|------|--------|---------|
| arcanine | 252m | 3% | 6291Mi | 9% |
| bulbasaur | 468m | 11% | 4675Mi | 29% |
| charmander | 799m | 19% | 4396Mi | 18% |
| chikorita | 446m | 11% | 3337Mi | 10% |
| cyndaquil | 463m | 11% | 4772Mi | 30% |
| growlithe | 327m | 8% | 4027Mi | 12% |
| pikachu | 743m | 18% | 4464Mi | 28% |
| sprigatito | 202m | 5% | 5944Mi | 18% |
| squirtle | 748m | 18% | 5926Mi | 37% |
| totodile | 114m | 2% | 1501Mi | 9% |

## Ceph Storage

- Health: HEALTH_OK
- Monitors: 3 (quorum f,h,j)
- MGR: active (a), standby (b)
- MDS: 1/1 up, 1 hot standby
- OSDs: 7 up, 7 in
- Usage: 1.4 TiB / 3.4 TiB (40.3%)
- PGs: 177 active+clean

## Open PRs (4)

| PR | Title | Created | Mergeable | Risk |
|----|-------|---------|-----------|------|
| #67 | fix(deps): update all non-major dependencies | 2026-02-24 | Yes | Medium (multi-component) |
| #68 | chore(deps): update bitnamilegacy/postgresql to v17 | 2026-02-24 | Yes | High (MAJOR - PostgreSQL) |
| #69 | chore(deps): update debian docker tag to v13 | 2026-02-24 | Yes | Low (archived moltbot) |
| #70 | chore(deps): update valkey/valkey to v9 | 2026-02-25 | Yes | Medium (MAJOR - Valkey for Nextcloud) |

## Open Issues (2)

- Issue #71: [Maintenance] 2026-02-28 - Homelab (maintenance label) - UPDATING
- Issue #4: Dependency Dashboard (5 unchecked items)

## Transient Events (non-blocking)

- Grafana readiness probe failed briefly (48m ago, resolved)
- Rook-ceph-mon-f liveness probe timed out once (6m ago, transient)

## Conclusion

Cluster is fully healthy. All layers GREEN. The only pending work is 4 open Renovate PRs for dependency updates. Maintenance issue #71 will be updated with current evidence and action items.
