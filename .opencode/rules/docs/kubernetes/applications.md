# Kubernetes Applications

## Application Access Overview

Applications in the cluster are accessible in three ways:

1. **External (Internet)** - Via Cloudflare Tunnel (`homelab-tunnel.eaglepass.io`)
2. **Internal (Network FQDN)** - Via local DNS resolution within the network
3. **Cluster-Only** - Via ClusterIP services within the Kubernetes cluster

---

## External Access (Internet Accessible)

These applications are configured with Cloudflare Tunnel and proxy, accessible from anywhere on the internet.

| Application | FQDN | Description |
|-------------|------|-------------|
| Open WebUI | `https://open.eaglepass.io` | AI chat interface |
| Emby | `https://emby.eaglepass.io` | Media server |
| HumbleAI | `https://humbleai.eaglepass.io` | AI application |
| HumbleAI Canary | `https://humbleai-canary.eaglepass.io` | AI application (canary) |

**Configuration Requirements:**
- Ingress annotation: `external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"`
- Ingress annotation: `external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"`

---

## Internal Access (Network FQDN)

These applications have ingress with an FQDN but are **only accessible within the local network**. DNS resolution must point to the ingress controller.

| Application | FQDN | Description |
|-------------|------|-------------|
| ArgoCD | `https://argocd.eaglepass.io` | GitOps continuous deployment |
| Radarr | `https://radarr.eaglepass.io` | Movie management |
| Sonarr | `https://sonarr.eaglepass.io` | TV show management |
| SABnzbd | `https://sabnzbd.eaglepass.io` | Usenet downloader |
| SearXNG | `https://searxng.eaglepass.io` | Privacy-focused search |
| LocalAI | `https://localai.eaglepass.io` | Local AI inference |

**To access these internally:**

1. Ensure your device is on the network (any VLAN)
2. DNS must resolve `*.eaglepass.io` to the ingress controller
3. Access via the FQDN in your browser

---

## Cluster-Only Services

These services have no ingress and are only accessible within the Kubernetes cluster via ClusterIP.

| Application | Service Name | Port(s) | Description |
|-------------|--------------|---------|-------------|
| Qdrant | `qdrant.qdrant.svc.cluster.local` | 6333, 6334 | Vector database |
| Ollama | `ollama.ollama.svc.cluster.local` | 11434 | LLM inference server |
| Doplarr | - | - | Discord bot (no service needed) |
| 1Password Connect | NodePort | - | Secrets management |

**To access cluster-only services:**

```bash
# From within the cluster (e.g., another pod)
curl http://qdrant.qdrant.svc.cluster.local:6333

# Port-forward from local machine
kubectl port-forward svc/qdrant -n qdrant 6333:6333
```

---

## Application Summary Table

| Application | Type | FQDN | Access Method |
|-------------|------|------|---------------|
| Open WebUI | External | `open.eaglepass.io` | Internet via Cloudflare |
| Emby | External | `emby.eaglepass.io` | Internet via Cloudflare |
| HumbleAI | External | `humbleai.eaglepass.io` | Internet via Cloudflare |
| ArgoCD | Internal | `argocd.eaglepass.io` | Network only |
| Radarr | Internal | `radarr.eaglepass.io` | Network only |
| Sonarr | Internal | `sonarr.eaglepass.io` | Network only |
| SABnzbd | Internal | `sabnzbd.eaglepass.io` | Network only |
| SearXNG | Internal | `searxng.eaglepass.io` | Network only |
| LocalAI | Internal | `localai.eaglepass.io` | Network only |
| Qdrant | Cluster | - | ClusterIP only |
| Ollama | Cluster | - | ClusterIP only |

---

## Configuration Source

Application configurations are managed in the homelab repository:

```
~/Documents/Github/homelab/
├── apps/           # Application deployments
│   ├── emby/
│   ├── openwebui/
│   ├── radarr/
│   ├── sonarr/
│   └── ...
└── system/         # System components
    ├── argocd/
    ├── cloudflared/
    └── ...
```

## Related Documentation

- [Cluster Overview](cluster.md) - Kubernetes cluster architecture
- [External Access](../access/external-access.md) - Cloudflare tunnel details
- [Agent Access Guide](../access/agent-access.md) - Connecting to resources
