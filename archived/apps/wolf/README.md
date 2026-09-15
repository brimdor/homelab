# Wolf (Games-on-Whales) — homelab game streaming server

Wolf is a [Moonlight-compatible streaming server](https://github.com/games-on-whales/wolf)
that runs a privileged K3s pod on the `arcanine` worker (Lenovo M900 + RTX 3090).
It spawns per-session Docker containers (Steam Big Picture, retroarch, etc.) with
GPU access and streams them to Moonlight clients on the homelab LAN or, via
Tailscale, anywhere in the world.

## Why this chart looks the way it does

### 1. Privileged + hostNetwork + many hostPath mounts

Wolf's design requires it to:
- Speak the Docker Engine HTTP API to spawn per-session child containers
  (`/var/run/docker.sock` is mounted)
- Use `/dev/dri`, `/dev/uinput`, `/dev/uhid` for the GStreamer pipeline
  and virtual input devices (inputtino)
- Bind the streaming ports (TCP 48010, UDP 47999/48100/48200) directly
  to the node's network stack for lowest latency (`hostNetwork: true`)
- Do `mknod` for virtual devices (`privileged: true`)

The pod is pinned to arcanine via:
- Toleration for the `dedicated=arcanine:NoSchedule` taint
- `nodeAffinity` to `kubernetes.io/hostname=arcanine`

Both are required: the taint alone is honored only by pods that tolerate
it; the affinity makes scheduling deterministic if the taint is ever
removed. With both in place, Wolf can never accidentally land on a
non-GPU worker.

### 2. `runtimeClassName: nvidia`

The cluster's GPU operator (see `system/gpu-operator/`) installs a
`nvidia` runtime class. When a pod uses it, the kubelet injects
`/dev/nvidia*`, `/dev/dri/renderD*`, and `/dev/nvidia-uvm*` into
the pod's container. Wolf's GStreamer pipeline picks them up
automatically; no manual device binding needed.

### 3. `WOLF_RENDER_NODE=/dev/dri/renderD128`

Wolf needs to know which `/dev/dri/renderD*` is the NVIDIA GPU.
On arcanine this is `renderD128`. To verify on a different node:

```bash
ls -l /sys/class/drm/renderD*/device/driver
# The line containing `nvidia` is the right one.
```

If arcanine ever has a second GPU added (e.g. the spare GTX 1650
from sprigatito gets migrated), this needs updating.

### 4. `WOLF_STOP_CONTAINER_ON_EXIT=TRUE`

When the streaming session ends, Wolf tears down the spawned child
container, releasing the GPU's VRAM. Without this, every Steam
session leaks a container that holds GPU memory.

### 5. PUID=1000 / PGID=1000

The GoW base-app images (used by `ghcr.io/games-on-whales/steam:edge`,
`xfce:edge`, etc.) all run their in-container processes as the
`retro` user (UID/GID 1000). Wolf's child container inherits this.
If you set PUID/PGID to anything else, spawned app containers
will fail to write to the per-profile state directory.

### 6. PVC for `/etc/wolf` (not hostPath NFS)

`/etc/wolf` holds Wolf's `config.toml`, per-profile per-user state
(`profile_data/<profile>/<app>/`), and the WebUI TLS keypair. The
chart provisions a PVC backed by the cluster's `nfs-rwx` storage
class, which provisions a sub-directory on the UNRAID NAS at
`10.0.40.3:/mnt/user/heartlib/`. This is the same pattern used by
other apps in the homelab (`zot`, `sporecast-canary`, etc.).

A direct hostPath mount to `10.0.40.3:/mnt/user/wolf` was
considered but rejected because (a) the cluster-idiomatic way to
get NFS is via the `nfs-rwx` storage class, and (b) the storage
class provisions the sub-directory automatically.

### 7. Two network exposure paths (not one)

| Path | What it carries | Mechanism | ToS risk |
|---|---|---|---|
| **WebUI** (TCP 47989) | HTTPS only, small bytes | Standard K8s Service + Ingress → cloudflared → `wolf.eaglepass.io` | None |
| **Streaming** (TCP 48010, UDP 47999/48100/48200) | High-bandwidth, low-latency video/audio | Service of type LoadBalancer with `loadBalancerClass: tailscale` → Tailscale ingress proxy pods → tailnet. The pod uses `hostNetwork: true` so the pod IP is the node IP, and K8s auto-populates Endpoints with the node IP. | None |

The streaming ports deliberately do **not** route through Cloudflare.
The Cloudflare ToS (Self-Serve Subscription Agreement §2.2.1(b)) flags
"undue burden" risk for sustained multi-Mbps traffic on the Free plan,
and Cloudflare's proxy layer (orange-cloud DNS + cloudflared) does not
support arbitrary UDP at all. See `specs/4-game-streaming-host/research.md`
for the full Cloudflare/Tailscale analysis.

### 8. NetworkPolicy

Cilium NetworkPolicy restricts ingress to:
- `ingress-nginx` namespace → TCP 47989 (WebUI)
- `tailscale` namespace → TCP 48010 + UDP 47999/48100/48200 (streaming)

The cluster's default-deny-all-ingress policy is not enabled, so this
is defense in depth, not strictly required.

## How a new app gets added to the catalog

Edit `values.yaml`, find the `configMaps.wolf-config.data.config.toml`
block, and add a new `[[profiles.apps]]` entry. Example: add Heroic
Games Launcher for Epic/GOG/Amazon Prime games:

```toml
[[profiles.apps]]
title = "Heroic"
image = "ghcr.io/games-on-whales/heroic-games-launcher:edge"
mounts = [
  "/etc/wolf/profile_data/main/Heroic:/home/retro:rw",
  "/mnt/user/games:/mnt/games:rw",
]
env = {}
```

Commit and push. ArgoCD will sync, the ConfigMap will update, and
Wolf will restart to pick up the new app. The new entry appears in
Moonlight's app list within 90 seconds.

See https://games-on-whales.github.io/wildlife/ for the full app
catalog (the official image tags to use).

## How a new client pairs

1. From the Moonlight client, add a new host manually with the name
   `wolf.tail18136a.ts.net` (for tailnet devices) or the LAN IP
   `10.0.20.19` (for LAN-only clients).
2. Moonlight will show a PIN.
3. Open a browser to either:
   - `https://wolf.eaglepass.io/pin/` (from anywhere — uses the
     cloudflared tunnel)
   - `http://10.0.20.19:47989/pin/` (from the homelab LAN directly)
4. Enter the PIN. Wolf completes the pairing.
5. The client appears in the Tailscale admin console with the
   permissions defined by the `tag:k8s-homelab` ACL grant.

The first client paired is automatically granted full permissions.
Subsequent clients must be granted access in the Wolf UI.

## How a user plays a Windows-only game

The Steam app container (the default `Steam` app in `config.toml`)
ships with Proton pre-installed. Most Windows-only Steam games work
out of the box. To launch a specific game directly, set the
`STEAM_ARGS` env to `steam://rungameid/<game_id>` in the app's
`env` block.

For non-Steam games or games with anti-cheat that doesn't support
Proton (Vanguard, in particular), this chart cannot help. A future
feature would be a Windows VM with Sunshine, but that's a separate
effort.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Pod CrashLoopBackOff, "Permission denied" on `/var/run/docker.sock` | arcanine's Docker socket is in `docker` group, not world-readable | The `metal/roles/docker/tasks/main.yml` configures this; verify `ls -la /var/run/docker.sock` on arcanine |
| Pod Pending, "0/N nodes are available" | taint or affinity not matching | `kubectl describe pod` to see exact reason; check arcanine taint (`kubectl get node arcanine -o jsonpath='{.spec.taints}'`) |
| `nvidia-smi` in the pod shows no GPU | runtimeClassName not honored | Check `kubectl get runtimeclass` and `system/gpu-operator/` ArgoCD status |
| "No render node" in Wolf logs | `WOLF_RENDER_NODE` is wrong or `/dev/dri` mount failed | Verify on arcanine: `ls -l /sys/class/drm/renderD*/device/driver` |
| Moonlight can pair but streaming session is black | Image still pulling for the first time | Wait 1-2 minutes for the first child container to download |
| Tailscale client can't resolve `wolf.tail18136a.ts.net` | MagicDNS not propagated | Check `kubectl get proxygroup ingress-proxies`; check `kubectl get service wolf-streaming` for an `EXTERNAL-IP` (that's the tailnet IP) |
| Tailscale client resolves but ACL denies | The `group:family` (or equivalent) ACL grant is missing | See `platform/tailscale/README.md` for the ACL snippet |
| Two users stutter on the RTX 3090 | NVENC concurrent session limit hit | Reduce per-session bitrate in Moonlight client settings, or only run one heavy game at a time |
