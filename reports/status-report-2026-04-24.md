# Homelab Recon Status Report (2026-04-24)

Generated: 2026-04-24
Context Pack: reports/context-pack-2026-04-24

## Executive Summary

**Overall Status: 🔴 RED**

Key findings:
- **Apps Layer RED**: `pages` pod in `CreateContainerError` due to stale NFS file handle; 26 leftover `node-debugger` pods in default namespace
- **System Layer YELLOW**: `nfs-client-provisioner` pod in `Unknown` state
- **Network Layer YELLOW**: `homelab-network-check.sh` script failure (unbound variable); DNS resolver (10.0.10.2) times out
- **Storage Layer GREEN**: Ceph HEALTH_OK; recovery in progress (~45m remaining)
- **Platform Layer GREEN**: All certs, ExternalSecrets, and ingress healthy
- **Metal Layer GREEN**: 10/10 nodes Ready

## Evidence Files

- `reports/context-pack-2026-04-24/baseline.txt` — Nodes, top nodes, all pods, non-running pods, ArgoCD apps, recent events
- `reports/context-pack-2026-04-24/recon.txt` — Recon script output (human-readable)
- `reports/context-pack-2026-04-24/recon.json` — Recon script JSON output
- `reports/context-pack-2026-04-24/network-manual.txt` — Manual VLAN, OPNSense, NAS, DNS, internet checks
- `reports/context-pack-2026-04-24/network.json` — Network check script output (script error captured)
- `reports/context-pack-2026-04-24/nas.json` — NAS check script output (RED due to script variable issue)
- `reports/context-pack-2026-04-24/system-core.txt` — kube-system pods, Cilium status
- `reports/context-pack-2026-04-24/ceph.txt` — Rook-Ceph pods, ceph health/status/df/osd tree/pg stat
- `reports/context-pack-2026-04-24/platform.txt` — Ingress, certificates, ExternalSecrets, monitoring, grafana
- `reports/context-pack-2026-04-24/apps-errors.txt` — Error pods and service inventory
- `reports/context-pack-2026-04-24/apps-details.txt` — Detailed describe/logs for error pods
- `reports/context-pack-2026-04-24/kube-system-details.txt` — kube-system and default namespace pod details
- `reports/context-pack-2026-04-24/nfs-provisioner-describe.txt` — NFS provisioner pod describe
- `reports/context-pack-2026-04-24/repo-prs-detailed.json` — Open PR details
- `reports/context-pack-2026-04-24/repo-issues.txt` — Open issues list
- `reports/context-pack-2026-04-24/dependency-dashboard.md` — Dependency Dashboard issue body

## Layer Health Summary

| Layer | Status | Key Findings |
|-------|--------|--------------|
| Metal | 🟢 GREEN | 10/10 nodes Ready, all v1.33.6+k3s1 |
| Network | 🟡 YELLOW | Gateways reachable, OPNSense 443 open, DNS timeout, script failure |
| Storage | 🟢 GREEN | Ceph HEALTH_OK, 7 OSDs up, recovery in progress |
| System | 🟡 YELLOW | nfs-client-provisioner Unknown; Cilium/etc healthy |
| Platform | 🟢 GREEN | Certs, Secrets, Ingress all healthy |
| Apps | 🔴 RED | pages CreateContainerError (stale NFS); 26 node-debugger debris pods |

## Open PRs (as of recon)

| PR | Title | Mergeable |
|----|-------|-----------|
| #83 | chore(deps): update helm release kube-prometheus-stack to v84 | true |
| #81 | chore(deps): update bitnamilegacy/postgresql docker tag to v17 | false |
| #80 | fix(deps): update all non-major dependencies | false |

## Recommendations

1. **P0**: Fix pages pod by resolving stale NFS file handle or deleting pod for recreation
2. **P1**: Clean up 26 node-debugger debris pods and Unknown nfs-client-provisioner pod
3. **P1**: Review and potentially merge PR #83 (kube-prometheus-stack v84)
4. **P2**: Fix homelab-network-check.sh unbound variable
5. **P2**: Investigate DNS timeout on 10.0.10.2
6. **P3**: Update Dependency Dashboard checkboxes after PR resolution

## Next Steps

Run `/homelab-action` to consume the maintenance issue and execute the action items.
