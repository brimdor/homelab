---
description: Analyze and test the entire Homelab server stack
sync_locations:
  - ~/.gemini/antigravity/global_workflows/homelab-recon.md
  - ~/.config/opencode/command/homelab-recon.md
sync_note: IMPORTANT - This file must be kept in sync across all locations. When making changes, update ALL files.
---

# Homelab Reconnaissance & Status Report

> [!IMPORTANT]
> **Sync Requirement**: This workflow exists in multiple locations that must stay synchronized:
> - `~/Documents/GitHub/homelab/.agent/workflows/homelab-recon.md` (Primary/Source)
> - `~/.gemini/antigravity/global_workflows/homelab-recon.md` (Antigravity)
> - `~/.config/opencode/command/homelab-recon.md` (OpenCode)
>
> When updating this file, **always copy changes to all locations**.

## Overview

This workflow analyzes the entire Homelab stack from bare metal to user applications to validate health and performance. It performs reconnaissance across four layers: **Metal** (hardware/OS), **System** (Kubernetes core), **Platform** (middleware), and **Apps** (user services).

## Access & Authentication

### Priority Order

1. **Local System (Preferred)**: Use local kubectl and tools when available
2. **Controller (Fallback)**: SSH to controller when local access is unavailable
3. **Direct Node Access**: Only via controller, never direct from workstation

### System Access

#### Local System Access (Preferred)

Verify local access to Kubernetes cluster:
```bash
# Test kubectl access
kubectl get nodes

# Verify context
kubectl config current-context
```

#### Controller Access (Fallback)

If local access is unavailable, use the controller:
```bash
# Connect to controller
ssh brimdor@10.0.50.120

# Navigate to homelab
cd ~/homelab

# Get latest code (run daily)
git pull

# Start tools container for advanced operations
make tools
```

**Controller Details**:
- **IP**: 10.0.50.120
- **User**: brimdor
- **Auth**: Passwordless SSH
- **Homelab Path**: `~/homelab`

#### Node Access

Direct SSH to nodes from workstation is **intentionally blocked**. To access nodes:

1. SSH to Controller: `ssh brimdor@10.0.50.120`
2. Navigate to homelab: `cd ~/homelab`
3. Start tools container: `make tools`
4. Wait ~20 seconds for container to be ready
5. SSH to node from container: `ssh root@<nodeIP>`

**Node IPs**: Access via controller only, SSH as `root`

### Gitea Access

#### MCP Tool Integration (Primary Method)

Use the available **Gitea** and **GitHub** MCP tools for all repository interactions when available.

**Priority Order**:
1. **Gitea MCP**: Use for all operations on the primary repository (`ops/homelab`)
2. **GitHub MCP**: Use as a fallback for GitHub-hosted mirrors
3. **API Fallback**: Use raw `curl` commands (below) **ONLY** if MCP tools are non-functional

**Common MCP Operations**:
- List Issues: Use `list_issues` (Gitea) or GitHub equivalent
- Create Issue: Use `create_issue` (Gitea) or GitHub equivalent
- Edit Issue: Use `edit_issue` (Gitea) to update issue body
- Add Comment: Use `add_issue_comment` (Gitea) - **Reserved for humans only in this workflow**

#### API Fallback (Emergency Only)

> [!WARNING]
> Only use the following API commands if MCP tools are failing or unavailable.

**Token Location**:
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

**API Base URL**: `https://git.eaglepass.io/api/v1`

**Common API Operations**:

```bash
# List issues
curl -s "$GITEA_URL/api/v1/repos/ops/homelab/issues?state=open" \
  -H "Authorization: token $GITEA_TOKEN"

# Get specific issue
curl -s "$GITEA_URL/api/v1/repos/ops/homelab/issues/{issue_number}" \
  -H "Authorization: token $GITEA_TOKEN"

# Edit existing issue body (PATCH to update)
curl -s -X PATCH "$GITEA_URL/api/v1/repos/ops/homelab/issues/{issue_number}" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body": "Updated content..."}'

# Create new issue
curl -s -X POST "$GITEA_URL/api/v1/repos/ops/homelab/issues" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "[Recon Report] YYYY-MM-DD - Title", "body": "Report content"}'
```

**Full API Documentation**: https://git.eaglepass.io/api/swagger

### GitHub Access

GitHub repository at `https://github.com/brimdor/homelab` is auto-synced from the primary Gitea repository. Use GitHub MCP tools or standard GitHub API with personal access token when needed.

## Reconnaissance Layers & Criteria

