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
- Keep infra diagnostics under `/mnt/projects/<project-id>/artifacts/`.
- Use completion markers in `handoff/` when Patch is explicitly assigned a stage.
