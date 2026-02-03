# Plan: OpenClaw Config From NFS

**Feature**: OpenClaw Config From NFS
**Created**: 2026-02-03

## Technical Context
- **Platform**: Kubernetes (GitOps)
- **Packaging**: Helm chart `apps/openclaw` (bjw-s `app-template` dependency)
- **Persistence**: NFS mount already used for `/home/node/.openclaw`
- **Config file**: `openclaw.json`

### Constraints
- No plaintext secrets committed; tokens/keys remain in Kubernetes Secret/ExternalSecret.
- `openclaw.json` content must not be embedded in Helm values/templates.
- Configuration must survive pod restarts and chart upgrades.

## Approach

### 1) Make NFS the config source-of-truth
- Set `OPENCLAW_CONFIG_PATH` to the persisted file path: `/home/node/.openclaw/openclaw.json`.
- Remove the `ConfigMap`-backed `/config/openclaw.json` mount.
- Remove `openclaw.json` from the chart values (`configMaps.*.data.openclaw.json`).

### 2) Validate the config file at startup
- Add an init container that mounts the same NFS volume and:
  - Fails if `/home/node/.openclaw/openclaw.json` is missing or empty.
  - Computes `sha256` of the file and compares it to an expected value provided via values.
  - Logs actionable guidance on failure.

This provides a deterministic guarantee that the pod is using the "current" intended config without re-embedding the JSON in the chart.

### 3) Provide a reference config for operators
- Add a repo-tracked reference file containing the intended `openclaw.json` content.
  - Store it outside the Helm chart directory so it is not packaged with the chart.

Reference file:
- `.specify/openclaw-config-nfs/reference/openclaw.json`
- Document the one-time migration and ongoing update workflow:
  - Copy reference config to the NFS share.
  - Update the expected checksum value in the chart.

## Migration Plan
1. Export the current config content (reference file in repo).
2. Copy it onto the NFS share as `openclaw.json` (at the root of the share backing `/home/node/.openclaw`).
   - NFS server path: `/mnt/user/openclaw/openclaw.json`
   - Pod path: `/home/node/.openclaw/openclaw.json`
3. Deploy the chart change.
4. Confirm the init container passes and OpenClaw becomes Ready.

## Constitution Check
- Spec-first development: satisfied (spec exists before implementation).
- Documentation as code: satisfied (plan/tasks + migration docs).
- Test-driven quality: use Helm lint + chart rendering validation, and add a smoke validation checklist for expected pod behavior.
