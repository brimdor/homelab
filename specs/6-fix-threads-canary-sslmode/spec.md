# Spec: Fix threads-canary DATABASE_URL sslmode mismatch

**Status:** Draft (Cartographer output, awaiting Lens review)
**Source task:** `t_2dac12eb` (cartographer)
**Predecessor task:** `t_6be51438` (spec: Fix threads-canary PVC Multi-Attach — already deployed `c7080c2e`)
**Trigger:** Vanguard FAIL on `t_bf92c349` (canary rollout) — main pod in `CrashLoopBackOff` after PVC fix landed.
**Chart:** `apps/threads-canary` (Helm chart version 0.1.0, `app-template` v5.0.1)
**Target namespace:** `threads-canary`
**Risk class:** Low — single-character string change in one env var, no schema migration, no data movement, no secret rotation.

---

## 1. Problem Statement

The `threads-canary` Deployment pod is in `CrashLoopBackOff` because the Go pgx/pq client cannot establish a TLS handshake against the local Postgres service.

### 1.1 Observed runtime state (kubectl)

```
$ kubectl get pods -n threads-canary
NAME                              READY   STATUS              RESTARTS   AGE
threads-canary-5578945489-tzh4c   0/1     CrashLoopBackOff    6          12m
threads-canary-minio-0            1/1     Running             0          90m

$ kubectl logs -n threads-canary threads-canary-5578945489-tzh4c
... pq: SSL is not enabled on the server
```

### 1.2 Root cause

`apps/threads-canary/values.yaml` line 31 hardcodes the connection string with `sslmode=require`:

```yaml
# apps/threads-canary/values.yaml, line 31 (current — BROKEN)
DATABASE_URL: "postgres://threads@postgres.postgres.svc.cluster.local:5432/threads?sslmode=require"
```

`sslmode=require` instructs the client to **require** a TLS connection and abort if the server is not speaking TLS. The actual `postgres` Deployment in the `postgres` namespace runs `docker.io/brimdor/postgres` with no `ssl=on` / `ssl=true` / `PGSSLMODE=require` configuration in `apps/postgres/values.yaml`, so the server reports `SSL is not enabled` and the client exits with a fatal error before the application starts.

The two configs are mutually exclusive: client demands TLS, server refuses it, every restart loops in <1s.

### 1.3 Why this was not caught earlier

The PVC fix (`c7080c2e`) was scoped to `persistence.minio-data.advancedMounts` and did not touch `env.DATABASE_URL`. The `sslmode=require` value was present in the chart at first deploy and was only revealed as a blocker once the Multi-Attach error stopped masking everything else — the pod could not even reach the Postgres connection step while stuck in `ContainerCreating`.

---

## 2. Fix

Change the `sslmode` query parameter in the `DATABASE_URL` env var from `require` to `disable`.

### 2.1 Precise diff (`apps/threads-canary/values.yaml`, line 31)

```diff
             env:
               TZ: America/Chicago
               ENVIRONMENT: staging
               LOG_LEVEL: info
-              DATABASE_URL: "postgres://threads@postgres.postgres.svc.cluster.local:5432/threads?sslmode=require"
+              DATABASE_URL: "postgres://threads@postgres.postgres.svc.cluster.local:5432/threads?sslmode=disable"
               S3_ENDPOINT: "http://threads-canary-minio:9000"
```

That is the **entire change** required to unblock the pod. No other lines in the file move; controllers, persistence, ingress, secrets, and sidecar env vars are unaffected.

### 2.2 Why `sslmode=disable` (not `prefer`, not `allow`, not removal)

`sslmode` valid values and their behavior in libpq / pgx:

| Value | Behavior | Fit for this case? |
|---|---|---|
| `disable` | Never attempt TLS. Fail if server demands it. | **Yes** — server has no SSL configured; this is the only mode that connects cleanly. |
| `allow` | Try plain first, upgrade to TLS if server asks. | No — server would not ask, but `allow` is ambiguous and historically buggy in libpq. |
| `prefer` | Try TLS first, fall back to plain. | No — adds handshake latency and a warning; same end state as `disable` here. |
| `require` | Insist on TLS or fail. | **Current broken value.** |
| `verify-ca` / `verify-full` | TLS + CA validation. | Out of scope — server has no certs. |

