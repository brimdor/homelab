# Tasks: Fix Exo Errors

**Status**: Complete
**Feature**: 1-fix-exo-errors

## Phase 1: Setup
- [x] 100-verify-context [US1] Verify and document correct Docker build context usage (Exo source tree + `apps/exo/Dockerfile`)

## Phase 2: User Story 1 (Fix Build)
- [x] 200-dockerfile-refactor [US1] Switch Dockerfile to copy local source `apps/exo/Dockerfile` (FR-001, FR-004)
- [x] 201-clean-up-clone [US1] Remove git clone instructions `apps/exo/Dockerfile` (FR-004)

## Phase 3: Verification
- [x] 300-verify-build [US1] Execute local docker build using Exo source tree as context (FR-001, SC-001)
- [x] 301-validate-image [US1] Inspect generated image layers (FR-001)
- [x] 302-helm-deploy [US1] Push image and deploy via Helm (FR-002, SC-002)
- [x] 303-pod-health [US1] Verify pods reach `Ready` state and do not crashloop (FR-003, SC-002, SC-003)
