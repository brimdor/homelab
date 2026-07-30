# Feature Specification: Containerized Game Streaming Host on Arcanine

**Feature Branch**: `4-game-streaming-host`
**Created**: 2026-07-29
**Status**: Draft
**Input**: User description: "Implement the full plan: get game streaming running on arcanine (RTX 3090) in the homelab, using a Tailscale+Cloudflare hybrid for networking. Bring back the archived `wolf` chart, fix the bugs, add the Tailscale operator, and ship it end-to-end."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stream a game from arcanine to a Moonlight client on the homelab LAN (Priority: P1)

**As a** homelab operator
**I want to** stream a Linux/Proton game running on the RTX 3090 in arcanine to a Moonlight client on my home network
**So that** I can play games that need a desktop-class GPU from any device in the house without moving the GPU

**Why this priority**: This is the core deliverable. If this does not work, nothing else matters. It is the primary user value of the feature.

**Independent Test**: Install a Moonlight client (e.g. Moonlight Qt on a Linux laptop, or Moonlight Embedded on a Steam Deck), point it at the streaming host, pair with a PIN, launch the "Desktop" or "Steam Big Picture" app from the Moonlight app list, and see the streaming session begin with both video and audio. The session can be observed end-to-end without any of the other user stories being implemented.

**Acceptance Scenarios**:

1. **Given** the Wolf pod is running on arcanine and a Moonlight client is on the same LAN, **When** the client adds the host's IP/hostname and pairs via PIN, **Then** the pairing completes within 30 seconds and the Moonlight app list shows at least the Wolf UI / Desktop app
2. **Given** the client is paired, **When** the user launches the Desktop app, **Then** a Wayland/Xfce desktop session starts within 60 seconds and the client displays a full-resolution interactive desktop with audio
3. **Given** a streaming session is active, **When** the user moves the mouse or types on the client keyboard, **Then** the input is reflected in the streamed desktop with sub-100ms perceived latency
4. **Given** a streaming session is active, **When** the user disconnects from the client, **Then** the session's child container is stopped within 30 seconds and no orphan processes remain

---

### User Story 2 - Reach the streaming host over Tailscale from a remote client (Priority: P1)

**As a** homelab operator
**I want to** stream games from a Moonlight client that is *not* on the homelab LAN (e.g. a laptop on a coffee-shop Wi-Fi, or a phone on cellular), using my Tailscale tailnet
**So that** I can play the same games when I'm away from home without exposing any UDP ports to the public internet and without violating Cloudflare's ToS

**Why this priority**: This is the network architecture the research proved to be the only valid one. The user explicitly asked for it and the Cloudflare ToS research demonstrated that the alternative (Cloudflare orange-cloud or `cloudflared` for UDP) does not exist.

**Independent Test**: From a device running the Tailscale client and joined to the homelab tailnet (`tail18136a.ts.net`), launch Moonlight, point it at the tailnet hostname of the streaming service, and successfully complete a streaming session. The local-LAN path (US-1) does not need to be tested for this story.

**Acceptance Scenarios**:

1. **Given** the Tailscale Kubernetes Operator is installed and authenticated in the cluster, **When** a Service in the streaming namespace is annotated `tailscale.com/expose: "true"`, **Then** the operator creates a MagicDNS hostname (`<svc>.tail18136a.ts.net`) that resolves from any device on the tailnet
2. **Given** the L3 Ingress is advertising the streaming ports (TCP 48010, UDP 47999/48100/48200) into the tailnet, **When** a tailnet client connects to the MagicDNS hostname on those ports, **Then** the traffic reaches the Wolf pod's hostNetwork-bound ports via WireGuard encapsulation
3. **Given** a tailnet client is connected, **When** the user streams a game, **Then** the latency is dominated by WireGuard (≤5ms overhead) and the upstream home network, not by Cloudflare or Tailscale relay servers
4. **Given** the existing `cloudflared` tunnel is running with the wildcard `*.eaglepass.io` route, **When** a streaming workload runs in the cluster, **Then** no streaming bytes traverse Cloudflare's network (only the small WebUI HTTPS on `wolf.eaglepass.io`)

---

### User Story 3 - Expose the Wolf pairing WebUI on `wolf.eaglepass.io` via existing cloudflared tunnel (Priority: P2)

