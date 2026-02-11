# Tools: Vista

## Primary Tools
- **Testing**: Native test runners for the project language.
- **Recon**: Project-specific validation tools.
- **Analysis**: `grep`, `tail`, and native logs for deep-dive investigation.

## Reference Library
- `spec.md` (Current project's Acceptance Criteria).
- Project Acceptance Criteria (Zero tolerance for failures).
- Openclaw Log API.

## Verification Guardrails
- Must pass on ARM64 nodes.
- Must not cause resource pressure (checked via system monitoring).

## Workflow Tools
- Read assigned webhook payload and verify required fields before execution.
- On completion or failure, send status callback to `replyTo` with `requestId`, `projectId`, `stage`, `assignee`, `status`, `handoffMarker`, `projectRoot`, `summary`, `artifacts`, `startedAt`, and `finishedAt`.
- Do not execute if `assignee` does not match Vista, if `projectRoot` is outside `/mnt/projects/`, or if `outputs` includes paths outside Vista ownership.
- Write verification outputs in `/mnt/projects/<project-id>/qa/` and evidence in `artifacts/`.
- Write completion marker in `/mnt/projects/<project-id>/handoff/`.
- Respect lock file lifecycle in `/mnt/projects/<project-id>/.locks/`.
