# Specification: Fix OpenClaw Pairing Issue

## Context
The OpenClaw application in the homelab is currently inaccessible via the WebUI. Users encounter a "disconnected (1008): pairing required" error. Attempting to connect via the token URL (`https://openclaw.eaglepass.io/?token=<gateway-token>`) also fails. This prevents management of game servers.

## User Scenarios & Testing

### P1: Successful WebUI Connection
**As a** homelab administrator
**I want to** access the OpenClaw WebUI without pairing errors
**So that** I can manage my game servers

**Acceptance Scenarios:**
- **Given** the OpenClaw pod is running and healthy
- **When** I navigate to `https://openclaw.eaglepass.io`
- **Then** the WebUI loads successfully without a "pairing required" error overlay
- **And** I can see the dashboard status

### P2: Token Authentication Verification
**As a** homelab administrator
**I want to** use the gateway token to authenticate if required
**So that** I can bypass pairing restrictions if they are enabled

**Acceptance Scenarios:**
- **Given** I have the correct gateway token
- **When** I access `https://openclaw.eaglepass.io/?token=<TOKEN>`
- **Then** the session is authenticated
- **And** subsequent accesses do not require the token in the URL (session persistence)

## Requirements

### Functional Requirements
- **FR-001**: The OpenClaw application MUST be configured to allow WebUI connections from the ingress domain.
- **FR-002**: The application MUST accept a valid authentication token or have pairing disabled/configured correctly.
- **FR-003**: The `gateway-token` (if required) MUST be correctly propagated from Kubernetes secrets/config to the application container.
- **FR-004**: Network policies (if any) MUST allow traffic from Ingress to the OpenClaw service.

### Key Entities
- **OpenClaw Pod**: The running container instance.
- **Values.yaml**: Helm chart configuration for the application.
- **Secret**: The Kubernetes secret containing the gateway token.
- **Ingress**: The entry point `openclaw.eaglepass.io`.

## Success Criteria
- [ ] User confirms "pairing required" error is resolved.
- [ ] WebUI is accessible and functional.
