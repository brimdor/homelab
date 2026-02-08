# HEARTBEAT.md - Patch

## Mission

- Keep Echo's OpenClaw healthy and responsive.
- Detect errors/warnings early; fix them deliberately.
- Plan first, act second.

---

## Heartbeat Checklist

1) **Check Echo Gateway Health** (non-disruptive)
   - `ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw gateway status`
   - `ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw channels status --probe`
   - `ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw status --deep`

2) **Scan Echo Logs for Problems**
   - `ssh brimdor@10.0.30.10 journalctl --user -u openclaw-gateway.service -n 200 --no-pager`
   - Look for: `ERROR`, `CRITICAL`, `Invalid config`, `FailoverError`, repeated restarts, channel stop/start loops.

3) **Review TASKS.md**
   - Read `~/.openclaw/workspace/TASKS.md`
   - If a Pending item is relevant and safe, plan it and execute it.
   - When finished, move the task from Pending to Completed.

4) **If No Action Needed**
   - `DO NOTHING`

5) **Post Heartbeat Report** (if issues detected)
   - Post to the canonical heartbeat channel: `-1003716495578`
   - Use the "Echo's Current Issues" template below.

---

## Scheduled Actions

| Cadence | Action | Description |
| :--- | :--- | :--- |
| **Every Heartbeat** | Gateway Health Check | Verify Echo OpenClaw gateway is responsive. |
| **Every Heartbeat** | Log Scan | Check for errors, warnings, and anomalies. |
| **Every Heartbeat** | Task Review | Process pending tasks from `TASKS.md`. |
| **As Needed** | Maintenance Execution | Fix detected issues autonomously. |
| **As Needed** | Heartbeat Report | Post issues to `-1003716495578` if detected. |

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

1) **Notify Echo first** via the shared group (`-5238236031`)
   - If Telegram is down, drop a file to `~/.openclaw/workspace/patch-inbox/`

2) **Proceed with the planned action**

3) **Report completion** in the shared group

Echo is responsible for pausing tasks during maintenance.

---

## Heartbeat Report Template

When posting issues to `-1003716495578`:

```
|-------------------------------------|
| Echo's Current Issues               |
|-------------------------------------|
──────────────
**Alerts:**
1. [Alert description]
2. [Alert description]
──────────────
**Plan (3+ steps):**
1. [Step]
2. [Step]
3. [Step]
──────────────
**Action Items:** [Priority order, high to low]
1. [Action] | [Priority] | [Impact Level]
2. [Action] | [Priority] | [Impact Level]
──────────────
**Order of Operations:**
1. [Step] | [Validation]
2. [Step] | [Validation]
──────────────
`Date: YYYY-MM-DD HH:MM CST` "Patch heartbeat report"
```

---

## Communication Rules

- **Coordination Group:** `-5238236031` (Echo + Patch)
- **Heartbeat Channel:** `-1003716495578` (issue reports only)
- All agent coordination should be autonomous.

---

## Alignment

Patch must keep `HEARTBEAT.md`, `TASKS.md`, `TOOLS.md`, and `MEMORY.md` aligned with Patch's mission.
