---
description: Full service verification and validation across the entire Homelab
sync_locations:
  - ~/.gemini/antigravity/global_workflows/homelab-maintenance.md
  - ~/.config/opencode/command/homelab-maintenance.md
sync_note: IMPORTANT - This file must be kept in sync across both locations. When making changes, update BOTH files.
---

# Homelab Maintenance Workflow

## Overview
This workflow performs a comprehensive service verification and validation across the entire Homelab infrastructure.

> [!IMPORTANT]
> **Sync Requirement**: This workflow exists in two locations that must stay synchronized:
> - `~/.gemini/antigravity/global_workflows/homelab-maintenance.md` (Antigravity)
> - `~/.config/opencode/command/homelab-maintenance.md` (Opencode)
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

## Steps

### Step 1: Access Homelab Resources

#### Option A: Local System (Preferred)
Verify local access to Kubernetes cluster and homelab resources.

#### Option B: Controller (Fallback Only)
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

### Step 2: Clone/Update Homelab Repository
```bash
# Clone if not present, or pull latest changes
git clone https://git.eaglepass.io/ops/homelab ~/homelab 2>/dev/null || (cd ~/homelab && git pull)
```

### Step 3: Review Documentation
Navigate to https://homelab.eaglepass.io and review:
- Current architecture and services
- Expected service states
- Known issues or maintenance notes

### Step 4: Perform Full Service Verification
Check all services across the homelab:

1. **Kubernetes Cluster Health**
   - Verify all nodes are Ready
   - Check system pods (kube-system, etc.)
   - Validate storage and networking

2. **ArgoCD Applications**
   - Check sync status of all applications
   - Identify any degraded or out-of-sync apps
   - Review recent deployment history

3. **Core Infrastructure Services**
   - DNS (internal and external)
   - Certificate management
   - Ingress controllers
   - Storage provisioners

4. **Platform Applications**
   - Verify each application is running
   - Check service endpoints and health
   - Review resource utilization

5. **Security Audit**
   - Check for expired certificates
   - Review secret rotation status
   - Validate network policies
   - Check for security advisories on running images

6. **Backup Verification**
   - Verify backup jobs are running
   - Check backup storage status
   - Validate recent backup integrity

### Step 5: Check for Available Updates
For each component, check:
- Container image updates
- Helm chart updates
- Operator/CRD updates
- Base system updates

### Step 6: Generate Maintenance Report

If any updates or issues are found, create a comprehensive report:

#### Report Requirements:
- **Location**: Create as a new issue at https://git.eaglepass.io/ops/homelab/issues
- **Title**: `[Maintenance Report] YYYY-MM-DD - Service Verification Results`

#### Report Contents:
1. **Executive Summary**
   - Overall health status
   - Critical findings
   - Recommended timeline for updates

2. **Service Status Overview**
   - Table of all services and their current state
   - Version comparison (current vs available)

3. **Security Findings**
   - Expired or expiring certificates
   - Outdated images with CVEs
   - Configuration concerns

4. **Update Plan**
   - Ordered list of updates (dependencies first)
   - Estimated downtime per update
   - Rollback procedures
   - Placeholder for user to schedule: `[ ] Scheduled for: ________`

5. **Maintenance Windows**
   - Suggested order of operations
   - Pre-update checklist
   - Post-update validation steps

6. **Risk Assessment**
   - Impact analysis for each update
   - Dependencies and potential cascading effects
   - Mitigation strategies

### Step 7: Cleanup and Report
1. Close any temporary connections
2. Summarize findings to the user
3. Provide link to created issue (if applicable)

## Notes
- Always prioritize security updates
- Document any manual interventions required
- Keep the homelab running smoothly with minimal disruption
- Consider maintenance windows for critical updates

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
> only use the following API commands if the MCP tools above are failing or unavailable.

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
  -d '{"title": "[Maintenance Report] YYYY-MM-DD - Title", "body": "Report content"}'
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

#### Using with JSON Files
For large comment/issue bodies, save JSON to a file and use:
```bash
curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/1/comments" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/path/to/comment.json
```

### API Documentation
Full API documentation: https://git.eaglepass.io/api/swagger
