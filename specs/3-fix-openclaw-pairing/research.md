# Research: OpenClaw Pairing Issue

## Investigation Findings

### 1. Log Analysis
- Pod logs show repeated `code=4008 reason=connect failed durationMs=... cause=pairing-required` errors.
- Connection attempts from trusted proxy `10.0.2.71` are rejected.

### 2. Configuration Verification
- `OPENCLAW_GATEWAY_TOKEN` environment variable is correctly set in the pod.
- Token value matches the `gateway-token` key in the `secrets` secret.

### 3. Persistence Check (CRITICAL)
- Execution of `ls -la /home/node/.openclaw` inside the pod returned `Stale file handle`.
- This indicates the NFS mount is broken, preventing the application from reading/writing configuration or pairing state.
- This is the likely root cause of the "pairing required" loop (app cannot read existing pairing or save new one).

## Decision
- **Action**: Restart the pod to refresh the NFS mount.
- **Rationale**: Stale file handles are typically resolved by client reconnection (pod restart).
