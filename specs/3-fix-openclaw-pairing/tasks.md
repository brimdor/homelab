# Tasks: Fix OpenClaw Pairing Issue

## Phase 1: Remediation
- [x] TASK-001 Restart OpenClaw pod to resolve NFS Stale Handle (kubectl delete pod).

## Phase 2: Verification
- [x] TASK-002 [US1] Verify NFS mount inside new pod `ls -la /home/node/.openclaw`
- [x] TASK-003 [US1] Verify WebUI connectivity check
- [x] TASK-004 [US2] Verify token authentication (optional if WebUI works)

## Phase 3: Cleanup
- [x] TASK-005 Update status report