### 1. Metal Layer (Hardware & OS)

**Purpose**: Validate physical/virtual hardware health and operating system status.

**Validation Steps**:

1. **Check Controller Reachability**
   ```bash
   # From local workstation
   ssh brimdor@10.0.50.120 echo "Controller online"
   ```

2. **Check Node Status**
   ```bash
   # Get all nodes
   kubectl get nodes -o wide
   
   # Check node conditions
   kubectl describe nodes | grep -A 5 "Conditions:"
   ```

3. **Check Resource Usage**
   ```bash
   # Node resource usage
   kubectl top nodes
   
   # Detailed node metrics
   kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, capacity: .status.capacity, allocatable: .status.allocatable}'
   ```

4. **Check Disk Usage** (if accessing controller/nodes)
   ```bash
   # From controller or nodes
   df -h
   
   # Check for ZFS/RAID health
   zpool status  # if ZFS is used
   ```

5. **Check System Temperatures** (if accessible)
   ```bash
   # From nodes (if sensors available)
   sensors
   ```

**Status Criteria**:

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | Controller reachable. All nodes online and Ready. CPU < 50%, RAM < 80%, Disk < 80%. Temps normal. No hardware errors. |
| 🟡 **Yellow** | High resource usage (CPU > 80% or RAM > 90%). Disk > 90%. Temps elevated but safe. Minor hardware warnings. Single node offline in HA setup. |
| 🔴 **Red** | Controller unreachable. Multiple nodes offline. Disk full (> 98%). Critical hardware failures. Overheating. Cluster degraded. |

### 2. System Layer (Kubernetes Core)

**Purpose**: Validate Kubernetes cluster components and core services.

**Validation Steps**:

1. **Check Node Status**
   ```bash
   # All nodes should be Ready
   kubectl get nodes
   ```

2. **Check System Pods**
   ```bash
   # All system pods should be Running/Completed
   kubectl get pods -n kube-system
   
   # Check for restart counts
   kubectl get pods -n kube-system --sort-by='.status.containerStatuses[0].restartCount'
   ```

3. **Check CNI (Cilium) Status**
   ```bash
   # Cilium pods
   kubectl get pods -n kube-system -l k8s-app=cilium
   
   # Cilium status (if cilium CLI available)
   cilium status
   
   # Network policies
   kubectl get networkpolicies --all-namespaces
   ```

4. **Check CSI (Rook-Ceph) Status**
   ```bash
   # Rook-Ceph pods
   kubectl get pods -n rook-ceph
   
   # Ceph cluster status
   kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status
   
   # Ceph health
   kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph health detail
   ```

5. **Check Storage Classes**
   ```bash
   # Available storage classes
   kubectl get storageclass
   
   # PV status
   kubectl get pv
   ```

**Status Criteria**:

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | All nodes Ready. Core pods healthy (Running/Completed). Ceph health HEALTH_OK. Network policies active. CSI functional. |
| 🟡 **Yellow** | Single node NotReady (if HA). Non-critical system pods restarting. Ceph HEALTH_WARN (non-critical). Minor CNI issues. |
| 🔴 **Red** | Multiple nodes down. API Server unreachable. Ceph HEALTH_ERR. CNI failures blocking traffic. Storage unavailable. |

### 3. Platform Layer (Middleware)

**Purpose**: Validate platform services that support applications (GitOps, ingress, certificates, authentication, monitoring).

**Validation Steps**:

1. **Check GitOps (ArgoCD)**
   ```bash
   # ArgoCD pods
   kubectl get pods -n argocd
   
   # Application sync status
   kubectl get applications -n argocd
   
   # Check for OutOfSync apps
   kubectl get applications -n argocd -o json | jq '.items[] | select(.status.sync.status != "Synced") | {name: .metadata.name, status: .status.sync.status}'
   
   # ArgoCD CLI (if available)
   argocd app list
   ```

2. **Check Ingress (NGINX)**
   ```bash
   # Ingress controller pods
   kubectl get pods -n ingress-nginx
   
   # Ingress resources
   kubectl get ingress --all-namespaces
   
   # Test ingress endpoint
   curl -I https://git.eaglepass.io
   ```

3. **Check Certificate Management (Cert-Manager)**
   ```bash
   # Cert-manager pods
   kubectl get pods -n cert-manager
   
   # Certificate status
   kubectl get certificates --all-namespaces
   
   # Check for expiring certs (< 30 days)
   kubectl get certificates --all-namespaces -o json | jq '.items[] | select(.status.renewalTime) | {name: .metadata.name, namespace: .metadata.namespace, notAfter: .status.notAfter}'
   ```

