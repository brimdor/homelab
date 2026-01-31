== Dependency Dashboard #4 body ==
2026-01-31T12:50:20-06:00
This issue lists Renovate updates and detected dependencies. Read the [Dependency Dashboard](https://docs.renovatebot.com/key-concepts/dashboard/) docs to learn more.

## Repository Problems

Renovate tried to run on this repository, but found these problems.

 - ⚠️ WARN: GitHub token is required for some dependencies
 - ⚠️ WARN: No github.com token has been configured. Skipping release notes retrieval

## Open

The following updates have all been created. To force a retry/rebase of any, click on a checkbox below.

 - [ ] <!-- rebase-branch=renovate/all-minor-patch -->[chore(deps): update all non-major dependencies](pulls/54) (`grafana`, `kube-prometheus-stack`, `ollama`, `supabase/logflare`, `supabase/postgres`, `supabase/realtime`, `supabase/storage-api`)
 - [ ] <!-- rebase-branch=renovate/renovate-46.x -->[chore(deps): update helm release renovate to v46](pulls/55)
 - [ ] <!-- rebase-all-open-prs -->**Click on this checkbox to rebase all open PRs at once**

## PR Closed (Blocked)

The following updates are blocked by an existing closed PR. To recreate the PR, click on a checkbox below.

 - [ ] <!-- recreate-branch=renovate/docker.io-library-debian-13.x -->[chore(deps): update docker.io/library/debian docker tag to v13](pulls/52)

## Detected Dependencies

<details><summary>docker-compose (2)</summary>
<blockquote>

<details><summary>docker-compose.yml (13)</summary>

 - `supabase/studio 2025.06.30-sha-6f5982d`
 - `kong 3.9.1`
 - `supabase/gotrue v2.186.0`
 - `postgrest/postgrest v13.0.8`
 - `supabase/realtime v2.73.3` → [Updates: `v2.73.5`]
 - `supabase/storage-api v1.35.3` → [Updates: `v1.36.0`]
 - `darthsim/imgproxy v3.30.1`
 - `supabase/postgres-meta v0.95.2`
 - `supabase/edge-runtime v1.70.0`
 - `supabase/logflare 1.30.5` → [Updates: `1.30.7`]
 - `supabase/postgres 17.6.1.074` → [Updates: `17.6.1.079`]
 - `timberio/vector 0.53.0-alpine`
 - `supabase/supavisor 2.7.4`

</details>

<details><summary>metal/roles/pxe_server/files/docker-compose.yml</summary>


</details>

</blockquote>
</details>

<details><summary>dockerfile (7)</summary>
<blockquote>

<details><summary>apps/n8n/Dockerfile (1)</summary>

 - `postgres 18.1-bookworm`

</details>

<details><summary>archived/apps/committee-training/Dockerfile (1)</summary>

 - `pytorch/pytorch 2.6.0-cuda12.4-cudnn9-runtime`

</details>

<details><summary>archived/apps/elysia/Dockerfile (1)</summary>

 - `python 3.14-slim`

</details>

<details><summary>archived/apps/heartlib/Dockerfile (2)</summary>

 - `nvidia/cuda 13.1.1-devel-ubuntu22.04`
 - `nvidia/cuda 13.1.1-runtime-ubuntu22.04`

</details>

<details><summary>archived/exo/Dockerfile (1)</summary>

 - `python 3.14-slim`

</details>

<details><summary>metal/roles/pxe_server/files/dnsmasq/Dockerfile (1)</summary>

 - `alpine 3.23`

</details>

<details><summary>metal/roles/pxe_server/files/http/Dockerfile (1)</summary>

 - `nginx 1.29-alpine`

</details>

</blockquote>
</details>

<details><summary>gomod (2)</summary>
<blockquote>

<details><summary>platform/gitea/files/config/go.mod (4)</summary>

 - `go 1.19`
 - `code.gitea.io/sdk/gitea v0.22.1`
 - `gopkg.in/yaml.v3 v3.0.1`
 - `gopkg.in/yaml.v3 v3.0.1`

</details>

<details><summary>platform/global-secrets/files/secret-generator/go.mod (7)</summary>

 - `go 1.25.0`
 - `go 1.25.6`
 - `github.com/sethvargo/go-password v0.3.1`
 - `gopkg.in/yaml.v3 v3.0.1`
 - `k8s.io/api v0.35.0`
 - `k8s.io/apimachinery v0.35.0`
 - `k8s.io/client-go v0.35.0`

</details>

</blockquote>
</details>

<details><summary>helm-values (77)</summary>
<blockquote>

<details><summary>apps/backlog-canary/values.yaml</summary>


</details>

<details><summary>apps/backlog/values.yaml</summary>


</details>

<details><summary>apps/budget-canary/values.yaml</summary>


</details>

<details><summary>apps/budget/values.yaml</summary>


</details>

<details><summary>apps/doplarr/values.yaml</summary>


</details>

<details><summary>apps/emby/values.yaml</summary>


</details>

<details><summary>apps/explorers-hub/values.yaml</summary>


</details>

<details><summary>apps/humbleai-canary/values.yaml</summary>


</details>

<details><summary>apps/humbleai/values.yaml</summary>


</details>

<details><summary>apps/n8n/values.yaml (2)</summary>

 - `docker.io/brimdor/postgres 17.5-bookworm`
 - `postgres 18.1-bookworm`

</details>

<details><summary>apps/nextcloud/values.yaml</summary>


</details>

<details><summary>apps/ollama/values.yaml</summary>


</details>

<details><summary>apps/openclaw/values.yaml</summary>


</details>

<details><summary>apps/openwebui/values.yaml</summary>


</details>

<details><summary>apps/postgres/values.yaml (2)</summary>

 - `docker.io/brimdor/postgres 17.5-bookworm`
 - `postgres 18.1-bookworm`

</details>

<details><summary>apps/qdrant/values.yaml</summary>


</details>

<details><summary>apps/radarr/values.yaml</summary>


</details>

<details><summary>apps/sabnzbd/values.yaml</summary>


</details>

<details><summary>apps/searxng/values.yaml (1)</summary>

 - `valkey/valkey 9-alpine`

</details>

<details><summary>apps/sonarr/values.yaml</summary>


</details>

<details><summary>archived/apps/agent-zero/values.yaml</summary>


</details>

<details><summary>archived/apps/altus/values.yaml</summary>


</details>

<details><summary>archived/apps/astroneer/values.yaml</summary>


</details>

<details><summary>archived/apps/backlog/values.yaml</summary>


</details>

<details><summary>archived/apps/bolt/values.yaml</summary>


</details>

<details><summary>archived/apps/browser-use-canary/values.yaml</summary>


</details>

<details><summary>archived/apps/browser-use/values.yaml</summary>


</details>

<details><summary>archived/apps/code-canary/values.yaml</summary>


</details>

<details><summary>archived/apps/code/values.yaml</summary>


</details>

<details><summary>archived/apps/color-race/values.yaml</summary>


</details>

<details><summary>archived/apps/comfyui/values.yaml</summary>


</details>

<details><summary>archived/apps/deepcode/values.yaml</summary>


</details>

<details><summary>archived/apps/elysia/values.yaml</summary>


</details>

<details><summary>archived/apps/emby-companion/values.yaml</summary>


</details>

<details><summary>archived/apps/embystat/values.yaml</summary>


</details>

<details><summary>archived/apps/family-games-host/values.yaml</summary>


</details>

<details><summary>archived/apps/family-games-rules/values.yaml</summary>


</details>

<details><summary>archived/apps/heartlib/values.yaml</summary>


</details>

<details><summary>archived/apps/homehub/values.yaml</summary>


</details>

<details><summary>archived/apps/homepage/values.yaml (1)</summary>

 - `ghcr.io/gethomepage/homepage v1.9.0`

</details>

<details><summary>archived/apps/kagent/values.yaml (2)</summary>

 - `ghcr.io/kagent-dev/kagent/tools 0.0.13`
 - `ghcr.io/kagent-dev/doc2vec/mcp v1.1.14`

</details>

<details><summary>archived/apps/kali-linux/values.yaml</summary>


</details>

<details><summary>archived/apps/kavita/values.yaml</summary>


</details>

<details><summary>archived/apps/livekit/values.yaml (1)</summary>

 - `redis 8.4-alpine`

</details>

<details><summary>archived/apps/localai/values.yaml</summary>


</details>

<details><summary>archived/apps/mcpo/values.yaml (1)</summary>

 - `alpine 3.23`

</details>

<details><summary>archived/apps/media-cleaner/values.yaml</summary>


</details>

<details><summary>archived/apps/minecraft/values.yaml</summary>


</details>

<details><summary>archived/apps/moltbot/values.yaml (3)</summary>

 - `docker.io/library/busybox 1.37.0`
 - `docker.io/library/debian 12-slim` → [Updates: `13-slim`]
 - `docker.io/library/alpine 3.23`

</details>

<details><summary>archived/apps/n8n-OLD/values.yaml (2)</summary>

 - `postgres 18-alpine`
 - `postgres 18-alpine`

</details>

<details><summary>archived/apps/nextcloud/values.yaml (1)</summary>

 - `mariadb 12.1`

</details>

<details><summary>archived/apps/nibble/values.yaml</summary>


</details>

<details><summary>archived/apps/obsidian/values.yaml</summary>


</details>

<details><summary>archived/apps/OLDsteam-headless/values.yaml</summary>


</details>

<details><summary>archived/apps/ombi/values.yaml</summary>


</details>

<details><summary>archived/apps/omni-tools/values.yaml</summary>


</details>

<details><summary>archived/apps/open-notebook/values.yaml</summary>


</details>

<details><summary>archived/apps/opencode/values.yaml</summary>


</details>

<details><summary>archived/apps/peppermint/values.yaml</summary>


</details>

<details><summary>archived/apps/pigeon-pod/values.yaml</summary>


</details>

<details><summary>archived/apps/planka/values.yaml (1)</summary>

 - `ghcr.io/plankanban/planka 2.0.0-rc.3`

</details>

<details><summary>archived/apps/pterodactyl/values.yaml (1)</summary>

 - `yoshiwalsh/pterodactyl-panel v1.11.10`

</details>

<details><summary>archived/apps/rocket/values.yaml (3)</summary>

 - `registry.rocket.chat/rocketchat/rocket.chat 8.0.1`
 - `mongo 8`
 - `mongo 8`

</details>

<details><summary>archived/apps/sherlock/values.yaml</summary>


</details>

<details><summary>archived/apps/sim/values.yaml</summary>


</details>

<details><summary>archived/apps/skyfactory5/values.yaml</summary>


</details>

<details><summary>archived/apps/speedtest/values.yaml</summary>


</details>

<details><summary>archived/apps/supabase/values.yaml (3)</summary>

 - `supabase/postgres 17.6.1.074` → [Updates: `17.6.1.079`]
 - `supabase/postgres-meta v0.95.2`
 - `supabase/edge-runtime v1.70.0`

</details>

<details><summary>archived/apps/ubuntu-mate/values.yaml</summary>


</details>

<details><summary>archived/apps/wolf/values.yaml</summary>


</details>

<details><summary>archived/exo/values.yaml</summary>


</details>

<details><summary>platform/kanidm/values.yaml (1)</summary>

 - `docker.io/kanidm/server 1.8.5`

</details>

<details><summary>system/cloudflared/values.yaml (1)</summary>

 - `docker.io/cloudflare/cloudflared 2026.1.2`

</details>

<details><summary>system/gpu-operator/values.yaml</summary>


</details>

<details><summary>system/kured/values.yaml</summary>


</details>

<details><summary>system/monitoring-system/values.yaml (1)</summary>

 - `ghcr.io/khuedoan/webhook-transformer v0.0.3`

</details>

<details><summary>system/rook-ceph/values.yaml (1)</summary>

 - `quay.io/ceph/ceph v20.2.0`

</details>

</blockquote>
</details>

<details><summary>helmv3 (81)</summary>
<blockquote>

<details><summary>apps/backlog-canary/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/backlog/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/budget-canary/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/budget/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/emby/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/explorers-hub/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/humbleai-canary/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/humbleai/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/n8n/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/nextcloud/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/ollama/Chart.yaml (1)</summary>

 - `ollama 1.39.0` → [Updates: `1.40.0`]

</details>

<details><summary>apps/openclaw/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/openwebui/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/postgres/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/qdrant/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/radarr/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/sabnzbd/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/searxng/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/sonarr/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/agent-zero/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/altus/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/astroneer/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/backlog/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/bolt/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/browser-use-canary/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/browser-use/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/code-canary/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/code/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/color-race/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/comfyui/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/deepcode/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/elysia/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/embystat/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/family-games-host/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/family-games-rules/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/heartlib/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/homehub/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/homepage/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/kavita/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/localai/Chart.yaml (1)</summary>

 - `local-ai >=3.3.0 <4.0.0`

</details>

<details><summary>archived/apps/matrix/Chart.yaml (2)</summary>

 - `elementweb 0.0.6`
 - `dendrite 0.14.6`

</details>

<details><summary>archived/apps/mcpo/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/media-cleaner/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/moltbot/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/n8n-OLD/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/nextcloud/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/nibble/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/obsidian/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/OLDsteam-headless/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/omni-tools/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/open-notebook/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/opencode/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/peppermint/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/pigeon-pod/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/planka/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/pterodactyl/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/rocket/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/sherlock/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/speedtest/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/weaviate/Chart.yaml (1)</summary>

 - `weaviate >= 1.0.0`

</details>

<details><summary>archived/apps/wolf/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/exo/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>platform/dex/Chart.yaml (1)</summary>

 - `dex 0.24.0`

</details>

<details><summary>platform/external-secrets/Chart.yaml (1)</summary>

 - `external-secrets 1.3.1`

</details>

<details><summary>platform/gitea/Chart.yaml (1)</summary>

 - `gitea 12.5.0`

</details>

<details><summary>platform/grafana/Chart.yaml (1)</summary>

 - `grafana 10.5.14` → [Updates: `10.5.15`]

</details>

<details><summary>platform/kanidm/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>platform/renovate/Chart.yaml (1)</summary>

 - `renovate 45.88.1` → [Updates: `46.0.4`]

</details>

<details><summary>platform/woodpecker/Chart.yaml (1)</summary>

 - `woodpecker 3.5.1`

</details>

<details><summary>platform/zot/Chart.yaml (1)</summary>

 - `zot 0.1.97`

</details>

<details><summary>system/argocd/Chart.yaml (2)</summary>

 - `argo-cd 9.3.7`
 - `argocd-apps 2.0.4`

</details>

<details><summary>system/cert-manager/Chart.yaml (1)</summary>

 - `cert-manager v1.19.2`

</details>

<details><summary>system/cloudflared/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>system/external-dns/Chart.yaml (1)</summary>

 - `external-dns 1.20.0`

</details>

<details><summary>system/gpu-operator/Chart.yaml (1)</summary>

 - `node-feature-discovery 0.18.3`

</details>

<details><summary>system/ingress-nginx/Chart.yaml (1)</summary>

 - `ingress-nginx 4.14.2`

</details>

<details><summary>system/kured/Chart.yaml (1)</summary>

 - `kured 5.11.0`

</details>

<details><summary>system/loki/Chart.yaml (1)</summary>

 - `loki-stack 2.10.3`

</details>

<details><summary>system/monitoring-system/Chart.yaml (1)</summary>

 - `kube-prometheus-stack 81.3.0` → [Updates: `81.4.2`]

</details>

<details><summary>system/rook-ceph/Chart.yaml (3)</summary>

 - `rook-ceph v1.19.0`
 - `rook-ceph-cluster v1.19.0`
 - `snapshot-controller 5.0.2`

</details>

<details><summary>system/volsync-system/Chart.yaml (1)</summary>

 - `volsync 0.14.0`

</details>

</blockquote>
</details>

<details><summary>terraform (5)</summary>
<blockquote>

<details><summary>external/main.tf</summary>


</details>

<details><summary>external/modules/cloudflare/versions.tf (3)</summary>

 - `cloudflare ~> 5.16.0`
 - `http ~> 3.5.0`
 - `kubernetes ~> 3.0.0`

</details>

<details><summary>external/modules/extra-secrets/versions.tf (1)</summary>

 - `kubernetes ~> 3.0.0`

</details>

<details><summary>external/modules/ntfy/versions.tf (1)</summary>

 - `kubernetes ~> 3.0.0`

</details>

<details><summary>external/versions.tf (3)</summary>

 - `cloudflare ~> 5.16.0`
 - `http ~> 3.5.0`
 - `kubernetes ~> 3.0.0`

</details>

</blockquote>
</details>

<details><summary>woodpecker (2)</summary>
<blockquote>

<details><summary>.woodpecker/helm-diff.yaml</summary>


</details>

<details><summary>.woodpecker/static-checks.yaml</summary>


</details>

</blockquote>
</details>


