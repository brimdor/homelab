# Tools: Vista

## Primary Tools
- **Testing**: Native test runners for the project language.
- **Recon**: `/homelab-recon` for absolute environment validation.
- **Analysis**: `grep`, `tail`, and `kubectl logs` for deep-dive investigation.

## Reference Library
- `spec.md` (Current project's Acceptance Criteria).
- Homelab Foundational Rules (Zero tolerance for non-GREEN).
- Openclaw Log API.

## Verification Guardrails
- Must pass on ARM64 nodes.
- Must not cause resource pressure (checked via `/homelab-recon`).
