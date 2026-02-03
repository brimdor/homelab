---
description: Governance rules for the Openclaw application
type: rule
applies_to:
  - homelab-troubleshoot
  - homelab-recon
  - homelab-action
  - do-the-thing
sync_locations:
  - .agent/rules/HOMELAB_openclaw.md
  - .opencode/rules/HOMELAB_openclaw.md
sync_note: Mandatory governance for Openclaw configuration and verification.
---

# 🦞 Openclaw Governance Rules

> [!IMPORTANT]
> **These rules ensure Openclaw remains maintainable and aligned with official releases.**
> All changes MUST reference the official documentation: [https://docs.openclaw.ai/](https://docs.openclaw.ai/).

---

## Rule 1: Official Pipeline Authority

**We do NOT patch or inject code into Openclaw.**

- **Official Images**: Always use official images from the Openclaw pipeline (`ghcr.io/openclaw/openclaw`).
- **No Injections**: Unlike the "Moltbot Protocol," Openclaw must NOT receive code injections, runtime patches, or overlay mounts for application logic.
- **Maintainability**: This ensures that updates from the official pipeline can be applied without breaking custom logic or requiring patch refactoring.

---

## Rule 2: Configuration Authority

**All application behavior modifications must be performed via configuration files and environment variables.**

- **Config File**: Use `openclaw.json` managed via the `openclaw-config` ConfigMap in `apps/openclaw/values.yaml`.
- **Environment Variables**: Use the `env` section in `apps/openclaw/values.yaml` for pod-level settings.
- **Traceability**: Every change to the configuration or environment variables MUST include a reference to the relevant section of the [Openclaw Documentation](https://docs.openclaw.ai/).

---

## Rule 3: Verification Protocol

**Every change to Openclaw configuration requires a full-stack health check.**

A change is not considered "complete" or "safe" until the following checks are passed:

1.  **Homelab Layer Check**: Execute `/homelab-recon` (or equivalent layer checks). All layers (**Metal**, **System**, **Platform**, **Apps**) MUST be **GREEN**.
2.  **Pod Status**: The Openclaw pod must be in the `Running` state and pass all health probes.
3.  **Internal Health (Logs)**: Inspect the Openclaw pod logs (`kubectl logs -l app.kubernetes.io/name=openclaw`). The logs must show successful initialization and no application-level errors or crashes.

---

## Rule 4: Zero Deviation

**If any of the verification steps fail, the change MUST be reverted or fixed immediately.**

There is no "partial success" for Openclaw configuration changes. If the logs show internal errors even if the pod is "Running," the configuration is considered invalid.