4. **Check Identity Provider (Kanidm/Dex)**
   ```bash
   # Kanidm pods
   kubectl get pods -n kanidm
   
   # Dex pods
   kubectl get pods -n dex
   
   # Test auth endpoint
   curl -I https://auth.eaglepass.io
   ```

5. **Check Monitoring (Prometheus/Grafana)**
   ```bash
   # Monitoring pods
   kubectl get pods -n monitoring-system
   
   # Prometheus targets (if prometheus CLI available)
   kubectl port-forward -n monitoring-system svc/prometheus 9090:9090 &
   curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health != "up")'
   
   # Grafana accessibility
   curl -I https://grafana.eaglepass.io
   ```

**Status Criteria**:

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | ArgoCD Synced & Healthy. Ingress serving traffic. Certs valid (> 30 days). Auth working. Monitoring active. All platform pods Running. |
| 🟡 **Yellow** | ArgoCD OutOfSync (but functional). Expiring certs (< 15 days). Minor monitoring gaps. Platform pod restarts. Slow response times. |
| 🔴 **Red** | ArgoCD broken or degraded. Ingress 404/503 errors. Expired certificates. Auth down or unreachable. Monitoring unavailable. |

### 4. Apps Layer (User Services)

**Purpose**: Validate user-facing applications are healthy and accessible.

**Validation Steps**:

1. **Check App Pods**
   ```bash
   # List all app namespaces (apps are in individual namespaces)
   kubectl get namespaces | grep -E 'emby|gitea|sonarr|radarr|ollama|openwebui|sabnzbd|searxng'
   
   # Check all app pods
   kubectl get pods -n emby
   kubectl get pods -n gitea
   kubectl get pods -n sonarr
   kubectl get pods -n radarr
   kubectl get pods -n ollama
   kubectl get pods -n openwebui
   kubectl get pods -n sabnzbd
   kubectl get pods -n searxng
   # ... etc for other apps
   
   # Get all pods in app namespaces with status
   for ns in emby gitea sonarr radarr ollama openwebui sabnzbd searxng; do
     echo "=== $ns ==="
     kubectl get pods -n $ns 2>/dev/null || echo "Namespace not found"
   done
   ```

2. **Check Service Endpoints**
   ```bash
   # Test HTTP endpoints for key apps
   curl -I https://emby.eaglepass.io
   curl -I https://git.eaglepass.io
   curl -I https://sonarr.eaglepass.io
   curl -I https://radarr.eaglepass.io
   curl -I https://chat.eaglepass.io
   curl -I https://search.eaglepass.io
   
   # Check for HTTP 200 status
   for url in https://emby.eaglepass.io https://git.eaglepass.io https://sonarr.eaglepass.io; do
     status=$(curl -s -o /dev/null -w "%{http_code}" $url)
     echo "$url: $status"
   done
   ```

3. **Check Application Logs**
   ```bash
   # Check recent logs for errors in critical apps
   kubectl logs -n emby --tail=50 -l app=emby | grep -i error
   kubectl logs -n gitea --tail=50 -l app=gitea | grep -i error
   
   # Check pod events
   kubectl get events -n emby --sort-by='.lastTimestamp'
   ```

4. **Check Resource Usage**
   ```bash
   # Top pods by resource usage
   kubectl top pods --all-namespaces --sort-by=memory | head -20
   kubectl top pods --all-namespaces --sort-by=cpu | head -20
   ```

**Status Criteria**:

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | All apps Running. Endpoints responsive (HTTP 200). No critical log errors. Normal resource usage. |
| 🟡 **Yellow** | Non-critical apps down. Slow response times (> 5s). Minor functional bugs. High but acceptable resource usage. |
| 🔴 **Red** | Critical apps (Emby, Gitea, etc.) down or unreachable. Data corruption signs. Persistent errors. Services unusable. |

## Execution Steps

### Prerequisites

1. **Verify Access**
   - Confirm kubectl access (local or via controller)
   - Load Gitea credentials if using API: `source ~/.config/gitea/gitea.fish` or `source ~/.config/gitea/.env`

2. **Prepare Report Location**
   ```bash
   # Ensure reports directory exists
   mkdir -p ~/homelab/reports
   ```

### Reconnaissance Execution

1. **Run Metal Checks**
   - Execute all commands in "Metal Layer" section
   - Document node status, resource usage, hardware health
   - Note any warnings or errors

