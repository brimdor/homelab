# Deploy Citadel Demo App

This guide covers deploying the Citadel Team Task Manager demo app via the GitOps workflow.

## Prerequisites

- Backend API code pushed to the citadel-backend Gitea repo
- Frontend UI code pushed to the citadel-frontend Gitea repo
- PostgreSQL instance accessible
- ArgoCD healthy and synced

## Deployment Steps

### 1. Build and Push Container Images

The CI pipeline in each app repo builds and pushes images automatically on push to `master`.

**Backend** — Add to `.gitea/workflows/ci.yml`:

```yaml
name: Backend CI
on:
  push:
    branches: [master]

jobs:
  ci:
    uses: git.eaglepass.io/ops/homelab/.gitea/workflows/citadel-ci.yml@master
    with:
      project-name: citadel-backend
      dockerfile: ./Dockerfile
      argocd-values-path: apps/citadel/values.yaml
    secrets:
      GITEA_TOKEN: "${{ secrets.GITEA_TOKEN }}"
```

**Frontend** — Add to `.gitea/workflows/ci.yml`:

```yaml
name: Frontend CI
on:
  push:
    branches: [master]

jobs:
  ci:
    uses: git.eaglepass.io/ops/homelab/.gitea/workflows/citadel-ci.yml@master
    with:
      project-name: citadel-frontend
      dockerfile: ./Dockerfile
    secrets:
      GITEA_TOKEN: "${{ secrets.GITEA_TOKEN }}"
```

### 2. Configure Secrets

Create a Kubernetes Secret named `citadel-secrets` in the `citadel` namespace. Create the namespace first if needed:

```bash
kubectl create namespace citadel
```

Then create the secret:

```bash
kubectl create secret generic citadel-secrets \
  -n citadel \
  --from-literal=db-host=postgres.postgres \
  --from-literal=db-port=5432 \
  --from-literal=db-name=citadel \
  --from-literal=db-user=citadel \
  --from-literal=db-password=$(openssl rand -hex 16) \
  --from-literal=jwt-secret=$(openssl rand -hex 32)
```

| Key | Description |
|-----|-------------|
| `db-host` | PostgreSQL host |
| `db-port` | PostgreSQL port (default: 5432) |
| `db-name` | Database name |
| `db-user` | Database user |
| `db-password` | Database password |
| `jwt-secret` | JWT signing secret |

### 3. Deploy via ArgoCD

Once the Helm chart is pushed to the homelab repo, ArgoCD automatically syncs it.

1. Push changes to `master`:
   ```bash
   git add apps/citadel/
   git commit -m "feat: add citadel demo app helm chart"
   git push
   ```
2. ArgoCD detects the new `apps/citadel/` directory and creates an Application
3. Verify sync in ArgoCD UI at `https://argocd.eaglepass.io`

### 4. Verification

Check all layers are GREEN:

```bash
# Metal — all nodes Ready
kubectl get nodes | grep -v Ready

# Apps — all pods Running
kubectl get pods -n citadel

# ArgoCD app status
kubectl get application citadel -n argocd

# Health check
curl -s https://citadel.eaglepass.io/api/health
```

## Architecture

```
citadel.eaglepass.io
  |
  +-- /api -> backend service (:3001) -> Node.js/Express API
  |             +-- PostgreSQL (separate chart)
  |
  +-- /    -> frontend service (:5173) -> React/Vite SPA
```

Both run in a single pod as separate containers sharing the same network namespace.

## Rollback

If deployment fails:

1. Revert the Helm chart change: `git revert HEAD && git push`
2. ArgoCD auto-syncs to the previous state
3. Verify ALL GREEN
