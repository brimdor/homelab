# Distributed Agent Team Workflow Implementation Guide

## Purpose

This document captures the full implementation context for the six-agent, multi-RPi operating model used in this homelab. It is intended to future-proof operations, onboarding, upgrades, and project execution by preserving the exact architecture decisions, rollout steps, validation outcomes, and operating rules.

This guide is authoritative for:

- Agent coordination architecture across separate RPIs
- Shared project storage and file ownership protocol
- Echo-first orchestration and stakeholder communication model
- Boot/readiness requirements for all six agents
- Operational procedures and troubleshooting

## Executive Summary

The team was moved to a robust distributed workflow model where:

1. Echo is the primary human-facing orchestrator for project workflows.
2. Worker agents (Scope, Forge, Pixel, Vista) execute scoped tasks and hand off artifacts.
3. Patch handles infra/exception scenarios and escalates only when needed.
4. All project files live in a centralized NFS share mounted identically on all RPIs.
5. Echo must provide an interactive test environment for projects that support interaction (web app/API/dashboard/bot) before final sign-off.
6. Telegram group bot-to-bot messaging is not used for inter-agent coordination.
7. Coordination is designed around webhook-triggered work and shared filesystem artifacts.

## Background and Key Constraints

### 1. Telegram Is Not a Bot-to-Bot Coordination Bus

Telegram Bot API does not provide reliable bot-to-bot message visibility in groups. In practice, bots can respond to user prompts but should not be expected to observe other bots' messages and use those as a reliable protocol.

Implication:

- Team collaboration must not depend on agents reading each other's Telegram posts.

### 2. OpenClaw Multi-Agent Scope

OpenClaw native multi-agent session routing (`agents.list` + `bindings`, `sessions_send`, `sessions_spawn`) is native to a single gateway instance.

Current topology is one gateway per Raspberry Pi node, one primary agent per node.

Implication:

- Native single-gateway multi-agent features are not the direct cross-node collaboration path in this deployment.

### 3. Distributed Team Requirement

All six agents remain on dedicated RPIs:

- Echo -> mario (`10.0.30.10`)
- Patch -> luigi (`10.0.30.11`)
- Scope -> toad (`10.0.30.12`)
- Forge -> yoshi (`10.0.30.13`)
- Pixel -> peach (`10.0.30.14`)
- Vista -> star (`10.0.30.15`)

Implication:

- Cross-agent team flow must be explicit, deterministic, and infrastructure-backed.

## Target Architecture

### Control Plane

- Echo-first orchestration model.
- Worker execution by webhook-triggered tasks.
- Deterministic task payload contract for all handoffs.

### Data Plane

- Shared NFS storage:
  - Server: `10.0.40.3`
  - Export: `/mnt/user/team_projects`
  - Client mountpoint (all RPIs): `/mnt/projects`

### Stakeholder Plane

- Echo is the normal project interface to Chris.
- Patch escalates direct only for critical physical/system emergencies or if Echo is unavailable.

## Canonical Project Contract

### Project ID Standard

- Required format: `proj-YYYYMMDD-###`

Examples:

- `proj-20260210-001`
- `proj-20260210-002`

### Project Root

- `/mnt/projects/<project-id>/`

### Required Folder Layout

- `spec/`
- `handoff/`
- `src/`
- `ui/`
- `qa/`
- `artifacts/`
- `.locks/`

### Stage Lock and Handoff Rules

- Lock file pattern:
  - `.locks/<project-id>.<stage>.lock`
- Completion marker pattern:
  - `handoff/<timestamp>-<agent>-<stage>-done.json`
- No stage progression without completion marker.

### Ownership and Write Boundaries

- Echo:
  - Orchestration, sequence control, stakeholder updates, final rollup
- Scope:
  - `spec/` primary
  - supporting material in `artifacts/`
  - done marker in `handoff/`
- Forge:
  - `src/` primary
  - supporting material in `artifacts/`
  - done marker in `handoff/`
- Pixel:
  - `ui/` primary
  - supporting material in `artifacts/`
  - done marker in `handoff/`
- Vista:
  - `qa/` primary
  - evidence in `artifacts/`
  - pass/fail marker in `handoff/`
- Patch:
  - infra/ops diagnostics, remediation outputs, exception notices

Rule:

- No agent modifies another stage owner domain unless Echo explicitly assigns remediation.

## Webhook Task Payload Contract

### Required Fields

- `requestId`
- `projectId`
- `stage`
- `assignee`
- `projectRoot`
- `task`
- `acceptanceCriteria`
- `replyTo`

### Recommended Fields