`disable` is the minimal, unambiguous, libpq-recommended mode for an in-cluster plain `postgres://` connection where the server does not advertise SSL. It also future-proofs us: if the Postgres deployment is later reconfigured with `ssl=on`, this app will fail loud rather than silently downgrading.

### 2.3 Why not enable TLS on the Postgres side instead

The `postgres` chart is a shared service used by `paperclip`, `threads` (canary + prod), and `backlog` (per `apps/postgres/values.yaml` env block). Enabling TLS there is a fleet-wide change with cert provisioning, secret rotation, and a coordinated rollout across all consumers. The threads-canary outage is a single-app regression and the correct blast radius is the threads-canary chart, not the shared Postgres. If a fleet-wide TLS rollout is desired, that is a separate spec and ticket.

---

## 3. Out of scope (do NOT change)

The following are explicitly preserved. The implementer MUST NOT modify them, even to "tidy up" while in the file:

- `TZ: America/Chicago` — env var, line 29.
- `ENVIRONMENT: staging` — env var, line 30.
- `LOG_LEVEL: info` — env var, line 30.
- `S3_ENDPOINT`, `S3_BUCKET` — env vars, lines 32–33.
- `S3_ACCESS_KEY`, `S3_SECRET_KEY` — secretKeyRef, lines 34–45.
- `BYOM_ENCRYPTION_KEY` — secretKeyRef, lines 46–52.
- `GOOGLE_CLIENT_ID` and any following `GOOGLE_*` secretKeyRef — env vars, lines 53+.
- The `persistence.minio-data.advancedMounts` block (the predecessor PVC fix) — lines ~210–218.
- `controllers.main.pod.terminationGracePeriodSeconds` and `securityContext` — lines 9–18.
- `controllers.minio.*` — entire minio controller block.
- `service`, `ingress`, `serviceAccount`, `podOptions` blocks.
- Any `app-template: global:` or `app-template: controllers:` settings.
- `Chart.yaml` and `Chart.lock` — version pins are stable.

If lint, pre-commit, or any other tool reports a finding on a line that is not 31, the implementer MUST stop and surface it to the user before touching anything else. The diff is one character set.

---

## 4. Verification

Acceptance is met only when all four steps pass, in order.

### 4.1 Pre-flight (operator, post-merge, pre-rollout)

```bash
cd ~/repos/homelab
grep -n 'DATABASE_URL' apps/threads-canary/values.yaml
# Expected: line 31 contains the literal string "sslmode=disable"
# MUST NOT contain "sslmode=require" anywhere in the file
```

### 4.2 Static checks

```bash
cd ~/repos/homelab
pre-commit run --files apps/threads-canary/values.yaml
# Expected: yamllint + helmlint clean. If either fails on an unrelated
# pre-existing issue, document it in the PR but do not block the rollout.
```

### 4.3 Rollout trigger

```bash
cd ~/repos/homelab
git add apps/threads-canary/values.yaml
git commit -m "fix(threads-canary): set DATABASE_URL sslmode=disable to match unencrypted local postgres"
git push http-origin master
# ArgoCD polls the gitea repo; the threads-canary Application should
# detect the change within ~3 min and start a RollingUpdate.
```

### 4.4 Runtime acceptance (Lens / Vanguard gate)

```bash
kubectl get pods -n threads-canary -w
# Wait up to 5 min. Expected terminal state:
#   threads-canary-<rs>-<pod>   1/1   Running   0   <age>
#   threads-canary-minio-0      1/1   Running   0   <age>

kubectl logs -n threads-canary -l app.kubernetes.io/name=app-template --tail=200
# Expected: no "pq: SSL is not enabled" errors. The app should log
# its normal startup banner (HTTP listener on :8080, DB pool ready, etc.).

kubectl exec -n threads-canary deploy/threads-canary -- \
  sh -c 'wget -qO- http://127.0.0.1:8080/healthz || curl -fsS http://127.0.0.1:8080/healthz'
# Expected: HTTP 200 with a JSON body indicating db=ok, s3=ok.
# If the app uses a different health path, use whatever the threads
# service exposes — but the DB pool must report healthy.
```

If any of the four steps fails, the rollout is **not** accepted; revert the commit and re-open.

---

## 5. Rollback

Single-line revert:

```bash
cd ~/repos/homelab
git revert HEAD --no-edit
git push http-origin master
# ArgoCD will sync the previous values.yaml and the pod will
# CrashLoopBackOff again, but no data is lost and no PVC is affected.
```