**As a** homelab operator
**I want to** access the Wolf WebUI for PIN pairing and configuration from any device, using the same `eaglepass.io` domain I already use for other homelab services
**So that** I have a memorable, certificate-managed URL for the pairing flow without standing up a new tunnel or service

**Why this priority**: This is a convenience over US-2. Without it, the operator has to either (a) be on the homelab LAN to pair, or (b) use the IP directly. It is not blocking, but it makes the system usable from outside the homelab.

**Independent Test**: From a phone on cellular (with Tailscale disabled to prove it's not going through the tailnet), browse to `https://wolf.eaglepass.io/pin/` and successfully enter a pairing PIN. WebUI is reachable, the existing `cloudflared` route carries the traffic, and the cert is valid (managed by cert-manager).

**Acceptance Scenarios**:

1. **Given** the Wolf Deployment is in the cluster and a Service is created, **When** an Ingress is added with host `wolf.eaglepass.io`, **Then** external-dns creates the corresponding CNAME in Cloudflare pointing to `homelab-tunnel.eaglepass.io`
2. **Given** the Ingress is in place, **When** a browser hits `https://wolf.eaglepass.io/pin/`, **Then** the Wolf pairing page loads, cert-manager has issued a valid Let's Encrypt cert, and the existing `cloudflared` tunnel routes the request to the cluster
3. **Given** the Ingress is in place, **When** a Moonlight client pairs via the WebUI PIN flow, **Then** the pairing completes successfully and the client shows the app list

---

### User Story 4 - Launch a Steam (Proton) game in a spawned child container (Priority: P2)

**As a** homelab operator
**I want to** launch a Steam Big Picture session in its own container with Proton enabled, and then launch a Windows-only game from Steam inside that session
**So that** I can play the ~80% of Steam games that have native Linux clients or Proton compatibility, with proper per-game isolation and without needing a Windows VM

**Why this priority**: This validates the end-to-end "containerized game streaming" thesis. Without it, Wolf is just a desktop-streaming tool. The Steam-app container (`ghcr.io/games-on-whales/steam:edge`) is what makes this a real "game streaming" platform rather than a "remote desktop" one.

**Independent Test**: From a paired Moonlight client, launch the "Steam" app from the app list. Steam Big Picture appears. Log in, pick a Proton-compatible Windows game, launch it, play for 5 minutes, exit. The child container is created on-demand, runs the game with GPU access, and is torn down cleanly on exit.

**Acceptance Scenarios**:

1. **Given** Wolf is running and the `steam:edge` app is configured in `config.toml`, **When** the client launches the "Steam" app, **Then** Wolf pulls the image (first run only) and spawns a child container named `WolfSteam_<session-id>` with the GPU bound via `HostConfig.Runtime="nvidia"`
2. **Given** Steam Big Picture is running in the child container, **When** the user launches a Proton-compatible Windows game (e.g. one in the ProtonDB "Platinum" tier), **Then** the game runs at ≥ 30 FPS at 1080p on the RTX 3090 and streams back to the Moonlight client
3. **Given** a Steam session is active, **When** a second user on the same Moonlight host pairs, **Then** the second user gets their own session with their own Steam login and their own state folder — no collision with the first session
4. **Given** the user exits the game and disconnects, **When** the session ends, **Then** the child container is stopped, the `WOLF_STOP_CONTAINER_ON_EXIT` env var triggers cleanup, and the RTX 3090's VRAM usage returns to zero

---

### User Story 5 - Multi-session: two concurrent users on the same GPU (Priority: P3)

**As a** homelab operator
**I want to** have two Moonlight clients connected at the same time, each playing a different game on the same RTX 3090
**So that** the system can serve more than one user without requiring a second GPU node

**Why this priority**: Nice-to-have. Most homelab use cases are single-user. Multi-user is the headline feature of Wolf but the practical limit on a single 3090 is "two light/medium games OR one heavy game." This story validates that the per-session isolation architecture works.

**Independent Test**: With two Moonlight clients paired, simultaneously launch a game in each session. Verify each session's display, audio, and input is independent. Verify NVENC concurrent-encoder limits are not exceeded (3090 supports up to ~5 concurrent HEVC encodes per the NVENC support matrix).

**Acceptance Scenarios**:

1. **Given** two clients are paired, **When** both launch an app simultaneously, **Then** two child containers are spawned, each with their own `WAYLAND_DISPLAY` and PulseAudio sink
2. **Given** both sessions are active, **When** the user types in client A, **Then** the input does NOT appear in client B's session (per-session virtual input via `inputtino`)
3. **Given** both sessions are encoding 1080p60 HEVC, **When** the user monitors `nvidia-smi`, **Then** the encoder utilization reports both sessions and stays below the 3090's NVENC session limit

---

### Edge Cases

- **What happens when the host's `nvidia-drm.modeset` kernel parameter is not set?** Wolf's GStreamer pipeline cannot find a usable render node. The container will fail to start with a "no render node" error. The fix is a one-time host kernel change.
- **What happens when the Docker socket on arcanine becomes unavailable?** Wolf panics because it cannot speak to its runner. Kubernetes will restart the pod (liveness probe). The existing cluster docker role is idempotent so a recovery is automatic once Docker is back.
- **What happens when the user pairs from a Moonlight client but the WebUI is not yet reachable via the cloudflared route?** Pairing falls back to the LAN IP; users on the same network can pair directly. The Tailscale path is always available because the operator's L3 Ingress is independent of Cloudflare.
- **What happens when the user tries to launch a Windows game with Vanguard anti-cheat (e.g. League of Legends, Valorant) inside a Proton container?** The game refuses to load (Vanguard kernel-level anti-cheat is incompatible with Linux). The spec does not commit to making these work; the user is informed via the Spec's Out of Scope section. A future Windows VM phase would address this.
- **What happens when Tailscale as a company has an outage?** Tailnet connectivity fails. The user falls back to direct LAN streaming (US-1) which is unaffected because it does not traverse Tailscale. The WebUI on `wolf.eaglepass.io` is also unaffected (Cloudflare tunnel carries the small HTTPS).
- **What happens when two users try to launch a heavy game simultaneously?** NVENC session limit hit, one or both streams stutter. No crash; the system self-recovers when one session ends. The 3090's HEVC B-frame support is the constraint, not the GPU shader time.
- **What happens when the Wolf pod is rescheduled to a different node?** The pod is pinned to arcanine via `nodeAffinity`, so this cannot happen unless the node is down. The `dedicated=arcanine:NoSchedule` taint + `nodeAffinity` together enforce the constraint.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run a single Wolf pod on the arcanine node (`10.0.20.19`) with `runtimeClassName: nvidia`, `hostNetwork: true`, and `privileged: true` so that it can access the GPU, the Docker socket, and the virtual input/uinput devices.
- **FR-002**: System MUST expose the Wolf WebUI (port 47989) via the existing `cloudflared` tunnel on hostname `wolf.eaglepass.io`, with a valid Let's Encrypt cert managed by cert-manager.
- **FR-003**: System MUST expose the streaming ports (TCP 48010, UDP 47999/48100/48200) into the homelab's Tailscale tailnet (`tail18136a.ts.net`) via the Tailscale Kubernetes Operator's L3 Ingress feature.
- **FR-004**: System MUST pin the Wolf pod to arcanine via both a `nodeAffinity` to `kubernetes.io/hostname=arcanine` and a toleration for the `dedicated=arcanine:NoSchedule` taint.
- **FR-005**: System MUST persist the Wolf configuration directory (`/etc/wolf`) to the homelab NAS at `10.0.40.3:/mnt/user/wolf` so that pairing, app definitions, and per-user state survive pod restarts.
- **FR-006**: System MUST mount the arcanine host's `/var/run/docker.sock` into the Wolf pod so that Wolf can speak the Docker Engine HTTP API and spawn child game containers.
- **FR-007**: System MUST run Wolf with `PUID=1000` and `PGID=1000` (matching the GoW base-app `retro` user) so that spawned child containers can read/write their per-user state.
- **FR-008**: System MUST set `WOLF_RENDER_NODE` to the correct render node for the RTX 3090 on arcanine (typically `/dev/dri/renderD128`; verified at deploy time by `ls -l /sys/class/drm/renderD*/device/driver`).
- **FR-009**: System MUST set `WOLF_STOP_CONTAINER_ON_EXIT=TRUE` so that child game containers are torn down when the streaming session ends, freeing the GPU and avoiding orphan processes.
- **FR-010**: System MUST include the Steam app (`ghcr.io/games-on-whales/steam:edge`) in the default `[[profiles.apps]]` list so that users can launch Steam Big Picture + Proton games on first install.
- **FR-011**: System MUST register the arcanine node's `nvidia-drm.modeset=1` kernel parameter via the existing metal Ansible role, so that Wolf can find a usable render node at runtime.
- **FR-012**: System MUST install the Tailscale Kubernetes Operator in a dedicated `tailscale` namespace, authenticated with a reusable auth key stored as an External Secret in the existing `external-secrets` system.
- **FR-013**: System MUST create an ArgoCD Application for the new Wolf chart and the Tailscale operator chart, both targeting the `master` branch of the homelab repo, so that changes are deployed via GitOps.
- **FR-014**: System MUST add `apps/streaming/wolf/` and `platform/tailscale/` to the existing ArgoCD App-of-Apps tree so that the new apps are picked up automatically on every Argo reconciliation.
- **FR-015**: System MUST surface clear operational documentation in `docs/streaming/` (a) how to pair a new Moonlight client, (b) how to launch a game, (c) how to add a new app to the catalog, (d) how to troubleshoot common issues, and (e) how to upgrade Wolf/the operator.

### Key Entities *(include if feature involves data)*

- **Streaming Session**: A single Moonlight client's active connection to a spawned child container. Attributes: `session_id` (UUID), `client_name`, `profile_id`, `app_title`, `container_id`, `start_time`, `end_time`. Persisted to `/etc/wolf/profile_data/<profile_id>/<app_title>/` on the NAS.
- **App**: An entry in Wolf's `[[profiles.apps]]` config table. Attributes: `title`, `image` (Docker image reference), `mounts` (hostPath or volume mounts for the child container), `env` (environment variables), `privileged` (boolean, default false).
- **Profile**: A grouping of apps in `[[profiles]]`. Attributes: `name`, `apps` (list of App references). Used to scope the app catalog per user group.
- **Tailnet Device**: A Tailscale-registered device. The homelab uses a tailnet named `tail18136a`. The arcanine pod appears as a tagged node (`tag:k8s-homelab`); client devices appear with their own tag.

## Clarifications

- **CL-001** (2026-07-29): Tailscale exposure mode. **Decision: Operator + L3 Ingress.** The cluster will host the official Tailscale Kubernetes Operator with a ProxyGroup that DNATs the streaming Service's ports into the tailnet. This requires (a) a new `platform/tailscale/` chart installing the operator, (b) a reusable auth key stored as an External Secret, and (c) annotations on the streaming Service. The sidecar-tailscaled and host-subnet-router alternatives were rejected for the reasons in the question prompt.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A Moonlight client on the homelab LAN can pair with the streaming host and start a desktop streaming session in under 90 seconds (time from launching the Moonlight app to seeing the streamed desktop frame).
- **SC-002**: A Moonlight client on a remote tailnet (e.g. cellular phone with Tailscale) can complete a full streaming session with a Proton-compatible game and report perceived latency under 100ms at 1080p60, achieving ≥ 30 FPS in a typical game.
- **SC-003**: The Wolf pod is scheduled to arcanine with 100% reliability (zero pods ever scheduled to a different node, verified by `kubectl get pod -o wide` and ArgoCD sync status).
- **SC-004**: The streaming workload generates zero bytes through Cloudflare's network (only the small WebUI HTTPS via `cloudflared`); verified by absence of any 47xxx UDP traffic in Cloudflare's logs.
- **SC-005**: Two concurrent Moonlight sessions on the same RTX 3090 both maintain ≥ 30 FPS at 1080p for a 5-minute test with light-to-medium games, with no input cross-talk between sessions.
- **SC-006**: All four layers of the homelab (Metal, System, Platform, Apps) remain GREEN throughout the deployment and a 24-hour post-deployment soak, with zero `CrashLoopBackOff` or `Degraded` apps per ArgoCD.
- **SC-007**: The complete end-to-end deployment is reproducible by running `make external && make platform && make apps` from a clean clone of the repo, in under 30 minutes of operator time (excluding cluster bootstrap and image pulls).
- **SC-008**: The total additional resource footprint of the new feature (Wolf pod + Tailscale operator + child game containers) is under 4 GB of system RAM and under 10% of arcanine's CPU when idle, leaving the RTX 3090's VRAM and shader time available for games.
