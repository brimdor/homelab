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
ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw gateway status

# Channel status with probe
ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw channels status --probe

# Deep status check
ssh brimdor@10.0.30.10 ~/.npm-global/bin/openclaw status --deep

# Service logs (last 200 lines)
ssh brimdor@10.0.30.10 journalctl --user -u openclaw-gateway.service -n 200 --no-pager
```

## Disruptive Work Protocol

Before performing disruptive maintenance on Echo (gateway restart, config changes, channel restarts):

1. Notify Echo via the shared group (`-5238236031`)
2. If Telegram is down, drop a file to `~/.openclaw/workspace/patch-inbox/`
3. Proceed with the planned action
4. Report completion in the shared group

## Messaging Targets

When sending messages, the target format is channel-specific.

**Telegram**
- Heartbeat Channel: `-1003716495578` (Echo's Current Issues Report)
- Coordination Group: `-5238236031` (Echo + Patch)

**Rules**
- Do not attempt to send Telegram targets via Nostr (or vice versa).
- Nostr targets must be `npub...`
- Telegram targets must be a numeric chatId.

## Agent Communication Channel (Telegram)

Shared group for direct Echo ↔ Patch communication:
- Group ID: `-5238236031`
- Echo bot: @Echo_orchestrator_bot
- Patch bot: @patch_repair_bot

**Rules:**
- Require @mention to trigger response (prevents loops)
- Use this channel when Echo needs to be notified of disruptive work
- Keep messages concise; this is an operational channel
- **patch-inbox is ONLY used when Telegram is down** — always prefer the shared group for real-time coordination

## Web Search Limits (Brave)

If web_search returns 429 (rate limit), stop retrying; defer and/or batch searches.
Do not set ui_lang: "en"; use en-US if needed.

## Subagents

- Prioritize creating subagents (via sessions_spawn) for repeated and ongoing tasks.
- Hand off long-running or periodic work to these subagents to keep the main thread clear.
