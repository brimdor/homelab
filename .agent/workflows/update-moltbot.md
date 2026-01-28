---
description: Workflow to update Moltbot (pull upstream, build image, restart)
sync_locations:
  - .agent/workflows/update-moltbot.md
  - .opencode/command/update-moltbot.md
  - ~/.gemini/antigravity/global_workflows/update-moltbot.md
  - ~/.opencode/command/update-moltbot.md
  - ~/.agent/workflows/update-moltbot.md
sync_note: Manages the Moltbot update lifecycle according to Homelab Application Rules.
---

> [!CAUTION]
> **This workflow follows the Foundational Rules defined in `HOMELAB_foundational_rules.md`.**
> The workflow is NOT complete until ALL layers are GREEN with ZERO issues.
> Do NOT stop, pause, or quit until the work is complete.

# Update Moltbot

## Overview
Updates the Moltbot application by synchronizing with the upstream repository, rebuilding the container image (applying any local Dockerfile overrides), and restarting the deployment.

**Protocol**:
- **Source**: Upstream (`github.com/moltbot/moltbot`) is the source of truth.
- **Modifications**: All logic changes are applied via `patches` in `values.yaml`, NOT by modifying source files.
- **Image**: Built locally. A custom `Dockerfile` in `apps/moltbot/` (if present) overrides the upstream one.

---

## Phase 1: Upstream Synchronization

1.  **Verify Repository**:
    -   Target: `~/Documents/Github/moltbot`
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
    -   Verify `apps/moltbot/values.yaml` contains all necessary `patches` (ConfigMap injections) for any custom logic.
    -   Ensure `image.repository` in `values.yaml` points to `10.0.20.11:32309/moltbot`.

2.  **Execute Build Script**:
    -   Run: `apps/moltbot/scripts/build.sh`
    -   **Action**: Builds the image using `apps/moltbot/Dockerfile` (if present) or upstream.
    -   **Push**: Pushes to local registry `registry.eaglepass.io/moltbot:latest`.
    -   **Note**: The build script automatically handles copying the custom Dockerfile to the source repo.

---

## Phase 3: Deployment Update

1.  **Restart Application**:
    -   Command: `kubectl rollout restart deployment moltbot -n moltbot`
    -   Validation: Wait for rollout to complete (`kubectl rollout status deployment/moltbot -n moltbot`).

2.  **Verify Pod Startup**:
    -   Wait for Pod Running: `kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=moltbot -n moltbot --timeout=60s`

---

## Phase 4: Test & Validation (Mandatory)

**Objective**: Confirm the new image is running, stable, and error-free.

1.  **Health Check**:
    -   Status: `kubectl get pods -n moltbot` (Expect: `1/1` Ready, `Running`, `0` Restarts)
    -   Endpoint: `curl -I https://moltbot.eaglepass.io` (Expect: HTTP 200/401/403 - reachable)

2.  **Log Analysis**:
    -   Fetch logs: `kubectl logs -n moltbot -l app.kubernetes.io/name=moltbot --tail=100`
    -   **Check**: Scan for `Error`, `Exception`, `Fatal`, or `SyntaxError`.
    -   **Verify Patches**: If patches were applied (e.g., timezone fix), grep logs for confirmation if available, or verify functionality.

3.  **Foundational Rule Check**:
    -   Metal: Nodes Ready?
    -   System: Ceph Healthy?
    -   Platform: ArgoCD Synced/Healthy?
    -   Apps: Moltbot Running?

4.  **Completion**:
    -   Only mark complete when ALL status checks are GREEN and logs are clean.
