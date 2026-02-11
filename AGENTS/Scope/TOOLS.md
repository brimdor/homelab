# Tools: Scope

## Primary Tools
- **Web Search**: For deep-dives into documentation.
- **Diagrams**: Use Mermaid syntax for architectural blueprints.
- **API Testing**: Use `curl` or subagents to test API responsiveness before locking the spec.

## Reference Library
- Project technical documentation.
- Project Network & Access rules.
- Openclaw API & Documentation.

## Tech Choice Guardrails
- ARM64 Support: Mandatory.
- Resource Usage: Must be lean (RPi-friendly).
- Portability: Must run in the specified project environment.

## Workflow Tools
- Read assigned webhook payload and verify required fields before execution.
- On completion or failure, send status callback to `replyTo` with `requestId`, `projectId`, `stage`, `assignee`, `status`, `handoffMarker`, `projectRoot`, `summary`, `artifacts`, `startedAt`, and `finishedAt`.
- Do not execute if `assignee` does not match Scope, if `projectRoot` is outside `/mnt/projects/`, or if `outputs` includes paths outside Scope ownership.
- Write architecture outputs in `/mnt/projects/<project-id>/spec/`.
- Write handoff marker in `/mnt/projects/<project-id>/handoff/`.
- Respect lock file lifecycle in `/mnt/projects/<project-id>/.locks/`.
