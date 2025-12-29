# Tasks: Fix Exo Errors

**Status**: Complete
**Feature**: 1-fix-exo-errors

## Phase 1: Setup
- [x] 100-verify-context [P] Verify local context availability `apps/exo/`

## Phase 2: User Story 1 (Fix Build)
- [x] 200-dockerfile-refactor [US1] Switch Dockerfile to copy local source `apps/exo/Dockerfile`
- [x] 201-clean-up-clone [US1] Remove git clone instructions `apps/exo/Dockerfile`

## Phase 3: Verification
- [x] 300-verify-build [US1] Execute local docker build `apps/exo/`
- [x] 301-validate-image [US1] Inspect generated image layers
- [x] 302-helm-deploy [US1] Push image and deploy via Helm (FR-002)
- [x] 303-pod-health [US1] Verify pods reach Running state (FR-003)
