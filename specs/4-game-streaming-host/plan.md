# Implementation Plan: Containerized Game Streaming Host on Arcanine

**Branch**: `4-game-streaming-host` | **Date**: 2026-07-29 | **Spec**: `specs/4-game-streaming-host/spec.md`
**Input**: Feature specification from `/specs/4-game-streaming-host/spec.md`

## Summary

Deploy Wolf (Games-on-Whales) on arcanine (`10.0.20.19`) as a privileged K3s pod with the GPU operator's `nvidia` runtimeClass, expose the WebUI on `wolf.eaglepass.io` via the existing `cloudflared` tunnel, and expose the streaming ports (TCP 48010, UDP 47999/48100/48200) into the homelab's Tailscale tailnet (`tail18136a.ts.net`) via the official Tailscale Kubernetes Operator's L3 Ingress feature. Bring back the archived `apps/wolf/` chart, fix the bugs, ship it as `apps/streaming/wolf/`, add `platform/tailscale/` for the operator, update the metal Ansible role to set `nvidia-drm.modeset=1` on arcanine, and add operational docs.

## Technical Context

**Language/Version**: YAML/Helm 3 for charts; Go (Wolf upstream) and Rust (gst-wayland-display); no new code in the homelab repo beyond chart templating.

**Primary Dependencies**:
- `ghcr.io/games-on-whales/wolf:stable` (MIT, ~2.1k stars)
- `ghcr.io/tailscale/tailscale-operator` (official; K8s operator that creates per-Service `ProxyGroup` ingress pods)
- bjw-s `app-template` v5.0.1 (already a transitive dep of every chart in this repo)
- `nvidia-container-toolkit` (already installed on arcanine via `metal/roles/docker/`)
- `nvidia-device-plugin` (already deployed via `system/gpu-operator/`)
- cert-manager, ingress-nginx, external-dns, external-secrets, cloudflared — all already deployed cluster-wide

**Storage**: NFS at `10.0.40.3:/mnt/user/wolf` for Wolf's `/etc/wolf` (config, profile state, key/cert). NAS already configured and reachable from the cluster.

**Testing**: Manual end-to-end (Moonlight client pair + launch + play); ArgoCD `App Health=Healthy` and `Sync=Synced` as the smoke test; `kubectl get pods` and `nvidia-smi` on arcanine to confirm GPU binding.

**Target Platform**: K3s 1.30+ on Fedora 43+ (arcanine); Moonlight clients on any platform with the Tailscale client installed (Linux/macOS/Windows/Android/iOS).

**Project Type**: Multi-chart Helm deployment (2 new charts: 1 platform operator + 1 app chart). No new application code.

**Performance Goals**:
- LAN streaming latency ≤ 100ms perceived (round-trip 48010 control + 47999/48100 RTP)
- Per-session NVENC utilization ≤ 80% at 1080p60 HEVC Main profile
- Tailscale L3 Ingress adds ≤ 5ms WireGuard encapsulation overhead
- Wolf pod idle CPU ≤ 200m, idle memory ≤ 1Gi (excl. spawned game containers)

**Constraints**:
- Wolf MUST be `privileged: true` + `hostNetwork: true` + many hostPath mounts (this is the upstream design; not a violation of the homelab rules because it is pinned to the dedicated GPU taint)
- Single-GPU lockout: when Wolf is running, the RTX 3090 is not available to other workloads on arcanine (Ollama etc. must be drained or co-scheduled carefully)
- Cloudflare ToS: no streaming bytes (UDP RTP) may traverse `*.eaglepass.io`; only the small WebUI HTTPS via `cloudflared` is allowed
- Tailscale Personal plan caps the homelab at 6 users (sufficient for the personal use case)
- `nvidia-drm.modeset=1` is a hard requirement and requires an arcanine reboot

**Scale/Scope**: 1 cluster, 1 GPU node, 1 streaming pod, 1 operator pod, 1 L3 ingress ProxyGroup, ≥1 game child container spawned on demand. Per-user state on NFS, ~10MB per profile. Total new persistent state: tens of MB at rest, scaling with installed Steam games (hundreds of GB on the NAS).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Compliance | Notes |
|---|---|---|
| I. Spec-First Development | ✅ Pass | `specs/4-game-streaming-host/spec.md` is complete with 5 user stories, 15 FRs, 8 SCs, 7 edge cases, 1 clarification |
| II. Test-Driven Quality | ✅ Pass | The "tests" for this feature are the operational smoke tests (LAN stream, Tailscale stream, Steam app launch, multi-user, 24h soak) — defined as Success Criteria SC-001 through SC-008. The ArgoCD app-health check + `kubectl get pods` + Moonlight-pairing-and-launch is the validation. |
| III. Constitution Alignment | ✅ Pass | The plan is consistent with `HOMELAB_foundational_rules.md`: Metal layer (arcanine kernel change), System layer (GPU operator already there), Platform layer (new platform/tailscale + apps chart, both picked up by App-of-Apps), Apps layer (Wolf pod healthy, Argo Synced+Healthy). |
| IV. Iterative Refinement | ✅ Pass | Phases 1-9 of this workflow are the iteration; each phase has a gate. |
| V. Documentation as Code | ✅ Pass | `apps/streaming/wolf/README.md` and `docs/streaming/*.md` are deliverables, not afterthoughts. |

No constitution violations.

## Project Structure

### Documentation (this feature)

