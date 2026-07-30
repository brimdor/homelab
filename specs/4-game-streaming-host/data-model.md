# Data Model: Containerized Game Streaming Host on Arcanine

This feature does not introduce a new database or persistent service. All state is either:
1. **On disk** in the Wolf config directory (`/etc/wolf`) on the NFS share
2. **In K8s** as standard resources (Secret, ConfigMap, Service, Ingress, CRDs)
3. **In Tailscale's control plane** (devices, tags, ACLs)

The data model below is documentation of the on-disk schema for Wolf's `config.toml` and the per-user state, plus a description of the K8s CRDs the Tailscale operator creates. It is *not* a new database schema.

---

## On-Disk Entities (Wolf `config.toml`)

### Profile (`[[profiles]]`)

A profile is a named grouping of apps. Used to scope the app catalog per user or per use case (e.g. "main", "kids", "retro").

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Display name shown in the Moonlight app list |
| `apps` | list of App | yes | The apps available under this profile (defined inline as `[[profiles.apps]]`) |

**Example**:
```toml
[[profiles]]
name = "main"
[[profiles.apps]]
title = "Steam"
image = "ghcr.io/games-on-whales/steam:edge"
# ... other app config
```

### App (`[[profiles.apps]]`)

An app is a single Moonlight-launchable entry that maps to a Docker image Wolf will spawn on demand.

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | Display title shown in the Moonlight app list |
| `image` | string | yes | Docker image reference (e.g. `ghcr.io/games-on-whales/steam:edge`) |
| `mounts` | list of strings | no | Bind mounts in `host_path:container_path[:options]` form |
| `env` | table<string,string> | no | Environment variables for the spawned container |
| `privileged` | bool | no | Whether to run the spawned container as privileged (default false) |
| `run_uid` | int | no | UID the spawned container runs as (default 1000) |
| `run_gid` | int | no | GID the spawned container runs as (default 1000) |
| `ports` | list of strings | no | Ports to expose from the spawned container (rare) |
| `stop_container_on_exit` | bool | no | Stop the container on session end (default true if `WOLF_STOP_CONTAINER_ON_EXIT=TRUE` is set globally) |

**Example**:
```toml
[[profiles.apps]]
title = "Steam"
image = "ghcr.io/games-on-whales/steam:edge"
mounts = [
  "/mnt/user/games:/mnt/games:rw",
  "/etc/wolf/profile_data/main/Steam:/home/retro:rw",
]
env = { STEAM_STARTUP_FLAGS = "steam://rungameid/<game_id>" }
```

### StreamingSession (per-user state, `/etc/wolf/profile_data/<profile>/<app>/`)

This is not a single config object but a directory of files. Per the Wolf source (`src/moonlight-server/sessions/moonlight.cpp`), per-session state is created at session start and torn down at session end. Persistent state survives across sessions.

| Path | Description |
|---|---|
| `state.json` | Last-known session metadata: session_id, client_name, start_time |
| `wolf-override.toml` | Optional per-profile/app overrides (rare) |
| `key.pem`, `cert.pem` | TLS keypair for the WebUI (auto-generated on first run) |

**State transitions**:
- `(none)` → **active** (session start: child container spawned, GStreamer pipeline started)
- **active** → **(none)** (session end: child container stopped, pipeline torn down)
- **active** → **stale** (Wolf restart with orphan child: next session start will clean up)

---

## K8s Resources (live cluster state)

The deployment creates the following K8s resources. None of these are custom CRDs owned by the homelab; they are all standard or provided by the Tailscale operator.

| Kind | Name | Namespace | Source | Purpose |
|---|---|---|---|---|
| Namespace | `wolf` | (cluster) | Wolf chart | Isolates the workload |
| Namespace | `tailscale` | (cluster) | Tailscale chart | Isolates the operator |
| Deployment | `wolf` | `wolf` | Wolf chart | The Wolf pod |
| Service | `webui` | `wolf` | Wolf chart | ClusterIP on 47989 → the WebUI only |
| Ingress | `wolf` | `wolf` | Wolf chart | `wolf.eaglepass.io` → webui |
| ConfigMap | `wolf-config` | `wolf` | Wolf chart | The `config.toml` |
| ExternalSecret | `wolf-webui` | `wolf` | Wolf chart | Pulls the WebUI password from 1Password |
| NetworkPolicy | `wolf` | `wolf` | Wolf chart | Cilium: allow ingress-nginx → 47989; allow tailscale → 48010 + UDP |
| Deployment | `tailscale-operator` | `tailscale` | Tailscale chart | The operator controller |
| Secret | `tailscale-operator-creds` | `tailscale` | Tailscale chart | Holds the auth key |
| ProxyGroup | `wolf-proxy` | `wolf` (or `tailscale`) | Wolf chart, owned by operator | HA proxy pods for the L3 Ingress |
| Service | `tailscale` (operator-managed) | `wolf` | Wolf chart, owned by operator | The Service being advertised into the tailnet |

