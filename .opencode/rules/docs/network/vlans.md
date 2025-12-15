# VLAN Reference

## VLAN Architecture

The network is segmented into VLANs for organization and traffic management. All VLANs can communicate with each other (full inter-VLAN routing enabled).

## VLAN Summary Table

| VLAN ID | Name | Network | Gateway | DHCP Range | Purpose |
|---------|------|---------|---------|------------|---------|
| 1 | Native/Default | `10.0.0.0/24` | `10.0.0.1` | - | Infrastructure only |
| 10 | Management | `10.0.10.0/24` | `10.0.10.1` | `10.0.10.100-254` | Network equipment management |
| 20 | Cluster-Prod | `10.0.20.0/24` | `10.0.20.1` | `10.0.20.100-254` | Kubernetes production cluster |
| 30 | Cluster-Extra | `10.0.30.0/24` | `10.0.30.1` | `10.0.30.100-254` | Raspberry Pi projects |
| 40 | Storage | `10.0.40.0/24` | `10.0.40.1` | `10.0.40.100-254` | NAS and storage traffic |
| 50 | IoT/Wireless | `10.0.50.0/24` | `10.0.50.1` | `10.0.50.100-254` | Wireless AP and IoT devices |

## VLAN Details

### VLAN 1 - Native/Default
- **Network**: `10.0.0.0/24`
- **Gateway**: `10.0.0.1`
- **Purpose**: Infrastructure backbone and switch management access
- **Key Devices**:
    - OPNSense: `10.0.0.1`
    - TPLink Switch management (via Port 1)

### VLAN 10 - Management
- **Network**: `10.0.10.0/24`
- **Gateway**: `10.0.10.1`
- **Purpose**: Network equipment management interfaces
- **Key Devices**:
    - TPLink Switch: `10.0.10.2`
    - TPLink AX5400 AP: `10.0.10.3`

### VLAN 20 - Cluster-Prod
- **Network**: `10.0.20.0/24`
- **Gateway**: `10.0.20.1`
- **Purpose**: Kubernetes production cluster nodes
- **Key Devices**:
    - ash (Controller): `10.0.20.10`
    - K8s Control Plane API: `10.0.20.50`
    - charmander - sprigatito (Workers): `10.0.20.11-20`
- **Switch Ports**: 2-11

### VLAN 30 - Cluster-Extra
- **Network**: `10.0.30.0/24`
- **Gateway**: `10.0.30.1`
- **Purpose**: Raspberry Pi side projects and extra nodes
- **Key Devices**:
    - mario: `10.0.30.10`
    - flareon: `10.0.30.11`
    - jolteon: `10.0.30.12`
    - vaporeon: `10.0.30.13`
    - glaceon: `10.0.30.14`
- **Switch Ports**: 12-18

### VLAN 40 - Storage
- **Network**: `10.0.40.0/24`
- **Gateway**: `10.0.40.1`
- **Purpose**: NAS and storage traffic
- **Key Devices**:
    - UNRAID NAS: `10.0.40.3`
- **Switch Ports**: 19-20 (LAG2 for NAS bonding)

!!! critical "NAS Accessibility"
    The NAS must be accessible from **all VLANs**. All devices on the network need access to storage at `10.0.40.3`.

### VLAN 50 - IoT/Wireless
- **Network**: `10.0.50.0/24`
- **Gateway**: `10.0.50.1`
- **Purpose**: Wireless devices and IoT
- **Key Devices**: Wireless clients via AP
- **Switch Ports**: 21 (IoT), 22 (AP trunk)

## TPLink Switch Port-to-VLAN Mapping

```
TPLink 24-Port Managed Switch
┌──────────────────────────────────────────────────────────────┐
│  Port 1    : VLAN 1  (Native - Switch Management)            │
│  Ports 2-11: VLAN 20 (Cluster-Prod - K8s nodes)              │
│  Ports 12-18: VLAN 30 (Cluster-Extra - Raspberry Pis)        │
│  Ports 19-20: VLAN 40 (Storage - NAS LAG2)                   │
│  Port 21   : VLAN 50 (IoT devices)                           │
│  Port 22   : Trunk   (AP - VLAN 10 Tagged, VLAN 50 Untagged) │
│  Ports 23-24: LAG1   (OPNSense - All VLANs tagged)           │
└──────────────────────────────────────────────────────────────┘
```

## OPNSense Interface Mapping

| OPNSense Interface | VLAN | IP Address | Description |
|--------------------|------|------------|-------------|
| WAN (eth0) | - | DHCP | Internet connection |
| LAGG0 | 1 | `10.0.0.1` | Native LAN (LAG of eth1+eth2) |
| LAGG0.10 | 10 | `10.0.10.1` | Management |
| LAGG0.20 | 20 | `10.0.20.1` | Cluster-Prod |
| LAGG0.30 | 30 | `10.0.30.1` | Cluster-Extra |
| LAGG0.40 | 40 | `10.0.40.1` | Storage |
| LAGG0.50 | 50 | `10.0.50.1` | IoT/Wireless |

## Firewall Rules Summary

All interfaces are configured with "Allow All" rules for full inter-VLAN communication:

- All VLANs can reach all other VLANs
- All VLANs have internet access
- NAS (`10.0.40.3`) is accessible from everywhere
- OPNSense and switch management are accessible from everywhere
