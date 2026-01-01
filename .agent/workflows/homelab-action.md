---
description: Execute maintenance spec from issue - Spec-Driven Development for infrastructure operations
sync_locations:
  - .agent/workflows/homelab-action.md
  - .opencode/command/homelab-action.md
  - .gemini/commands/homelab-action.toml
sync_note: IMPORTANT - This file must be kept in sync across all locations. When making changes, update ALL files.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

The text the user typed after the command **is** their priority input - it may specify:
- A specific issue number to work on
- Specific action items to prioritize
- Components to focus on first
- Any special instructions or constraints

---

# Homelab Action -> Execute Maintenance Spec (Spec-Driven Development)

## Overview

This workflow **consumes** the maintenance spec produced by `/homelab-recon` and **executes** it safely, one task at a time, with continuous validation.

It is **Spec-Driven Development (SDD)** adapted to operations execution:
- **Phase 1: Context Loading** - Locate maintenance issue, validate access
- **Phase 2: Specification** - Parse the issue as the authoritative spec
- **Phase 3: Clarification** - Resolve any decision gates requiring input
- **Phase 4: Planning** - Validate ordering, gates, and stop conditions
- **Phase 5: Task Extraction** - Build executable task queue from checkboxes
- **Phase 6: Analysis** - Pre-flight self-audit of task readiness
- **Phase 7: Remediation** - Fix any gaps before execution
- **Phase 8: Implementation** - Execute tasks one-by-one with validation
- **Phase 9: Validation & Closure** - Confirm GREEN, close issue with full documentation

> [!CAUTION]
> **FOUNDATIONAL RULES APPLY** - See `foundational-rules.md`.
> The workflow is NOT complete until ALL layers are GREEN with ZERO issues.
> Do NOT stop, pause, or quit until the work is complete.

> [!IMPORTANT]
> **Do NOT add comments to issues.** Comments are reserved for humans only.
> Always **edit the original issue body** to mark items as completed and update status.

## References
- **Documentation**: https://homelab.eaglepass.io
- **Primary Repo**: https://git.eaglepass.io/ops/homelab
- **Fallback Repo**: https://github.com/brimdor/homelab (auto-synced)
- **Recon Workflow**: `homelab-recon.md` (produces the maintenance spec)
- **Troubleshoot Workflow**: `homelab-troubleshoot.md` (for remediation)

---

## Maintenance Issue Contract (What This Workflow Expects)

The maintenance issue produced by `/homelab-recon` is the **specification**.

The issue body MUST contain:

| Section | Purpose | Required |
|---------|---------|:--------:|
| `## Status` | Overall health status, last updated | YES |
| `## Context Pack` | Cluster identity, health evidence, repo inventory | YES |
| `## Proposed Changes (Spec)` | Table of changes with type, layer, priority, risk | YES |
| `## Execution Plan` | Ordering rules, validation gate, stop conditions | YES |
| `## Action Items (Tasks)` | Top-level `- [ ]` checkboxes, atomic, ordered | YES |
| `## Change Log` | Timestamps and results of each action | YES |
| `## Closure` | Filled by this workflow upon completion | NO (added) |

**Task Format** (each checkbox line):
```
- [ ] [Phase][Seq] P[Priority] [Layer]: [Description]
```
Example: `- [ ] B1 P0 System: resolve Ceph HEALTH_WARN`

If the issue does not meet this contract, return to `/homelab-recon` to fix it.

---

## Phase 1: Context Loading

Output:
```
## Phase 1: Context Loading

Locating maintenance spec and validating access...
```

### 1.1 Validate Access (must succeed)

```bash
# Verify kubectl access
kubectl cluster-info

# Verify controller access (fallback)
ssh -o ConnectTimeout=5 brimdor@10.0.50.120 "echo 'Controller accessible'"

# Verify Gitea API access
source ~/.config/gitea/.env
curl -s "https://git.eaglepass.io/api/v1/user" -H "Authorization: token $GITEA_TOKEN" | jq -r '.login'
```

