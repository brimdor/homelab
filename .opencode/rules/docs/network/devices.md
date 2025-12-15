# Device Inventory

## Infrastructure Devices

| Device Name | IP Address | VLAN | MAC Address | Device Type | Make/Model | Notes |
|-------------|------------|------|-------------|-------------|------------|-------|
| OPNSense | `10.0.0.1` | All | `00:e0:67:2e:20:b3` | Router/Firewall | HPE ProLiant MicroServer | Gateway for all VLANs |
| TPLink Switch | `10.0.10.2` | 10 | `14:EB:B6:0D:F2:B2` | Managed Switch | TP-Link TL-SG1024DE | 24-Port Gigabit |
| TPLink AX5400 | `10.0.10.3` | 10 | `6c:5a:b0:db:45:80` | Access Point | TP-Link AX5400 | Wireless AP, broadcasts VLAN 50 |
| UNRAID | `10.0.40.3` | 40 | `00:e0:4c:17:87:83` | NAS Server | Zimaboard 832 | Storage + Twingate host |

## Kubernetes Cluster (VLAN 20 - Cluster-Prod)

| Device Name | IP Address | MAC Address | Device Type | Make/Model | Role | Notes |
|-------------|------------|-------------|-------------|------------|------|-------|
| ash | `10.0.20.10` | `DC:A6:32:D2:C5:48` | SBC | Raspberry Pi 4 | **Controller** | SSH access for cluster management |
| charmander | `10.0.20.11` | `00:23:24:B0:FF:03` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| squirtle | `10.0.20.12` | `00:23:24:E2:1F:A1` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| bulbasaur | `10.0.20.13` | `00:23:24:E2:0D:EA` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| pikachu | `10.0.20.14` | `E0:4F:43:24:0B:53` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| chikorita | `10.0.20.15` | `6C:4B:90:60:29:C4` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| cyndaquil | `10.0.20.16` | `6C:4B:90:5F:8E:43` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| totodile | `10.0.20.17` | `6C:4B:90:5B:A3:56` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| growlithe | `10.0.20.18` | `6C:4B:90:5B:6E:6D` | Mini PC | Lenovo ThinkCentre M700 | Worker | |
| arcanine | `10.0.20.19` | `4C:CC:6A:3D:E5:3F` | Mini PC | Lenovo ThinkCentre M900 | Worker | NVIDIA RTX 3090 |
| sprigatito | `10.0.20.20` | `4c:cc:6a:34:dc:6d` | Mini PC | Lenovo ThinkCentre M700 | Worker | NVIDIA GTX 1650 |

### Cluster Summary
- **Total Nodes**: 11 (1 controller + 10 workers)
- **Control Plane API**: `https://10.0.20.50:6443`
- **GPU Nodes**: 2 (arcanine with RTX 3090, sprigatito with GTX 1650)

## Raspberry Pi Extras (VLAN 30 - Cluster-Extra)

| Device Name | IP Address | MAC Address | Device Type | Make/Model | Notes |
|-------------|------------|-------------|-------------|------------|-------|
| mario | `10.0.30.10` | `DC:A6:32:D3:32:5C` | SBC | Raspberry Pi 4 | Side projects |
| flareon | `10.0.30.11` | `DC:A6:32:B9:29:CA` | SBC | Raspberry Pi 4 | Side projects |
| jolteon | `10.0.30.12` | `DC:A6:32:D3:32:AD` | SBC | Raspberry Pi 4 | Side projects |
| vaporeon | `10.0.30.13` | `DC:A6:32:D3:31:63` | SBC | Raspberry Pi 4 | Side projects |
| glaceon | `10.0.30.14` | `DC:A6:32:B9:2A:45` | SBC | Raspberry Pi 4 | Side projects |

## Switch Port Assignments

| Port(s) | VLAN | Mode | Connected Device(s) | IP Range |
|---------|------|------|---------------------|----------|
| 1 | 1 | Access | Switch Management | `10.0.0.x` |
| 2 | 20 | Access | ash (K8s Controller) | `10.0.20.10` |
| 3 | 20 | Access | charmander | `10.0.20.11` |
| 4 | 20 | Access | squirtle | `10.0.20.12` |
| 5 | 20 | Access | bulbasaur | `10.0.20.13` |
| 6 | 20 | Access | pikachu | `10.0.20.14` |
| 7 | 20 | Access | chikorita | `10.0.20.15` |
| 8 | 20 | Access | cyndaquil | `10.0.20.16` |
| 9 | 20 | Access | totodile | `10.0.20.17` |
| 10 | 20 | Access | growlithe | `10.0.20.18` |
| 11 | 20 | Access | arcanine | `10.0.20.19` |
| 12 | 30 | Access | mario | `10.0.30.10` |
| 13 | 30 | Access | flareon | `10.0.30.11` |
| 14 | 30 | Access | jolteon | `10.0.30.12` |
| 15 | 30 | Access | vaporeon | `10.0.30.13` |
| 16 | 30 | Access | glaceon | `10.0.30.14` |
| 17 | 30 | Access | (spare) | - |
| 18 | 30 | Access | (spare) | - |
| 19-20 | 40 | LAG2 | UNRAID NAS (bonded) | `10.0.40.3` |
| 21 | 50 | Access | IoT devices | `10.0.50.x` |
| 22 | 10+50 | Trunk | TPLink AX5400 AP | `10.0.10.3` (mgmt) |
| 23-24 | All | LAG1 | OPNSense (eth1+eth2) | `10.0.0.1` |

## DHCP Static Reservations

All devices above are configured with DHCP static reservations in OPNSense (Kea DHCP) to ensure consistent IP assignments based on MAC address.
