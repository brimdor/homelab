# TASKS.md - Patch

## Pending
- [ ] Monitor Echo logs for 429 FailoverErrors (confirm failover to local Echo works)
- [ ] Hardening: Propose and apply Telegram security fixes (groupPolicy="allowlist") on Echo
- [ ] Hardening: Propose and apply Gateway bind address fix (bind="loopback") on Echo

## Completed
- [x] Tightening: Document Echo infra-only boundary (no agents/skills/bindings/tools/workspace edits)
- [x] Investigate Telegram 409 Conflict (Resolved)
- [x] Apply config fix (maxConcurrent=1 + fallbacks) to Echo (Remote)
- [x] Verify Echo restart and stability after fix (Echo restarted and channels reloaded)