**Access Status:**
| System | Check | Status |
|--------|-------|:------:|
| Kubernetes | `kubectl cluster-info` | |
| Controller | SSH to 10.0.50.120 | |
| Gitea API | Token validation | |

If any access check fails: STOP and report which access is unavailable.

### 1.2 Locate Maintenance Issue

**Priority Order:**
1. If `$ARGUMENTS` contains an issue number → use that issue
2. Otherwise → find the latest open issue with `maintenance` label

**MCP Tool (preferred):**
```
gitea_list_repo_issues(owner="ops", repo="homelab", state="open")
```
Filter for label `maintenance`, sort by `updated_at` descending.

**API Fallback:**
```bash
source ~/.config/gitea/.env
curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues?state=open&labels=maintenance" \
  -H "Authorization: token $GITEA_TOKEN" | jq -r '.[0] | "Issue #\(.number): \(.title)"'
```

**Output:**
```
Maintenance spec located: Issue #[NUMBER] - [TITLE]
```

If no maintenance issue found: STOP and recommend running `/homelab-recon` first.

### 1.3 Fetch Issue Content

Retrieve the full issue body for parsing in Phase 2.

**MCP Tool (preferred):**
```
gitea_get_issue_by_index(owner="ops", repo="homelab", index=NUMBER)
```

Store:
- `ISSUE_NUMBER` - The issue number
- `ISSUE_TITLE` - The issue title
- `ISSUE_BODY` - The full markdown body

### 1.4 Context Loading Complete

```
✓ Access validated
✓ Maintenance spec: Issue #[NUMBER]
✓ Issue content loaded ([LENGTH] bytes)
```

Proceed to Phase 2.

---

## Phase 2: Specification (Parse the Maintenance Spec)

Output:
```
## Phase 2: Specification

Parsing maintenance spec structure...
```

### 2.1 Validate Issue Contract

Check that all required sections exist in `ISSUE_BODY`:

| Section | Pattern | Found |
|---------|---------|:-----:|
| Status | `## Status` | |
| Context Pack | `## Context Pack` | |
| Proposed Changes | `## Proposed Changes` | |
| Execution Plan | `## Execution Plan` | |
| Action Items | `## Action Items` | |
| Change Log | `## Change Log` | |

**If any required section is missing:**
```
⚠️ Maintenance spec incomplete. Missing sections:
- [list of missing sections]

Returning to /homelab-recon to fix the spec.
```
Halt and recommend running `/homelab-recon` with specific guidance.

### 2.2 Extract Current Status

From `## Status` section, extract:
- **Overall Status**: GREEN / YELLOW / RED
- **Last Updated**: timestamp
- **Source Report**: path to status report

### 2.3 Extract Context Pack

From `## Context Pack` section, extract:
- **Cluster Identity**: K3s version, node count, ArgoCD apps, Ceph health
- **Current Health Evidence**: Node status, non-running pods, ArgoCD apps, Ceph summary
- **Repo Inventory**: Open PRs (Renovate vs user), open issues

### 2.4 Extract Proposed Changes (Spec)

From `## Proposed Changes (Spec)` section, parse the table:

| Item | Type | Layer | Priority | Risk | Summary | Notes |
|------|------|:-----:|:--------:|:----:|---------|-------|

Build a `CHANGES` array with each row as a structured object.

### 2.5 Extract Execution Plan

From `## Execution Plan` section, extract:
- **Ordering**: P0→P3, Metal→Apps, DB last
- **Validation Gate**: commands to run after every change
- **Stop Conditions**: what triggers a halt

### 2.6 Specification Parsed

```
Specification Summary:
- Status: [OVERALL]
- Proposed Changes: [COUNT]
- Priority Distribution: P0=[N], P1=[N], P2=[N], P3=[N]
- Risk Distribution: Critical=[N], High=[N], Medium=[N], Low=[N]
```

Proceed to Phase 3.

---

## Phase 3: Clarification (Decision Gates)

Output:
```
## Phase 3: Clarification

Checking for decision gates requiring input...
```

### 3.1 Scan for Decision Gates

