# Kubernetes Cluster

## Cluster Overview

The Nelson Network runs a K3s Kubernetes cluster for hosting homelab applications and services.

## Cluster Details

| Property | Value |
|----------|-------|
| **Distribution** | K3s |
| **SSH Access** | `ash` (`10.0.20.10`) - Raspberry Pi for management |
| **Control Plane API** | `https://10.0.20.11:6443` (charmander) |
| **Node Count** | 10 (3 control-plane + 7 workers) |
| **Network VLAN** | VLAN 20 (Cluster-Prod) |
| **Service CIDR** | `10.43.0.0/16` |
| **CNI** | Cilium |

## Nodes

### Control Plane Nodes (etcd + master)

| Node | IP Address | Hardware | Notes |
|------|------------|----------|-------|
| charmander | `10.0.20.11` | Lenovo ThinkCentre M700 | Primary API endpoint |
| squirtle | `10.0.20.12` | Lenovo ThinkCentre M700 | Control plane |
| bulbasaur | `10.0.20.13` | Lenovo ThinkCentre M700 | Control plane |

### Worker Nodes

| Node | IP Address | Hardware | GPU | Notes |
|------|------------|----------|-----|-------|
| pikachu | `10.0.20.14` | Lenovo ThinkCentre M700 | - | Worker |
| chikorita | `10.0.20.15` | Lenovo ThinkCentre M700 | - | Worker |
| cyndaquil | `10.0.20.16` | Lenovo ThinkCentre M700 | - | Worker |
| totodile | `10.0.20.17` | Lenovo ThinkCentre M700 | - | Worker |
| growlithe | `10.0.20.18` | Lenovo ThinkCentre M700 | - | Worker |
| arcanine | `10.0.20.19` | Lenovo ThinkCentre M900 | NVIDIA RTX 3090 | GPU Worker |
| sprigatito | `10.0.20.20` | Lenovo ThinkCentre M700 | NVIDIA GTX 1650 | GPU Worker |

### Management Node

| Node | IP Address | Hardware | Notes |
|------|------------|----------|-------|
| ash | `10.0.20.10` | Raspberry Pi 4 | SSH jump host, homelab repo, kubectl access |

## Connecting to the Cluster

### SSH Access to Management Node

```bash
ssh brimdor@10.0.20.10
```

### Running kubectl Commands

There are two ways to run kubectl commands:

#### Method 1: Direct kubectl (Quick)

If kubectl is installed on ash, you can run commands directly using the kubeconfig:

```bash
# SSH to ash
ssh brimdor@10.0.20.10

# Run kubectl with explicit kubeconfig
export KUBECONFIG=~/homelab/metal/kubeconfig.yaml
kubectl get nodes -o wide
```

#### Method 2: Nix Tools Container (Full Environment)

For the complete development environment with all tools (ansible, terraform, etc.):

```bash
# 1. SSH to ash
ssh brimdor@10.0.20.10

# 2. Navigate to homelab repo
cd ~/homelab
git pull

# 3. Enter the Nix tools container (wait 20-30 seconds for it to load)
make tools

# 4. Now you can run kubectl and other tools
kubectl get nodes -o wide
```

### SSH to Cluster Nodes

From inside the Nix tools container on ash, you can SSH to any cluster node as root:

```bash
# From ash, inside nix tools container
ssh root@10.0.20.11  # charmander
ssh root@10.0.20.19  # arcanine (GPU node)
```

**Kubeconfig Location**:
- Path: `~/homelab/metal/kubeconfig.yaml`
- Environment variable: `KUBECONFIG` is set automatically in the Nix container

### Common Commands

```bash
# Check cluster health
kubectl get nodes -o wide

# View all pods
kubectl get pods -A

# View services
kubectl get svc -A

# View ingress resources
kubectl get ingress -A

# Check ArgoCD applications
kubectl get applications -n argocd

# Check Cilium network status
kubectl exec -n kube-system ds/cilium -- cilium status
```

## Storage

### Rook-Ceph (Primary)
The cluster uses Rook-Ceph for distributed block storage across the worker nodes.

- **Storage Class**: `standard-rwo` (block), `standard-rwx` (filesystem)
- **Namespace**: `rook-ceph`

### NFS (Secondary)
The cluster can also access the NAS at `10.0.40.3` (VLAN 40) for NFS storage.

**NFS Ports**: 111, 2049, 20048

All cluster nodes on VLAN 20 have full access to the NAS on VLAN 40 through inter-VLAN routing.

## Cluster Services

### CNI - Cilium
- **Version**: 1.15.x
- Provides pod networking and network policies
- Runs as a DaemonSet on all nodes
- Uses KubeProxyReplacement for improved performance

**Important**: After node IP changes (e.g., VLAN migration), Cilium must be restarted to pick up new IPs:
```bash
kubectl rollout restart daemonset cilium -n kube-system
```

### Internal DNS
- Kubernetes internal DNS: `svc.cluster.local`
- Example: `my-service.my-namespace.svc.cluster.local`
- Provided by CoreDNS in `kube-system` namespace

### Ingress Controller
- **Type**: NGINX Ingress Controller
- **Namespace**: `ingress-nginx`
- Routes external traffic to services based on hostname

### GitOps
- **ArgoCD**: Manages cluster deployments
- **Primary Repository**: Internal Gitea at `http://gitea-http.gitea:3000/ops/homelab`
- **Backup Repository**: `https://github.com/brimdor/homelab`

The ApplicationSet `root` in the `argocd` namespace generates all cluster applications from the git repository.

## Troubleshooting

### DNS Issues
If pods can't resolve service names:
```bash
# Check CoreDNS is running
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Restart CoreDNS
kubectl rollout restart deployment coredns -n kube-system
```

### Network Connectivity Issues
If pods can't communicate across nodes:
```bash
# Check Cilium node IPs are correct
kubectl get ciliumnodes -o wide

# If IPs are stale (e.g., after VLAN migration), restart Cilium
kubectl rollout restart daemonset cilium -n kube-system
```

### ArgoCD Not Syncing
If ArgoCD can't reach the git repository:
```bash
# Check ApplicationSet status
kubectl get applicationset root -n argocd -o yaml

# Temporarily switch to GitHub if Gitea is down
kubectl patch applicationset root -n argocd --type=json -p='[
  {"op": "replace", "path": "/spec/generators/0/git/repoURL", "value": "https://github.com/brimdor/homelab"},
  {"op": "replace", "path": "/spec/template/spec/source/repoURL", "value": "https://github.com/brimdor/homelab"}
]'
```

## Related Documentation

- [Applications](applications.md) - Deployed applications and their access methods
- [Agent Access Guide](../access/agent-access.md) - How to connect to cluster resources
- [External Access](../access/external-access.md) - Cloudflare tunnel configuration
