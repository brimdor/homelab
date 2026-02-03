# Specification: OpenClaw Mem Integration

## Overview
This specification defines the setup and configuration of the "OpenClaw Mem" skill from ClawHub within the homelab's OpenClaw instance. OpenClaw Mem is an intelligent auto-journaling and memory retention system that summarizes daily logs and prunes old data to maintain efficient context.

## User Stories
1. **Automated Memory Hygiene**: As a user of OpenClaw, I want the system to automatically summarize my raw logs into structured journals so that I can maintain long-term context without hitting token limits.
2. **Declarative Configuration**: As a homelab maintainer, I want to manage the installation of this skill via GitOps (declarative config) so that the setup is reproducible and survives pod restarts.

## Requirements
1. **Skill Source**: `https://www.clawhub.com/WeAreAllSatoshiN/openclaw-mem`
2. **Installation Method**: 
    - Use both `openclaw.json` (via `skills.managed`) and environment variables if required, ensuring GitOps compliance.
    - Preference is given to `openclaw.json` as it is the central authority for OpenClaw.
3. **Governance Compliance**:
    - Do NOT patch the OpenClaw container.
    - Use the `openclaw-config` ConfigMap for configuration (defined in `values.yaml`).
    - Reference [official documentation](https://docs.openclaw.ai/) for any configuration parameters.
4. **Verification**:
    - Verify that the skill is successfully loaded and initialized by OpenClaw.
    - Perform a `/homelab-recon` to ensure cluster health.
    - Check pod logs for "OpenClaw Mem" initialization messages.

## Quality Checklist
- [ ] `openclaw.json` or `values.yaml` environment variables updated.
- [ ] No manual code injections or mounts for application logic.
- [ ] Pod restarts successfully and shows the skill as loaded.
- [ ] All homelab layers are GREEN.
