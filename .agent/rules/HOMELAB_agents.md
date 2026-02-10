---
description: OpenClaw agent team - Echo, Patch, Scope, Forge, Pixel, Vista configuration, communication, and management
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

# OpenClaw Agent Team

The homelab runs six OpenClaw AI agents on dedicated Raspberry Pi nodes. They operate as a single team: each agent has a specialty, and the workflow depends on all of them.

Team roles (see `AGENTS/team.html`):
- **Echo**: Project Manager / Orchestrator
- **Patch**: SRE / DevOps
- **Scope**: Research & Architect
- **Forge**: Engineer
- **Pixel**: Designer
- **Vista**: Analyst / QA

Agents communicate with Chris via Telegram DMs and may coordinate via shared file inboxes for agent-to-agent communication.

---

## Agent Overview

| Agent | Role | Host | Telegram Username |
|------|------|------|------------------|
| Echo | Project Manager / Orchestrator | mario (`10.0.30.10`) | `@echo_orchestrator_bot` |
| Patch | SRE / DevOps | luigi (`10.0.30.11`) | `@patch_repair_bot` |
| Scope | Research & Architect | toad (`10.0.30.12`) | `@scope_research_bot` |
| Forge | Engineer | yoshi (`10.0.30.13`) | `@forge_engineer_bot` |
| Pixel | Designer | peach (`10.0.30.14`) | `@pixel_designer_bot` |
| Vista | Analyst / QA | star (`10.0.30.15`) | `@vista_analyst_bot` |

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
- **Telegram Username**: `@echo_orchestrator_bot`

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
- **Telegram Username**: `@patch_repair_bot`

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

## Scope - Research & Architect

### Purpose
Scope is the research and architecture specialist. It handles:
- Documentation deep-dives to identify best tools/libraries
- Technical feasibility and compatibility validation *before* implementation begins
- Technical blueprints, schemas, and data models for Forge to follow

### Identity
- **Name**: Scope
- **Telegram Username**: `@scope_research_bot`

### Host Details
- **Node**: toad
- **IP Address**: `10.0.30.12`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

---

## Forge - Engineer

### Purpose
Forge is the implementation specialist. It handles:
- Backend logic and services strictly according to the spec/blueprints
- Data models and APIs defined by Scope
- Integration of UI components provided by Pixel

### Identity
- **Name**: Forge
- **Telegram Username**: `@forge_engineer_bot`

### Host Details
- **Node**: yoshi
- **IP Address**: `10.0.30.13`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

---

## Pixel - Designer

### Purpose
Pixel is the UI/UX specialist. It handles:
- Visual design and interaction requirements
- Frontend components and assets
- Hand-off of completed UI work to Forge for integration

### Identity
- **Name**: Pixel
- **Telegram Username**: `@pixel_designer_bot`

### Host Details
- **Node**: peach
- **IP Address**: `10.0.30.14`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

---

## Vista - Analyst / QA

### Purpose
Vista is the validation specialist. It handles:
- Test case generation from acceptance criteria
- Validation that implementation is compliant
- Rejection and remediation loops when requirements are not met

### Identity
- **Name**: Vista
- **Telegram Username**: `@vista_analyst_bot`

### Host Details
- **Node**: star
- **IP Address**: `10.0.30.15`
- **VLAN**: 30 (Cluster-Extra)
- **Hardware**: Raspberry Pi

---

## File Locations

### OpenClaw Installation

These locations apply to each agent host:

- **Config**: `~/.openclaw/openclaw.json`
- **Workspace**: `~/.openclaw/workspace/`
- **Agent Dir**: `~/.openclaw/agents/main/agent/`
- **Sessions**: `~/.openclaw/agents/main/sessions/`
- **Logs**: `/tmp/openclaw/openclaw-YYYY-MM-DD.log`
- **Binary**: run `command -v openclaw` (commonly `~/.local/bin/openclaw` or `~/.npm-global/bin/openclaw`)

### Workspace Documents

The Agent Documents for every Agent that is run in OpenClaw by default is located in `~/.openclaw/workspace/`.

Each agent maintains these files in `~/.openclaw/workspace/`:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Agent coordination rules and boundaries |
| `TOOLS.md` | Operator-specific cheat sheet, CLI commands, messaging targets |
| `MEMORY.md` | Long-term memory, identity, guardrails |
| `HEARTBEAT.md` | Current status and health information |
| `IDENTITY.md` | Core identity definition |
| `SOUL.md` | Personality and behavioral guidelines |
| `TASKS.md` | Pending work items (role-specific; often Patch) |
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

