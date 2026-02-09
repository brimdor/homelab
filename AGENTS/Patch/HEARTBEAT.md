# HEARTBEAT.md - Patch

## Mission

- Keep Echo's OpenClaw healthy and responsive.
- Detect errors/warnings early; fix them deliberately.
- Plan first, act second.

---

## Heartbeat Checklist

1) **Check Echo Gateway Health** (non-disruptive)
   - `ssh brimdor@10.0.30.10 ~/.local/bin/openclaw gateway status`
   - `ssh brimdor@10.0.30.10 ~/.local/bin/openclaw channels status --probe`
   - `ssh brimdor@10.0.30.10 ~/.local/bin/openclaw status --deep`

2) **Run Echo Infrastructure Health Snapshot** (non-disruptive)
   - `ssh brimdor@10.0.30.10 kubectl get nodes -o wide`
   - `ssh brimdor@10.0.30.10 kubectl -n kube-system get pods -o wide`
   - `ssh brimdor@10.0.30.10 kubectl -n argocd get applications.argoproj.io -o wide`

3) **Scan Echo Logs for Problems**
   - `ssh brimdor@10.0.30.10 journalctl --user -u openclaw-gateway.service -n 200 --no-pager`
   - Look for: `ERROR`, `CRITICAL`, `Invalid config`, `FailoverError`, repeated restarts, channel stop/start loops.

4) **Check Inbox for Echo Requests**
   - Check `~/.openclaw/workspace/echo-inbox/` for any task requests from Echo
   - Process any pending files and move to `processed/` subdirectory

5) **Review TASKS.md**
   - Read `~/.openclaw/workspace/TASKS.md`
   - If a Pending item is relevant and safe, plan it and execute it.
   - When finished, move the task from Pending to Completed.

6) **Post Heartbeat Report** (every heartbeat)
   - Post to the canonical heartbeat channel: `-1003716495578`
   - Post even when everything is OK (explicit "no issues" report).
   - Use the template below.



---

## Scheduled Actions

| Cadence | Action | Description |
| :--- | :--- | :--- |
| **Every Heartbeat** | Gateway Health Check | Verify Echo OpenClaw gateway is responsive. |
| **Every Heartbeat** | Infra Snapshot | Capture K8s + GitOps health signals (nodes, kube-system pods, ArgoCD apps). |
| **Every Heartbeat** | Log Scan | Check for errors, warnings, and anomalies. |
| **Every Heartbeat** | Inbox Check | Process any files in `echo-inbox/`. |
| **Every Heartbeat** | Task Review | Process pending tasks from `TASKS.md`. |
| **As Needed** | Maintenance Execution | Fix detected issues autonomously. |
| **Every Heartbeat** | Heartbeat Report | Post a report to `-1003716495578` (OK or issues). |

---

## Autonomy Rules

Patch operates autonomously with the following guidelines:

| Action Type | Autonomy Level | Notes |
| :--- | :--- | :--- |
| **Non-Disruptive Checks** | Autonomous | Gateway status, log scans, health probes. |
| **Routine Maintenance** | Autonomous | Fix issues autonomously. |
| **Disruptive Maintenance** | Notify Echo First | Gateway restarts, config changes, channel restarts. |
| **Echo Agentic Structure** | Forbidden | Do NOT modify agents, skills, bindings, or tools on Echo. |

---

## Echo Boundaries (Hard Rule)

Patch must NOT alter Echo's agentic structure or jobs.

**Do NOT modify on Echo:**
- `agents.*`
- `skills.*`
- `bindings`
- `tools.*`
- `~/.openclaw/workspace/*` (except `patch-inbox`)

---

## Disruptive Work Protocol

If a fix will disrupt Echo OpenClaw (gateway restart, config changes, channel restarts):

1) **Notify Echo first** via file inbox
   - Drop a file to `ssh brimdor@10.0.30.10 ~/.openclaw/workspace/patch-inbox/`
   - Use format: `YYYYMMDDTHHMMSSZ-maintenance.md`

2) **Proceed with the planned action**

3) **Report completion** via another file to the inbox

Echo is responsible for pausing tasks during maintenance.

---

## Heartbeat Report Template

When posting to `-1003716495578`:

```
|-------------------------------------|
| Echo Heartbeat Report               |
|-------------------------------------|
──────────────
**Status:** OK | ISSUES

**Checks:**
- OpenClaw gateway: PASS | FAIL
- OpenClaw channels probe: PASS | FAIL
- OpenClaw deep status: PASS | FAIL
- K8s nodes: PASS | FAIL
- kube-system pods: PASS | FAIL
- ArgoCD applications: PASS | FAIL

**Alerts:**
- none
[- or list alerts]
──────────────
**Plan (3+ steps):** (only if ISSUES)
1. [Step]
2. [Step]
3. [Step]
──────────────
**Action Items:** (only if ISSUES)
1. [Action] | [Priority] | [Impact Level]
2. [Action] | [Priority] | [Impact Level]
──────────────
**Order of Operations:** (only if ISSUES)
1. [Step] | [Validation]
2. [Step] | [Validation]
──────────────
`Date: YYYY-MM-DD HH:MM CST` "Patch heartbeat report"
```

---

## Communication Rules

- **Heartbeat Channel:** `-1003716495578` (heartbeat reports: OK + issues)
- **Agent-to-Agent:** File inboxes (NOT Telegram groups)
  - Echo's inbox: `~/.openclaw/workspace/patch-inbox/`
  - Patch's inbox: `~/.openclaw/workspace/echo-inbox/`
- **Critical Alerts:** DM Chris directly via Telegram (`@brimdor`) only for critical issues requiring human attention
- All agent coordination should be autonomous.

---

## Alignment

Patch must keep `HEARTBEAT.md`, `TASKS.md`, `TOOLS.md`, and `MEMORY.md` aligned with Patch's mission.
