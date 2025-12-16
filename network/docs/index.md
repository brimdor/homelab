# Nelson Network Documentation

Welcome to the Nelson Network (The Geek Network) documentation. This is the central hub for all network, Kubernetes cluster, and infrastructure documentation.

## Quick Access

| Resource | IP Address | Access Method |
|----------|------------|---------------|
| OPNSense Firewall | `10.0.0.1` | Web UI: `https://10.0.0.1` |
| TPLink Switch | `10.0.10.2` | Web UI: `http://10.0.10.2` |
| NAS (UNRAID) | `10.0.40.3` | Web UI / SMB / NFS |
| K8s Controller (ash) | `10.0.20.10` | `ssh brimdor@10.0.20.10` |
| K8s Control Plane API | `10.0.20.50` | `https://10.0.20.50:6443` |

## Documentation Sections

### Network
- [Network Overview](network/overview.md) - High-level network architecture
- [VLAN Reference](network/vlans.md) - VLAN structure and IP assignments
- [Device Inventory](network/devices.md) - Complete list of all network devices

### Kubernetes
- [Cluster Overview](kubernetes/cluster.md) - K8s cluster architecture and nodes
- [Applications](kubernetes/applications.md) - Deployed applications and access

### Access
- [Agent Access Guide](access/agent-access.md) - How to connect to network resources
- [External Access](access/external-access.md) - Cloudflare tunnel and external FQDNs

### Network Upgrade (Reference)
- [Upgrade Documentation](network/upgrade/index.md) - VLAN migration guide (historical reference)

## Critical Information

!!! warning "NAS Connectivity"
    The NAS at `10.0.40.3` is a critical component. It runs Twingate connectors for remote access.
    **Connectivity to the NAS must be preserved at all times.**

!!! info "Source of Truth"
    - **Cluster Configuration**: `~/Documents/Github/homelab`
    - **Network Configuration**: This repository (`nelson_network`)