2. **Run System Checks**
   - Execute all commands in "System Layer" section
   - Check Kubernetes node status, system pods, CNI, CSI
   - Verify Ceph health and storage availability

3. **Run Platform Checks**
   - Execute all commands in "Platform Layer" section
   - Verify ArgoCD sync status, ingress functionality
   - Check certificate expiration, auth services, monitoring

4. **Run App Checks**
   - Execute all commands in "Apps Layer" section
   - Test endpoints with curl, check pod status
   - Review application logs for errors

5. **Generate Report**
   - Fill out the Report Template below
   - Assign overall status (🟢/🟡/🔴) for each layer
   - Document all findings and recommendations
   - Save to `reports/status-report-YYYY-MM-DD.md`

## Report Output

**Reports must always be saved to the `reports/` folder** in the homelab repository.

### File Naming Convention
```
reports/status-report-YYYY-MM-DD.md
```

**Example**: `reports/status-report-2025-12-10.md`

If multiple reports are generated on the same day, append a sequence number:
```
reports/status-report-2025-12-10-2.md
```

## Gitea Issue Integration

After generating the report, **update or create a maintenance issue** in Gitea to track findings.

> [!IMPORTANT]
> **Do NOT add comments to issues.** Comments are reserved for humans only.
> Always **edit the original issue body** to merge new recon data into the existing content.

### Issue Management Steps

1. **Search for existing open maintenance issue**:
   - Look for open issues with title containing `[Maintenance Report]`, `[Recon Report]`, or `[Status Report]`
   - Use MCP tools (preferred) or Gitea API to search

2. **If an existing maintenance issue is found**:
   - **Edit the original issue body** (do NOT add comments)
   - Merge the new recon data into the existing issue content
   - Update relevant sections with latest findings
   - Update the "Last updated" timestamp
   - Preserve any existing content that is still relevant (action items, schedules, etc.)

3. **If no existing issue exists**:
   - Create a new issue with title: `[Recon Report] YYYY-MM-DD - Homelab Status`
   - Include the full report in the issue body
   - Add appropriate labels based on status:
     - `status:green` - All systems healthy
     - `status:yellow` - Warnings present
     - `status:red` - Critical issues

### Merging Data into Existing Issues

When updating an existing issue, follow these guidelines:

1. **Preserve existing structure** - Keep the overall format of the existing issue
2. **Update status tables** - Replace old status data with current findings
3. **Keep action items** - Preserve checkboxes and scheduled items from humans
4. **Update timestamps** - Change "Last updated" to current date/time
5. **Add recon section** if not present - Include a "Latest Recon Status" section
6. **Reference report file** - Add link to `reports/status-report-YYYY-MM-DD.md`

## Report Template

```markdown
# Homelab Status Report - [YYYY-MM-DD]

## Executive Summary
**Overall Status**: [🟢 GREEN / 🟡 YELLOW / 🔴 RED]

**Summary**: [Brief 2-3 sentence summary of the overall state. Mention the most critical finding if any issues exist.]

## Detailed Status

| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2]<br>- [Finding 3] |
| **System** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2]<br>- [Finding 3] |
| **Platform** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2]<br>- [Finding 3] |
| **Apps** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2]<br>- [Finding 3] |

## Issues & Recommendations

### Critical (Red)
- [ ] **Issue**: [Description of critical issue]
  - **Fix**: [Proposed remediation steps]
  - **Impact**: [What happens if not fixed]

### Warnings (Yellow)
- [ ] **Issue**: [Description of warning]
  - **Fix**: [Proposed remediation steps]
  - **Timeline**: [Suggested timeline]

### Observations (Green)
- [Note on optimizations or healthy status observations]
- [Recommendations for improvements even when healthy]

## Verification Data

- **Nodes**: [X] Online / [Y] Total
- **Storage**: [Usage]% Used ([Free GB] free)
- **Top Resource Consumer**: [Pod/Process Name - XX% CPU / YY% RAM]
- **Ceph Status**: [HEALTH_OK / HEALTH_WARN / HEALTH_ERR]
- **ArgoCD**: [X] Synced / [Y] OutOfSync / [Z] Total Apps
- **Certificate Expiry**: [Shortest expiry time remaining]

## Next Steps

1. [Immediate action required]
2. [Follow-up tasks]
3. [Scheduled maintenance items]

---
**Report Generated**: [YYYY-MM-DD HH:MM]  
**Generated by**: Antigravity  
**Report File**: `reports/status-report-YYYY-MM-DD.md`
```

---
Generated by Antigravity
