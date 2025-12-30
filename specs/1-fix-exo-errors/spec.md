# Feature Specification: Fix Exo Errors

**Feature Branch**: `1-fix-exo-errors`
**Created**: 2025-12-29
**Status**: Complete
**Test Report**: `tests/reports/1-fix-exo-errors-2025-12-30T00-02-22Z.md`
**Input**: User description: "Its getting lots of errors, fix it."

## User Scenarios & Testing

### User Story 1 - Error-Free Build and Deployment (Priority: P1)

As a developer, I want the Exo application to build and deploy without errors so that I can use the distributed AI cluster.

**Why this priority**: The application is currently unusable due to errors.

**Independent Test**: Run `docker build` and deploy via Helm.

**Acceptance Scenarios**:

1. **Given** the Exo source code, **When** I run `docker build`, **Then** the image builds successfully without errors.
2. **Given** a deployed Exo cluster, **When** I check pod status, **Then** all pods are Running and Healthy.

## Requirements

### Functional Requirements

- **FR-001**: The `apps/exo/Dockerfile` MUST build successfully when invoked against the Exo source tree as the build context (exit code 0).
- **FR-002**: The Helm chart at `apps/exo/` MUST render and install/upgrade successfully (e.g., `helm lint` passes; `helm upgrade --install` exits 0 in a real cluster).
- **FR-003**: After deployment, the Exo pod(s) MUST reach `Ready` state within 5 minutes and MUST NOT enter `CrashLoopBackOff` during a 10-minute observation window.
- **FR-004**: The container build MUST NOT fetch Exo source code via `git clone` (the image is built from the provided build context to avoid “works on upstream, fails locally” drift).

### Key Entities

- **Exo Node**: A node in the AI cluster.

## Edge Cases

- Building the image requires using the Exo source tree as the Docker build context (the Dockerfile lives in this repo, but the sources it copies come from the Exo repo).
- Network-restricted environments may fail during `npm install`, `uv sync`, or `rustup` downloads during image build; treat these as environment issues rather than Dockerfile logic regressions.

## Success Criteria

### Measurable Outcomes

- **SC-001**: `docker build` returns exit code 0.
- **SC-002**: Exo pod(s) reach `Ready` state within 5 minutes after deployment.
- **SC-003**: No `CrashLoopBackOff` events occur during the first 10 minutes after startup; logs during the first 60 seconds contain no Python traceback / unhandled exception output.
