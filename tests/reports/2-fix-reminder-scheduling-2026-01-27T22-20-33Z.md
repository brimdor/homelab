# Test Report: Fix Reminder Scheduling

**Feature**: 2-fix-reminder-scheduling
**Branch**: 2-fix-reminder-scheduling
**Generated**: 2026-01-27T22:20:33Z
**Status**: ❌ FAILED (environment prerequisites missing)

---

## Summary

| Category | Total | Passed | Failed | Skipped | Status |
|----------|-------|--------|--------|---------|--------|
| Unit Tests | 1 | 1 | 0 | 0 | ✅ |
| Integration Tests | 0 | 0 | 0 | - | ⊘ Not Run |
| Contract Tests | 0 | 0 | 0 | - | ⊘ Not Run |
| E2E Tests | 0 | 0 | 0 | - | ⊘ Not Run |
| Visual Regression | 0 | 0 | 0 | - | ⊘ Not Run |
| Accessibility | 0 | 0 | 0 | - | ⊘ Not Run |
| Cross-Browser | 0 | 0 | 0 | - | ⊘ Not Run |
| Performance | 0 | 0 | 0 | - | ⊘ Not Run |
| Linting | 0 | 0 | 0 | - | ⊘ Not Run |
| Security | 0 | 0 | 0 | - | ⊘ Not Run |

**Overall Coverage**: N/A
**Total Issues**: 2

---

## Detailed Results

### Unit Tests

| Test | Result |
|------|--------|
| `TestClawdbotParseTimeWithZone_DefaultsToSystemTZ` | PASS |

Command:

```bash
make -C test filter=TestClawdbotParseTimeWithZone_DefaultsToSystemTZ
```

Notes:
- This test executes the patched `parse.js` logic embedded in `apps/clawdbot/values.yaml` using the local `node` binary.

---

## Failure Details

### FAIL-001 Missing `gotestsum`

The repository test runner (`make test`) requires `gotestsum`, but it is not available in this environment.

### FAIL-002 Missing `pre-commit`

The repo lint workflow expects `pre-commit`, but it is not available in this environment.
