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
- Write verification outputs in `/mnt/projects/<project-id>/qa/` and evidence in `artifacts/`.
- Write completion marker in `/mnt/projects/<project-id>/handoff/`.
- Respect lock file lifecycle in `/mnt/projects/<project-id>/.locks/`.
