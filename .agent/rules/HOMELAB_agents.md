---
description: OpenClaw AI agents - Echo and Patch configuration, communication, and management
type: reference
applies_to:
  - homelab-troubleshoot
  - homelab-recon
  - homelab-action
sync_locations:
  - ~/.gemini/SUB_RULES/HOMELAB_agents.md
  - ~/.gemini/antigravity/global_workflows/HOMELAB_agents.md
  - ~/.config/opencode/command/HOMELAB_agents.md
  - ~/Documents/Github/homelab/.agent/rules/HOMELAB_agents.md
  - ~/Documents/Github/homelab/.opencode/rules/HOMELAB_agents.md
sync_note: OpenClaw agent reference. Update when agent configuration changes.
---

# OpenClaw Agents

The homelab runs two OpenClaw AI agents on dedicated Raspberry Pi nodes. These agents operate autonomously and communicate via Telegram.

---

## Agent Overview

| Property | Echo | Patch |
|----------|------|-------|
| **Purpose** | Primary orchestrator agent | Maintenance and repair agent |
| **Host** | mario (`10.0.30.10`) | luigi (`10.0.30.11`) |
| **Identity** | Platform manager, project coordinator | Echo's health monitor and fixer |
| **Telegram Bot** | `@Echo_orchestrator_bot` | `@patch_repair_bot` |
| **Primary Model** | `google-antigravity/gemini-3-pro-high` | `github-copilot/gpt-5-mini` |
| **Theme** | Orchestrator | Orchestrator |
| **Emoji** | Rocket | Bandage |

---

## Echo - Primary Orchestrator

### Purpose
Echo is the primary AI orchestrator for the homelab. It handles:
- Project management and coordination
- User communication via Telegram/Nostr
- Daily news and system health reports
- Task delegation and workflow management

### Identity
- **Name**: Echo
- **Persona**: Persistent, determined, and creative project manager
- **Human Partner**: Chris (`@brimdor`)

### Host Details
- **Node**: mario
- **IP Address**: `10.0.30.10`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

---

## Patch - Maintenance Agent

### Purpose
Patch monitors Echo's health and performs maintenance when issues are detected:
- Gateway health monitoring
- Model/provider diagnostics
- Configuration repairs
- Service restarts when needed

### Identity
- **Name**: Patch
- **Persona**: Autonomous maintenance agent
- **Operating Mode**: Autonomous by default; informs Chris only for critical items

### Host Details
- **Node**: luigi
- **IP Address**: `10.0.30.11`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

### Patch Boundaries (Hard Rules)
Patch must **never** alter Echo's agentic structure or jobs. Do NOT modify on Echo:
- `agents.*` (agents.list, agents.defaults, identities)
- `skills.*`
- `bindings`
- `tools.*` (unless explicitly required)
- `~/.openclaw/workspace/*` (except `patch-inbox/`)

Allowed infrastructure changes on Echo (with backups + verification):
- `channels.*` (Telegram/Nostr hardening, credentials, allowlists)
- `gateway.*` (bind, auth token, trusted proxies)
- `models/providers/auth` (provider availability, fallbacks)
- OS/service hygiene (systemd, disk space)

---

## File Locations

### OpenClaw Installation

| Component | Echo (mario) | Patch (luigi) |
|-----------|--------------|---------------|
| **Binary** | `~/.local/bin/openclaw` | `~/.npm-global/bin/openclaw` |
| **Config** | `~/.openclaw/openclaw.json` | `~/.openclaw/openclaw.json` |
| **Workspace** | `~/.openclaw/workspace/` | `~/.openclaw/workspace/` |
| **Agent Dir** | `~/.openclaw/agents/main/agent/` | `~/.openclaw/agents/main/agent/` |
| **Sessions** | `~/.openclaw/agents/main/sessions/` | `~/.openclaw/agents/main/sessions/` |
| **Logs** | `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | `/tmp/openclaw/openclaw-YYYY-MM-DD.log` |

### Workspace Documents

Both agents maintain these files in `~/.openclaw/workspace/`:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Agent coordination rules and boundaries |
| `TOOLS.md` | Operator-specific cheat sheet, CLI commands, messaging targets |
| `MEMORY.md` | Long-term memory, identity, guardrails |
| `HEARTBEAT.md` | Current status and health information |
| `IDENTITY.md` | Core identity definition |
| `SOUL.md` | Personality and behavioral guidelines |
| `TASKS.md` | Pending work items (Patch only) |
| `USER.md` | User preferences and information |
| `memory/` | Persistent memory storage directory |

### Echo-Specific Locations

| Path | Purpose |
|------|---------|
| `~/.openclaw/workspace/patch-inbox/` | Patch drops maintenance notices here |
| `~/.openclaw/workspace/daily_news_template.txt` | Template for daily news reports |
| `~/.openclaw/workspace/system_health_template.txt` | Template for health reports |

---

## Systemd Service

Both agents run as user services:

```bash
# Service name
openclaw-gateway.service

