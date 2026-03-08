# Homelab Recon Status Report (2026-03-07)

Generated: 2026-03-07T16:41:49-06:00
Context Pack: reports/context-pack-2026-03-07

## Recon Scope

- Mode: Recon only (no infrastructure changes)
- Canonical order used: Metal -> Network -> Storage -> System -> Platform -> Apps
- Primary evidence captured via scripts plus command snapshots

## Phase 1 Evidence Index

### Access and Tooling

- Cluster/API access: `reports/context-pack-2026-03-07/recon.json`
- Network tool output: `reports/context-pack-2026-03-07/network.json`
- NAS tool output: `reports/context-pack-2026-03-07/nas.json`

### Baseline Health

- Nodes inventory: `reports/context-pack-2026-03-07/nodes-wide.txt`
- Node utilization: `reports/context-pack-2026-03-07/nodes-top.txt`
- Pods inventory: `reports/context-pack-2026-03-07/pods-all-sorted.txt`
- Non-running pods: `reports/context-pack-2026-03-07/pods-nonrunning.txt`
- ArgoCD app status: `reports/context-pack-2026-03-07/argocd-applications.txt`
- ArgoCD non-healthy apps: `reports/context-pack-2026-03-07/argocd-applications-nonhealthy.txt`
- Recent events: `reports/context-pack-2026-03-07/events-all-sorted.txt`

### System/Core

- kube-system pods: `reports/context-pack-2026-03-07/kube-system-pods-wide.txt`
- kube-system non-running: `reports/context-pack-2026-03-07/kube-system-nonrunning.txt`
- kube-system daemonsets: `reports/context-pack-2026-03-07/kube-system-daemonsets.txt`
- cilium daemonset: `reports/context-pack-2026-03-07/kube-system-cilium-daemonset.txt`
- cilium pods: `reports/context-pack-2026-03-07/kube-system-cilium-pods.txt`

### Storage (Rook/Ceph)

- rook-ceph pods: `reports/context-pack-2026-03-07/rook-ceph-pods-wide.txt`
- ceph health: `reports/context-pack-2026-03-07/ceph-health.txt`
- ceph health detail: `reports/context-pack-2026-03-07/ceph-health-detail.txt`
- ceph status: `reports/context-pack-2026-03-07/ceph-status.txt`
- ceph df: `reports/context-pack-2026-03-07/ceph-df.txt`
- ceph osd tree: `reports/context-pack-2026-03-07/ceph-osd-tree.txt`
- ceph pg stat: `reports/context-pack-2026-03-07/ceph-pg-stat.txt`

### Platform

- ingress pods/services/ingresses: `reports/context-pack-2026-03-07/ingress-nginx-pods.txt`, `reports/context-pack-2026-03-07/ingress-nginx-services.txt`, `reports/context-pack-2026-03-07/ingress-all.txt`
- cert resources: `reports/context-pack-2026-03-07/certificates-all.txt`, `reports/context-pack-2026-03-07/certificaterequests-all.txt`, `reports/context-pack-2026-03-07/cert-orders-all.txt`, `reports/context-pack-2026-03-07/cert-challenges-all.txt`
- external secrets: `reports/context-pack-2026-03-07/externalsecrets-all.txt`, `reports/context-pack-2026-03-07/secretstores-all.txt`, `reports/context-pack-2026-03-07/clustersecretstores-all.txt`
- monitoring pods: `reports/context-pack-2026-03-07/monitoring-system-pods.txt`, `reports/context-pack-2026-03-07/grafana-namespace-pods.txt`

### Apps

- app error focus list: `reports/context-pack-2026-03-07/apps-problem-pods.txt`
- all services: `reports/context-pack-2026-03-07/services-all.txt`

### Repo (Gitea)

- open PRs raw: `reports/context-pack-2026-03-07/gitea-open-prs.json`
- open PRs summary: `reports/context-pack-2026-03-07/gitea-open-prs-summary.txt`
- open PRs detailed: `reports/context-pack-2026-03-07/gitea-open-prs-detailed.json`
- open non-maintenance issues: `reports/context-pack-2026-03-07/gitea-open-issues-nonmaintenance-summary.txt`
- dependency dashboard body: `reports/context-pack-2026-03-07/dependency-dashboard.md`
- dependency dashboard unchecked: `reports/context-pack-2026-03-07/dependency-dashboard-unchecked.txt`

## Snapshot Findings

- Metal: GREEN (10/10 nodes Ready)
- Network: GREEN (`overall_status=GREEN`, 0 warnings, 0 errors)
- Storage/NAS: GREEN (`overall_status=GREEN`, 0 warnings, 0 errors)
- Ceph: GREEN (`HEALTH_OK`; 7/7 OSD up/in)
- System: GREEN (no non-running kube-system pods)
- Platform: GREEN (ArgoCD apps all Synced/Healthy)
- Apps: GREEN (no CrashLoopBackOff/Error/ImagePullBackOff/Pending pods)
- Repo maintenance pressure: 4 open Renovate PRs + 5 unchecked dependency dashboard items

## Recon Outcome

- Infrastructure health is currently GREEN across layers.
- Maintenance issue should prioritize dependency governance workflow (PR triage, staged merge/deferral, dashboard hygiene), with full validation gates after each action.