Search `ISSUE_BODY` for markers requiring human decision:
- `[DECISION REQUIRED]`
- `[NEEDS APPROVAL]`
- `[BREAKING CHANGE]`
- Risk level `Critical` on any proposed change

### 3.2 Evaluate Each Gate

For each decision gate found:

| Gate | Location | Context | Resolution Required |
|------|----------|---------|:-------------------:|
| [ID] | [Section] | [Description] | YES/NO |

### 3.3 Resolve Gates

**If no gates require resolution:**
```
✓ No decision gates pending. Proceeding autonomously.
```

**If gates require resolution:**
```
⚠️ Decision gates require input:

1. [Gate description]
   Context: [relevant context]
   Options:
   - A: [option A description]
   - B: [option B description]

Please provide your decision (e.g., "1A" or "1B").
```

Wait for user input, then update the issue body with the decision and proceed.

### 3.4 Clarification Complete

```
✓ All decision gates resolved
```

Proceed to Phase 4.

---

## Phase 4: Planning (Validate Ordering, Gates, Stop Conditions)

Output:
```
## Phase 4: Planning

Validating execution plan...
```

### 4.1 Ordering Rules

Validate the execution plan follows these rules:
1. **Priority Order**: P0 → P1 → P2 → P3
2. **Layer Order** (within priority): Metal → System → Platform → Apps
3. **Database Last**: Within any priority, databases are processed last
4. **One Change at a Time**: No parallel changes; validate GREEN after each

### 4.2 Validation Gate Definition

The validation gate runs after EVERY change:

```bash
# Quick validation - ALL must pass
kubectl get nodes | grep -v "Ready"                             # Empty = GREEN
kubectl get pods -n kube-system | grep -v "Running\|Completed"  # Empty = GREEN
kubectl get applications -n argocd | grep -v "Synced.*Healthy"  # Empty = GREEN
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health # HEALTH_OK = GREEN
kubectl get pods -A --no-headers | grep -v "Running\|Completed" # Empty = GREEN
```

**Pass Criteria:**
- All greps return no output
- Ceph returns `HEALTH_OK`

### 4.3 Stop Conditions

Execution MUST halt if:
- Any validation gate check fails
- Any command returns an unexpected error
- Rollback information is missing for a destructive change
- Human escalation is required (see foundational rules)

### 4.4 Planning Complete

```
✓ Ordering validated
✓ Validation gate defined
✓ Stop conditions understood
```

Proceed to Phase 5.

---

## Phase 5: Task Extraction

Output:
```
## Phase 5: Task Extraction

Building executable task queue...
```

### 5.1 Extract Checkboxes

Parse `## Action Items (Tasks)` section for all lines matching:
```regex
^- \[ \] [A-Z][0-9]+ P[0-3] .*$
```

### 5.2 Build Task Queue

For each checkbox, extract:
- **ID**: e.g., `B1`
- **Priority**: e.g., `P0`
- **Layer**: e.g., `System`
- **Description**: The task description
- **Subtext**: Any non-checkbox lines immediately following (commands, expected results, rollback)

Build a `TASK_QUEUE` array sorted by:
1. Priority (P0 first)
2. Phase letter (A, B, C, D...)
3. Sequence number (1, 2, 3...)

### 5.3 Task Queue Summary

```
Task Queue Built:
| ID | Priority | Layer | Description |
|----|:--------:|:-----:|-------------|
[table of tasks in execution order]

Total Tasks: [N]
Estimated Execution: [rough estimate based on task types]
```

Proceed to Phase 6.

---

## Phase 6: Analysis (Pre-Flight Self-Audit)

Output:
```
## Phase 6: Analysis

Performing pre-flight self-audit...
```

### 6.1 Task Readiness Checks

For each task in `TASK_QUEUE`, verify:

| Check | Description | Pass Criteria |
|-------|-------------|---------------|
| **Atomic** | Single action + single verification | No compound tasks |
| **Commands** | Exact commands provided | No placeholders, no TBD |
| **Expected** | Pass criteria defined | Clear success condition |
| **Rollback** | Rollback defined (or N/A) | Present for destructive actions |
| **Context** | Required context available | No missing references |

### 6.2 Coverage Check

