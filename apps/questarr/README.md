# Questarr Homelab Deployment

This directory contains the Helm charts for deploying [Questarr](https://github.com/Doezer/questarr) to the Homelab Kubernetes cluster via ArgoCD.

Two tracks are deployed in parallel:

- **Production** (`apps/questarr/`): pinned to a stable image tag, reachable at `https://questarr.eaglepass.io`.
- **Canary** (`apps/questarr-canary/`): tracks the upstream `dev` tag, reachable at `https://questarr-canary.eaglepass.io`.

Both tracks use the [bjw-s `app-template`](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/app-template) library chart and run Questarr as a single-container Node.js + SQLite application.

## Tracks

| Track | Chart | Host | Image tag | Pull policy | PVC size | Secrets |
| --- | --- | --- | --- | --- | --- | --- |
| Production | `apps/questarr/` | `questarr.eaglepass.io` | `1.3.1` | `IfNotPresent` | `5Gi` | `questarr-secrets` |
| Canary | `apps/questarr-canary/` | `questarr-canary.eaglepass.io` | `dev` | `Always` | `2Gi` | `questarr-canary-secrets` |

The canary track has lower resource limits, a smaller PVC, its own ingress host/TLS secret, and a **different** 1Password item so its JWT secret and credential encryption key are isolated from production.

## Image mirror

Upstream images live on GHCR (`ghcr.io/doezer/questarr`). Per Homelab Rule 2 ("We own specific container images stored in our local registry"), the cluster pulls from `registry.eaglepass.io/questarr` instead. The one-time mirror script is at:

- `apps/questarr/scripts/mirror-images.sh`

Run it once to copy the upstream tags into the local registry. The upstream stable tag is `v1.3.1`; the mirror writes it as `registry.eaglepass.io/questarr:1.3.1` to match the production chart:

```bash
./apps/questarr/scripts/mirror-images.sh
```

The script is idempotent; re-running it is safe. A CronJob or GitHub Action to refresh the `:dev` tag within one hour of upstream pushes is recommended as a follow-up.

### ARM64 caveat

Upstream `ghcr.io/doezer/questarr:v1.3.1` is multi-arch and includes a `linux/arm64` manifest, so it will run on ARM64 nodes. The `ghcr.io/doezer/questarr:dev` tag is currently `linux/amd64` only. The Homelab node pool is `linux/amd64`, so this does not block deployment. If ARM64 nodes are ever added and you want to run the canary there, either:

- Request an ARM64 build via the upstream `deploy.yml` workflow input `build_arm64: true`, or
- Build the image from the local `~/repos/Questarr` clone and push it to `registry.eaglepass.io/questarr`.

## Promoting canary to production

When the canary image has been soaked and tested, promote it to production by editing the production chart:

1. In `apps/questarr/values.yaml`, update the `image.tag` from `1.3.1` to the tested tag.
2. Commit and push the change to the homelab repo.
3. Wait for ArgoCD to show the `questarr` app as `Synced` / `Healthy`.
4. Run the smoke checks:
   - `curl -fsS https://questarr.eaglepass.io/api/health`
   - `curl -fsS https://questarr.eaglepass.io/api/ready`
   - Log in to the web UI and load the library.
   - Trigger a manual download against a test game.

There is no `helm upgrade --set image.tag=...` workflow — the Git repository is the source of truth.

## Rollback

If the promoted image misbehaves, revert the `image.tag` change in `apps/questarr/values.yaml`, commit, push, and re-sync via ArgoCD.

## Backups

Questarr has no built-in backup mechanism. The authoritative data is the SQLite database at `/app/data/sqlite.db` inside the production pod. A recommended ad-hoc backup is:

```bash
kubectl exec -n questarr-prod deploy/questarr -- \
  sqlite3 /app/data/sqlite.db ".backup /app/data/snapshot-$(date +%F).db"
kubectl cp questarr-prod/<pod>:/app/data/snapshot-YYYY-MM-DD.db ./questarr-snapshot-YYYY-MM-DD.db
```

A CronJob that snapshots the PVC to a backup target (S3, rsync, restic) is a recommended follow-up.

## References

- Upstream Questarr repository: https://github.com/Doezer/questarr
- Upstream changelog: `~/repos/Questarr/docs/CHANGELOG.md`
- Upstream secrets documentation: `~/repos/Questarr/docs/SECRETS.md`
- Upstream migration notes: `~/repos/Questarr/docs/MIGRATION.md`
- Homelab app governance: `~/.agent/rules/HOMELAB_applications.md`
- Questarr deployment research: `~/repos/Questarr/research/deployment-research-brief.md`
- Approved deployment spec: `~/repos/Questarr/specs/homelab-deployment-spec.md`
