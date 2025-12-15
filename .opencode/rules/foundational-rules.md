---
description: Foundational rules for all homelab workflows - MUST be followed without exception
type: foundational
applies_to:
  - homelab-troubleshoot
  - homelab-recon
  - homelab-action
sync_locations:
  - ~/.gemini/antigravity/global_workflows/_foundational-rules.md
  - ~/.config/opencode/command/_foundational-rules.md
sync_note: IMPORTANT - This file must be kept in sync across all locations. When making changes, update ALL files.
---

# Homelab Foundational Rules

> [!CAUTION]
> **These rules are ABSOLUTE and NON-NEGOTIABLE.**
> Every homelab workflow (`homelab-troubleshoot`, `homelab-recon`, `homelab-action`) MUST adhere to these rules.
> There are NO exceptions. Violating these rules means the work is INCOMPLETE.

---

## Rule 1: Completion Requires ALL GREEN Status

**The workflow is NOT complete until ALL of the following conditions are met:**

### Layer Status Requirements

| Layer | GREEN Criteria | ANY deviation = NOT COMPLETE |
|-------|----------------|------------------------------|
| **Metal** | All nodes `Ready`, no resource pressure, no hardware warnings | A single `NotReady` node = NOT COMPLETE |
| **System** | Ceph `HEALTH_OK`, all kube-system pods `Running` | `HEALTH_WARN` or any non-Running pod = NOT COMPLETE |
| **Platform** | All ArgoCD apps `Synced` AND `Healthy` | A single `OutOfSync` or `Degraded` app = NOT COMPLETE |
| **Apps** | All pods `Running`, no error states | A single `CrashLoopBackOff` or `Error` = NOT COMPLETE |

### Overall Status Requirement

```
OVERALL STATUS = GREEN
        ↓
   Only when ALL four layers are GREEN
        ↓
   Only then is the workflow COMPLETE
```

**There is NO partial success. There is NO "good enough."**

---

## Rule 2: Zero Tolerance for Issues of ANY Severity

**ALL issues must be resolved regardless of severity level:**

| Severity | Requirement | Example |
|----------|-------------|---------|
| **CRITICAL** | Must be resolved | Node down, data at risk |
| **HIGH** | Must be resolved | Security vulnerabilities, service outages |
| **MEDIUM** | Must be resolved | Warnings, suboptimal configurations |
| **LOW** | Must be resolved | Minor cleanup, documentation gaps |

> [!WARNING]
> **Even LOW priority issues block completion.**
> If you find yourself thinking "I'll skip this minor issue," STOP.
> The workflow is NOT complete until the issue is resolved.

---

## Rule 3: No Pause, No Stop, No Quit Until Complete

**The workflow operates in a continuous execution loop:**

```
┌─────────────────────────────────────────────────────────┐
│                    EXECUTION LOOP                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│   │ EXECUTE  │ → │ VALIDATE │ → │ CHECK    │          │
│   │ ACTION   │    │ RESULTS  │    │ STATUS   │          │
│   └──────────┘    └──────────┘    └──────────┘          │
│        ↑                               │                 │
│        │         ┌──────────┐          │                 │
│        │         │ ALL      │←─────────┤                 │
│        │         │ GREEN?   │          │                 │
│        │         └──────────┘          │                 │
│        │              │                │                 │
│        │         NO   │   YES          │                 │
│        │              ↓                │                 │
│        └──────────────┘          ┌─────┴─────┐          │
│                                  │ COMPLETE! │          │
│                                  │ EXIT LOOP │          │
│                                  └───────────┘          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**The ONLY exit condition is ALL GREEN status.**

### Prohibited Actions

- ❌ **DO NOT** stop because "most things are working"
- ❌ **DO NOT** pause and ask the user "should I continue?"
- ❌ **DO NOT** quit because an issue seems difficult
- ❌ **DO NOT** defer issues to "a later time"
- ❌ **DO NOT** mark the workflow as complete with any non-GREEN status
- ❌ **DO NOT** ignore warnings or non-critical issues

### Required Actions

- ✅ **DO** continue until ALL layers are GREEN
- ✅ **DO** resolve every issue found, regardless of severity
- ✅ **DO** iterate: execute → validate → repeat until GREEN
- ✅ **DO** escalate blockers only when genuinely blocked by external factors
- ✅ **DO** document all actions taken and their outcomes

---

## Rule 4: Continuous Validation Loop

**After every significant action, validate the current state:**

```bash
# Quick validation check - run after each action
kubectl get nodes | grep -v "Ready"               # Should be empty
kubectl get pods -n kube-system | grep -v "Running\|Completed"  # Should be empty
kubectl get applications -n argocd | grep -v "Synced.*Healthy"  # Should be empty
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health  # Should be HEALTH_OK
```

**If any check fails, the loop continues. No exceptions.**

---

## Rule 5: Exhaustive Completion Criteria

**Before declaring a workflow complete, ALL of the following must be true:**

### For `homelab-troubleshoot`:
- [ ] Root cause identified and documented
- [ ] Fix applied and verified
- [ ] All layers validated GREEN
- [ ] No residual warnings or issues
- [ ] Issue documented if significant

### For `homelab-recon`:
- [ ] All layers analyzed and reported
- [ ] All security findings addressed or documented
- [ ] All available updates catalogued
- [ ] Status report generated and saved
- [ ] Gitea issue created/updated with findings
- [ ] Overall status is GREEN (or issues are tracked for action)

### For `homelab-action`:
- [ ] All action items from maintenance issue executed
- [ ] All PRs processed (merged, closed, or documented why not)
- [ ] All related issues processed (resolved or documented)
- [ ] ArgoCD sync verified after changes
- [ ] Full recon validation completed
- [ ] All layers GREEN
- [ ] Maintenance issue updated with exhaustive closure notes
- [ ] Issue closed with complete documentation

---

## Rule 6: Escalation Protocol

**The ONLY acceptable reasons to pause or notify the user:**

| Reason | Action | Example |
|--------|--------|---------|
| **Human intervention required** | Notify user with specific ask | "USB device found dead - requires physical replacement" |
| **Destructive action confirmation** | Notify user for approval | "Deleting PVC with production data - confirm?" |
| **External dependency blocked** | Notify user with context | "Waiting for DNS propagation, ETA 24 hours" |
| **Security finding requires decision** | Present options to user | "Found CVE-2024-XXXX - options: patch, disable, accept risk" |

**These are the ONLY acceptable reasons. Everything else should be handled autonomously.**

---

## Rule 7: Success Definition

**A workflow is SUCCESSFUL if and only if:**

1. **Overall Status = GREEN**
2. **Metal Layer = GREEN** (all nodes Ready)
3. **System Layer = GREEN** (Ceph HEALTH_OK, all system pods Running)
4. **Platform Layer = GREEN** (all ArgoCD apps Synced + Healthy)
5. **Apps Layer = GREEN** (all pods Running)
6. **Issue Count = ZERO** (no issues of any severity remaining)

**If ANY of the above conditions is not met, the workflow is NOT complete.**

---

## Enforcement

Each workflow file MUST include at the top:

```markdown
> [!CAUTION]
> **This workflow follows the Foundational Rules defined in `_foundational-rules.md`.**
> The workflow is NOT complete until ALL layers are GREEN with ZERO issues.
> Do NOT stop, pause, or quit until the work is complete.
```

---

*These rules ensure the Homelab infrastructure is always maintained to the highest standard.*
*No partial success. No ignored warnings. Only GREEN means complete.*
