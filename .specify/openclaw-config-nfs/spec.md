# Spec: OpenClaw Config From NFS

**Feature**: OpenClaw Config From NFS
**Created**: 2026-02-03
**Status**: Implemented

## Context
The OpenClaw deployment currently embeds `openclaw.json` in the Helm chart and mounts it read-only into the pod.

This change moves the configuration source-of-truth to the existing NFS-backed persistent storage so configuration survives chart updates and pod restarts.

## Goals
- Persist `openclaw.json` on the existing NFS-backed state volume.
- Remove `openclaw.json` content from the Helm chart.
- Ensure the pod uses the persisted `openclaw.json` and fails fast if it is missing or incorrect.

## Non-Goals
- Redesign the OpenClaw configuration schema.
- Change OpenClaw authentication/secrets handling.
- Introduce a new secrets management mechanism.

## User Stories & Acceptance Scenarios

### P1 - Persisted Config File Is Used
As an operator, I want OpenClaw to load its configuration from a file stored on the NFS-backed persistent volume so configuration persists across chart upgrades.

Acceptance scenarios:
- Given the NFS volume contains `openclaw.json` with valid configuration
  When the pod starts
  Then OpenClaw reads configuration from the NFS file path
  And OpenClaw reaches Ready state.

### P1 - Fail Fast When Config Is Missing
As an operator, I want the deployment to clearly fail if the persisted `openclaw.json` is missing so misconfiguration is obvious.

Acceptance scenarios:
- Given the NFS volume does not contain `openclaw.json`
  When the pod starts
  Then the pod does not become Ready
  And logs include a clear message describing the expected file path and how to populate it.

### P2 - Validate Persisted Config Matches Expected Configuration
As an operator, I want the deployment to validate that the persisted `openclaw.json` matches the expected configuration so drift is detected.

Acceptance scenarios:
- Given the NFS volume contains `openclaw.json` but its content does not match the expected configuration
  When the pod starts
  Then the pod does not become Ready
  And logs include a clear message that validation failed.

## Requirements

### Functional Requirements
- FR-001: The Helm chart must not embed the `openclaw.json` configuration content.
- FR-002: OpenClaw must be configured to load `openclaw.json` from the NFS-backed persistent volume.
- FR-003: The pod must fail fast with a clear error if the persisted `openclaw.json` is missing.
- FR-004: The pod must validate the persisted `openclaw.json` against an expected checksum (or equivalent deterministic validation) before starting OpenClaw.
- FR-005: The repository must include a reference copy of the current `openclaw.json` configuration used for validation and for populating NFS out-of-band.
  - The reference copy must live outside the Helm chart directory so the configuration is not packaged with the chart.

### Operational Requirements
- OR-001: Migration must be documented so operators can copy the current config onto the NFS share before rollout.
- OR-002: No plaintext secrets are introduced in the configuration file; secrets remain sourced from Kubernetes Secret/ExternalSecret.

## Success Criteria
- SC-001: `apps/openclaw/values.yaml` no longer contains the `openclaw.json` content.
- SC-002: A pod with a correctly populated NFS config starts and becomes Ready.
- SC-003: A pod with missing or mismatched NFS config fails quickly with actionable logs.
