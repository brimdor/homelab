# Network Overview

## Architecture Summary

The Nelson Network (The Geek Network) is a segmented VLAN network designed for a homelab environment running a Kubernetes cluster, NAS storage, and various infrastructure services.

```
                    ┌─────────────────┐
                    │    Internet     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   AT&T Modem    │
                    └────────┬────────┘
                             │ WAN
                    ┌────────▼────────┐
                    │    OPNSense     │
                    │    10.0.0.1     │
                    │ (Firewall/Router)│
                    └────────┬────────┘
                             │ LAG (eth1+eth2)
                    ┌────────▼────────┐
                    │  TPLink Switch  │
                    │    10.0.10.2    │
                    │ (24-Port Managed)│
                    └────────┬────────┘
                             │
        ┌──────────┬─────────┼─────────┬──────────┐
        │          │         │         │          │
   ┌────▼────┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐
   │ K8s     │ │ Extra │ │  NAS  │ │  IoT  │ │  AP   │
   │ Cluster │ │ (RPi) │ │       │ │       │ │       │
   │ VLAN 20 │ │VLAN 30│ │VLAN 40│ │VLAN 50│ │Trunk  │
   └─────────┘ └───────┘ └───────┘ └───────┘ └───────┘
```

## Network Segments (VLANs)

| VLAN ID | Name | Network | Gateway | Purpose |
|---------|------|---------|---------|---------|
| 1 | Native/Default | `10.0.0.0/24` | `10.0.0.1` | Infrastructure only (switch management) |
| 10 | Management | `10.0.10.0/24` | `10.0.10.1` | Network equipment management |
| 20 | Cluster-Prod | `10.0.20.0/24` | `10.0.20.1` | Kubernetes production cluster |
| 30 | Cluster-Extra | `10.0.30.0/24` | `10.0.30.1` | Raspberry Pi projects |
| 40 | Storage | `10.0.40.0/24` | `10.0.40.1` | NAS and storage traffic |
| 50 | IoT/Wireless | `10.0.50.0/24` | `10.0.50.1` | Wireless AP and IoT devices |

## Key Infrastructure Components

### OPNSense Firewall/Router
- **IP**: `10.0.0.1` (gateway for all VLANs)
- **Access**: Web UI at `https://10.0.0.1`
- **Hardware**: HPE ProLiant MicroServer
- **Role**: Inter-VLAN routing, firewall, DHCP, DNS

### TPLink Managed Switch
- **IP**: `10.0.10.2` (VLAN 10 - Management)
- **Access**: Web UI at `http://10.0.10.2`
- **Model**: TL-SG1024DE 24-Port Gigabit
- **Role**: Layer 2 switching with VLAN support

### UNRAID NAS
- **IP**: `10.0.40.3` (VLAN 40 - Storage)
- **Access**: Web UI, SMB, NFS
- **Hardware**: Zimaboard 832
- **Role**: Network storage, Twingate connector host

### Wireless Access Point
- **IP**: `10.0.10.3` (Management on VLAN 10)
- **Model**: TPLink AX5400
- **Role**: Wireless access, broadcasts on VLAN 50

## Inter-VLAN Communication

The network uses "God Mode" firewall rules - all VLANs can communicate with all other VLANs.
This enables:

- All devices can access the NAS (`10.0.40.3`)
- All devices can access the internet
- Kubernetes nodes can communicate across the cluster
- Management devices can access all infrastructure

## Kubernetes Service IPs

- **K8s Service ClusterIPs**: `10.43.0.0/16`
- **Control Plane API**: `https://10.0.20.50:6443`

## DNS

- Internal DNS resolution via OPNSense
- Kubernetes uses `svc.cluster.local` for service discovery
- External FQDNs via Cloudflare (see [External Access](../access/external-access.md))