Verify every row in `## Proposed Changes (Spec)` has at least one corresponding task in `## Action Items (Tasks)`.

| Proposed Change | Has Task? | Task IDs |
|-----------------|:---------:|----------|
| [Change 1] | YES/NO | [IDs] |
| ... | | |

**Coverage**: [N]/[M] proposed changes have tasks ([X]%)

### 6.3 Dependency Check

Verify tasks reference existing resources:
- Namespaces exist
- Pods/deployments referenced are present
- PRs referenced are open and mergeable

### 6.4 Analysis Report

```
Pre-Flight Analysis:
| Check | Status | Issues |
|-------|:------:|--------|
| Task Readiness | ✓/⚠ | [count] issues |
| Coverage | ✓/⚠ | [missing count] |
| Dependencies | ✓/⚠ | [invalid count] |

Overall: READY / NEEDS REMEDIATION
```

If READY: Proceed to Phase 8.
If NEEDS REMEDIATION: Proceed to Phase 7.

---

## Phase 7: Remediation (Fix Gaps)

Output:
```
## Phase 7: Remediation

Resolving pre-flight issues...
```

### 7.1 Issue Resolution

For each issue found in Phase 6:

**Missing Commands:**
- Research the correct command
- Add to task subtext in issue body

**Missing Rollback:**
- Document rollback procedure
- Or mark as `Rollback: N/A (non-destructive)`

**Missing Coverage:**
- Add missing tasks to `## Action Items (Tasks)`
- Or update `## Proposed Changes (Spec)` to remove item if not needed

**Invalid Dependencies:**
- Investigate why resource is missing
- Either fix the dependency or update the task

### 7.2 Update Issue

Edit the issue body with all remediations. Do NOT add comments.

### 7.3 Re-run Analysis

Return to Phase 6 and verify all issues resolved.

### 7.4 Gate Check

Repeat remediation cycle until:
- All tasks are READY
- Coverage is 100%
- All dependencies are valid

Then proceed to Phase 8.

---

## Phase 8: Implementation (Execute Tasks)

Output:
```
## Phase 8: Implementation

Beginning task execution...
```

### 8.1 Execution Loop

For each task in `TASK_QUEUE` (in order):

```
┌─────────────────────────────────────────────────────────┐
│                 TASK EXECUTION LOOP                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌──────────────┐                                      │
│   │ Load Task    │                                      │
│   │ [ID] [DESC]  │                                      │
│   └──────┬───────┘                                      │
│          ↓                                              │
│   ┌──────────────┐                                      │
│   │ Execute      │                                      │
│   │ Commands     │                                      │
│   └──────┬───────┘                                      │
│          ↓                                              │
│   ┌──────────────┐     ┌──────────────┐                 │
│   │ Check        │ NO  │ Troubleshoot │                 │
│   │ Expected?    ├────►│ + Rollback   │                 │
│   └──────┬───────┘     └──────┬───────┘                 │
│          │ YES                │                         │
│          ↓                    │                         │
│   ┌──────────────┐           │                          │
│   │ Run          │◄──────────┘                          │
│   │ Validation   │                                      │
│   │ Gate         │                                      │
│   └──────┬───────┘                                      │
│          ↓                                              │
│   ┌──────────────┐     ┌──────────────┐                 │
│   │ ALL GREEN?   │ NO  │ STOP         │                 │
│   │              ├────►│ Troubleshoot │                 │
│   └──────┬───────┘     └──────────────┘                 │
│          │ YES                                          │
│          ↓                                              │
│   ┌──────────────┐                                      │
│   │ Mark Task    │                                      │
│   │ Complete     │                                      │
│   │ Update Issue │                                      │
│   └──────┬───────┘                                      │
│          ↓                                              │
│   ┌──────────────┐                                      │
│   │ More Tasks?  │ YES ──► [Loop to next task]          │
│   └──────┬───────┘                                      │
│          │ NO                                           │
│          ↓                                              │
│   ┌──────────────┐                                      │
│   │ Phase 8      │                                      │
│   │ Complete     │                                      │
│   └──────────────┘                                      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 8.2 Task Execution Protocol

For each task:

**1. ANNOUNCE:**
```
Executing: [ID] P[PRIORITY] [LAYER]: [DESCRIPTION]
```

**2. EXECUTE:**
Run the commands specified in the task subtext.

**3. VERIFY:**
Check the expected result is achieved.

**4. VALIDATE:**
Run the validation gate (§4.2).

**5. UPDATE:**
- Change `- [ ]` to `- [x]` in issue body
- Add entry to `## Change Log`:
  ```
  | [TIMESTAMP] | [ID] | [DESCRIPTION] | [RESULT] | [STATUS AFTER] |
  ```

