# Plan: OpenClaw Mem Integration

## Context
We are adding the `openclaw-mem` skill from ClawHub to the OpenClaw deployment in the homelab. We follow the SDD workflow and ensure compliance with OpenClaw Governance Rules.

## Proposed Changes

### 1. Update `apps/openclaw/values.yaml`
- **Configuration (`openclaw.json`)**:
    - Add `"managed": ["clawhub:WeAreAllSatoshiN/openclaw-mem"]` to the `skills` object.
    - This will instruct OpenClaw to fetch and manage the skill automatically.
- **Environment Variables**:
    - Add `OPENCLAW_MANAGED_SKILLS: "clawhub:WeAreAllSatoshiN/openclaw-mem"` to ensure the skill is prioritized during bootstrap.

### 2. Verification Steps
- **Deployment**: Apply the changes via GitOps (in this case, I will assume the user or ArgoCD will apply, but I will verify the pod status).
- **Initialization**: Check `kubectl logs` for the `openclaw` pod to see if it fetches the skill from ClawHub.
- **Health**: Run `/homelab-recon` to ensure no regressions in other layers.

## Technical Details
- **OpenClaw Version**: `latest` (ghcr.io/openclaw/openclaw)
- **State Directory**: `/home/node/.openclaw` (NFS persisted)
- **Config Path**: `/config/openclaw.json` (ConfigMap)

## Risks & Mitigations
- **Network Access**: The pod must be able to reach `clawhub.ai` or `clawhub.com`.
- **Duplicate IDs**: If the skill ID conflicts with an internal one, check logs and adjust `openclaw.json`.
