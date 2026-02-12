# Homelab Recon Status Report (2026-02-12)

Generated: 2026-02-12T15:42:00-06:00
Context Pack: reports/context-pack-2026-02-12

## Overall Status: YELLOW

### Layer Summary

| Layer | Status | Key Findings |
|-------|--------|--------------|
| Metal | YELLOW | 10/10 Ready; arcanine disk 82% used (image GC failing); sprigatito 78.5%, totodile 74.4% |
| Network | RED (script) / GREEN (actual) | VLAN gateways ICMP blocked (by design); all services reachable via TCP; internet GREEN |
| Storage (NAS) | YELLOW (script) / GREEN (actual) | All ports open; SMB shares require auth (expected); NFS exports not visible to script |
| Storage (Ceph) | GREEN | HEALTH_OK; 7/7 OSDs; 36.38% raw used; 177 PGs active+clean |
| System | GREEN | All kube-system pods Running; Cilium healthy; CoreDNS/metrics-server OK |
| Platform | GREEN | All 26 certs Ready; 7/7 ExternalSecrets synced; 41/41 ArgoCD apps Synced+Healthy |
| Apps | GREEN | Zero problem pods (no CrashLoop/Error/Pending/ImagePull) |

### Evidence Files

All evidence saved to `reports/context-pack-2026-02-12/`:

| File | Description |
|------|-------------|
| `recon.json` | Full recon script output (nodes, apps, ceph, pods) |
| `network.json` | Network health check results (RED due to ICMP) |
| `nas.json` | NAS/Unraid health check results (YELLOW) |
| `nodes.txt` | Node list with versions and IPs |
| `node-usage.txt` | Node CPU/memory consumption |
| `node-fs-summary.txt` | Node filesystem usage summary |
| `argocd-apps.txt` | All 41 ArgoCD applications status |
| `argocd-unhealthy.txt` | Unhealthy ArgoCD apps (empty) |
| `kube-system-pods.txt` | kube-system pods |
| `kube-system-problems.txt` | kube-system problem pods (empty) |
| `ceph-health.txt` | Ceph health status (HEALTH_OK) |
| `ceph-status.txt` | Full Ceph cluster status |
| `ceph-health-detail.txt` | Ceph health detail |
| `ceph-df.txt` | Ceph disk usage |
| `ceph-osd-tree.txt` | Ceph OSD tree |
| `ceph-pg-stat.txt` | Ceph PG statistics |
| `rook-ceph-pods.txt` | Rook-Ceph pods |
| `ingress-pods.txt` | Ingress-nginx pods |
| `ingress-svc.txt` | Ingress-nginx services |
| `ingresses.txt` | All ingress resources |
| `certificates.txt` | All certificates (26, all Ready) |
| `certrequests.txt` | Certificate requests |
| `orders.txt` | ACME orders |
| `challenges.txt` | ACME challenges (none) |
| `external-secrets.txt` | ExternalSecret resources |
| `clustersecretstores.txt` | ClusterSecretStore resources |
| `monitoring-pods.txt` | Monitoring system pods |
| `grafana-pods.txt` | Grafana pods |
| `problem-pods.txt` | Problem pods across all namespaces (empty) |
| `services.txt` | All services |
| `recent-events.txt` | Last 200 cluster events |
| `open-prs.json` | Open pull requests (3 PRs) |
| `open-issues.json` | Open issues (maintenance #53, dep dashboard #4) |
| `dependency-dashboard.md` | Dependency Dashboard body |
| `dependency-dashboard-unchecked.txt` | Unchecked dashboard items |
| `growlithe-analysis.txt` | Growlithe kubelet restart loop analysis (NORMAL) |
| `arcanine-analysis.txt` | Arcanine disk pressure analysis |

### Key Findings

#### P1: Metal - arcanine Disk Space Pressure
- **Evidence**: `arcanine-analysis.txt`, `node-fs-summary.txt`
- Filesystem 81.82% used (8.14 GB free)
- `FreeDiskSpaceFailed` event: cannot GC images (0 bytes eligible)
- GPU node with likely large AI/ML container images
- Risk: continued image pulls could trigger eviction threshold (85% default)

#### P2: Metal - sprigatito & totodile Disk Space Caution
- **Evidence**: `node-fs-summary.txt`
- sprigatito: 78.50% used (10.21 GB free) - GPU node
- totodile: 74.36% used (12.79 GB free)
- Not critical yet but trending toward eviction thresholds

#### P2: Network - Script Reports RED (False Positive)
- **Evidence**: `network.json`
- 4 VLAN gateways unreachable via ICMP (VLAN10/20/30/40)
- All critical services reachable via TCP (OPNSense:443, Controller:22, NAS:445)
- VLAN50 (IoT) responds to ICMP (1.77ms, 0% loss)
- Internet connectivity fully GREEN
- Known issue from previous recons: ICMP blocked by design on management VLANs

#### P2: Storage/NAS - Script Reports YELLOW (Expected)
- **Evidence**: `nas.json`
- All ports open (HTTP/HTTPS/SMB/NFS)
- SMB shares not visible without auth (expected for Unraid)
- NFS exports not found by showmount (may require auth or different export config)
- Web interface accessible

#### P2: Repo - 3 Open PRs
- **Evidence**: `open-prs.json`
- PR #54: Non-major dependency updates (27 packages) - 13 days old, mergeable
- PR #61: external-secrets v1 -> v2 (MAJOR) - 5 days old, mergeable
- PR #62: doc2vec-mcp v1 -> v2 (MAJOR) - 2 days old, mergeable

#### P3: Repo - Renovate Missing GitHub Token
- **Evidence**: `dependency-dashboard.md`
- Renovate warns about missing `GITHUB_COM_TOKEN`
- Cannot fetch release notes or look up some dependencies
- Affects PR quality (no release notes embedded)

### Observations

- growlithe kubelet "Starting" events every ~7s are normal K3s cert-monitor behavior, not actual restarts
- All 41 ArgoCD apps are Synced+Healthy with zero drift
- Ceph cluster is fully healthy with comfortable capacity (63.6% free)
- Existing maintenance issue #53 from 2026-01-31 needs to be updated (not duplicated)
