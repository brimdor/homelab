# Homelab Recon Status Report (2026-02-22)

Generated: 2026-02-22T17:41:45-06:00
Context Pack: reports/context-pack-2026-02-22

## Phase 1.2 Access Validation
- kubectl (controller with repo kubeconfig): reports/context-pack-2026-02-22/phase1.2-kubectl-cluster-info.txt
- kubectl version (fallback from --short if needed): reports/context-pack-2026-02-22/phase1.2-kubectl-version.txt
- ssh controller: reports/context-pack-2026-02-22/phase1.2-ssh-controller.txt
- gitea token validation: reports/context-pack-2026-02-22/phase1.2-gitea-token.txt

## Phase 1.0.1 Toolchain Gate
- toolchain evidence: reports/context-pack-2026-02-22/phase1.0.1-toolchain-gate.txt

## Phase 1.1 Access Establishment
- selected pathway evidence: reports/context-pack-2026-02-22/phase1.1-access-strategy.txt

## Phase 1.3 Baseline Health Snapshot (Manual)
- nodes wide: reports/context-pack-2026-02-22/phase1.3-nodes-wide.txt
- node metrics: reports/context-pack-2026-02-22/phase1.3-nodes-top.txt
- all pods sorted: reports/context-pack-2026-02-22/phase1.3-pods-all-sorted.txt
- non-running pods: reports/context-pack-2026-02-22/phase1.3-pods-nonrunning.txt
- argocd applications: reports/context-pack-2026-02-22/phase1.3-argocd-apps.txt
- argocd non-healthy apps: reports/context-pack-2026-02-22/phase1.3-argocd-apps-nonhealthy.txt
- events (last 200): reports/context-pack-2026-02-22/phase1.3-events-last200.txt
- command exit status: reports/context-pack-2026-02-22/phase1.3-manual-status.txt

## Phase 1.4 Network Evidence
- network script JSON: reports/context-pack-2026-02-22/network.json
- network script stderr: reports/context-pack-2026-02-22/phase1.4-network-stderr.txt
- network script status: reports/context-pack-2026-02-22/phase1.4-network-status.txt

## Phase 1.5 Storage/NAS Evidence
- nas script JSON: reports/context-pack-2026-02-22/nas.json
- nas script stderr: reports/context-pack-2026-02-22/phase1.5-nas-stderr.txt
- nas script status: reports/context-pack-2026-02-22/phase1.5-nas-status.txt

## Phase 1.6 System/Core Evidence
- kube-system pods: reports/context-pack-2026-02-22/phase1.6-kube-system-pods-wide.txt
- kube-system non-running: reports/context-pack-2026-02-22/phase1.6-kube-system-nonrunning.txt
- cilium daemonsets: reports/context-pack-2026-02-22/phase1.6-cilium-daemonsets.txt
- cilium pods: reports/context-pack-2026-02-22/phase1.6-cilium-pods.txt
- command exit status: reports/context-pack-2026-02-22/phase1.6-system-status.txt

## Phase 1.7 Ceph Storage Evidence
- rook-ceph pods: reports/context-pack-2026-02-22/phase1.7-rook-ceph-pods-wide.txt
- ceph health: reports/context-pack-2026-02-22/phase1.7-ceph-health.txt
- ceph status: reports/context-pack-2026-02-22/phase1.7-ceph-status.txt
- ceph health detail: reports/context-pack-2026-02-22/phase1.7-ceph-health-detail.txt
- ceph df: reports/context-pack-2026-02-22/phase1.7-ceph-df.txt
- ceph osd tree: reports/context-pack-2026-02-22/phase1.7-ceph-osd-tree.txt
- ceph pg stat: reports/context-pack-2026-02-22/phase1.7-ceph-pg-stat.txt
- ceph crash ls-new: reports/context-pack-2026-02-22/phase1.7-ceph-crash-ls-new.txt
- rook-ceph operator logs: reports/context-pack-2026-02-22/phase1.7-rook-ceph-operator-logs.txt
- command exit status: reports/context-pack-2026-02-22/phase1.7-ceph-status-codes.txt

## Phase 1.8 Platform Evidence
- ingress pods: reports/context-pack-2026-02-22/phase1.8-ingress-pods.txt
- ingress services: reports/context-pack-2026-02-22/phase1.8-ingress-services.txt
- ingress inventory: reports/context-pack-2026-02-22/phase1.8-ingress-all.txt
- certificates: reports/context-pack-2026-02-22/phase1.8-certificates.txt
- certificate requests: reports/context-pack-2026-02-22/phase1.8-certificaterequests.txt
- cert orders: reports/context-pack-2026-02-22/phase1.8-orders.txt
- cert challenges: reports/context-pack-2026-02-22/phase1.8-challenges.txt
- externalsecrets: reports/context-pack-2026-02-22/phase1.8-externalsecrets.txt
- secretstores: reports/context-pack-2026-02-22/phase1.8-secretstores.txt
- clustersecretstores: reports/context-pack-2026-02-22/phase1.8-clustersecretstores.txt
- monitoring-system pods: reports/context-pack-2026-02-22/phase1.8-monitoring-system-pods.txt
- grafana pods: reports/context-pack-2026-02-22/phase1.8-grafana-pods.txt
- command exit status: reports/context-pack-2026-02-22/phase1.8-platform-status.txt