### Tailscale ProxyGroup CRD (operator-managed)

| Field | Type | Description |
|---|---|---|
| `metadata.name` | string | The ProxyGroup name (used in `Ingress.spec.proxyGroup`) |
| `spec.type` | string | `ingress` (cluster-to-tailnet) or `egress` (tailnet-to-cluster) |
| `spec.hostname` | string | MagicDNS hostname to assign (e.g. `wolf`) → `wolf.tail18136a.ts.net` |
| `spec.tags` | list | Tailscale ACL tags for the proxy nodes |
| `spec.replicas` | int | Number of HA proxy pods (default 2) |

### Tailscale Ingress (operator-managed)

The operator creates one of these per annotated Service. Either the operator creates it via CRD or we declare it explicitly:

```yaml
apiVersion: tailscale.com/v1alpha1
kind: Ingress
metadata:
  name: wolf-streaming
  namespace: wolf
spec:
  proxyGroup: wolf-proxy
  hostname: wolf
  tailscaleIngress: {}  # operator populates with the L3 DNAT rules
```

The operator then generates a `Service` of `type=LoadBalancer, loadBalancerClass=tailscale` for the streaming ports (TCP 48010, UDP 47999/48100/48200), and the proxy pods DNAT incoming tailnet traffic to the cluster-internal Service.

---

## Tailscale Devices (control plane, not stored in homelab)

| Device Type | Name | Tags | Purpose |
|---|---|---|---|
| K8s operator node | `wolf-proxy-0`, `wolf-proxy-1` | `tag:k8s-homelab`, `tag:streaming` | HA proxy pods (HAProxy or iptables, depending on operator version) |
| Operator control plane | `operator-homelab` | `tag:k8s-homelab` | The operator itself, used to manage the tailnet from the cluster |
| Client devices | `chrismbp`, `steam-deck`, etc. | user-specific | The Moonlight clients (each runs the Tailscale client) |

ACLs on the Tailscale admin console must allow:
- `tag:streaming` to advertise the `wolf` hostname
- user devices (or a group like `group:family`) to connect to `tag:streaming` on ports 47989 (TCP), 48010 (TCP), 47999/48100/48200 (UDP)

This ACL config is out of scope for the helm charts (it lives in the Tailscale admin UI) but is documented in `docs/streaming/pair-moonlight-client.md`.

---

## Validation Rules

- **`PUID=1000, PGID=1000`**: must match the UID/GID that the NFS share at `10.0.40.3:/mnt/user/wolf` is chowned to. If the NAS uses different defaults (e.g. Unraid `nobody:users` is 99:100), the spec's `PUID/PGID` env must be adjusted in `apps/wolf/values.yaml` and the NFS share chowned accordingly.
- **`WOLF_RENDER_NODE`**: must be the actual render node for the RTX 3090 on arcanine, determined at deploy time by `ls -l /sys/class/drm/renderD*/device/driver` (the line containing `nvidia` is the one to use).
- **Streaming ports in Tailscale Ingress**: must match Wolf's actual binding (`hostNetwork: true` means Wolf binds to the host's network stack on these ports). The exact ports are: TCP 48010, UDP 47999, UDP 48100, UDP 48200 (per Wolf's `docker/wolf.Dockerfile` `EXPOSE` directives).

---

## What's NOT a Data Model Concern

- The K3s cluster, the GPU operator, ingress-nginx, cert-manager, external-dns, external-secrets, cloudflared, the NFS provisioner — all are pre-existing and out of scope.
- The Moonlight protocol wire format — owned by LizardByte, not modeled here.
- Tailscale's internal device database — owned by Tailscale's control plane, not modeled here.
