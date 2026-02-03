# Specification: Openclaw Governance Rule

## Overview
This specification defines the creation of a governance rule for the Openclaw application within the homelab environment. The rule ensures that Openclaw remains maintainable and up-to-date with official releases by strictly controlling how modifications are made and verified.

## User Stories
1. **Developer Guidance**: As a developer, I want a clear set of rules for modifying Openclaw so that I don't break the application or complicate updates.
2. **Stability Assurance**: As a maintainer, I want to ensure that every change to Openclaw is verified against the entire homelab stack to maintain stability.

## Requirements
1. **File Locations**:
    - `.agent/rules/HOMELAB_openclaw.md`
    - `.opencode/rules/HOMELAB_openclaw.md`
2. **Mandatory Documentation Reference**: Every change must reference [https://docs.openclaw.ai/](https://docs.openclaw.ai/).
3. **Configuration Only**:
    - All application changes must be performed through `openclaw.json` (via ConfigMap) or environment variables.
    - No code injections, manual patches, or modifications to the container's internal files are allowed.
4. **Official Updates**: The setup must be able to receive updates from the official Openclaw pipeline (ghcr.io/openclaw/openclaw) without breaking customizations.
5. **Verification Protocol**:
    - Every change to environment variables or `openclaw.json` must be followed by a verification step.
    - All homelab layers (Metal, System, Platform, Apps) must be "green" (healthy).
    - The Openclaw pod must be running and healthy.
    - Openclaw pod logs must be checked to ensure internal health.

## Quality Checklist
- [ ] Rule files exist in both `.agent/rules/` and `.opencode/rules/`.
- [ ] Documentation URL is clearly mentioned as a mandatory reference.
- [ ] Forbidding of code patches is explicit.
- [ ] Verification steps (layers + pod + logs) are defined.