- `fromAgent`
- `createdAt`
- `priority`
- `dependsOn`
- `deliver`
- `timeoutSeconds`

### Session Key Convention

- `hook:<projectId>:<assignee>:<stage>`

## Implemented Changes (Repo)

### Team-Level Contract

Updated:

- `AGENTS/TEAM.md`

Purpose:

- Defines distributed RPI workflow contract, storage model, payload standards, lock/handoff protocol, and communication model.

### Agent-Specific Operational Docs

Updated for each agent:

- `AGENTS/<Agent>/AGENTS.md`
- `AGENTS/<Agent>/TOOLS.md`
- `AGENTS/<Agent>/BOOT.md`
- `AGENTS/<Agent>/TEAM.md`

Agents:

- Echo
- Patch
- Scope
- Forge
- Pixel
- Vista

Purpose:

- Scope each role in shared storage workflow.
- Add mount/readiness checks to boot process.
- Add explicit stage ownership and payload expectations.

### Shared Rule Mirror

Updated:

- `.opencode/rules/HOMELAB_agents.md`

Purpose:

- Align global agent rule references with the distributed webhook + NFS workflow model.

## Implemented Changes (Remote Runtime Sync)

After local repo updates, runtime docs were copied to each host workspace.

### Destination Path

- `~/.openclaw/workspace/`

### Files Synced Per Host

- `AGENTS.md`
- `TOOLS.md`
- `BOOT.md`
- `TEAM.md`

### Host Mapping

- Echo: `10.0.30.10`
- Patch: `10.0.30.11`
- Scope: `10.0.30.12`
- Forge: `10.0.30.13`
- Pixel: `10.0.30.14`
- Vista: `10.0.30.15`

### Backup Before Sync

Per-host backup location created:

- `~/.openclaw/workspace/backup-docs-20260210T204140Z`

### Verification

- Local and remote checksums for synced docs were verified.
- Presence of key workflow markers (`team_projects`, `/mnt/projects`, `requestId`, and stage-specific sections) was validated on every host.

## Implemented Changes (NFS Rollout)

### Package Installation

Installed on all six hosts:

- `nfs-common`

### Mountpoint

Created:

- `/mnt/projects`

### Persistent Mount Configuration

Added to `/etc/fstab` on each host:

`10.0.40.3:/mnt/user/team_projects /mnt/projects nfs4 rw,_netdev,noauto,x-systemd.automount,x-systemd.idle-timeout=600,timeo=14,retrans=3 0 0`

### Validation

Validated on all hosts:

- package installed
- fstab entry present
- mount usable
- read/write test (`touch` + `rm`) successful

### Special Handling Performed

Two hosts experienced stale NFS handles during validation:

- mario (`10.0.30.10`)
- peach (`10.0.30.14`)

Remediation:

- force unmount + mount refresh
- post-fix read/write validation passed

## Reboot and Post-Reboot Readiness Run

### Reboot Executed

Rebooted all six RPIs:

- `10.0.30.10`
- `10.0.30.11`
- `10.0.30.12`
- `10.0.30.13`
- `10.0.30.14`
- `10.0.30.15`

### Post-Reboot Health

Confirmed for all six:

- host reachable via SSH
- kernel: `6.8.0-1047-raspi`
- `openclaw-gateway.service` active (user service)
- expected agent id present on each node
- NFS `/mnt/projects` RW access successful
- role-scoped workflow docs present and readable

## Current Operational State

The environment is now in a ready state for distributed project execution:

- Shared project storage standardized and mounted on all agents
- Agent docs and role boundaries synchronized to runtime
- Echo-first orchestration model codified in both repo and runtime docs
- Boot checklists include project mount validation

Interactive delivery directive:

- For interactive project types, Echo must publish a concrete test surface and provide Chris with direct validation steps.
- Standard template: `AGENTS/INTERACTIVE_ENV_TEMPLATE.md` (project copy at `/mnt/projects/<project-id>/artifacts/interactive-env.md`).

## Runbook: New Project Startup

1. Create `project-id` using `proj-YYYYMMDD-###`.
2. Create root in `/mnt/projects/<project-id>/`.
3. Create required subfolders:
   - `spec/`, `handoff/`, `src/`, `ui/`, `qa/`, `artifacts/`, `.locks/`
4. Initialize `spec/spec.md` with project vision and constraints.
5. Echo issues first worker task via webhook payload (usually Scope).
6. Worker writes outputs only in owned locations.
7. Worker writes completion marker in `handoff/`.
8. Echo validates handoff marker and acceptance criteria.
9. Echo triggers next stage.
10. If project type is interactive, Echo ensures a runnable interactive environment exists and records access details in `artifacts/` (Patch may support only when explicitly assigned infra tasks).
11. Vista validates completion and writes pass/fail evidence.
12. Echo sends final stakeholder summary including environment URL/endpoint and test instructions.

