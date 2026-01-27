---
description: Rules for managing applications in the homelab
type: rule
applies_to:
  - homelab-troubleshoot
  - homelab-action
  - do-the-thing
sync_locations:
  - ~/.gemini/SUB_RULES/HOMELAB_applications.md
  - ~/.config/opencode/rules/HOMELAB_applications.md
  - .agent/rules/HOMELAB_applications.md
sync_note: Governance for application lifecycle and code modifications.
---

# 📦 Homelab Application Rules

> [!IMPORTANT]
> **These rules govern how applications are managed, built, and patched.**
> Strict adherence ensures maintainability and prevents "fork-drift" where our version diverges permanently from upstream.

---

## Rule 1: External Source Authority

**We do not own external application repositories.**

- **No Permanent Forks**: Do not create persistent forks of upstream repositories unless absolutely necessary (and approved).
- **Upstream Priority**: Always assume the upstream repository is the source of truth.
- **Local Clones**: Local clones (e.g., in `~/Documents/Github/`) are ephemeral workspaces for analysis or build generation, NOT permanent storage for our changes.

---

## Rule 2: Image Ownership

**We own specific container images stored in our local registry.**

- **Registry**: `registry.eaglepass.io` (Internal) / `10.0.20.11:32309` (Cluster Pull).
- **Self-Built Images**: We build and own images for core applications (like Clawdbot) that require deep customization. These are pushed to `registry.eaglepass.io`.
- **Upstream Images**: For standard applications, we use official upstream images (e.g., from Docker Hub). We do NOT own these.

- **Build Scripts**: Build logic resides in `apps/<app-name>/scripts/build.sh` within the homelab repository.
- **Dockerfile Management**: If we need a custom Dockerfile, it lives in the homelab repository or is generated during the build process. Do not rely on the upstream Dockerfile remaining compatible with our needs.

---

## Rule 3: The "Patch-Over" Strategy (Clawdbot Protocol)

**Code changes MUST be injected at runtime, not committed to source.**

When we need to modify the behavior of an external application (like fixing a bug in Clawdbot):

1.  **Analyze Source**: Clone the upstream repo locally to understand the code.
2.  **Develop Fix**: Create the fix locally and verify it (e.g., via unit tests).
3.  **Compile & Extract**: If the app is compiled (TypeScript/Go/etc.), build the artifacts.
4.  **Inject via ConfigMap**: 
    - Create a `patches` ConfigMap in the application's `values.yaml` (in the homelab repo).
    - Paste the **compiled/final code** into the ConfigMap data.
    - Use `volumeMounts` (or `advancedMounts`) to overlay the patched file onto the container's filesystem at runtime (e.g., mounting `/app/dist/foo.js`).
5.  **Do Not Commit Source**: Revert changes in the local source repo. Do NOT commit custom logic to the upstream git history.

### Why?
- **Updatability**: We can pull the latest upstream image/code and simply re-apply our patches (or remove them if upstream fixes the issue).
- **Cleanliness**: The homelab repo remains the single source of truth for *our* configuration and logic.
- **Persistence**: Data in the homelab repo is persistent; data in a local git clone is not guaranteed.

---

## Rule 4: Application Structure

**All application configuration resides in the homelab repository.**

Standard structure for `apps/<app-name>/`:
- `Chart.yaml` / `Chart.lock`: Helm dependency definition.
- `values.yaml`: The definitive configuration, including:
    - Image tags.
    - Environment variables.
    - **Patches (ConfigMaps)**.
    - Ingress/Service configuration.
- `scripts/`: Maintenance scripts (backup, restore, build).

---

## Example: Clawdbot

**Context**: Clawdbot is an external agent framework. We run it as a comprehensive homelab assistant.

- **Source**: External repo (locally at `~/Documents/Github/clawdbot`).
- **Image**: Built via `apps/clawdbot/scripts/build.sh`.
- **Modifications**: 
    - **Forbidden**: Editing `src/...` in the clawdbot repo and committing it there.
    - **Required**: Editing `values.yaml` in the homelab repo to mount patched JS files into `/app/dist/...`.