# Check status
systemctl --user status openclaw-gateway.service

# View logs
journalctl --user -u openclaw-gateway.service -n 100 --no-pager

# Restart service
systemctl --user restart openclaw-gateway.service

# Service file location
~/.config/systemd/user/openclaw-gateway.service
```

---

## Telegram Configuration

### Bot Tokens
- **Echo**: Token in `channels.telegram.botToken` (openclaw.json)
- **Patch**: Token in `channels.telegram.botToken` (openclaw.json)

### DM Policy
Both agents use `dmPolicy: "pairing"` - unknown senders receive a pairing code.

### DM Allowlist
Both agents allow DMs from `@brimdor` via `channels.telegram.allowFrom`.

### Shared Communication Group

Echo and Patch communicate directly via a shared Telegram group:

| Property | Value |
|----------|-------|
| **Group Name** | The Grand Council |
| **Group ID** | `-5238236031` |
| **Members** | Echo, Patch, Chris |

**IMPORTANT**: The correct group ID is `-5238236031` (NOT `-1005238236031` - this is a common error).

### Group Configuration

Each agent's `openclaw.json` must have the group configured:

```json
{
  "channels": {
    "telegram": {
      "groups": {
        "-5238236031": {
          "requireMention": true,
          "allowFrom": ["@brimdor", "@other_bot_handle"]
        }
      }
    }
  }
}
```

**Echo's allowFrom for group**: `["@brimdor", "@patch_repair_bot"]`
**Patch's allowFrom for group**: `["@brimdor", "@Echo_orchestrator_bot"]`

### Group Communication Rules
1. **Require @mention** - Both agents require being mentioned to respond (prevents loops)
2. **Use for real-time coordination** - When Patch loses SSH connection to Echo
3. **Keep messages concise** - This is an operational channel
4. **Mention targets**:
   - `@Echo_orchestrator_bot` - Get Echo's attention
   - `@patch_repair_bot` - Get Patch's attention
   - `@brimdor` - Alert Chris

---

## Nostr Configuration

Both agents have Nostr enabled with the same relay configuration:

```
wss://relay.damus.io
wss://nos.lol
wss://relay.nostr.band
wss://nostr.lol
wss://nostr.mom
wss://auth.nostr1.com
wss://relay.0xchat.com
```

Chris's Nostr pubkey: `npub1g8ntsc97udpmhs322635vcc8rgcumh795l6mtvps23armcvcwevs3f44f7`

---

## Model Configuration

Both agents connect to the homelab's Ollama instance:

```json
{
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://ollama.eaglepass.io/v1",
        "apiKey": "ollama-local",
        "api": "openai-completions"
      }
    }
  }
}
```

### Available Local Models
- `Echo:latest` - Custom model
- `gpt-oss:20b` - Open-source GPT variant

---

## SSH Access

```bash
# SSH to Echo's host (mario)
ssh brimdor@10.0.30.10

# SSH to Patch's host (luigi)
ssh brimdor@10.0.30.11

# Check OpenClaw status
~/.local/bin/openclaw gateway status     # Echo
~/.npm-global/bin/openclaw gateway status # Patch

# Check channel status with probe
openclaw channels status --probe

