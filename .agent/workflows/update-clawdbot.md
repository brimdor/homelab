---
description: Workflow to update Clawdbot (pull upstream, build image, restart)
sync_locations:
  - .agent/workflows/update-clawdbot.md
  - ~/.config/opencode/command/update-clawdbot.md
  - ~/.gemini/antigravity/global_workflows/update-clawdbot.md
sync_note: Manages the Clawdbot update lifecycle according to Homelab Application Rules.
---

> [!CAUTION]
> **This workflow follows the Foundational Rules defined in `HOMELAB_foundational_rules.md`.**
> The workflow is NOT complete until ALL layers are GREEN with ZERO issues.
> Do NOT stop, pause, or quit until the work is complete.

# Update Clawdbot

## Overview
Updates the Clawdbot application by synchronizing with the upstream repository, rebuilding the container image (applying any local Dockerfile overrides), and restarting the deployment.

**Protocol**:
- **Source**: Upstream (`github.com/clawdbot/clawdbot`) is the source of truth.
- **Modifications**: All logic changes are applied via `patches` in `values.yaml`, NOT by modifying source files.
- **Image**: Built locally. A custom `Dockerfile` in `apps/clawdbot/` (if present) overrides the upstream one.

---

## Phase 1: Upstream Synchronization

1.  **Verify Repository**:
    -   Target: `~/Documents/Github/clawdbot`
    -   Action: Ensure directory exists.

2.  **Reset to Upstream**:
    > [!WARNING]
    > We do not own the source repo. Any local uncommitted changes will be lost.
    -   `git fetch origin`
    -   `git reset --hard origin/main` (or master)
    -   `git clean -fd`

---

## Phase 2: Build & Push

1.  **Update Configuration**:
    -   Verify `apps/clawdbot/values.yaml` contains all necessary `patches` (ConfigMap injections) for any custom logic.
    -   Ensure `image.repository` in `values.yaml` points to `10.0.20.11:32309/clawdbot`.

2.  **Execute Build Script**:
    -   Run: `apps/clawdbot/scripts/build.sh`
    -   **Action**: Builds the image using `apps/clawdbot/Dockerfile` (if present) or upstream.
    -   **Push**: Pushes to local registry `registry.eaglepass.io/clawdbot:latest`.
    -   **Note**: The build script automatically handles copying the custom Dockerfile to the source repo.

---

## Phase 3: Deployment Update

1.  **Restart Application**:
    -   Command: `kubectl rollout restart deployment clawdbot -n clawdbot`
    -   Validation: Wait for rollout to complete (`kubectl rollout status ...`).

2.  **Verify Status**:
    -   Check pod status: `kubectl get pods -n clawdbot` (Must be Running).
    -   Check logs for patch application: `kubectl logs -n clawdbot -l app.kubernetes.io/name=clawdbot` (Look for patch success messages if available, or absence of errors).

---

## Phase 4: Validation (Foundational Rules)

1.  **Layer Check**:
    -   Metal: Nodes Ready?
    -   System: Ceph Healthy?
    -   Platform: ArgoCD Synced/Healthy?
    -   Apps: Clawdbot Running?

2.  **Completion**:
    -   Only mark complete when ALL status checks are GREEN.
