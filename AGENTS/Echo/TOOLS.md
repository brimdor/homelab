# TOOLS.md - Echo Local Notes

This file is the operator-specific cheat sheet for this gateway.
Keep it concrete and copy/paste friendly.

## Agents

- Echo:  10.0.30.10 (this gateway)
- Patch: 10.0.30.11 (maintenance agent)

## When a Patch Notice Arrives

Monitor the shared Telegram group (`-5238236031`) for notifications from Patch.

If Patch reports disruptive work:
1. Pause current tasks
2. Wait for Patch's "All Clear"
3. Resume operations

**Fallback (only if Telegram is down):** Check `~/.openclaw/workspace/patch-inbox/` for maintenance notices.

## Messaging Targets

When sending messages, the target format is channel-specific.

**Telegram**
- Coordination Group: `-5238236031` (Echo + Patch)
- Daily News Channel: `-1003384005865`

**Nostr**
- Echo npub: (add if configured)

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
- Use this channel for health coordination with Patch
- Keep messages concise; this is an operational channel

## Web Search Limits (Brave)

If web_search returns 429 (rate limit), stop retrying; defer and/or batch searches.
Do not set ui_lang: "en"; use en-US if needed.

## Subagents

- Prioritize creating subagents (via sessions_spawn) for repeated and ongoing tasks.
- Hand off long-running or periodic work to these subagents to keep the main thread clear.
