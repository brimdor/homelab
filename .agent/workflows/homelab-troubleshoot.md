---
description: Troubleshoot issues across the Homelab Kubernetes cluster
sync_locations:
  - ~/.gemini/antigravity/global_workflows/homelab-troubleshoot.md
  - ~/.config/opencode/command/homelab-troubleshoot.md
sync_note: IMPORTANT - This file must be kept in sync across both locations. When making changes, update BOTH files.
---

# Homelab Troubleshooting Workflow

## Overview
This workflow guides troubleshooting of issues across the Homelab Kubernetes infrastructure.

> [!IMPORTANT]
> **Sync Requirement**: This workflow exists in two locations that must stay synchronized:
> - `~/.gemini/antigravity/global_workflows/homelab-troubleshoot.md` (Antigravity)
> - `~/.config/opencode/command/homelab-troubleshoot.md` (Opencode)
> 
> When updating this file, **always copy changes to both locations**.

## References
- **Documentation**: https://homelab.eaglepass.io
- **Primary Repo**: https://git.eaglepass.io/ops/homelab
- **Fallback Repo**: https://github.com/brimdor/homelab (auto-synced from primary)

## Prerequisites

### 1. Ensure Local Tools Are Up-to-Date
Before starting, verify all local tools are current and functional.

### 2. Access Priority
- **Primary**: Use the local system for all work
- **Controller Fallback**: Only use when local access to Kubernetes cluster is unavailable
  - SSH: `ssh brimdor@10.0.50.120`
  - Homelab files: `~/homelab`

### 3. Controller Access (Fallback Only)
If local access is unavailable:
```bash
# Connect to controller
ssh brimdor@10.0.50.120

# Navigate to homelab directory
cd ~/homelab

# Get latest code (run every time you connect for the day)
git pull

# Start the tools container
make tools
```

## Cluster Architecture
- **Kubernetes Distribution**: K3s
- **GitOps**: ArgoCD (manages application deployments)
- **CNI**: Cilium (network connectivity and policies)
- **Storage**: Rook Ceph (persistent volumes)
- **Ingress**: NGINX Ingress Controller (external access)
- **Monitoring**: Prometheus + Grafana + Loki (metrics and logs)
- **External DNS**: Manages DNS records for services
- **Cert Manager**: Manages TLS certificates
- **External Secrets**: Manages secrets from external sources

## Cluster Organization
The homelab is organized into several key directories:

### 1. system/ - Core Cluster Infrastructure
- `argocd/` - GitOps controller
- `cert-manager/` - Certificate management
- `cloudflared/` - Cloudflare tunnel
- `external-dns/` - DNS management
- `ingress-nginx/` - Ingress controller
- `monitoring-system/` - Prometheus/Grafana
- `rook-ceph/` - Storage provider
- `gpu-operator/` - GPU support
- `kured/` - Node reboot manager
- `loki/` - Log aggregation
- `volsync-system/` - Volume synchronization

### 2. platform/ - Platform Services
- `dex/` - Identity provider
- `external-secrets/` - Secret management
- `gitea/` - Git hosting
- `global-secrets/` - Cluster-wide secrets
- `grafana/` - Visualization
- `kanidm/` - Identity management
- `renovate/` - Dependency updates
- `woodpecker/` - CI/CD
- `zot/` - Container registry

### 3. apps/ - User Applications
- `emby/` - Media server
- `radarr/` - Movie management
- `sonarr/` - TV show management
- `sabnzbd/` - Download client

### 4. metal/ - Bare Metal Provisioning
- Ansible playbooks for cluster setup
- Node configuration
- K3s installation

### 5. external/ - External Resources (Terraform)
- Cloudflare configuration
- External service setup

## Available Helper Scripts
Located in `scripts/` directory:
| Script | Description |
|--------|-------------|
| `get-status` | Get overall cluster status |
| `argocd-admin-password` | Retrieve ArgoCD admin password |
| `get-dns-config` | Check DNS configuration |
| `get-wireguard-config` | Get VPN config |
| `kanidm-reset-password` | Reset identity management passwords |
| `helm-diff` | Compare Helm chart changes |
| `error_check` | Check for common errors |
| `configure` | Configure cluster components |
| `new-service` | Scaffold new service |
| `onboard-user` | Add new user |
| `spin_up` / `spin_down` | Manage cluster power state |
| `pxe-logs` | Check PXE boot logs |
| `take-screenshots` | Capture service screenshots |

## Compatible Tools
| Tool | Purpose |
|------|---------|
| `kubectl` | Kubernetes CLI (required) |
| `helm` | Kubernetes package manager (required) |
| `kustomize` | Kubernetes configuration management |
| `k9s` | Terminal UI for Kubernetes |
| `argocd` | ArgoCD CLI (for GitOps management) |
| `cilium` | Cilium CLI (for network troubleshooting) |
| `ceph` | Ceph storage CLI (for storage issues) |
| `terraform` | Infrastructure as code (for external resources) |
| `ansible` | Configuration management (for bare metal) |

## Key Namespaces
| Namespace | Purpose |
|-----------|---------|
| `argocd` | GitOps controller |
| `cert-manager` | Certificate management |
| `rook-ceph` | Storage system |
| `ingress-nginx` | Ingress controller |
| `monitoring-system` | Monitoring stack |
| `external-secrets` | Secret management |
| `gitea` | Git hosting |
| `platform-*` | Platform services |

