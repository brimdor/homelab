# Homelab Recon Status Report (2026-01-31)

Generated: 2026-01-31T10:55:59-06:00
Context Pack: reports/context-pack-2026-01-31

## Overall Health: YELLOW

### Summary
- **Ceph**: HEALTH_WARN (2 OSDs stalled read in BlueFS DB device: osd.2, osd.4)
- **Nodes**: 10/10 Ready
- **Network**: Gateways reachable (Port 80/445/2049)
- **GitOps**: 40 apps healthy
- **Pending Updates**: 2 Renovate PRs (#54, #55)

## Evidence
- Nodes: [nodes.txt](reports/context-pack-2026-01-31/nodes.txt)
- Pods: [pods_all.txt](reports/context-pack-2026-01-31/pods_all.txt)
- Unhealthy Pods: [pods_unhealthy.txt](reports/context-pack-2026-01-31/pods_unhealthy.txt)
- Ceph Status: [ceph_status.txt](reports/context-pack-2026-01-31/ceph_status.txt)
- Ceph Health Detail: [ceph_health_detail.txt](reports/context-pack-2026-01-31/ceph_health_detail.txt)
- PRs: [prs_raw.json](reports/context-pack-2026-01-31/prs_raw.json)
- Network Checks: [port_checks_python.txt](reports/context-pack-2026-01-31/port_checks_python.txt)

## Findings
### Ceph Stalled Reads
OSD.2 (arcanine) and OSD.4 (bulbasaur) are reporting stalled reads in their DB devices. This can lead to performance degradation or I/O hangs.

### Renovate PRs
- #54: Minor/Patch updates
- #55: Major update (v46)
