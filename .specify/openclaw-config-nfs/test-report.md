# Test Report: OpenClaw Config From NFS

**Date**: 2026-02-03
**Branch**: feat/openclaw-config-nfs

## Checks Run
- `helm lint apps/openclaw` (PASS)
- `helm template openclaw apps/openclaw` + search for embedded config strings (PASS)

## Notes
- Rendered manifests no longer include the `openclaw.json` content.
- Rendered manifests still reference the config file path `/home/node/.openclaw/openclaw.json` (expected).