## Troubleshooting Steps

### Step 1: Pre-flight Checklist
Before diving deep, verify these basics:
```bash
# 1. Cluster is reachable
kubectl cluster-info

# 2. Nodes are healthy
kubectl get nodes

# 3. Core system pods are running
kubectl get pods -n kube-system

# 4. ArgoCD is operational
kubectl get pods -n argocd

# 5. Storage is healthy
kubectl get cephcluster -n rook-ceph

# 6. Network is functional (if available)
cilium status

# 7. Check for critical events
kubectl get events -A | grep -i error
```

### Step 2: Identify the Issue Category

#### Application Issues
```bash
# Check ArgoCD application status
kubectl get applications -n argocd

# Check pod status
kubectl get pods -n <namespace>

# View pod logs
kubectl logs -n <namespace> <pod-name>

# Check events
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Verify ingress
kubectl get ingress -n <namespace>

# Check secrets
kubectl get secrets -n <namespace>
```

#### Network Issues
```bash
# Check Cilium status
cilium status

# Test connectivity
cilium connectivity test

# Check network policies
kubectl get networkpolicies -A

# Verify DNS
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup kubernetes.default

# Check ingress controller
kubectl get pods -n ingress-nginx
```

#### Storage Issues
```bash
# Check Ceph cluster health
kubectl get cephcluster -n rook-ceph

# View PVC status
kubectl get pvc -A

# Check storage classes
kubectl get storageclass
```

#### GitOps Issues
```bash
# Check ArgoCD sync status
argocd app list

# Force sync
argocd app sync <app-name>

# View sync logs
argocd app logs <app-name>

# Check ArgoCD health
kubectl get pods -n argocd
```

#### Certificate Issues
```bash
# Check cert-manager
kubectl get certificates -A

# View certificate requests
kubectl get certificaterequests -A

# Check issuers
kubectl get clusterissuers

# Review cert-manager logs
kubectl logs -n cert-manager deploy/cert-manager
```

#### Monitoring & Logging
```bash
# Query Prometheus
kubectl port-forward -n monitoring-system svc/prometheus 9090:9090

# Check monitoring pods
kubectl get pods -n monitoring-system
```

### Step 3: Gather Debug Information
When troubleshooting, collect:
- Pod status and descriptions
- Container logs (current and previous if crashed)
- Events in relevant namespaces
- Resource usage (CPU/Memory)
- Network connectivity tests
- Storage health and PVC bindings
- Ingress and service configurations
- Certificate status
- ArgoCD application sync status
- Recent changes from git history

### Step 4: Resolve and Document
1. Apply the fix
2. Verify the solution
3. Document findings if significant
4. Consider creating an issue for recurring problems at https://git.eaglepass.io/ops/homelab/issues

## MCP Tool Integration (Primary Method)
Use the available **Gitea** and **GitHub** MCP tools for all repository interactions. These are safer, more robust, and preferred over direct API calls.

### Priority Order
1. **Gitea MCP**: Use for all operations on the primary repository (`ops/homelab`).
2. **GitHub MCP**: Use as a fallback for GitHub-hosted mirrors or if Gitea MCP is unavailable.
3. **API Fallback**: Use raw `curl` commands (detailed below) **ONLY** if MCP tools are non-functional.

### Common MCP Operations
- **List Issues**: Use `list_issues` (Gitea) or `mcp_list_issues` (GitHub).
- **Create Issue**: Use `create_issue` (Gitea) or `mcp_create_issue` (GitHub).
- **Add Comment**: Use `add_issue_comment` (Gitea/GitHub).
- **List PRs**: Use `list_pull_requests` (Gitea) or `mcp_list_pull_requests` (GitHub).
- **Get Repo Info**: Use `get_repository` (Gitea) or `mcp_search_repositories` (GitHub).

---

## Gitea API Fallback (Emergency Only)

> [!WARNING]
> Only use the following API commands if the MCP tools above are failing or unavailable.

For automated repo, issue, and PR operations without MCP, use the Gitea API with the stored token.

### Token Location
```bash
# Token files are stored at:
~/.config/gitea/.env        # For bash/zsh
~/.config/gitea/gitea.fish  # For fish shell

# Load token in fish shell:
source ~/.config/gitea/gitea.fish

# Load token in bash/zsh:
source ~/.config/gitea/.env

# Environment variables available after sourcing:
# GITEA_TOKEN - API access token
# GITEA_URL   - Base URL (https://git.eaglepass.io)
```

### API Base URL
```
https://git.eaglepass.io/api/v1
```

### Common API Operations

#### List Issues
```bash
curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues" \
  -H "Authorization: token $GITEA_TOKEN"
```

#### Create Issue
```bash
curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Issue Title", "body": "Issue description"}'
```

#### Add Comment to Issue
```bash
curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/{issue_number}/comments" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body": "Comment text"}'
```

#### List Pull Requests
```bash
curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls" \
  -H "Authorization: token $GITEA_TOKEN"
```

#### Get Repository Info
```bash
curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab" \
  -H "Authorization: token $GITEA_TOKEN"
```

### API Documentation
Full API documentation: https://git.eaglepass.io/api/swagger

## Troubleshooting Task
Please resolve the following issue:

$ARGUMENTS