### 8.3 Special Task Types

#### PR Merge Tasks

For tasks that merge PRs:

```bash
source ~/.config/gitea/.env
PR_NUM=[number]

# 1. Check PR is mergeable
curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/${PR_NUM}" \
  -H "Authorization: token $GITEA_TOKEN" | jq '{mergeable, merged, state}'

# 2. Merge if ready
curl -s -X POST "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls/${PR_NUM}/merge" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"Do": "merge", "delete_branch_after_merge": true}'

# 3. Wait for ArgoCD sync (60 seconds)
sleep 60

# 4. Run validation gate
```

**Renovate PR Ordering** (safest to riskiest):
1. Non-major bundles
2. Platform services (kured, cloudflared, renovate)
3. Monitoring (grafana, prometheus, loki)
4. Core infrastructure (argocd, external-secrets, cert-manager)
5. App templates
6. Databases (CRITICAL - backup required)

#### Ceph Tasks

For Ceph-related tasks:

```bash
# Archive crashes
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph crash archive-all

# Check health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health detail

# OSD operations
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd tree
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd reweight [OSD_ID] 1.0
```

#### Database Upgrade Tasks

> [!DANGER]
> Database upgrades carry the highest risk of data loss.
> NEVER proceed without verified, restorable backups.

Before any database upgrade:
1. Scale down dependent applications
2. Create and verify backup
3. Document recovery procedure
4. Execute upgrade
5. Verify data integrity
6. Scale up applications

### 8.4 Troubleshooting During Execution

If a task fails or validation gate fails:

1. **STOP** - Do not proceed to next task
2. **Log** - Record the failure in Change Log
3. **Investigate** - Check logs, events, describe resources
4. **Fix** - Apply remediation
5. **Rollback** - If fix fails, execute rollback from task subtext
6. **Validate** - Re-run validation gate
7. **Resume** - Only after GREEN

If unable to resolve:
```
⚠️ Task [ID] failed. Manual intervention required.

Error: [description]
Attempted: [what was tried]
Current State: [cluster state]

Halting execution. Address the issue and re-run /homelab-action.
```

### 8.5 Progress Tracking

After each task, report progress:
```
Progress: [COMPLETED]/[TOTAL] tasks
Current Status: GREEN / YELLOW / RED
Last Completed: [ID] - [DESCRIPTION]
```

### 8.6 Implementation Complete

When all tasks are executed:
```
## Implementation Complete

Tasks Completed: [N]/[N]
All Layers: Pending validation
```

Proceed to Phase 9.

---

## Phase 9: Validation & Closure

Output:
```
## Phase 9: Validation & Closure

Running final validation...
```

### 9.1 Final Validation

Run comprehensive validation:

```bash
# Nodes
kubectl get nodes -o wide
kubectl top nodes

# System pods
kubectl get pods -n kube-system

# ArgoCD applications
kubectl get applications -n argocd

# Ceph
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health detail

# All pods
kubectl get pods -A --no-headers | grep -v "Running\|Completed" || echo "All pods healthy"

# Events (recent warnings/errors)
kubectl get events -A --sort-by=.lastTimestamp | tail -50 | grep -E "Warning|Error" || echo "No warnings"
```

### 9.2 Layer Status

| Layer | Status | Evidence |
|-------|:------:|----------|
| **Metal** | | All nodes Ready, resource usage |
| **System** | | Ceph HEALTH_OK, kube-system pods |
| **Platform** | | ArgoCD apps Synced/Healthy |
| **Apps** | | All pods Running |

