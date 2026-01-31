# Implementation Plan - Fix OpenClaw Pairing Issue

## Technical Context
- **Component**: OpenClaw Gateway
- **Issue**: WebUI connectivity fails with 1008 Pairing Required.
- **Root Cause (Suspected)**: NFS Stale File Handle on `/home/node/.openclaw` prevents persistence/config access.
- **Infrastructure**: Kubernetes (K3s), Helm, NFS.

## Constitution Checks
- **Spec-First**: Spec defined in `spec.md`.
- **Test-Driven**: Verification via logs and pod health checks.
- **Constitution Alignment**: Remediation of unhealthy infrastructure aligns with homelab maintenance rules.

## Strategy
1.  **Immediate Fix**: Restart the OpenClaw pod to remount the NFS volume.
2.  **Verify**: Check that `/home/node/.openclaw` is accessible after restart.
3.  **Validate**: Confirm WebUI connectivity.
4.  **Documentation**: Update status.

## Verification Plan
- **Pre-Fix**: Confirmed "Stale file handle" via exec.
- **Post-Fix**: Run `kubectl exec ... ls -la /home/node/.openclaw` to confirm access.
- **User Validation**: User to confirm WebUI loads.

## Rollback Plan
- If pod fails to start after restart (e.g. NFS server down), investigate NFS server `10.0.40.3`.
