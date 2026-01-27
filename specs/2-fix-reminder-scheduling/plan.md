# Implementation Plan: Fix Reminder Scheduling

**Feature**: Fix Reminder Scheduling
**Branch**: `2-fix-reminder-scheduling`
**Created**: 2026-01-27

## Technical Context

- **Project Type**: Homelab GitOps repo; Clawdbot deployed via Helm chart at `apps/clawdbot/`
- **Relevant Runtime**: Node.js (Clawdbot gateway)
- **Patch Mechanism**: ConfigMap injection defined in `apps/clawdbot/values.yaml` under `patches.data` (overlays files in `/app/dist/...`)
- **Timezone Source**: Runtime `TZ` env var (`America/Chicago`)

## Problem Summary

Clawdbot reminder scheduling produces cron jobs with a later day/time than requested. The cron tool documentation indicates that `schedule.kind="at"` supports ISO strings or `YYYY-MM-DD HH:mm` and an optional `tz`. When `tz` is omitted, the current parsing path interprets date/time strings as UTC, causing timezone/day shifts.

## Approach

1. Adjust the patched time parsing utility so that when no explicit timezone (`schedule.tz`) is provided, it defaults to the runtime environment timezone (derived from `Intl.DateTimeFormat().resolvedOptions().timeZone` / `TZ`).
2. Keep explicit timezone / offset inputs authoritative (e.g., `Z`, `-06:00`, `+01:00`).
3. Add a small repository-local validation script/test harness to prevent regressions in the parsing behavior for:
   - absolute local times (no tz provided)
   - explicit tz provided
   - near-midnight cases (day boundary)
   - DST boundary sanity cases

## Files to Change

- `apps/clawdbot/values.yaml` (update `parse.js` patch)
- `test/` (add a lightweight validation test for the parsing behavior)

## Constitution Check

- **Spec-First Development**: Spec exists at `specs/2-fix-reminder-scheduling/spec.md`
- **Test-Driven Quality**: Add automated validation for time parsing behavior (within repo constraints)
- **Documentation as Code**: Keep spec/plan/tasks updated to match implementation

## Risks / Constraints

- Upstream Clawdbot is the source of truth; this repo can only patch via Helm/config injection.
- Node/Intl timezone behavior depends on ICU data and `TZ`; tests must avoid assumptions beyond `America/Chicago`.
