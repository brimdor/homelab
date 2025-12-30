# Plan: Fix Exo Errors

**Feature**: 1-fix-exo-errors
**Status**: Complete

## Technical Context

- **Language**: Python (Exo), TypeScript (Dashboard)
- **Containerization**: Docker
- **Orchestration**: Kubernetes (Helm)
- **Dependencies**: `uv` (Python), `npm` (Node.js), `rustup` (Rust)

## Approach

1.  **Refactor Dockerfile**: Switch from "clone-and-build" to "copy-and-build" pattern.
2.  **Verify Build**: Ensure local code builds successfully.
3.  **Validate Deployment**: Ensure the new image works in the cluster.

## Phase 0: Research
- [x] Analyze current Dockerfile (Found `git clone` usage).
- [x] Verify upstream build (Succeeded, implying local context mismatch or confusion).

## Phase 1: Design
- **Data Model**: N/A
- **API**: N/A

## Phase 2: Implementation
- Modify `apps/exo/Dockerfile`

## Phase 3: Testing
- Build Docker image locally.
