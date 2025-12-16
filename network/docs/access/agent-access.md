# Agent Access Guide

This guide documents how an AI agent (or human) can connect to different resources and areas of the Nelson Network.

## Quick Reference

| Resource | Connection Method | Access From |
|----------|-------------------|-------------|
| K8s Controller (ash) | `ssh brimdor@10.0.20.10` | Port 1, AP, any VLAN |
| K8s Control Plane API | `https://10.0.20.50:6443` | Any VLAN (via kubectl) |
| OPNSense Firewall | `https://10.0.0.1` | Port 1, AP, any VLAN |
| TPLink Switch | `http://10.0.10.2` | Port 1, AP, any VLAN |
| NAS (UNRAID) | `http://10.0.40.3` or SMB/NFS | Port 1, AP, any VLAN |

---

## SSH Access

### Kubernetes Controller (ash)

The primary entry point for cluster management:

```bash
ssh brimdor@10.0.20.10
```

**From ash, you can:**
- Run `kubectl` commands to manage the cluster
- Access other nodes via SSH
- Manage cluster deployments

**Requirements:**
- SSH key authentication configured
- Network access to VLAN 20 (or inter-VLAN routing enabled)

### Other K8s Nodes

```bash
# Worker nodes (replace hostname as needed)
ssh brimdor@10.0.20.11  # charmander
ssh brimdor@10.0.20.12  # squirtle
ssh brimdor@10.0.20.13  # bulbasaur
# ... etc
```

### Raspberry Pis (VLAN 30)

```bash
ssh pi@10.0.30.10  # mario
ssh pi@10.0.30.11  # flareon
ssh pi@10.0.30.12  # jolteon
ssh pi@10.0.30.13  # vaporeon
ssh pi@10.0.30.14  # glaceon
```

---

## Web UI Access

### OPNSense Firewall

- **URL**: `https://10.0.0.1`
- **Access**: From Port 1, AP, or any device on the network
- **Purpose**: Firewall configuration, DHCP, DNS, routing

### TPLink Switch

- **URL**: `http://10.0.10.2`
- **Access**: From Port 1, AP, or any device on the network
- **Purpose**: VLAN configuration, port settings, LAG management

### UNRAID NAS

- **URL**: `http://10.0.40.3`
- **Access**: From Port 1, AP, or any device on the network
- **Purpose**: Storage management, Docker containers, Twingate

---

## Storage Access

### NAS (UNRAID) - SMB/CIFS

```bash
# Mount SMB share
mount -t cifs //10.0.40.3/share /mnt/nas -o username=user
```

### NAS - NFS

```bash
# Mount NFS share
mount -t nfs 10.0.40.3:/mnt/user/share /mnt/nas
```

**NFS Ports**: 111, 2049, 20048

---

## Kubernetes API Access

### Accessing kubectl via Nix Container

kubectl is available through a Nix development environment on the controller (ash). Follow these steps:

```bash
# 1. SSH to the controller
ssh brimdor@10.0.20.10

# 2. Navigate to homelab repo and ensure it's up to date
cd ~/homelab
git pull

# 3. Enter the Nix tools container (wait 20-30 seconds for it to load)
make tools

# 4. Now you can run kubectl commands
kubectl get nodes -o wide
```

### Kubeconfig Location

Inside the Nix container, the kubeconfig is located at:

- **Primary**: `~/.kube/config`
- **Alternative**: Check `echo $KUBECONFIG` for custom path

The kubeconfig points to the control plane API at `https://10.0.20.50:6443`.

### Common kubectl Commands

```bash
# Cluster status
kubectl get nodes -o wide
kubectl cluster-info

# Workload status
kubectl get pods -A
kubectl get deployments -A

# Service discovery
kubectl get svc -A
kubectl get ingress -A

# Logs
kubectl logs -n <namespace> <pod-name>

# Execute commands in pods
kubectl exec -it -n <namespace> <pod-name> -- /bin/sh
```

---

## Network Accessibility Matrix

All devices on the network can access all other devices due to full inter-VLAN routing.

| Source VLAN | Can Access |
|-------------|------------|
| VLAN 1 (Native) | All VLANs |
| VLAN 10 (Management) | All VLANs |
| VLAN 20 (Cluster-Prod) | All VLANs |
| VLAN 30 (Cluster-Extra) | All VLANs |
| VLAN 40 (Storage) | All VLANs |
| VLAN 50 (IoT/Wireless) | All VLANs |

### Key Accessibility Requirements

1. **OPNSense (`10.0.0.1`)**: Accessible from Port 1 and AP (any VLAN)
2. **TPLink Switch (`10.0.10.2`)**: Accessible from Port 1 and AP (any VLAN)
3. **NAS (`10.0.40.3`)**: Accessible from entire network (all VLANs)
4. **ash (`10.0.20.10`)**: Accessible from Port 1 and AP for SSH cluster management
5. **K8s API (`10.0.20.50`)**: Accessible from any VLAN for kubectl commands

---

## Physical Access Points

### Port 1 on TPLink Switch
- VLAN 1 (Native)
- Direct access to switch management
- Can reach all infrastructure via inter-VLAN routing

### Wireless AP (VLAN 50)
- Connects to Port 22 on switch
- Wireless clients get VLAN 50 IPs
- Full access to all network resources via inter-VLAN routing

---

## Troubleshooting Access

### Cannot reach a device

1. **Check IP assignment**: `ip addr` or `ifconfig`
2. **Check gateway**: `ip route` - should point to VLAN gateway
3. **Ping gateway**: `ping 10.0.X.1`
4. **Ping destination**: `ping <target-ip>`
5. **Check OPNSense firewall**: Ensure "Allow All" rules are in place

### SSH connection refused

1. Verify SSH service is running: `systemctl status sshd`
2. Check firewall on target: `ufw status` or `iptables -L`
3. Verify correct username and key

### kubectl not working

1. Ensure you're in the Nix container: `make tools` from `~/homelab`
2. Check kubeconfig exists: `ls -la ~/.kube/config` or `echo $KUBECONFIG`
3. Verify API server is reachable: `curl -k https://10.0.20.50:6443`
4. Check authentication: Ensure certificates/tokens are valid
