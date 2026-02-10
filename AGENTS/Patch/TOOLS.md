# Tools: Patch

## Core CLI
- `kubectl`: Cluster management.
- `helm`: Chart deployments.
- `ssh`: Direct node access (use sparingly).
- `ceph`: Storage health.
- `argocd`: GitOps state.

## Homelab Workflows
- `/homelab-recon`: Your primary diagnostic tool.
- `/homelab-action`: Your primary repair tool.
- `/homelab-troubleshoot`: Use when standard actions fail.

## Environment Variables
- Ensure `KUBECONFIG` is always valid.
- Use `GITEA_TOKEN` for repository interactions.
