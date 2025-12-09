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
This workflow analyzes the entire Homelab stack from bare metal to user applications to validate health and performance.

## Reconnaissance Layers & Criteria

### 1. Metal Layer (Hardware & OS)
**Validation Steps**:
- Check Controller reachability (ssh brimdor@10.0.50.120)
- Check node reachability via Controller (see SSH Access below)
- Check Resource Usage (CPU, RAM, Disk) via kubectl top nodes
- Check System Temperatures (if accessible)
- Check ZFS/Raid health if applicable

#### SSH Access to Nodes
Direct SSH to nodes from workstation is **intentionally blocked**. To access nodes:

1. SSH to Controller: `ssh brimdor@10.0.50.120`
2. Navigate to homelab: `cd homelab`
3. Start tools container: `make tools`
4. Wait ~20 seconds for container to be ready
5. SSH to node from container: `ssh root@<nodeIP>`

**Controller**: 10.0.50.120 (user: brimdor, passwordless SSH)
**Nodes**: SSH as root from Controller only

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | Controller reachable. All nodes online. CPU < 50%, RAM < 80%, Disk < 80%. Temps normal. No hardware errors. |
| 🟡 **Yellow** | High resource usage (CPU > 80% or RAM > 90%). Disk > 90%. Temps elevated but safe. Minor hardware warnings. |
| 🔴 **Red** | Controller unreachable. Node offline. Disk full (> 98%). Critical hardware failures. Overheating. |

### 2. System Layer (Kubernetes Core)
**Validation Steps**:
- `kubectl get nodes` (All Ready).
- `kubectl get pods -n kube-system` (All Running/Completed).
- Check CNI (Cilium) status.
- Check CSI (Rook-Ceph) status and health.

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | All nodes Ready. Core pods healthy. Ceph health HEALTH_OK. Network policies active. |
| 🟡 **Yellow** | Single node NotReady (if HA). Non-critical system pods restarting. Ceph HEALTH_WARN (non-critical). |
| 🔴 **Red** | Multiple nodes down. API Server unreachable. Ceph HEALTH_ERR. CNI failures blocking traffic. |

### 3. Platform Layer (Middleware)
**Validation Steps**:
- Check GitOps (ArgoCD) sync status.
- Check Ingress (NGINX) functionality.
- Check Certificate Management (Cert-Manager).
- Check Identity Provider (Dex/Kanidm).
- Check Monitoring (Prometheus/Grafana).

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | ArgoCD Synced & Healthy. Ingress serving traffic. Certs valid. Auth working. Monitoring active. |
| 🟡 **Yellow** | ArgoCD OutOfSync (but functional). Expiring certs (< 15 days). Minor monitoring gaps. |
| 🔴 **Red** | ArgoCD broken. Ingress 404/503 loops. Expired certs. Auth down. |

### 4. Apps Layer (User Services)
**Validation Steps**:
- Check App Pods status.
- Check Service endpoints (HTTP 200).
- Check Application logs for errors.

| Status | Criteria |
|--------|----------|
| 🟢 **Green** | All apps Running. Endpoints responsive. No critical log errors. |
| 🟡 **Yellow** | Non-critical apps down. Slow response times. Minor functional bugs. |
| 🔴 **Red** | Critical apps (Emby, Gitea, etc.) down. Data corruption signs. Unusable services. |

## Execution Steps

1.  **Run Metal Checks**: SSH into nodes, check resources.
2.  **Run System Checks**: `kubectl` commands for nodes and system namespace.
3.  **Run Platform Checks**: Check ArgoCD, Ingress, Certs.
4.  **Run App Checks**: Curl endpoints, check specific app pods.
5.  **Generate Report**: Fill out the template below and save to file.

## Report Output

**Reports must always be saved to the `reports/` folder** in the homelab repository.

### File Naming Convention
```
reports/status-report-YYYY-MM-DD.md
```

### Example
```
reports/status-report-2025-12-09.md
```

If multiple reports are generated on the same day, append a sequence number:
```
reports/status-report-2025-12-09-2.md
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
   - Update the "Last updated" timestamp at the bottom
   - Preserve any existing content that is still relevant (action items, schedules, etc.)

3. **If no existing issue exists**:
   - Create a new issue with title: `[Maintenance Report] YYYY-MM-DD - Homelab Status`
   - Include the full report in the issue body
   - Add appropriate labels based on status:
     - `status:green` - All systems healthy
     - `status:yellow` - Warnings present
     - `status:red` - Critical issues

### MCP Tool Usage (Preferred)

```
# Search for existing issues
Use Gitea MCP: list_issues with state="open"

# Create new issue (only if none exists)
Use Gitea MCP: create_issue with title, body, labels

# Edit existing issue body (preferred for updates)
Use Gitea MCP: edit_issue with issue_number, body
```

### API Fallback (If MCP Unavailable)

```bash
# Search for existing maintenance issues
source ~/.config/gitea/.env
curl -s "$GITEA_URL/api/v1/repos/ops/homelab/issues?state=open" \
  -H "Authorization: token $GITEA_TOKEN"

# Get existing issue body for merging
curl -s "$GITEA_URL/api/v1/repos/ops/homelab/issues/{issue_number}" \
  -H "Authorization: token $GITEA_TOKEN" | jq -r '.body'

# Edit existing issue (PATCH to update body)
curl -s -X PATCH "$GITEA_URL/api/v1/repos/ops/homelab/issues/{issue_number}" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body": "Updated merged content..."}'

# Create new issue (only if no maintenance issue exists)
curl -s -X POST "$GITEA_URL/api/v1/repos/ops/homelab/issues" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "[Maintenance Report] YYYY-MM-DD - Homelab Status", "body": "Report content..."}'
```

### Merging Data into Existing Issues

When updating an existing issue, follow these guidelines:

1. **Preserve existing structure** - Keep the overall format of the existing issue
2. **Update status tables** - Replace old status data with current findings
3. **Keep action items** - Preserve checkboxes and scheduled items from humans
4. **Update timestamps** - Change "Last updated" to current date/time
5. **Add recon section** if not present - Include a "Latest Recon Status" section
6. **Reference report file** - Add link to `reports/status-report-YYYY-MM-DD.md`

## Report Template

# Homelab Status Report - [YYYY-MM-DD]

## Executive Summary
**Overall Status**: [🟢 GREEN / 🟡 YELLOW / 🔴 RED]
**Summary**: [Brief summary of the overall state of the lab. Mention the most critical finding.]

## Detailed Status
| Layer | Status | Key Findings |
|-------|:------:|--------------|
| **Metal** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2] |
| **System** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2] |
| **Platform** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2] |
| **Apps** | [🟢/🟡/🔴] | - [Finding 1]<br>- [Finding 2] |

## Issues & Recommendations
### Critical (Red)
- [ ] **Issue**: [Description]
  - **Fix**: [Proposed remediation]

### Warnings (Yellow)
- [ ] **Issue**: [Description]
  - **Fix**: [Proposed remediation]

### Observations (Green)
- [Note on optimizations or healthy status]

## Verification Data
- **Nodes**: [Count] Online / [Count] Total
- **Storage**: [Usage]% Used ([Free] free)
- **Top Resource Consumer**: [Pod/Process Name]

---
Generated by Antigravity
