# Homelab Recon Status Report (2026-01-31)

Generated: 2026-01-31T12:39:32-06:00
Context Pack: reports/context-pack-2026-01-31

## Summary
- Cluster Health: GREEN (All nodes Ready)
- Ceph Health: GREEN (HEALTH_OK)
- Network Health: RED (VLAN gateways unreachable via ICMP, though TCP 443 is working)
- Storage Health: YELLOW (NAS share visibility and NFS export issues)
- Repository: 2 open dependency PRs (#54, #55)

## Evidence Files
- ceph-df.txt
- ceph-health.txt
- ceph-osd-tree.txt
- ceph-status.txt
- certificates.txt
- dependency-dashboard.md
- external-secrets.txt
- ingress-pods.txt
- kube-system-ds.txt
- kube-system-pods.txt
- nas.json
- network.json
- open-issues.json
- open-prs.json
- recon.json
- rook-ceph-pods.txt
- troubled-pods.txt
# Homelab Recon Status Report (2026-01-31)

Generated: 2026-01-31T12:46:37-06:00
Context Pack: reports/context-pack-2026-01-31

## Phase 1.0 - Initialize Run

- Report: reports/status-report-2026-01-31.md
- Context dir: reports/context-pack-2026-01-31
- Task tracker: recon-tasks.md

## Phase 1.0.1 - Toolchain Gate

Evidence: reports/context-pack-2026-01-31/toolchain.txt

## Phase 1.2 - Access Validation

Evidence: reports/context-pack-2026-01-31/kubectl-cluster-info.txt
Evidence: reports/context-pack-2026-01-31/kubectl-version.txt
Evidence: reports/context-pack-2026-01-31/ssh-controller.txt
Evidence: reports/context-pack-2026-01-31/gitea-token-check.txt

## Phase 1.3 - Baseline Health Snapshot

Evidence: reports/context-pack-2026-01-31/recon.json
Evidence: reports/context-pack-2026-01-31/recon.json.stderr
Evidence: reports/context-pack-2026-01-31/recon.txt
Evidence: reports/context-pack-2026-01-31/baseline-nodes.txt
Evidence: reports/context-pack-2026-01-31/baseline-pods.txt
Evidence: reports/context-pack-2026-01-31/baseline-argocd-apps.txt
Evidence: reports/context-pack-2026-01-31/baseline-events-tail-200.txt

## Phase 1.4 - Network Evidence

Evidence: reports/context-pack-2026-01-31/network.json
Evidence: reports/context-pack-2026-01-31/network.json.stderr
Evidence: reports/context-pack-2026-01-31/network.exitcode
Evidence: reports/context-pack-2026-01-31/network.txt

## Phase 1.5 - Storage/NAS Evidence

Evidence: reports/context-pack-2026-01-31/nas.json
Evidence: reports/context-pack-2026-01-31/nas.json.stderr
Evidence: reports/context-pack-2026-01-31/nas.exitcode
Evidence: reports/context-pack-2026-01-31/nas.txt

## Phase 1.6 - System/Core Evidence

Evidence: reports/context-pack-2026-01-31/system-core-kube-system.txt

## Phase 1.7 - Ceph Evidence

Evidence: reports/context-pack-2026-01-31/storage-ceph.txt
Evidence: reports/context-pack-2026-01-31/storage-ceph-crash-ls-new.txt
Evidence: reports/context-pack-2026-01-31/storage-ceph-operator-logs.txt

## Phase 1.8 - Platform Evidence

Evidence: reports/context-pack-2026-01-31/platform.txt

## Phase 1.9 - Apps Evidence

Evidence: reports/context-pack-2026-01-31/apps-problem-pods.txt
Evidence: reports/context-pack-2026-01-31/apps-services.txt
Evidence: reports/context-pack-2026-01-31/apps-problem-pod-details/

## Phase 1.10 - Repo Evidence (Gitea)

Evidence: reports/context-pack-2026-01-31/gitea-open-prs.txt
Evidence: reports/context-pack-2026-01-31/gitea-open-prs.json
Evidence: reports/context-pack-2026-01-31/gitea-open-issues-nonmaintenance.txt
Evidence: reports/context-pack-2026-01-31/dependency-dashboard.number
Evidence: reports/context-pack-2026-01-31/dependency-dashboard.md
Evidence: reports/context-pack-2026-01-31/dependency-dashboard-unchecked.txt

## Recon Fixups

Evidence (updated): reports/context-pack-2026-01-31/gitea-open-prs.txt
Evidence (updated): reports/context-pack-2026-01-31/gitea-open-issues-nonmaintenance.txt
Evidence (updated): reports/context-pack-2026-01-31/dependency-dashboard-unchecked.txt
Evidence: reports/context-pack-2026-01-31/network-gateway-tcp-443.txt
Evidence: reports/context-pack-2026-01-31/nas-showmount.txt

## Final Recon Summary (2026-01-31)

- Cluster: GREEN (nodes Ready, apps Synced+Healthy, Ceph HEALTH_OK, no problem pods)
- Network gate: RED from ICMP-only VLAN gateway checks; TCP 443 to all gateways is open (likely false positive)
- NAS gate: YELLOW from SMB listing + legacy export expectations; cluster NFS dependency is /mnt/user/heartlib and export exists
- Repo: 2 open Renovate PRs (#54, #55); Dependency Dashboard #4 also has blocked PR #52 + missing github.com token warning

Key evidence:
- reports/context-pack-2026-01-31/network.json
- reports/context-pack-2026-01-31/network-gateway-tcp-443.txt
- reports/context-pack-2026-01-31/nas.json
- reports/context-pack-2026-01-31/nas-showmount.txt
- reports/context-pack-2026-01-31/storage-nfs-provisioner.txt
- reports/context-pack-2026-01-31/baseline-argocd-apps.txt
- reports/context-pack-2026-01-31/storage-ceph.txt

Maintenance issue: https://git.eaglepass.io/ops/homelab/issues/53