Each agent runs as a user service:

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
- **Echo** (`@echo_orchestrator_bot`): Token in `channels.telegram.botToken` (openclaw.json)
- **Patch** (`@patch_repair_bot`): Token in `channels.telegram.botToken` (openclaw.json)
- **Scope** (`@scope_research_bot`): Token in `channels.telegram.botToken` (openclaw.json)
- **Forge** (`@forge_engineer_bot`): Token in `channels.telegram.botToken` (openclaw.json)
- **Pixel** (`@pixel_designer_bot`): Token in `channels.telegram.botToken` (openclaw.json)
- **Vista** (`@vista_analyst_bot`): Token in `channels.telegram.botToken` (openclaw.json)

### DM Policy
Standard: agents use `dmPolicy: "pairing"` - unknown senders receive a pairing code.

### DM Allowlist
Standard: agents allow DMs from `@brimdor` via `channels.telegram.allowFrom`.

### Agent-to-Agent Communication (File Inbox)

Agents coordinate via shared file inboxes (Telegram groups are NOT used for agent-to-agent communication). The currently defined inbox pairing is Echo <-> Patch.

#### Shared Inbox Locations

| Agent | Inbox Path | Purpose |
|-------|------------|---------|
| **Echo** | `~/.openclaw/workspace/patch-inbox/` | Patch drops maintenance notices here |
| **Patch** | `~/.openclaw/workspace/echo-inbox/` | Echo drops task requests here |

#### File Naming Convention
```
YYYYMMDDTHHMMSSZ-<type>.md
```
Examples:
- `20260209T143000Z-maintenance.md` - Maintenance notice
- `20260209T150000Z-checklist.md` - Checklist item
- `20260209T160000Z-status.md` - Status update

#### Communication Protocol
1. **Writer creates file** with timestamped name
2. **Reader polls inbox** periodically (or on heartbeat)
3. **Reader processes file** and moves to `processed/` subdirectory
4. **Critical items** may also trigger a DM to Chris (`@brimdor`)

#### Inbox File Format
```markdown
---
type: maintenance|checklist|status|alert
priority: low|normal|high|critical
from: echo|patch|scope|forge|pixel|vista
timestamp: 2026-02-09T14:30:00Z
---

# Subject Line

Message content here.
```

---

## Nostr Configuration

If Nostr is enabled on an agent, use the same relay configuration:

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

If an agent uses local models, it connects to the homelab's Ollama instance:

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
# SSH to agent hosts
ssh brimdor@10.0.30.10  # Echo (mario)
ssh brimdor@10.0.30.11  # Patch (luigi)
ssh brimdor@10.0.30.12  # Scope (toad)
ssh brimdor@10.0.30.13  # Forge (yoshi)
ssh brimdor@10.0.30.14  # Pixel (peach)
ssh brimdor@10.0.30.15  # Vista (star)

# Find OpenClaw binary path
command -v openclaw

# Check OpenClaw status
openclaw gateway status

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

### File-Based Communication (Primary Method)
Patch drops notices for Echo in the patch-inbox:

```bash
# From Patch's host, write to Echo's inbox
ssh brimdor@10.0.30.10 "mkdir -p ~/.openclaw/workspace/patch-inbox"
ssh brimdor@10.0.30.10 "cat > ~/.openclaw/workspace/patch-inbox/$(date +%Y%m%dT%H%M%SZ)-maintenance.md << 'EOF'
---
type: maintenance
priority: normal
from: patch
timestamp: $(date -Iseconds)
---

# Maintenance Notice

Content here.
EOF"
```

### Critical Alerts
For critical issues requiring immediate human attention, Patch should DM Chris directly via Telegram (`@brimdor`).

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
1. Notify Echo via `patch-inbox/` file drop
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

### File Inbox Not Being Processed
1. Verify inbox directory exists: `ls -la ~/.openclaw/workspace/patch-inbox/`
2. Check file permissions are correct
3. Verify agent heartbeat is running and checking inbox
4. Check for malformed markdown frontmatter in inbox files

### Gateway Crash Loop
1. Check logs for "Config invalid" or "Unrecognized key" errors
2. Run `openclaw doctor --fix` to remove invalid config keys
3. Restore from backup if needed: `cp ~/.openclaw/openclaw.json.bak-* ~/.openclaw/openclaw.json`

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

From the OpenClaw docs, key Telegram settings (DMs only, no groups for agent-to-agent communication):

```json5
{
  channels: {
    telegram: {
      enabled: true,
      botToken: "your-bot-token",
      
      // DM access control
      dmPolicy: "pairing",  // pairing | allowlist | open | disabled
      allowFrom: ["@username", "123456789"],  // DM allowlist
      
      // Message handling
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

> **Note**: Agent-to-agent communication uses file inboxes, NOT Telegram groups.

### Common Configuration Mistakes

1. **Invalid config keys**: OpenClaw validates strictly; run `openclaw doctor --fix`
2. **Old data in session files**: After config changes, old session files may have stale data

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