There is no migration or data state to undo — the change is configuration-only. Worst-case rollback time is the same as the forward rollout (~3 min for ArgoCD sync + ~1 min for pod restart).

---

## 6. Constraints, risks, and assumptions Lens must inspect

### 6.1 Constraints

- **Single-file, single-line change.** Anything beyond the `sslmode=require` → `sslmode=disable` substitution on line 31 is out of scope and should be flagged as scope creep.
- **No Postgres-side changes.** This spec does not authorize editing `apps/postgres/values.yaml`, the Postgres Deployment, or any Secret consumed by Postgres. The shared service stays as-is.
- **No secret rotation.** `threads-canary-secrets` is untouched. The `threads` database user/password are unchanged.
- **No chart version bump.** `Chart.yaml` and `Chart.lock` stay pinned at 0.1.0 / app-template 5.0.1.

### 6.2 Risks

- **Low blast radius.** A wrong `sslmode` value either fails loud (require, verify-ca, verify-full) or succeeds silently with no encryption (disable, allow, prefer). Because the server is currently `ssl=off`, no value in this family silently downgrades a working TLS path.
- **Rollback is trivial.** One `git revert`. No data, no PVC, no secret, no migration is at risk.
- **No coordination with prod.** The threads **prod** chart (`apps/threads`) is not in scope; if it has the same bug, it is a separate ticket and a separate Vanguard cycle. Lens should confirm but not require it as part of this spec.

### 6.3 Assumptions Lens should verify

1. The Postgres server in the `postgres` namespace is actually running without SSL. (Confirmed by reading `apps/postgres/values.yaml` — no `ssl=true`, no cert mounts, `brimdor/postgres` image default config. Lens may want a live `kubectl exec` to verify `SHOW ssl;` returns `off` before approving.)
2. The threads-canary app uses a pgx/libpq client that honors the `sslmode` query parameter the same way. (Standard Go behavior; Lens may want to grep the app source for `pgxpool.ParseConfig` or `pq.ParseURL` to confirm the URL is parsed rather than overridden.)
3. No canary traffic is currently routed to threads-canary. (Low risk because the pod has been in CrashLoopBackOff for >10 min and the PVC fix deploy predates this spec, but Lens should check the Ingress / Argo Rollouts state if one exists.)
4. The threads database in Postgres has no TLS-only clients (e.g., a separate read replica) that would break if a future spec flips the server to `ssl=on`. Out of scope for this fix but worth a note in the PR description.

If any of these assumptions is wrong, the spec needs a follow-up revision before Lens can approve.

---

## 7. Tasks (sequenced)

| # | Owner | Task | Done when |
|---|---|---|---|
| 1 | Implementer | Apply the 1-line diff in `apps/threads-canary/values.yaml` line 31 | `git diff` shows exactly the `sslmode=require` → `sslmode=disable` substitution and nothing else |
| 2 | Implementer | Run `pre-commit run --files apps/threads-canary/values.yaml` | Both yamllint and helmlint pass; any pre-existing unrelated failure is documented in the PR description but does not block |
| 3 | Implementer | Commit with the message in §4.3 and push to `http-origin master` | `git log -1` shows the new commit on master; ArgoCD Application for threads-canary picks up the change within ~3 min |
| 4 | Lens / Vanguard | Run §4.4 runtime acceptance checks | `kubectl get pods -n threads-canary` shows `1/1 Running`, logs show no SSL error, `/healthz` returns 200 with `db=ok` |
| 5 | Lens | If any check in #4 fails, execute §5 rollback and reopen | Pod returns to `CrashLoopBackOff` (proving the revert worked); new task opened to investigate |

Tasks 1–3 are mechanical and unblock ArgoCD. Tasks 4–5 are the Lens/Vanguard gate that actually accepts the fix.

---

## 8. What this spec does NOT cover

- A fleet-wide Postgres TLS rollout. (Separate spec if/when desired.)
- Mirroring this fix to `apps/threads` (prod). (Separate spec — out of scope here per the Vanguard ticket chain.)
- Changing the threads-canary `healthz` path or adding a new liveness probe. The fix relies on the existing health surface.
- Rotating the `threads` DB password or any Secret under `threads-canary-secrets`.
- Any change to the `persistence.minio-data.advancedMounts` block from the predecessor spec.

---

*End of spec. Awaiting Lens review.*
