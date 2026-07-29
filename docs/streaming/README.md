# Game Streaming

The homelab runs [Wolf (Games-on-Whales)](https://github.com/games-on-whales/wolf)
on the `arcanine` worker (Lenovo M900 + RTX 3090). It is a
[Moonlight-compatible](https://moonlight-stream.org/) streaming server
that spawns per-session Docker containers with GPU access and streams
them to clients on the homelab LAN or, via Tailscale, anywhere in the
world.

## Quick start

1. **Install a Moonlight client** on the device you want to play from.
   - Linux: `apt install moonlight-qt` (Debian/Ubuntu) or
     [Moonlight Qt from GitHub](https://github.com/moonlight-stream/moonlight-qt)
   - macOS: download from https://moonlight-stream.org/
   - Windows: download from https://moonlight-stream.org/
   - Android / iOS: install from the app store
   - Steam Deck: included via SteamOS

2. **Install Tailscale** on the same device. Sign in to the homelab
   tailnet (`tail18136a.ts.net`).

3. **Pair a new client** — see [`pair-moonlight-client.md`](pair-moonlight-client.md).

4. **Launch a game** — see [`launch-a-game.md`](launch-a-game.md).

## Network architecture

```
                    Cloudflare Tunnel                Tailscale WireGuard
                    (eaglepass.io)                   (tail18136a.ts.net)
                          │                                  │
              ┌───────────┴──────────┐              ┌────────┴────────┐
              │                      │              │                 │
        WebUI traffic         WebUI traffic    Streaming traffic  Streaming traffic
        (HTTPS, small)        (HTTPS, small)   (UDP, large)       (UDP, large)
              │                      │              │                 │
              ▼                      ▼              ▼                 ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  ingress-nginx  ←→  wolf pod (hostNetwork)  ←→  arcanine node IP  │
        │                                  │                          │       │
        │                                  │  child containers         │       │
        │                                  │  (Steam, etc.)             │       │
        │                                  ▼                          │       │
        │  arcanine (10.0.20.19)  ◄─────  RTX 3090 (24GB)              │       │
        └─────────────────────────────────────────────────────────────────────┘
```

**Why two paths?**

Cloudflare's proxy layer (both the orange-cloud DNS toggle and
`cloudflared` tunnels) only proxies HTTP/HTTPS/WS/WSS — no UDP.
Exposing Moonlight's UDP video/audio streams (ports 47999, 48100,
48200) through `*.eaglepass.io` would require either Cloudflare
Spectrum (paid Enterprise add-on) or a §2.2.1(b) "undue burden" ToS
violation on the Free plan. Neither is acceptable.

Tailscale's WireGuard data plane carries both TCP and UDP
transparently. The [Tailscale Kubernetes
Operator](https://tailscale.com/kb/1236/kubernetes-operator/) deploys
ingress proxy pods that DNAT tailnet traffic to a backend Service.
This is the only path that:
- Doesn't violate Cloudflare's ToS
- Doesn't expose any ports on the public internet
- Carries the bandwidth-intensive UDP video/audio

The WebUI (port 47989) goes through the existing `cloudflared`
tunnel because it is HTTPS-only, small in bytes, and the user wants
a memorable `https://wolf.eaglepass.io` URL. The streaming ports
(TCP 48010, UDP 47999/48100/48200) go through Tailscale only.

## Components

| Component | Chart | Role |
|---|---|---|
| Wolf (Games-on-Whales) | `apps/wolf/` | Streaming server, spawns child containers with GPU access |
| Tailscale operator | `platform/tailscale/` | Deploys ingress proxy pods that DNAT tailnet traffic |
| GPU operator | `system/gpu-operator/` | Provides the `nvidia` runtimeClassName |
| ArgoCD | `system/argocd/` | GitOps controller; auto-discovers the new charts |
| External Secrets | `platform/external-secrets/` | Pulls the Tailscale OAuth client from 1Password |
| Cloudflared | `system/cloudflared/` | Already in place; carries the `*.eaglepass.io` wildcard |
| Metal | `metal/roles/virtualization/tasks/gpu_install_drivers.yml` | Sets `nvidia-drm.modeset=1` on arcanine's kernel cmdline (now idempotent) |

## Detailed docs

- [`pair-moonlight-client.md`](pair-moonlight-client.md) — first-time pairing
- [`launch-a-game.md`](launch-a-game.md) — gameplay workflow
- [`add-an-app.md`](add-an-app.md) — how to add a new app to the catalog
- [`upgrade-wolf-and-operator.md`](upgrade-wolf-and-operator.md) — version bumps
- [`troubleshooting.md`](troubleshooting.md) — full issue catalog

## Architecture details

For the full design rationale, see:

- `specs/4-game-streaming-host/spec.md` — the user stories, requirements, and success criteria
- `specs/4-game-streaming-host/plan.md` — the implementation plan and design decisions
- `specs/4-game-streaming-host/research.md` — symlink to the upstream research report
- `apps/wolf/README.md` — chart-specific design rationale
- `platform/tailscale/README.md` — operator-specific design rationale