```text
specs/4-game-streaming-host/
├── plan.md              # This file
├── research.md          # (already done — plans/research/windows-gaming-on-arcanine-report.md is the research; we will symlink or copy)
├── data-model.md        # Streaming Session, App, Profile, Tailnet Device entities
├── quickstart.md        # Operator runbook: pair, launch, troubleshoot
├── contracts/           # No external API contracts (Moonlight protocol is opaque; no new HTTP APIs are created)
├── checklists/requirements.md  # Already created
└── tasks.md             # Phase 5 output
```

### Source Code (repository root)

```text
# New charts (will be created)
platform/tailscale/
├── Chart.yaml                              # tailscale-operator chart
├── values.yaml                             # operator config, oauth_client_id/secret (or auth_key)
├── README.md                               # Why we run it, how to bootstrap the auth key
└── templates/
    ├── operator.yaml                       # The operator deployment + RBAC
    └── externalsecret.yaml                 # The auth key pulled from 1Password

apps/streaming/wolf/
├── Chart.yaml                              # wolf:stable with app-template v5.0.1
├── values.yaml                             # All the runtime/host/secret config
├── README.md                               # Why each env var is set, how the streaming stack works
├── configmap-wolf.yaml                     # Wolf's /etc/wolf/cfg/config.toml with [[profiles.apps]]
└── templates/
    ├── deployment.yaml                     # The Wolf pod (privileged, hostNetwork, nvidia runtime)
    ├── service.yaml                        # WebUI Service on 47989
    ├── ingress.yaml                        # wolf.eaglepass.io via cert-manager + external-dns
    ├── tailscale-proxygroup.yaml           # The L3 Ingress ProxyGroup advertising TCP 48010 + UDP 47999/48100/48200
    ├── external-secret.yaml                # Pulls the webui password from 1Password
    └── networkpolicy.yaml                  # Cilium: allow ingress-nginx to 47989, allow Tailscale ingress to 48010+UDP

# Modified (existing)
metal/roles/virtualization/tasks/gpu_install_drivers.yml
# Add a new task: set nvidia-drm.modeset=1 in /etc/default/grub + grub2-mkconfig + reboot (or alert)

metal/roles/virtualization/handlers/main.yml (if not present, add)
# Handler: reboot if grub changed

external/terraform.tfvars (or .example)
# Add the tailscale auth key reference (already in the schema; just needs to be populated)

docs/streaming/
├── README.md                               # Index
├── pair-moonlight-client.md                # First-time setup
├── launch-a-game.md                        # Workflow
├── add-an-app.md                           # How to add to the catalog
├── upgrade-wolf-and-operator.md            # Bumping image versions
└── troubleshooting.md                      # Common issues (NVENC, audio, network)
```

**Structure Decision**: Two new top-level charts (one platform, one app) under the existing `platform/` and `apps/` directories so they are auto-discovered by the ArgoCD ApplicationSet defined in `system/argocd/values.yaml`. The `apps/streaming/wolf/` lives at `apps/streaming/wolf/` rather than `apps/wolf/` because the App-of-Apps would create an `apps/wolf` namespace and we want a more descriptive `streaming` namespace. The `apps/streaming/` path means the App-of-Apps will create an `apps/streaming` namespace for the ApplicationSet, which is what we want — but a single chart at `apps/streaming/wolf/` won't be auto-discovered (the App-of-Apps picks up `apps/*` directories, not `apps/streaming/*`). **Mitigation: we will either (a) use a flat `apps/wolf/` (simpler, auto-discovered) or (b) explicitly add the path to the App-of-Apps. Going with (a) — `apps/wolf/` — for simplicity. The streaming subdir idea was over-engineering.**

## Complexity Tracking

> No constitution violations. This table is empty.

## Phase 0: Research (complete)

The deep research was completed before this plan was written — see `plans/research/windows-gaming-on-arcanine-report.md` (a 13-page research report covering Wolf architecture, Windows-in-container, K3s viability, Cloudflare ToS, Tailscale, WireGuard, Twingate) and the `plans/research/` directory's earlier agent sub-reports. All technical unknowns are resolved. No `NEEDS CLARIFICATION` items remain.

## Phase 1: Design & Contracts

### Data Model (`data-model.md`)

Will be written in Phase 5. Entities:

- **StreamingSession** (UUID, client_name, profile_id, app_title, container_id, start_time, end_time, state) — persisted to `/etc/wolf/profile_data/<profile_id>/<app_title>/state.json`
- **App** (title, image_ref, mounts[], env{}, privileged, run_uid, run_gid) — persisted in `config.toml` `[[profiles.apps]]`
- **Profile** (name, apps[]) — persisted in `config.toml` `[[profiles]]`
- **TailscaleProxyGroup** (name, hostname, tags[], service_selector) — K8s CRD owned by the operator

### Contracts

No new HTTP/gRPC APIs are introduced. The Moonlight protocol is consumed off-the-shelf; the Tailscale operator consumes standard K8s Service+Ingress types. No new contracts/ files are needed.

### Quickstart

Will be written as `docs/streaming/` markdown files in Phase 5 (the runbook format the homelab uses elsewhere — see `docs/getting-started/vpn-setup.md`).

## Phase 5: Task Generation (next)

The next phase will produce `tasks.md` with the work items needed to implement this plan. The tasks will be grouped by the four homelab layers (Metal, System, Platform, Apps) and ordered so each layer can be brought up incrementally and validated.
