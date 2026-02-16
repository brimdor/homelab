# Homelab Recon Status Report (2026-02-13)

Generated: 2026-02-13T09:02:33-06:00
Context Pack: reports/context-pack-2026-02-13

## Overall Status: YELLOW

Cluster is operational with one actionable warning: Ceph HEALTH_WARN due to a
prometheus mgr module crash (known Ceph v20.2.0 bug). All nodes Ready, all 40
ArgoCD apps Synced+Healthy, all pods healthy, all certificates valid.

## Cluster Identity

| Component | Value |
|-----------|-------|
| K3s Version | v1.33.6+k3s1 |
| Node Count | 10 (3 control-plane, 7 worker) |
| ArgoCD Apps | 40 Synced+Healthy |
| Ceph Status | HEALTH_WARN (1 mgr module crash) |

## Layer Summary

### Metal: GREEN
- 10/10 nodes Ready, all on v1.33.6+k3s1, Fedora 39, kernel 6.11.9
- Cilium CNI: 10/10 desired/ready (restarts normal after reboot ~7h ago)
- kube-vip: 3/3 on control-plane nodes

### Network: GREEN
- All VLANs reachable, OPNSense accessible, 0% packet loss
- NAS (10.0.40.3): SMB/NFS/HTTP all accessible
- Evidence: `context-pack-2026-02-13/network.json`, `nas.json`

### Storage: YELLOW
- Ceph HEALTH_WARN: prometheus mgr module crashed on mgr.a at 2026-02-13T14:55:07Z
  - Root cause: JSONDecodeError -> TypeError in logging handler (known Ceph v20.2.0 bug)
  - Fix: `ceph crash archive-all`
- OSDs: 7/7 up and in (2 weeks stable)
- Usage: 36.25% raw (1.2 TiB / 3.4 TiB)
- Pools: 4 pools, 177 PGs active+clean
- Monitors: 3 in quorum (f, h, j)
- Evidence: `context-pack-2026-02-13/ceph.txt`

### System: GREEN
- CoreDNS: 1/1 Running
- Metrics Server: 1/1 Running
- kube-vip: 3/3 Running
- ArgoCD: 40/40 apps Synced+Healthy

### Platform: GREEN
- Ingress-nginx: 1/1 Running, LB at 10.0.20.226
- Certificates: 27/27 Ready=True, 0 pending challenges
- External Secrets: 7/7 SecretSynced, ClusterSecretStore Valid+Ready
- Evidence: `context-pack-2026-02-13/platform.txt`

### Apps: GREEN
- No CrashLoopBackOff, Error, ImagePullBackOff, or Pending pods
- Gitea: Running, API authenticated as gitea_admin
- Grafana: 3/3 containers Running
- Evidence: `context-pack-2026-02-13/apps.txt`

## Observations

### Node Activity
- **Growlithe kubelet event spam**: InvalidDiskCapacity warning + Starting kubelet
  every ~7 seconds. Node is Ready and all workloads healthy. Likely transient
  disk reporting issue after reboot (~7h ago).
- Evidence: `context-pack-2026-02-13/events.txt`

### Renovate
- PR #63: "chore(deps): update all non-major dependencies" (mergeable)
  - argo-cd 9.4.1 -> 9.4.2
  - kube-prometheus-stack 81.6.3 -> 81.6.7
  - mariadb 12.1 -> 12.2
  - postgres 18.1 -> 18.2-bookworm
  - renovate 46.10.1 -> 46.11.1
  - supabase/logflare 1.31.0 -> 1.31.2
  - supabase/postgres 17.6.1.083 -> 17.6.1.084
  - supabase/realtime v2.76.4 -> v2.76.5
- Evidence: `context-pack-2026-02-13/open-prs.json`

## Action Items (3)

| ID | Priority | Layer | Summary |
|----|----------|-------|---------|
| A1 | P1 | Storage | Archive Ceph mgr crash to clear HEALTH_WARN |
| A2 | P2 | Metal | Investigate growlithe InvalidDiskCapacity event spam |
| A3 | P2 | Apps | Review and merge PR #63 (non-major dep updates) |

## Evidence Files

All captured in `reports/context-pack-2026-02-13/`:
- `recon.json` - Full cluster recon (nodes, apps, ceph)
- `network.json` - Network health (ALL GREEN)
- `nas.json` - NAS health (ALL GREEN)
- `baseline-health.txt` - Nodes, top, pods, ArgoCD apps
- `kube-system.txt` - kube-system pods, Cilium DaemonSet
- `ceph.txt` - Ceph pods, health, status, df, osd tree, pg stat
- `platform.txt` - Ingress, certs, external secrets, monitoring
- `apps.txt` - Non-running pods (none), services
- `events.txt` - Recent events (growlithe spam, renovate cronjob)
- `open-prs.json` - PR #63 metadata
- `open-issues.json` - Issue #4 (Dependency Dashboard)
- `maintenance-issue-data.yaml` - YAML data for Gitea issue creation
