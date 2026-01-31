# Specification: Fix OpenClaw Pairing Issue

## Context
User reports "disconnected (1008): pairing required" when accessing OpenClaw WebUI at `https://openclaw.eaglepass.io`.
Token connection attempt also failed.
Pod is running and healthy in Kubernetes.
Ingress is configured.

## User Story
As a user, I want to connect to the OpenClaw WebUI without "pairing required" errors so I can manage my game servers.

## Requirements
- [ ] Diagnose the root cause of the 1008 error.
- [ ] Verify the `gateway-token` configuration in `values.yaml` or secrets.
- [ ] Ensure the correct token is being used or generated.
- [ ] Update configuration if necessary to allow connection or persist the token.
- [ ] Validate WebUI access works.

## Technical Considerations
- OpenClaw seems to generate a token on first start if not provided.
- Persistence is mounted at `/home/node/.openclaw`.
- Config might be needing a static token or specific env var.

## Quality Checklist
- [ ] WebUI loads without error.
- [ ] Login/Connection persists across restarts (if applicable).
- [ ] No regression in deployment status.