## Phase 1.9 Apps Evidence
- problem pods inventory: reports/context-pack-2026-02-22/phase1.9-problem-pods.txt
- service inventory: reports/context-pack-2026-02-22/phase1.9-services-all.txt
- command exit status: reports/context-pack-2026-02-22/phase1.9-apps-status.txt

## Phase 1.10 Repo Evidence
- open PR list: reports/context-pack-2026-02-22/phase1.10-open-prs.txt
- open issues (excluding maintenance): reports/context-pack-2026-02-22/phase1.10-open-issues-non-maintenance.txt
- open PR details JSON: reports/context-pack-2026-02-22/phase1.10-open-prs-detailed.json
- dependency dashboard number: reports/context-pack-2026-02-22/phase1.10-dependency-dashboard-number.txt
- dependency dashboard body: reports/context-pack-2026-02-22/dependency-dashboard.md
- dependency dashboard unchecked items: reports/context-pack-2026-02-22/dependency-dashboard-unchecked.txt
- command status: reports/context-pack-2026-02-22/phase1.10-repo-status.txt

## Phase 1.0 Initialization
- init status: reports/context-pack-2026-02-22/phase1.0-init-status.txt
- recon task tracker: recon-tasks.md

## Phase 4 Validation Gate Snapshot
- nodes gate: reports/context-pack-2026-02-22/phase4-gate-nodes.txt
- kube-system gate: reports/context-pack-2026-02-22/phase4-gate-kube-system.txt
- argocd gate: reports/context-pack-2026-02-22/phase4-gate-argocd.txt
- ceph health gate: reports/context-pack-2026-02-22/phase4-gate-ceph-health.txt
- all pods gate: reports/context-pack-2026-02-22/phase4-gate-all-pods.txt
- network gate JSON: reports/context-pack-2026-02-22/network-gate.json
- nas gate JSON: reports/context-pack-2026-02-22/nas-gate.json
- gate exit status: reports/context-pack-2026-02-22/phase4-validation-gate.status

## Phase 5 Maintenance Issue Update
- existing issue check: reports/context-pack-2026-02-22/phase5.2-check-existing-maintenance.json
- maintenance YAML input: reports/context-pack-2026-02-22/maintenance-data.yaml
- rendered preview: reports/context-pack-2026-02-22/phase5-maintenance-issue-preview.md
- update result: reports/context-pack-2026-02-22/phase5.3-maintenance-issue-update.json
- update stderr: reports/context-pack-2026-02-22/phase5.3-maintenance-issue-update.stderr
- update status: reports/context-pack-2026-02-22/phase5.3-maintenance-issue-update.status
- title normalization result: reports/context-pack-2026-02-22/phase5.3-maintenance-issue-retitle.json

## Additional Diagnostic Evidence
- argocd emby app YAML: reports/context-pack-2026-02-22/phase1.3-argocd-app-emby.yaml
- argocd rook-ceph app YAML: reports/context-pack-2026-02-22/phase1.3-argocd-app-rook-ceph.yaml
- argocd emby app JSON: reports/context-pack-2026-02-22/phase1.3-argocd-app-emby.json
- argocd rook-ceph app JSON: reports/context-pack-2026-02-22/phase1.3-argocd-app-rook-ceph.json
- emby runtime deployment evidence: reports/context-pack-2026-02-22/phase1.9-emby-deployment.yaml
- emby runtime pod evidence: reports/context-pack-2026-02-22/phase1.9-emby-pods.txt
- PR analysis summary: reports/context-pack-2026-02-22/phase1.10-pr-analysis.txt
- existing maintenance issue body snapshot: reports/context-pack-2026-02-22/phase5.3-existing-maintenance-issue-64-body.md

## Phase 6 Self-Audit
- audit output: reports/context-pack-2026-02-22/phase6-self-audit.txt
- post-update issue payload: reports/context-pack-2026-02-22/phase6-post-update-issue-64.json
- post-update issue body: reports/context-pack-2026-02-22/phase6-post-update-issue-64-body.md

## Phase 7 Remediation
- remediation status: not required after final audit pass (OVERALL: PASS in phase6-self-audit.txt)

## Synthesis Summary
- overall status: RED (Ceph HEALTH_ERR + ArgoCD drift + NAS YELLOW)
- critical finding: Ceph mgr prometheus module crash loop with 4 recent crashes keeps storage layer non-GREEN
- high finding: emby ArgoCD sync error due invalid Deployment strategy (rollingUpdate with Recreate)
- medium finding: NAS script YELLOW from web endpoint behavior despite open SMB/NFS/HTTP/HTTPS ports
- repo findings: PR #63 and PR #65 open and mergeable; Dependency Dashboard #4 has 4 unchecked items

## Phase 8 Handoff
- maintenance issue URL: https://git.eaglepass.io/ops/homelab/issues/64
- handoff status: ready for `/homelab-action` consumption (recon-only workflow complete)
- completion criteria checklist: reports/context-pack-2026-02-22/phase8-completion-criteria.txt