## Runbook: Agent Boot Readiness Check

Each agent should satisfy at startup:

1. `openclaw-gateway.service` active.
2. `/mnt/projects` accessible and writable.
3. Team workflow docs present in workspace.
4. Agent-specific stage ownership section present in `AGENTS.md`.

## Runbook: Troubleshooting

### NFS Mount Missing

1. Verify `/etc/fstab` contains the correct line.
2. Verify network reachability to `10.0.40.3`.
3. Trigger automount by accessing path:
   - `ls /mnt/projects`
4. If stale:
   - `sudo umount -fl /mnt/projects`
   - `sudo mount /mnt/projects`
5. Validate with touch/delete test.

### Stale File Handle

Symptoms:

- `ls: cannot access '/mnt/projects': Stale file handle`

Fix:

1. `sudo umount -fl /mnt/projects`
2. `sudo mount /mnt/projects`
3. verify `touch`/`rm` on mountpoint

### Gateway Service Not Active

1. `systemctl --user status openclaw-gateway.service`
2. `journalctl --user -u openclaw-gateway.service -n 100 --no-pager`
3. restart service if needed:
   - `systemctl --user restart openclaw-gateway.service`

### Wrong Agent Identity on Node

1. `~/.npm-global/bin/openclaw agents list --bindings`
2. verify expected default id:
   - mario -> echo
   - luigi -> patch
   - toad -> scope
   - yoshi -> forge
   - peach -> pixel
   - star -> vista

## Security and Governance Notes

### Open RW Share Reality

Because the NFS share is open RW, discipline is enforced by process and contracts:

- stage ownership boundaries
- lock files
- completion markers
- Echo-controlled stage progression
- immutable request IDs for idempotency

### Governance Recommendations

- Keep all project transition decisions in Echo.
- Keep worker tasks narrow and deterministic.
- Require evidence in `artifacts/` + `handoff/` before progression.
- Preserve marker files for auditability.

## Change Management Checklist

Before changing workflow/storage:

1. Update repo docs in `AGENTS/` first.
2. Update `.opencode/rules/HOMELAB_agents.md` for rule parity.
3. Sync docs to all six runtime workspaces.
4. Verify checksums + marker strings on remote files.
5. Validate NFS mount and RW on all nodes.
6. Run one project-stage smoke test.

## Upgrade Checklist

When performing package/system upgrades:

1. confirm NFS mount state before upgrade
2. run upgrade per host
3. reboot host if kernel upgrade pending
4. verify post-reboot:
   - gateway active
   - agent identity correct
   - `/mnt/projects` RW works
   - docs present

## Rollback and Recovery

### Docs Rollback

Runtime rollback source:

- `~/.openclaw/workspace/backup-docs-20260210T204140Z`

Repo rollback:

- use git history for `AGENTS/` and `.opencode/rules/HOMELAB_agents.md`

### NFS Rollback

If required:

1. remove fstab line for `/mnt/projects`
2. `sudo umount -fl /mnt/projects`
3. leave mountpoint empty or remove it

## What Is Implemented vs Pending

### Implemented

- docs redesign and role scoping
- runtime doc synchronization to all agent workspaces
- NFS client install and persistent mount configuration on all nodes
- reboot and post-reboot readiness validation on all nodes

### Pending/Optional Next Step

- run a live workflow smoke test with a real project id and actual webhook task chain (for example Echo -> Scope -> handoff marker -> Echo validation)

## Canonical Command Snippets

### Verify NFS RW

```bash
ls /mnt/projects >/dev/null 2>&1 && touch /mnt/projects/.rw-test && rm -f /mnt/projects/.rw-test
```

### Verify Gateway + Agent

```bash
systemctl --user is-active openclaw-gateway.service
~/.npm-global/bin/openclaw agents list --bindings
```

### Verify Team Contract Presence

```bash
grep -n "proj-YYYYMMDD-###" ~/.openclaw/workspace/TEAM.md
grep -n "Stage Ownership" ~/.openclaw/workspace/AGENTS.md
```

## Final Operating Principle

This team succeeds by enforcing deterministic coordination over ad-hoc chat behavior:

- shared storage for artifacts
- strict payload contracts
- stage ownership boundaries
- Echo-first orchestration
- evidence-based progression

If these principles are preserved, the system remains resilient through agent upgrades, infrastructure changes, and larger project loads.