**Overall Status**: GREEN / YELLOW / RED

### 9.3 Validation Result

**If ALL GREEN:**
```
✓ All layers GREEN. Proceeding to closure.
```
Continue to §9.4.

**If NOT GREEN:**
```
⚠️ Validation failed. Issues found:
[list of issues]

Running /homelab-troubleshoot to resolve...
```

Execute troubleshooting, then re-run validation. Loop until GREEN.

### 9.4 Prepare Closure Notes

Build exhaustive closure documentation:

```markdown
## Closure

### Resolution Summary

| Field | Value |
|-------|-------|
| **Status** | RESOLVED |
| **Started** | [START_TIMESTAMP] |
| **Completed** | [END_TIMESTAMP] |
| **Duration** | [DURATION] |
| **Resolved By** | homelab-action workflow |

---

### Final Infrastructure State

| Layer | Status | Verification |
|-------|:------:|--------------|
| **Metal** | GREEN | [node count] nodes Ready, CPU <[X]%, Memory <[X]% |
| **System** | GREEN | Ceph HEALTH_OK, all kube-system pods Running |
| **Platform** | GREEN | All ArgoCD apps Synced/Healthy, certs valid |
| **Apps** | GREEN | All application pods Running |

**Overall Status**: GREEN

---

### Actions Completed

[Generate table from Change Log]

| Timestamp | Task | Description | Result |
|-----------|:----:|-------------|--------|
| ... | ... | ... | ... |

---

### PRs Merged

| PR | Title | Merged At | Verification |
|----|-------|-----------|--------------|
| #[N] | [Title] | [Timestamp] | ArgoCD synced |

---

### Issues Closed

| Issue | Title | Resolution |
|-------|-------|------------|
| #[N] | [Title] | [How resolved] |

---

### Verification Data (Final Recon)

#### Cluster Status
- **Nodes**: [X]/[X] Ready
- **Pods**: [X] Running, 0 Failed
- **ArgoCD Apps**: [X]/[X] Synced & Healthy
- **Certificates**: [X]/[X] Valid

#### Ceph Status
- **Health**: HEALTH_OK
- **OSDs**: [X] up, [X] in
- **Storage**: [X]% used ([X] TiB available)
- **PGs**: All active+clean

---

### Lessons Learned

[Any observations about recurring issues, process improvements, etc.]

---

*Closed by homelab-action workflow*
*Completion time: [TIMESTAMP]*
```

### 9.5 Update Issue

1. Prepend `[RESOLVED]` to issue title
2. Append closure section to issue body
3. Close the issue

**MCP Tools (preferred):**
```
gitea_edit_issue(owner="ops", repo="homelab", index=NUMBER, 
  title="[RESOLVED] [ORIGINAL_TITLE]",
  body="[UPDATED_BODY_WITH_CLOSURE]",
  state="closed")
```

**API Fallback:**
```bash
source ~/.config/gitea/.env

# Update title and close
curl -s -X PATCH "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/${ISSUE_NUMBER}" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "[RESOLVED] Original Title", "state": "closed"}'
```

### 9.6 Close Related Items

For any PRs merged or issues resolved during execution:

**Close related issues with reference:**
```bash
curl -s -X PATCH "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/${RELATED_ISSUE}" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"body\": \"Resolved as part of maintenance issue #${ISSUE_NUMBER}.\\n\\n---\\n\\n${ORIGINAL_BODY}\", \"state\": \"closed\"}"
```

### 9.7 Final Confirmation

```
## Workflow Complete

**Maintenance Issue**: #[NUMBER] - [TITLE]
**Status**: RESOLVED

### Summary
- Tasks Completed: [N]/[N]
- PRs Merged: [N]
- Issues Closed: [N]
- All Layers: GREEN

### Final State
| Layer | Status |
|-------|:------:|
| Metal | GREEN |
| System | GREEN |
| Platform | GREEN |
| Apps | GREEN |

**Overall**: GREEN

The homelab is healthy. All maintenance actions have been executed and validated.
```

---

