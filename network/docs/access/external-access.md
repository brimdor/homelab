# External Access

## Overview

External access to Nelson Network services is provided via Cloudflare Tunnel. This allows secure access to selected applications from the internet without exposing the network directly.

## Cloudflare Tunnel Configuration

| Property | Value |
|----------|-------|
| **Tunnel Name** | `homelab` |
| **Tunnel Domain** | `homelab-tunnel.eaglepass.io` |
| **Wildcard Hostname** | `*.eaglepass.io` |
| **Backend** | `https://ingress-nginx-controller.ingress-nginx` |

The Cloudflare tunnel is configured in the homelab repository:
```
~/Documents/Github/homelab/system/cloudflared/values.yaml
```

## Externally Accessible Applications

These applications are accessible from the internet via Cloudflare Tunnel:

| Application | URL | Description |
|-------------|-----|-------------|
| Open WebUI | `https://open.eaglepass.io` | AI chat interface |
| Emby | `https://emby.eaglepass.io` | Media server |
| Emby Health | `https://emby-health.eaglepass.io` | Emby health endpoint |
| HumbleAI | `https://humbleai.eaglepass.io` | AI application |
| HumbleAI Canary | `https://humbleai-canary.eaglepass.io` | AI application (canary) |

## How External Access Works

```
Internet User
     │
     ▼
┌─────────────────┐
│   Cloudflare    │
│   Edge Network  │
└────────┬────────┘
         │ (encrypted tunnel)
         ▼
┌─────────────────┐
│  Cloudflared    │
│   (K8s Pod)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ NGINX Ingress   │
│   Controller    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Application   │
│     Service     │
└─────────────────┘
```

## Configuring External Access for an Application

To make an application externally accessible:

### 1. Add Cloudflare Annotations to Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  annotations:
    external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
spec:
  rules:
    - host: my-app.eaglepass.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

### 2. Required Annotations

| Annotation | Value | Purpose |
|------------|-------|---------|
| `external-dns.alpha.kubernetes.io/target` | `homelab-tunnel.eaglepass.io` | Points DNS to tunnel |
| `external-dns.alpha.kubernetes.io/cloudflare-proxied` | `true` | Enables Cloudflare proxy |

## Internal-Only Applications

Applications that should NOT be externally accessible should omit the Cloudflare annotations. They will only be accessible within the local network.

| Application | URL | Access |
|-------------|-----|--------|
| ArgoCD | `https://argocd.eaglepass.io` | Internal only |
| Radarr | `https://radarr.eaglepass.io` | Internal only |
| Sonarr | `https://sonarr.eaglepass.io` | Internal only |
| SABnzbd | `https://sabnzbd.eaglepass.io` | Internal only |
| SearXNG | `https://searxng.eaglepass.io` | Internal only |
| LocalAI | `https://localai.eaglepass.io` | Internal only |

For internal-only access, ensure:
1. DNS resolves to the ingress controller IP within the network
2. No Cloudflare tunnel annotations are present
3. Device is connected to the local network (any VLAN)

## Remote Access Alternatives

### Twingate

The NAS at `10.0.40.3` runs Twingate connectors, providing secure remote access to internal network resources without exposing them to the internet.

**Use Twingate for:**
- SSH access to servers
- Internal web applications
- NAS file access
- Any resource not exposed via Cloudflare

### VPN

OPNSense can be configured with WireGuard or OpenVPN for direct VPN access to the network.

## Security Considerations

1. **External applications** are protected by Cloudflare's security features (DDoS protection, WAF)
2. **Internal applications** are only accessible from the local network or via Twingate
3. **Cloudflare proxy** hides the origin server IP
4. **TLS** is enforced for all external connections
