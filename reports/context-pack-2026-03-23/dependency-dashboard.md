This issue lists Renovate updates and detected dependencies. Read the [Dependency Dashboard](https://docs.renovatebot.com/key-concepts/dashboard/) docs to learn more.

## Repository Problems

Renovate tried to run on this repository, but found these problems.

 - ⚠️ WARN: GitHub token is required for some dependencies
 - ⚠️ WARN: No github.com token has been configured. Skipping release notes retrieval

## Open

The following updates have all been created. To force a retry/rebase of any, click on a checkbox below.

 - [ ] <!-- rebase-branch=renovate/all-minor-patch -->[fix(deps): update all non-major dependencies](pulls/72) (`alpine`, `argo-cd`, `cert-manager`, `curlimages/curl`, `darthsim/imgproxy`, `docker.io/alpine`, `docker.io/cloudflare/cloudflared`, `docker.io/kanidm/server`, `external-secrets`, `ghcr.io/gethomepage/homepage`, `ghcr.io/kagent-dev/doc2vec/mcp`, `ghcr.io/kagent-dev/kagent/tools`, `ingress-nginx`, `k8s.io/api`, `k8s.io/apimachinery`, `k8s.io/client-go`, `kube-prometheus-stack`, `nvidia/cuda`, `ollama`, `registry.k8s.io/kubectl`, `registry.rocket.chat/rocketchat/rocket.chat`, `renovate`, `supabase/edge-runtime`, `supabase/gotrue`, `supabase/logflare`, `supabase/postgres`, `supabase/realtime`, `supabase/storage-api`, `timberio/vector`, `valkey/valkey`, `zot`)
 - [ ] <!-- rebase-branch=renovate/bitnamilegacy-postgresql-17.x -->[chore(deps): update bitnamilegacy/postgresql docker tag to v17](pulls/73)
 - [ ] <!-- rebase-branch=renovate/nextcloud-9.x -->[chore(deps): update helm release nextcloud to v9](pulls/74)
 - [ ] <!-- rebase-all-open-prs -->**Click on this checkbox to rebase all open PRs at once**

## Detected Dependencies

<details><summary>docker-compose (2)</summary>
<blockquote>

<details><summary>docker-compose.yml (13)</summary>

 - `supabase/studio 2025.06.30-sha-6f5982d`
 - `kong 3.9.1`
 - `supabase/gotrue v2.187.0` → [Updates: `v2.188.1`]
 - `postgrest/postgrest v13.0.8`
 - `supabase/realtime v2.78.11` → [Updates: `v2.78.16`]
 - `supabase/storage-api v1.42.2` → [Updates: `v1.44.10`]
 - `darthsim/imgproxy v3.30.1` → [Updates: `v3.31.1`]
 - `supabase/postgres-meta v0.96.1`
 - `supabase/edge-runtime v1.71.0` → [Updates: `v1.73.0`]
 - `supabase/logflare 1.34.8` → [Updates: `1.34.14`]
 - `supabase/postgres 17.6.1.095` → [Updates: `17.6.1.101`]
 - `timberio/vector 0.53.0-alpine` → [Updates: `0.54.0-alpine`]
 - `supabase/supavisor 2.7.4`

</details>

<details><summary>metal/roles/pxe_server/files/docker-compose.yml</summary>


</details>

</blockquote>
</details>

<details><summary>dockerfile (9)</summary>
<blockquote>

<details><summary>apps/n8n/Dockerfile (1)</summary>

 - `postgres 18.3-bookworm`

</details>

<details><summary>apps/paperclip/Dockerfile</summary>


</details>

<details><summary>archived/apps/committee-training/Dockerfile (1)</summary>

 - `pytorch/pytorch 2.6.0-cuda12.4-cudnn9-runtime`

</details>

<details><summary>archived/apps/elysia/Dockerfile (1)</summary>

 - `python 3.14-slim`

</details>

<details><summary>archived/apps/heartlib/Dockerfile (2)</summary>

 - `nvidia/cuda 13.1.1-devel-ubuntu22.04` → [Updates: `13.2.0-devel-ubuntu22.04`]
 - `nvidia/cuda 13.1.1-runtime-ubuntu22.04` → [Updates: `13.2.0-runtime-ubuntu22.04`]

</details>

<details><summary>archived/apps/workshop/image/Containerfile</summary>


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
 - `code.gitea.io/sdk/gitea v0.23.2`
 - `gopkg.in/yaml.v3 v3.0.1`
 - `gopkg.in/yaml.v3 v3.0.1`

</details>

<details><summary>platform/global-secrets/files/secret-generator/go.mod (7)</summary>

 - `go 1.25.0`
 - `go 1.26.1`
 - `github.com/sethvargo/go-password v0.3.1`
 - `gopkg.in/yaml.v3 v3.0.1`
 - `k8s.io/api v0.35.2` → [Updates: `v0.35.3`]
 - `k8s.io/apimachinery v0.35.2` → [Updates: `v0.35.3`]
 - `k8s.io/client-go v0.35.2` → [Updates: `v0.35.3`]

</details>

</blockquote>
</details>

<details><summary>helm-values (82)</summary>
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

<details><summary>apps/humbleai-demo/values.yaml</summary>


</details>

<details><summary>apps/humbleai/values.yaml</summary>


</details>

<details><summary>apps/matrix/values.yaml (1)</summary>

 - `bitnamilegacy/postgresql 16.6.0` → [Updates: `17.6.0`]

</details>

<details><summary>apps/n8n/values.yaml (2)</summary>

 - `docker.io/brimdor/postgres 17.5-bookworm`
 - `postgres 18.3-bookworm`

</details>

<details><summary>apps/nextcloud/values.yaml (1)</summary>

 - `valkey/valkey 9.0-alpine` → [Updates: `9.1-alpine`]

</details>

<details><summary>apps/ollama/values.yaml (1)</summary>

 - `alpine 3.21` → [Updates: `3.23`]

</details>

<details><summary>apps/openwebui/values.yaml</summary>


</details>

<details><summary>apps/paperclip/values.yaml (4)</summary>

 - `docker.io/alpine 3.21` → [Updates: `3.23`]
 - `docker.io/alpine 3.21` → [Updates: `3.23`]
 - `docker.io/mariadb 12.2`
 - `docker.io/alpine 3.21` → [Updates: `3.23`]

</details>

<details><summary>apps/postgres/values.yaml (3)</summary>

 - `docker.io/brimdor/postgres 17.5-bookworm`
 - `postgres 18.3-bookworm`
 - `postgres 18.3-bookworm`

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

<details><summary>apps/strata/values.yaml</summary>


</details>

<details><summary>archived/apps/ace-step/values.yaml</summary>


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

<details><summary>archived/apps/heartlib/values.yaml</summary>


</details>

<details><summary>archived/apps/homehub/values.yaml</summary>


</details>

<details><summary>archived/apps/homepage/values.yaml (1)</summary>

 - `ghcr.io/gethomepage/homepage v1.10.1` → [Updates: `v1.11.0`]

</details>

<details><summary>archived/apps/kagent/values.yaml (2)</summary>

 - `ghcr.io/kagent-dev/kagent/tools 0.1.1` → [Updates: `0.1.2`]
 - `ghcr.io/kagent-dev/doc2vec/mcp 2.0.0` → [Updates: `2.9.2`]

</details>

<details><summary>archived/apps/kali-linux/values.yaml</summary>


</details>

<details><summary>archived/apps/kavita/values.yaml</summary>


</details>

<details><summary>archived/apps/livekit/values.yaml (1)</summary>

 - `redis 8.6-alpine`

</details>

<details><summary>archived/apps/llama/values.yaml (1)</summary>

 - `curlimages/curl 8.12.1` → [Updates: `8.18.0`]

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
 - `docker.io/library/debian 13-slim`
 - `docker.io/library/alpine 3.23`

</details>

<details><summary>archived/apps/n8n-OLD/values.yaml (2)</summary>

 - `postgres 18-alpine`
 - `postgres 18-alpine`

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

<details><summary>archived/apps/openclaw/values.yaml</summary>


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

 - `registry.rocket.chat/rocketchat/rocket.chat 8.2.0` → [Updates: `8.2.1`]
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

 - `supabase/postgres 17.6.1.095` → [Updates: `17.6.1.101`]
 - `supabase/postgres-meta v0.96.1`
 - `supabase/edge-runtime v1.71.0` → [Updates: `v1.73.0`]

</details>

<details><summary>archived/apps/ubuntu-mate/values.yaml</summary>


</details>

<details><summary>archived/apps/unsloth/values.yaml</summary>


</details>

<details><summary>archived/apps/wolf/values.yaml</summary>


</details>

<details><summary>archived/apps/workshop/values.yaml</summary>


</details>

<details><summary>archived/exo/values.yaml</summary>


</details>

<details><summary>platform/kanidm/values.yaml (1)</summary>

 - `docker.io/kanidm/server 1.9.1` → [Updates: `1.9.2`]

</details>

<details><summary>system/cloudflared/values.yaml (1)</summary>

 - `docker.io/cloudflare/cloudflared 2026.2.0` → [Updates: `2026.3.0`]

</details>

<details><summary>system/gpu-operator/values.yaml</summary>


</details>

<details><summary>system/kured/values.yaml</summary>


</details>

<details><summary>system/monitoring-system/values.yaml (1)</summary>

 - `ghcr.io/khuedoan/webhook-transformer v0.0.3`

</details>

<details><summary>system/rook-ceph/values.yaml (2)</summary>

 - `quay.io/ceph/ceph v20.2.0`
 - `registry.k8s.io/kubectl v1.33.6` → [Updates: `v1.35.3`]

</details>

</blockquote>
</details>

<details><summary>helmv3 (85)</summary>
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

<details><summary>apps/humbleai-demo/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/humbleai/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/matrix/Chart.yaml (2)</summary>

 - `elementweb 0.0.6`
 - `dendrite 0.14.6`

</details>

<details><summary>apps/n8n/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/nextcloud/Chart.yaml (1)</summary>

 - `nextcloud 8.9.1` → [Updates: `9.0.3`]

</details>

<details><summary>apps/ollama/Chart.yaml (1)</summary>

 - `ollama 1.49.0` → [Updates: `1.52.0`]

</details>

<details><summary>apps/openwebui/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>apps/paperclip/Chart.yaml (1)</summary>

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

<details><summary>apps/strata/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/ace-step/Chart.yaml (1)</summary>

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

<details><summary>archived/apps/llama/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/localai/Chart.yaml (1)</summary>

 - `local-ai >=3.3.0 <4.0.0`

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

<details><summary>archived/apps/openclaw/Chart.yaml (1)</summary>

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

<details><summary>archived/apps/unsloth/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/weaviate/Chart.yaml (1)</summary>

 - `weaviate >= 1.0.0`

</details>

<details><summary>archived/apps/wolf/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/apps/workshop/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>archived/exo/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>platform/dex/Chart.yaml (1)</summary>

 - `dex 0.24.0`

</details>

<details><summary>platform/external-secrets/Chart.yaml (1)</summary>

 - `external-secrets 2.0.1` → [Updates: `2.2.0`]

</details>

<details><summary>platform/gitea/Chart.yaml (1)</summary>

 - `gitea 12.5.0`

</details>

<details><summary>platform/grafana/Chart.yaml (1)</summary>

 - `grafana 10.5.15`

</details>

<details><summary>platform/kanidm/Chart.yaml (1)</summary>

 - `app-template 4.6.2`

</details>

<details><summary>platform/renovate/Chart.yaml (1)</summary>

 - `renovate 46.56.2` → [Updates: `46.81.1`]

</details>

<details><summary>platform/woodpecker/Chart.yaml (1)</summary>

 - `woodpecker 3.5.1`

</details>

<details><summary>platform/zot/Chart.yaml (1)</summary>

 - `zot 0.1.98` → [Updates: `0.1.104`]

</details>

<details><summary>system/argocd/Chart.yaml (2)</summary>

 - `argo-cd 9.4.7` → [Updates: `9.4.15`]
 - `argocd-apps 2.0.4`

</details>

<details><summary>system/cert-manager/Chart.yaml (1)</summary>

 - `cert-manager v1.19.4` → [Updates: `v1.20.0`]

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

 - `ingress-nginx 4.14.3` → [Updates: `4.15.1`]

</details>

<details><summary>system/kured/Chart.yaml (1)</summary>

 - `kured 5.11.0`

</details>

<details><summary>system/loki/Chart.yaml (1)</summary>

 - `loki-stack 2.10.3`

</details>

<details><summary>system/monitoring-system/Chart.yaml (1)</summary>

 - `kube-prometheus-stack 82.10.1` → [Updates: `82.13.5`]

</details>

<details><summary>system/rook-ceph/Chart.yaml (3)</summary>

 - `rook-ceph v1.19.2`
 - `rook-ceph-cluster v1.19.2`
 - `snapshot-controller 5.0.3`

</details>

<details><summary>system/volsync-system/Chart.yaml (1)</summary>

 - `volsync 0.15.0`

</details>

</blockquote>
</details>

<details><summary>terraform (5)</summary>
<blockquote>

<details><summary>external/main.tf</summary>


</details>

<details><summary>external/modules/cloudflare/versions.tf (3)</summary>

 - `cloudflare ~> 5.18.0`
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

 - `cloudflare ~> 5.18.0`
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