## MCP Tool Integration (Preferred)

Use MCP tools for all Gitea interactions when available:

| Operation | Tool |
|-----------|------|
| List issues | `gitea_list_repo_issues` |
| Get issue | `gitea_get_issue_by_index` |
| Edit issue | `gitea_edit_issue` |
| List PRs | `gitea_list_repo_pull_requests` |
| Get PR | `gitea_get_pull_request_by_index` |

---

## Gitea API Fallback (Emergency Only)

> [!WARNING]
> Use only if MCP tools are unavailable.

### Token Location
```bash
~/.config/gitea/.env        # bash/zsh
~/.config/gitea/gitea.fish  # fish
```

### API Base URL
`https://git.eaglepass.io/api/v1`

---

## Escalation Protocol

Escalate to human intervention when:

| Reason | Action |
|--------|--------|
| Physical hardware access required | Document location and issue |
| Data loss risk present | Halt and request confirmation |
| Credentials need rotation | Document and halt |
| Network infrastructure changes | Document and halt |
| Multiple cascading failures | Halt and summarize |
| Root cause undetermined after 3 attempts | Halt with investigation notes |

When escalating:
1. Document the issue clearly in the Gitea issue body
2. Set issue to `needs-human` label if available
3. Stop automated actions
4. Preserve logs and state
5. Summarize findings

---

## Execution Checklist

- [ ] Phase 1: Access validated, maintenance issue located
- [ ] Phase 2: Specification parsed, all sections present
- [ ] Phase 3: Decision gates resolved
- [ ] Phase 4: Execution plan validated
- [ ] Phase 5: Task queue built
- [ ] Phase 6: Pre-flight analysis passed
- [ ] Phase 7: Any gaps remediated (if needed)
- [ ] Phase 8: All tasks executed with validation
- [ ] Phase 9: Final validation - ALL GREEN
- [ ] Phase 9: Closure notes added to issue
- [ ] Phase 9: Maintenance issue closed
- [ ] Phase 9: Related issues/PRs closed
- [ ] **Overall Status: GREEN**

---

## Workflow State Machine

```
[START]
    |
    v
[Phase 1: Context Loading]
    |
    v
[Phase 2: Specification]──────NO─────► [HALT: Run /homelab-recon]
    | (contract met?)           
    | YES
    v
[Phase 3: Clarification]
    |
    v
[Phase 4: Planning]
    |
    v
[Phase 5: Task Extraction]
    |
    v
[Phase 6: Analysis]
    |
    +── READY? ──NO──► [Phase 7: Remediation] ──► [Back to Phase 6]
    |
    | YES
    v
[Phase 8: Implementation]◄──────────────────┐
    |                                        |
    +── Task Failed? ──YES──► [Troubleshoot] |
    |                              |         |
    | All Tasks Complete           └─────────┘
    v
[Phase 9: Validation]
    |
    +── ALL GREEN? ──NO──► [/homelab-troubleshoot] ──► [Back to Phase 9]
    |
    | YES
    v
[Phase 9: Closure]
    |
    v
[END: All Layers GREEN, Issue Closed]
```

---

## Success Criteria

The workflow is complete when ALL of the following are true:

1. **All action items** in the maintenance issue are checked off
2. **Metal Layer**: GREEN - All nodes Ready, resources healthy
3. **System Layer**: GREEN - Ceph HEALTH_OK, core pods healthy
4. **Platform Layer**: GREEN - All ArgoCD apps Synced/Healthy
5. **Apps Layer**: GREEN - All application pods running
6. **Overall Status**: GREEN
7. **Validation gate**: Passes with no output
8. **All PRs actioned**: Merged or closed as specified
9. **All related issues closed**: With resolution references
10. **Exhaustive closure notes**: Added to issue
11. **Maintenance issue**: Closed with `[RESOLVED]` prefix

---

## Notes

- Always prioritize data safety over speed
- One task at a time, validate before proceeding
- Update the issue frequently for visibility
- If in doubt, pause and assess
- This workflow complements `/homelab-recon` - use recon to produce the spec
- Human escalation is a valid outcome for complex issues