# Deep status check
openclaw status --deep
```

---

## Common Operations

### Restart an Agent

```bash
# SSH to the host first
ssh brimdor@10.0.30.10  # or 10.0.30.11

# Restart the gateway
systemctl --user restart openclaw-gateway.service

# Verify it's running
systemctl --user status openclaw-gateway.service
```

### View Agent Logs

```bash
# Recent logs
journalctl --user -u openclaw-gateway.service -n 100 --no-pager

# Follow logs in real-time
journalctl --user -u openclaw-gateway.service -f

# Detailed log file
cat /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log
```

### Edit Agent Configuration

```bash
# Always backup first
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak-$(date +%Y%m%dT%H%M%SZ)

# Edit config (use jq for JSON manipulation)
jq '.some.path = "value"' ~/.openclaw/openclaw.json > /tmp/oc.json && mv /tmp/oc.json ~/.openclaw/openclaw.json

# Restart to apply
systemctl --user restart openclaw-gateway.service
```

### Check Model/Provider Status

```bash
openclaw models status --probe
```

---

## Patch -> Echo Communication

### File-Based (Primary Method)
Patch can drop notices for Echo in the patch-inbox:

```bash
# From Patch's host, write to Echo's inbox
ssh brimdor@10.0.30.10 "mkdir -p ~/.openclaw/workspace/patch-inbox"
ssh brimdor@10.0.30.10 "echo 'Maintenance notice content' > ~/.openclaw/workspace/patch-inbox/$(date +%Y%m%dT%H%M%SZ).md"
```

### Telegram (Fallback/Real-Time)
When SSH/file-based methods fail, use Telegram group `-5238236031`:
- Patch mentions `@Echo_orchestrator_bot` for Echo's attention
- Patch mentions `@brimdor` to alert Chris

---

## Echo Health Checks (Non-Disruptive)

Run these from Patch or any SSH session to mario:

```bash
# Gateway status
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw gateway status

# Channel status with probe
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw channels status --probe

# Deep status
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw status --deep

# Model/quota diagnostics
ssh brimdor@10.0.30.10 ~/.local/bin/openclaw models status --probe

