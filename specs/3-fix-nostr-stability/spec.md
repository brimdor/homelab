# Specification: Fix Nostr Stability

**Feature ID**: 3-fix-nostr-stability  
**Status**: Draft  
**Created**: 2026-02-03  
**Author**: OpenCode Agent

---

## Overview

The OpenClaw application's Nostr channel stops working after approximately 30-40 minutes of runtime. This specification addresses the stability issue through Kubernetes-level monitoring and automatic recovery.

## Problem Statement

The Nostr extension uses `nostr-tools` `SimplePool.subscribeMany` to maintain WebSocket connections to Nostr relays. These connections are dropped after 30-60 minutes due to:
- Relay-side idle timeouts
- Network interruptions
- Relay restarts

The current implementation lacks automatic reconnection logic - when the subscription closes, it logs an error but doesn't re-establish the connection.

## Success Criteria

- OpenClaw's Nostr channel remains functional for **45+ minutes** continuously
- Automatic recovery occurs without manual intervention
- No data loss during reconnection events

---

## User Stories

### US-1: Reliable Nostr Messaging
**As** a homelab operator  
**I want** the Nostr channel to remain functional indefinitely  
**So that** I can communicate with OpenClaw via Nostr without interruptions

**Acceptance Criteria**:
- Nostr channel works continuously for at least 45 minutes
- Pod restarts automatically if Nostr health degrades
- Recovery time is less than 2 minutes

### US-2: Health Visibility
**As** a homelab operator  
**I want** to see Nostr health status  
**So that** I can monitor the system's reliability

**Acceptance Criteria**:
- Health check endpoint indicates Nostr subscription status
- Kubernetes events show restart reasons

---

## Technical Requirements

### TR-1: Nostr Health Endpoint
The OpenClaw container must expose a health endpoint that verifies the Nostr subscription is active, not just that the HTTP server is responding.

**Current State**: The `/health` endpoint only checks if the gateway HTTP server is running, not the Nostr subscription health.

**Solution Options**:
1. **Option A (Selected)**: Enhance the existing wss-watchdog sidecar to check the actual Nostr relay connectivity and use its healthz endpoint for liveness probes
2. **Option B**: Add an additional health check that queries OpenClaw's channels.status API

### TR-2: Liveness Probe Enhancement
Configure Kubernetes liveness probes to restart the pod when Nostr health degrades.

**Current State**:
- Main container has liveness probe on `/health:18789` (gateway health only)
- wss-watchdog sidecar has liveness probe on `/healthz:8080` (relay connectivity check)

**Solution**: Tighten wss-watchdog probe thresholds to trigger faster restarts when relays are unreachable, since unreachable relays indicate the Nostr subscription is likely dead.

### TR-3: Graceful Recovery
The pod restart should:
- Complete within 2 minutes
- Restore Nostr connectivity automatically
- Not affect other OpenClaw channels (Discord)

---

## Implementation Approach

### Approach: Add wss-watchdog as Sidecar Container

The previous architecture had wss-watchdog as a **separate Deployment**, which meant it couldn't trigger OpenClaw pod restarts. The fix is to add wss-watchdog as a **sidecar container** within the OpenClaw pod itself.

**Files Modified**:
1. `apps/openclaw/values.yaml` - Add wss-watchdog sidecar container
2. `apps/openclaw/templates/configmap-wss-checker.yaml` - Add ConfigMap with wss-checker code

### Sidecar Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| CHECK_INTERVAL | 15000ms | Check relays every 15 seconds |
| FAIL_THRESHOLD | 2 | Mark unhealthy after 2 consecutive failures (30s) |
| Liveness periodSeconds | 20 | Check sidecar health every 20 seconds |
| Liveness failureThreshold | 3 | Restart pod after 3 failed probes (60s) |
| Liveness initialDelaySeconds | 30 | Allow time for npm install |

### Expected Behavior

1. wss-watchdog sidecar checks relay connectivity every 15 seconds
2. After 2 consecutive failures (30s of relay issues), `/healthz` returns 500
3. After 3 failed liveness probes (60s), Kubernetes restarts the **entire pod**
4. Pod restart forces OpenClaw main container to reinitialize Nostr subscriptions
5. Total time from issue to recovery: ~90-120 seconds

---

## Out of Scope

- Modifying the Nostr extension source code
- Adding reconnection logic to nostr-tools usage
- Multi-pod high-availability setup
- Nostr subscription-level health checks (would require extension changes)

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| False positives from relay checks | Unnecessary restarts | Use multiple relays, require 2+ failures |
| Discord channel disruption on restart | Temporary unavailability | Discord gateway handles reconnection gracefully |
| Restart loops if relays truly down | Pod crashloop | Kubernetes backoff prevents tight loops |

---

## Testing Strategy

### Validation Test
1. Deploy the changes
2. Monitor the pod for 45+ minutes
3. Verify Nostr messages are received throughout
4. Check for any unexpected restarts

### Success Metrics
- Pod runs continuously for 45+ minutes with healthy Nostr
- If relay issues occur, recovery happens within 2 minutes
