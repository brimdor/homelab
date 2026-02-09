# TOOLS.md - Patch Local Notes

This file is the operator-specific cheat sheet for this gateway.
Keep it concrete and copy/paste friendly.

## Agents

- Echo:  10.0.30.10 (orchestrator agent)
- Patch: 10.0.30.11 (this gateway)

## Echo Gateway Access

SSH commands for Echo health checks and maintenance:

```bash
# Gateway status
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw gateway status

# Channel status with probe
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw channels status --probe

# Deep status check
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw status --deep

# Service logs (last 200 lines)
ssh brimdor@10.0.30.10 journalctl --user -u openclaw-gateway.service -n 200 --no-pager
```

## Disruptive Work Protocol

Before performing disruptive maintenance on Echo (gateway restart, config changes, channel restarts):

1. Drop a notice file to Echo's inbox: `~/.openclaw/workspace/patch-inbox/`
2. File format: `YYYYMMDDTHHMMSSZ-maintenance.md` with frontmatter
3. Proceed with the planned action
4. Drop a completion notice to Echo's inbox

## Agent-to-Agent Communication (File Inbox)

Agent coordination with Echo uses **file inboxes** (NOT Telegram groups):

| Agent | Inbox Path | Purpose |
|-------|------------|---------|
| **Echo** | `~/.openclaw/workspace/patch-inbox/` | Patch drops maintenance notices here |
| **Patch** | `~/.openclaw/workspace/echo-inbox/` | Echo drops task requests here |

### Sending a Message to Echo

```bash
# Create a maintenance notice for Echo
ssh brimdor@10.0.30.10 "mkdir -p ~/.openclaw/workspace/patch-inbox"
ssh brimdor@10.0.30.10 "cat > ~/.openclaw/workspace/patch-inbox/$(date +%Y%m%dT%H%M%SZ)-maintenance.md << INNER_EOF
---
type: maintenance
priority: normal
from: patch
timestamp: $(date -Iseconds)
---

# Maintenance Notice

Content here.
INNER_EOF"
```

### File Format

```markdown
---
type: maintenance|checklist|status|alert
priority: low|normal|high|critical
from: echo|patch
timestamp: 2026-02-09T14:30:00Z
---

# Subject Line

Message content here.
```

## Messaging Targets (Telegram DMs Only)

When sending Telegram messages, use DMs only (no group messages for agent coordination):

**Telegram**
- Heartbeat Channel: `-1003716495578` (Echo's Current Issues Report)
- Chris DM: `@brimdor` (for critical alerts requiring human attention)

**Rules**
- Do not attempt to send Telegram targets via Nostr (or vice versa).
- Nostr targets must be `npub...`
- Telegram targets must be a numeric chatId.
- Agent-to-agent coordination uses file inboxes, NOT Telegram groups.

## Web Search Limits (Brave)

If web_search returns 429 (rate limit), stop retrying; defer and/or batch searches.
Do not set ui_lang: "en"; use en-US if needed.

## Subagents

- Prioritize creating subagents (via sessions_spawn) for repeated and ongoing tasks.
- Hand off long-running or periodic work to these subagents to keep the main thread clear.