# View logs
ssh brimdor@10.0.30.10 journalctl --user -u openclaw-gateway.service -n 200 --no-pager
```

---

## Disruptive Actions (Require Coordination)

Before performing disruptive actions on Echo:
1. Notify Echo via `patch-inbox/` or Telegram group
2. Wait for acknowledgment if possible
3. Perform the action
4. Verify restoration

```bash
# Gateway restart (disruptive)
ssh brimdor@10.0.30.10 systemctl --user restart openclaw-gateway.service
```

---

## Troubleshooting

### Agent Not Responding to DMs
1. Check if gateway is running: `systemctl --user status openclaw-gateway.service`
2. Check for config errors in logs: `journalctl --user -u openclaw-gateway.service -n 50`
3. Verify `dmPolicy` and `allowFrom` in config
4. Run `openclaw doctor --fix` if config issues found

### Agent Not Responding in Groups
1. Verify group ID is correct (`-5238236031`, not `-1005238236031`)
2. Check `channels.telegram.groups` has the group listed
3. Verify `allowFrom` includes the sender's username
4. Ensure `requireMention: true` and you're @mentioning the bot

### Gateway Crash Loop
1. Check logs for "Config invalid" or "Unrecognized key" errors
2. Run `openclaw doctor --fix` to remove invalid config keys
3. Restore from backup if needed: `cp ~/.openclaw/openclaw.json.bak-* ~/.openclaw/openclaw.json`

### Telegram "Chat Not Found" Errors
1. Verify the group ID is correct
2. Ensure bot is a member of the group
3. Check bot privacy settings in BotFather (`/setprivacy`)
4. Verify bot token is correct

---

## Configuration Reference

### Key Config Paths (openclaw.json)

| Path | Purpose |
|------|---------|
| `agents.list[0].name` | Agent display name |
| `agents.list[0].identity` | Name, theme, emoji |
| `agents.defaults.model.primary` | Primary LLM model |
| `agents.defaults.model.fallbacks` | Fallback models |
| `channels.telegram.botToken` | Telegram bot token |
| `channels.telegram.allowFrom` | DM allowlist |
| `channels.telegram.groups` | Per-group configuration |
| `channels.telegram.groups.<id>.allowFrom` | Group-specific allowlist |
| `channels.telegram.groups.<id>.requireMention` | Mention requirement |
| `channels.nostr.privateKey` | Nostr private key |
| `channels.nostr.relays` | Nostr relay list |
| `gateway.port` | Gateway port (default: 18789) |
| `gateway.bind` | Network binding (lan/localhost) |

---

## OpenClaw Documentation Reference

> **IMPORTANT**: OpenClaw has extensive documentation at https://docs.openclaw.ai/
> The documentation index is available at: https://docs.openclaw.ai/llms.txt

### Essential Documentation Pages

| Topic | URL | Description |
|-------|-----|-------------|
| **Getting Started** | https://docs.openclaw.ai/start/getting-started | Initial setup guide |
| **Configuration** | https://docs.openclaw.ai/gateway/configuration | Full config reference |
| **Telegram** | https://docs.openclaw.ai/channels/telegram | Telegram bot setup |
| **Agent Workspace** | https://docs.openclaw.ai/concepts/agent-workspace | Workspace files explained |
| **CLI Reference** | https://docs.openclaw.ai/cli/index.md | All CLI commands |
| **Troubleshooting** | https://docs.openclaw.ai/help/troubleshooting | Common issues |

### Workspace Files (from OpenClaw Docs)

The workspace is the agent's home directory. Standard files include:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Operating instructions, rules, priorities, "how to behave" |
| `SOUL.md` | Persona, tone, and boundaries |
| `USER.md` | Who the user is and how to address them |
| `IDENTITY.md` | Agent's name, vibe, and emoji |
| `TOOLS.md` | Notes about local tools and conventions |
| `HEARTBEAT.md` | Optional tiny checklist for heartbeat runs |
| `BOOT.md` | Optional startup checklist on gateway restart |
| `BOOTSTRAP.md` | One-time first-run ritual (delete after complete) |
| `memory/*.md` | Daily memory logs (one file per day) |
| `MEMORY.md` | Curated long-term memory |
| `skills/` | Workspace-specific skills |

### Key CLI Commands

```bash
# Setup and Configuration
openclaw setup              # Initialize config + workspace
openclaw onboard            # Interactive setup wizard
openclaw configure          # Configuration wizard
openclaw doctor             # Health checks + quick fixes
openclaw doctor --fix       # Apply safe migrations/repairs

# Status and Health
openclaw status             # Show session health
openclaw status --deep      # Deep health probe
openclaw health             # Gateway health
openclaw channels status    # Channel status
openclaw channels status --probe  # With live checks

# Gateway Management
openclaw gateway status     # Gateway status
openclaw gateway restart    # Restart gateway
openclaw logs               # View gateway logs
openclaw logs --follow      # Follow logs in real-time

# Models
openclaw models status      # Model status
openclaw models status --probe  # Live probe of auth profiles
openclaw models list        # List available models

# Sessions
openclaw sessions           # List conversation sessions

# Memory
openclaw memory status      # Show index stats
openclaw memory search "query"  # Semantic search over memory

# Messaging
openclaw message send --channel telegram --target <chat_id> --message "text"
```

### Telegram Configuration Deep Dive

From the OpenClaw docs, key Telegram settings:

```json5
{
  channels: {
    telegram: {
      enabled: true,
      botToken: "your-bot-token",
      
      // DM access control
      dmPolicy: "pairing",  // pairing | allowlist | open | disabled
      allowFrom: ["@username", "123456789"],  // DM allowlist
      
      // Group access control  
      groupPolicy: "allowlist",  // open | allowlist | disabled
      groupAllowFrom: ["@username"],  // Group sender allowlist
      
      // Per-group configuration
      groups: {
        "-5238236031": {
          requireMention: true,
          allowFrom: ["@brimdor", "@other_bot"],
          systemPrompt: "Keep answers brief.",
        },
      },
      
      // Message handling
      historyLimit: 50,  // Group message context
      textChunkLimit: 4000,  // Outbound chunk size
      streamMode: "partial",  // off | partial | block
      
      // Bot actions
      actions: {
        reactions: true,
        sendMessage: true,
        sticker: true,
      },
    },
  },
}
```

### Telegram Access Control (Important!)

**DM Policy Options**:
- `pairing` (default): Unknown senders get a pairing code; owner must approve
- `allowlist`: Only allow senders in `allowFrom`
- `open`: Allow all inbound DMs (requires `allowFrom: ["*"]`)
- `disabled`: Ignore all inbound DMs

**Group Policy Options**:
- `open`: Groups bypass allowlists; mention-gating still applies
- `allowlist`: Only allow groups/senders matching the configured allowlist
- `disabled`: Block all group messages

**Per-Group `allowFrom`**: Controls which senders can trigger responses in that specific group.

### Agent-to-Agent Communication

For agents to communicate in a shared Telegram group:

1. **Add group to both configs** with the correct group ID
2. **Set `requireMention: true`** to prevent infinite loops
3. **Add each bot to the other's `allowFrom`**:
   - Echo allows `@patch_repair_bot`
   - Patch allows `@Echo_orchestrator_bot`

### Common Configuration Mistakes

1. **Wrong group ID format**: Use `-5238236031` not `-1005238236031` for regular groups
2. **Invalid config keys**: OpenClaw validates strictly; run `openclaw doctor --fix`
3. **Missing bot in group**: Bot must be added to group before it can receive messages
4. **Privacy mode enabled**: In BotFather, run `/setprivacy` -> Disable for group messages
5. **Old data in session files**: After config changes, old session files may have stale data

### Configuration Validation

OpenClaw strictly validates configuration:
- Unknown keys cause gateway to refuse to start
- Run `openclaw doctor` to see issues
- Run `openclaw doctor --fix` to apply safe repairs
- Only diagnostic commands work when config is invalid

### Multi-Agent Routing

For running multiple agents in one gateway (not our setup, but useful reference):

```json5
{
  agents: {
    list: [
      { id: "echo", workspace: "~/.openclaw/workspace-echo" },
      { id: "patch", workspace: "~/.openclaw/workspace-patch" },
    ],
  },
  bindings: [
    { agentId: "echo", match: { channel: "telegram", accountId: "echo-bot" } },
    { agentId: "patch", match: { channel: "telegram", accountId: "patch-bot" } },
  ],
}
```

### Documentation Categories

**Installation & Setup**:
- https://docs.openclaw.ai/install/index.md
- https://docs.openclaw.ai/install/node.md
- https://docs.openclaw.ai/start/setup

**Channels**:
- https://docs.openclaw.ai/channels/telegram
- https://docs.openclaw.ai/channels/discord
- https://docs.openclaw.ai/channels/slack
- https://docs.openclaw.ai/channels/whatsapp
- https://docs.openclaw.ai/channels/signal

**Concepts**:
- https://docs.openclaw.ai/concepts/agent-workspace
- https://docs.openclaw.ai/concepts/session
- https://docs.openclaw.ai/concepts/memory
- https://docs.openclaw.ai/concepts/model-failover
- https://docs.openclaw.ai/concepts/streaming

**Gateway**:
- https://docs.openclaw.ai/gateway/configuration
- https://docs.openclaw.ai/gateway/logging
- https://docs.openclaw.ai/gateway/troubleshooting
- https://docs.openclaw.ai/gateway/health

**Automation**:
- https://docs.openclaw.ai/automation/cron-jobs
- https://docs.openclaw.ai/automation/webhook
- https://docs.openclaw.ai/hooks

**Tools**:
- https://docs.openclaw.ai/tools/skills
- https://docs.openclaw.ai/tools/slash-commands
- https://docs.openclaw.ai/tools/browser
- https://docs.openclaw.ai/tools/exec

**CLI Commands**:
- https://docs.openclaw.ai/cli/gateway
- https://docs.openclaw.ai/cli/channels
- https://docs.openclaw.ai/cli/models
- https://docs.openclaw.ai/cli/doctor
- https://docs.openclaw.ai/cli/status
