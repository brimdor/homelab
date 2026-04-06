# Homelab Recon Status Report (2026-04-03)

Generated: 2026-04-03T13:28:36-05:00
Context Pack: reports/context-pack-2026-04-03

## Executive Summary

- Overall status: YELLOW
- Metal, network, NAS, ingress, certificates, external secrets, and core apps are healthy.
- Primary maintenance focus is `rook-ceph`: Ceph is `HEALTH_WARN` and the ArgoCD `rook-ceph` app is `Degraded` due recent mgr module crashes on Ceph `v20.2.0`.
- Secondary maintenance items are existing Woodpecker SQLite lock investigation, two open Renovate PRs (`#80`, `#81`), stale Dependency Dashboard problems, and long-term Ceph disk/capacity work.
- `scribe` is currently `Progressing` on a rollout with RWO PVC multi-attach behavior, but that remediation is being handled in parallel and is excluded from this maintenance prioritization run.

## Layer Snapshot

| Layer | Status | Details |
|-------|--------|---------|
| Metal | GREEN | 10/10 nodes Ready; uniform `v1.33.6+k3s1`; no pressure conditions |
| Network | GREEN | `network.json` reports all VLAN gateways, controller, NAS, and Internet checks GREEN |
| Storage | YELLOW | Ceph `HEALTH_WARN`; 6/6 OSDs up/in; root cause aligns with known Ceph `v20.2.0` mgr bug |
| System | YELLOW | kube-system healthy, but ArgoCD has `rook-ceph` degraded and `scribe` progressing |
| Platform | GREEN | Ingress, cert-manager, certificates, and external secrets healthy |
| Apps | YELLOW | Core apps healthy; `scribe` rollout progressing under separate remediation |

## Key Findings

1. `rook-ceph` remains the highest-priority maintenance item.
   Evidence: `ceph-health.txt`, `ceph-health-detail.txt`, `ceph-status.txt`, `rook-ceph-pods.txt`
   Details: current warnings are recent mgr crashes (`prometheus`, `rook`) after reproducing the known `v20.2.0` mgr/orchestrator bug path.

2. The durable Ceph fix is still pending in GitOps.
   Evidence: `system/rook-ceph/values.yaml`
   Details: the repo is still pinned to `quay.io/ceph/ceph:v20.2.0` and has `rook-ceph-cluster.monitoring.enabled: false` pending a fixed Ceph patch release.

3. There is unresolved storage hardware risk outside the immediate mgr crash.
   Evidence: `system/rook-ceph/values.yaml`
   Details: `bulbasaur` remains excluded from OSD placement due recurring BlueFS stalled-read alerts.

4. Dependency maintenance backlog is active.
   Evidence: `open-prs.json`, `open-issues.json`, `dependency-dashboard.md`
   Details: open PRs `#80` and `#81`; Dependency Dashboard `#4` also reports missing GitHub token/release-note coverage, docker lookup failures, and blocked Nextcloud `v9` recreation.

5. Existing app maintenance work remains.
   Evidence: maintenance issue `#79`, prior findings retained
   Details: Woodpecker intermittent SQLite lock errors still warrant follow-up.

## Evidence Index

### Baseline

- `reports/context-pack-2026-04-03/nodes.txt`
- `reports/context-pack-2026-04-03/top-nodes.txt`
- `reports/context-pack-2026-04-03/pods-all.txt`
- `reports/context-pack-2026-04-03/argocd-apps.txt`
- `reports/context-pack-2026-04-03/events-all.txt`

### Network And NAS

- `reports/context-pack-2026-04-03/network.json`
- `reports/context-pack-2026-04-03/network.txt`
- `reports/context-pack-2026-04-03/nas.json`
- `reports/context-pack-2026-04-03/nas.txt`

### System And Storage

- `reports/context-pack-2026-04-03/kube-system-pods.txt`
- `reports/context-pack-2026-04-03/cilium-ds.txt`
- `reports/context-pack-2026-04-03/cilium-pods.txt`
- `reports/context-pack-2026-04-03/rook-ceph-pods.txt`
- `reports/context-pack-2026-04-03/ceph-health.txt`
- `reports/context-pack-2026-04-03/ceph-health-detail.txt`
- `reports/context-pack-2026-04-03/ceph-status.txt`
- `reports/context-pack-2026-04-03/ceph-df.txt`
- `reports/context-pack-2026-04-03/ceph-osd-tree.txt`
- `reports/context-pack-2026-04-03/ceph-pg-stat.txt`
- `reports/context-pack-2026-04-03/ceph-crash-ls-new.txt`
- `reports/context-pack-2026-04-03/scribe-deployment.yaml`

### Platform And Apps

- `reports/context-pack-2026-04-03/ingress-nginx-pods.txt`
- `reports/context-pack-2026-04-03/ingress-nginx-svc.txt`
- `reports/context-pack-2026-04-03/ingress-all.txt`
- `reports/context-pack-2026-04-03/certificates.txt`
- `reports/context-pack-2026-04-03/certificate-requests.txt`
- `reports/context-pack-2026-04-03/orders.txt`
- `reports/context-pack-2026-04-03/challenges.txt`
- `reports/context-pack-2026-04-03/external-secrets.txt`
- `reports/context-pack-2026-04-03/gitea-pods.txt`
- `reports/context-pack-2026-04-03/grafana-pods.txt`
- `reports/context-pack-2026-04-03/kanidm-pods.txt`

### Repo And Planning

- `reports/context-pack-2026-04-03/open-prs.json`
- `reports/context-pack-2026-04-03/open-issues.json`
- `reports/context-pack-2026-04-03/dependency-dashboard.md`
- `reports/context-pack-2026-04-03/maintenance-issue-check.json`
- `reports/context-pack-2026-04-03/maintenance-issue-79-body.md`

## Maintenance Issue Target

- Existing maintenance issue: `#79`
- URL: `https://git.eaglepass.io/ops/homelab/issues/79`
- Action: update body in place with refreshed evidence, preserved prior work, and new Ceph/Rook remediation priorities.
