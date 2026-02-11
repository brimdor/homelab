# Openclaw Agent Team

This document defines the team workflow contract for distributed RPIs.

## Team Composition

| Agent | Role | Core Responsibility |
| :--- | :--- | :--- |
| **Echo** (📋) | Project Manager / Orchestrator | Starts every project, routes tasks, and delivers final results to Chris |
| **Patch** (🔧) | SRE / DevOps | Maintains infra reliability and handles exceptions/escalations |
| **Scope** (🔬) | Research & Architect | Produces technical specs and architecture |
| **Forge** (⚒️) | Engineer | Implements backend and integration work |
| **Pixel** (🎨) | Designer | Implements UI/UX assets and frontend views |
| **Vista** (🔍) | Analyst / QA | Validates acceptance criteria and issues pass/fail certification |

## Canonical Project Storage

- NFS server: `10.0.40.3`
- NFS export: `/mnt/user/team_projects`
- Local mount on every agent host: `/mnt/projects`
- Canonical project root: `/mnt/projects/<project-id>/`
- Project id format: `proj-YYYYMMDD-###`

### Required Project Layout

- `spec/` - project spec and architecture docs
- `handoff/` - stage handoff artifacts and completion markers
- `src/` - implementation code
- `ui/` - UI/UX assets and frontend code
- `qa/` - test plans and verification outputs
- `artifacts/` - logs, screenshots, reports, generated evidence
- `.locks/` - stage locks and workflow coordination files

## Echo-First Workflow

1. Echo creates the project root and initializes `spec/spec.md`.
2. Echo dispatches each stage to workers through webhook triggers.
3. Workers update only their owned areas and produce handoff evidence.
4. For interactive project types (web app, API, dashboard, bot), Echo ensures a runnable interactive environment is hosted and testable.
5. Echo validates handoff artifacts before triggering the next stage.
6. Echo delivers progress and final outcomes to Chris, including environment access instructions.

Patch is exception-oriented and normally reports through Echo.

## Webhook Payload Contract

Dispatch endpoint for all stage triggers:

- `/hooks/agent`
- `replyTo` must point to Echo's `/hooks/agent` endpoint for completion callbacks

Every cross-agent task payload must include:

- `requestId`
- `projectId`
- `stage`
- `assignee`
- `projectRoot`
- `specPath`
- `specLocked`
- `lockFile`
- `task`
- `acceptanceCriteria`
- `inputs`
- `outputs`
- `handoffMarkerExpected`
- `replyTo`

Worker completion callback payload to Echo must include:

- `requestId`
- `projectId`
- `stage`
- `assignee`
- `status` (`done` or `failed`)
- `handoffMarker` (path in `handoff/`)
- `projectRoot`
- `summary`
- `artifacts`
- `startedAt`
- `finishedAt`

Recommended fields:

- `fromAgent`
- `createdAt`
- `priority`
- `dependsOn`
- `deliver`
- `timeoutSeconds`

Session key convention:

- `hook:<projectId>:<assignee>:<stage>`
- Worker must execute only when `assignee` matches the receiving agent identity.
- `projectRoot` must point to `/mnt/projects/<project-id>/` for all file I/O.
- Worker must reject payloads with missing required fields or out-of-scope `outputs`.

## Stage Ownership and Write Boundaries

- Echo: orchestration artifacts, spec governance, final rollups
- Scope: `spec/`, supporting docs in `artifacts/`, handoff marker in `handoff/`
- Forge: `src/`, implementation notes in `artifacts/`, handoff marker in `handoff/`
- Pixel: `ui/`, design notes in `artifacts/`, handoff marker in `handoff/`
- Vista: `qa/`, verification evidence in `artifacts/`, certification marker in `handoff/`
- Patch: environment/ops artifacts and exception notices

No agent should modify another stage's owned files unless Echo explicitly assigns remediation.

## Lock and Handoff Rules

- Use lock files in `.locks/` before stage work starts.
- Lock file pattern: `.locks/<project-id>.<stage>.lock`
- Completion marker pattern: `handoff/<timestamp>-<agent>-<stage>-done.json`
- Do not advance to next stage without a completion marker.
- Echo must not advance stages until callback payload and handoff marker both validate.

## Communication Protocols

- Primary stakeholder channel: Echo <-> Chris
- Agent coordination channel id: `-5207483609`
- Direct addressing format: `AgentName, ...`
- Use reply threading to preserve context

Telegram group bot-to-bot visibility is not a coordination mechanism.
Use webhook dispatch plus shared project artifacts instead.
