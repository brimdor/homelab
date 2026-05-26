# Tasks: Jovo K8s Infrastructure — Canary + Production Helm Charts

## T1: Create production `apps/jovo/` Chart.yaml
- [ ] Add Helm `apiVersion: v2`, name `jovo`, description, version `0.1.0`
- [ ] Dependency on `app-template` 4.6.2 from bjw-s repo
- **Acceptance**: `helm dependency build` succeeds

## T2: Create production `apps/jovo/values.yaml`
- [ ] `controllers.main.strategy: Recreate` (RWO PVCs)
- [ ] `database` container: MariaDB 10.11, probes, env from `jovo-secrets`
- [ ] `backend` container: FastAPI, probes, env including `JOVO_AUTH_REQUIRED=*** `service.main` (frontend), `backend`, `mariadb`
- [ ] `ingress.main`: host `jovo.eaglepass.io`, TLS `jovo-tls`, paths `/`→frontend, `/api/*` and `/health`→backend
- [ ] `persistence.data`: 10Gi PVC for MariaDB
- [ ] `persistence.audio`: 50Gi PVC for backend uploads
- [ ] `configMaps.init-db`: 01-init.sql with `CREATE DATABASE IF NOT EXISTS jovo`
- [ ] `networkpolicies.main`: ingress from ingress-nginx namespace only; egress DNS + HTTPS to internet (no private ranges)
- [ ] `defaultPodOptions.securityContext.fsGroup: 999`
- [ ] `defaultPodOptions.annotations`: 1Password operator item for `jovo-secrets`
- **Acceptance**: `helm template jovo apps/jovo/ --namespace jovo` renders without errors

## T3: Refine `apps/jovo-canary/values.yaml`
- [ ] Align probe `enabled`/`custom`/`spec` pattern with production
- [ ] Confirm `external-dns` annotations and `cert-manager` TLS
- [ ] Ensure `networkpolicies` exists and matches pattern
- [ ] Add `RESTART_AT` to backend and frontend for canary rebuild forcing
- **Acceptance**: `helm template jovo-canary apps/jovo-canary/ --namespace jovo-canary` renders without errors

## T4: Validate generated manifests
- [ ] Run `helm dependency build` in both directories
- [ ] Run `helm template` for both canary and prod
- [ ] Verify: no hardcoded secrets, PVCs mount correctly, ingress TLS covers correct hosts
- **Acceptance**: Both templates render without errors; no orphaned resources

## T5: Commit and open PR
- [ ] Stage all changes (`apps/jovo/` + `apps/jovo-canary/`)
- [ ] Conventional commit: `feat(infra): add Jovo production Helm chart and refine canary (refs #2)`
- [ ] Push branch `issue-2-jovo-k8s`
- [ ] Open non-draft PR on homelab Gitea
- **Acceptance**: PR created with `draft: false`

## T6: Drain feedback + apply label
- [ ] Check issue comments for queued feedback markers
- [ ] If none, apply `agent:pr-ready` label to GitHub issue #2
- **Acceptance**: Label applied successfully
