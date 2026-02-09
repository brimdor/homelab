# TOOLS.md - Echo

Keep this file copy/paste friendly. Prefer simple, correct actions over clever ones.

## Hosts

- Echo (mario): `10.0.30.10`
- Patch (luigi): `10.0.30.11`

## Inboxes (Agent-to-Agent)

- Patch -> Echo: `~/.openclaw/workspace/patch-inbox/`
- Echo -> Patch: `~/.openclaw/workspace/echo-inbox/`

## Telegram Targets

- Chris DM: `@brimdor` (username) or chatId `8226887535`
- Daily News channel: `-1003384005865`

## Telegram Sending Rules

- Use ONE outbound message per action.
- No "ack" / "confirm" messages.
- If there is no deliverable, do not send anything.

## Canonical Message Tool Calls

DM Chris:
- channel: `telegram`
- action: `send`
- to: `8226887535`
- message: `<text>`

Post to Daily News channel:
- channel: `telegram`
- action: `send`
- to: `-1003384005865`
- message: `<text>`

## SSH Quick Checks (Echo host)

```bash
systemctl --user status openclaw-gateway.service
journalctl --user -u openclaw-gateway.service -n 200 --no-pager
```
