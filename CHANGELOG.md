# Changelog

## [v0.1.1-rc.1] — 2026-07-29 — Canary release candidate

### Fixed
- PVC Multi-Attach error: scoped minio-data PVC to minio controller via `advancedMounts`
- DB Password security: replaced hardcoded `DATABASE_URL` with `secretKeyRef` referencing `threads-canary-secrets`
- Connection error: set `sslmode=disable` for `DATABASE_URL` to match local unencrypted postgres
