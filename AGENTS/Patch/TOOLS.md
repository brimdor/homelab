# Tools: Patch

## Core CLI
- `ssh`: Direct node access.
- `docker` / `podman`: Container management.
- `systemctl`: Native service management.
- Version control or file management for project state.

## Project Workflows
- `Project Recon`: Your primary diagnostic process.
- `Project Action`: Your primary maintenance process.
- `Troubleshooting`: Use when standard processes fail.

## Environment Variables
- Ensure all relevant project tokens are always valid.
- Use project-specific tokens for storage interactions (if applicable).

## NFS and Workflow Operations
- Verify `/mnt/projects` mount health before any project operation.
- Read assigned webhook payload and verify required fields before execution.
- On completion or failure, send status callback to `replyTo` with `requestId`, `projectId`, `stage`, `assignee`, `status`, `handoffMarker`, `projectRoot`, `summary`, `artifacts`, `startedAt`, and `finishedAt`.
- Do not execute if `assignee` does not match Patch, if `projectRoot` is outside `/mnt/projects/`, or if `outputs` includes paths outside assigned infra scope.
- Keep infra diagnostics under `/mnt/projects/<project-id>/artifacts/`.
- Use completion markers in `handoff/` when Patch is explicitly assigned a stage.
