# Tailscale (platform/tailscale)

The Tailscale Kubernetes Operator exposes cluster workloads to the homelab's
Tailscale tailnet (`tail18136a.ts.net`). It is deployed here so the Wolf
game-streaming app can serve UDP video/audio to clients that are not on the
homelab LAN — the only path that doesn't violate Cloudflare's ToS or
require opening inbound ports on the home router.

## Why this exists

The Moonlight game-streaming protocol (used by both Wolf and Sunshine)
sends audio/video as UDP RTP on ports 47999/48100/48200. Cloudflare's
proxy layer (both the orange-cloud DNS toggle and `cloudflared` tunnels)
only proxies HTTP/HTTPS/WS/WSS — no UDP. Exposing UDP through
`*.eaglepass.io` would either (a) require Cloudflare Spectrum (paid
Enterprise add-on) or (b) violate the §2.2.1(b) "undue burden" clause
of Cloudflare's Self-Serve Subscription Agreement by routing sustained
multi-Mbps traffic over the Free plan.

Tailscale's WireGuard data plane carries both TCP and UDP transparently.
The Tailscale Kubernetes Operator's L3 Ingress feature deploys proxy pods
that DNAT tailnet traffic to a backend `Service`, so a `Service` of
`type: LoadBalancer, loadBalancerClass: tailscale` becomes reachable
from any device on the tailnet as `wolf.tail18136a.ts.net`.

The `*.eaglepass.io` WebUI path (HTTPS only, small bytes) goes through
the existing `cloudflared` tunnel as before. Only the streaming traffic
goes through Tailscale.

## What it deploys

- Namespace: `tailscale`
- Deployment: `tailscale-operator` (the operator controller)
- ServiceAccounts: `operator`, `proxies`
- CRDs: `connectors.tailscale.com`, `dnsconfigs.tailscale.com`,
  `proxyclasses.tailscale.com`, `proxygroups.tailscale.com`,
  `recorders.tailscale.com`, `tailscale.com/ingress`, etc.
- Secret: `operator-oauth` (managed by ExternalSecret, sourced from 1Password)

The pinned upstream chart is stored under `vendor/tailscale-operator`. The only
local patch makes the operator replica count configurable because upstream
1.98.9 hard-codes one replica. Keep `operatorConfig.replicas: 0` while the OAuth
client is invalid; set it to `1` only after verifying the rotated credential.

## One-time setup (Tailscale admin console)

Before the chart can install successfully, two Tailscale-admin tasks
are required. See the top of `values.yaml` for the full step-by-step:

1. **OAuth client** — create at
   https://login.tailscale.com/admin/settings/trust-credentials
   with `write` scope on `General/Services`, `Devices/Core`, and
   `Keys/Auth Keys`, tagged with `tag:k8s-operator`. Store the
   client_id and client_secret in the 1Password `secrets` item as
   `ts-oauth-client-id` and `ts-oauth-client-secret`.

2. **ACL tagOwners** — at
   https://login.tailscale.com/admin/acls/file, add to the `tagOwners`
   section:

   ```json
   "tagOwners": {
     "tag:k8s-operator": [],
     "tag:k8s": ["tag:k8s-operator"],
     "tag:k8s-homelab": ["tag:k8s-operator"],
   }
   ```

   The third entry (`tag:k8s-homelab`) is the tag the operator applies
   to ingress proxy pods (`proxyConfig.defaultTags`). Adding it here
   means the operator can create devices with that tag without
   admin approval.

3. **Ingress ACL** — in the same ACL file, add a section that permits
   tailnet clients to reach `tag:k8s-homelab` on the streaming ports
   (TCP 48010, UDP 47999/48100/48200, plus TCP 47989 for the WebUI):

   ```json
   "acls": [
     {
       "action": "accept",
       "src": ["group:family"],
       "dst": ["tag:k8s-homelab:48010", "tag:k8s-homelab:47989",
               "tag:k8s-homelab:47999", "tag:k8s-homelab:48100", "tag:k8s-homelab:48200"],
     },
   ]
   ```

   The `group:family` source is whatever user group you have configured
   in your tailnet; substitute as appropriate. Alternatively, you can
   grant to a single user (`"src": ["user@you"]`).

## How a new workload gets exposed to the tailnet

Once the operator is running, any `Service` (or `Ingress` for L7) can be
exposed to the tailnet by adding annotations:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
  annotations:
    tailscale.com/proxy-group: ingress-proxies  # HA proxy group (defined in apps/wolf)
    tailscale.com/hostname: myservice            # → myservice.tail18136a.ts.net
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  ...
```

The operator detects the annotation and `loadBalancerClass`, creates the
proxy StatefulSet (or joins the existing ProxyGroup), provisions a
MagicDNS name, and DNATs incoming tailnet traffic to the Service's
cluster IP. From the tailnet client, the service is reachable at
`myservice.tail18136a.ts.net:port`.

See `apps/wolf/templates/service-streaming.yaml` for the Wolf-specific
example that exposes the streaming ports (TCP 48010, UDP 47999/48100/48200)
to the tailnet.

## Failure modes

- **Operator not running** — L3 ingress does nothing. The Service
  stays as a regular ClusterIP. Streaming works from the homelab LAN
  only.
- **Tailnet down** — Tailscale's control plane outage. Local LAN
  streaming still works. Remote streaming does not.
- **ACL denies** — `tailscale status` on the client shows
  "denied" for the streaming hostname. Fix the ACL in the
  Tailscale admin console.
- **DNS not resolving** — `nslookup wolf.tail18136a.ts.net` from
  the client. If it fails, the operator hasn't created the
  Tailscale Service yet (check `kubectl get proxygroup -n wolf`).

## What is NOT exposed

- UDP RTP streams (47999/48100/48200) — exposed via Tailscale only
  (NOT via `*.eaglepass.io` / Cloudflare)
- TCP RTSP (48010) — exposed via Tailscale only
- WebUI HTTPS (47989) — exposed via BOTH (Tailscale for tailnet
  clients, `wolf.eaglepass.io` for the public-facing web)
