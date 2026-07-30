# Spec: Fix threads-canary missing DB password

**Spec id:** 5-fix-threads-canary-db-password
**Created:** 2026-07-29
**Author:** Cartographer
**Source task:** t_c6879658
**Reference evidence:** t_9b337fed (Vanguard verification FAIL — pre-existing chart bug)

## 1. Overview

The threads-canary pod has been crashing on every start since the chart was first committed (04a07eec, 2026-07-29 19:28) with `pq: password authentication failed for user "threads"`. The root cause is a missing password in the `DATABASE_URL` env var at `apps/threads-canary/values.yaml:31`. Two earlier fixes (PVC Multi-Attach c7080c2e, SSL sslmode bb008009) unblocked the pod long enough to surface the auth failure. This spec routes a single-line chart fix that interpolates the threads postgres password from a Kubernetes Secret via `secretKeyRef`.

## 2. Problem statement

### Current state (broken)
`apps/threads-canary/values.yaml:31`:
```yaml
DATABASE_URL: "postgres://threads@postgres.postgres.svc.cluster.local:5432/threads?sslmode=require"
```

- No password component in the URL.
- The threads postgres user (`THREADS_POSTGRES_USER=threads`, `THREADS_POSTGRES_PASSWORD=<secret>`) is provisioned by the postgres chart from the `secrets` Secret in the `postgres` namespace.
- The threads-canary 1Password item `klgtclyw2ctf435fa65t4eb5be` (item-name `threads-canary-secrets`) currently contains: `s3-access-key`, `s3-secret-key`, `byom-encryption-key`, `google-client-id`, `google-client-secret`, `session-secret`. **It does NOT contain the threads postgres password.**
- The 1Password operator materializes the item into a Secret literally named `threads-canary-secrets` in the threads-canary namespace (matches the `operator.1password.io/item-name` annotation on `defaultPodOptions`).

### Desired state
`DATABASE_URL` env var on the `main` container is set via `secretKeyRef` so the password is interpolated at pod start from a Kubernetes Secret that holds the threads postgres password. After the fix, the pod starts, the threads app connects to postgres, the migration runs, and the readiness/liveness probes return 200.

### Hard constraints
- Canary-only fix. Do **not** touch any production values file or deploy to the production namespace.
- The 1Password item `klgtclyw2ctf435fa65t4eb5be` is the canonical secret source for threads-canary (matches existing pattern: 6 other env vars already pull from `threads-canary-secrets`). The fix must add the threads postgres password to that item, not introduce a new cross-namespace secret ref.
- Do not change the user (`threads`), host (`postgres.postgres.svc.cluster.local`), port (`5432`), database (`threads`), or `sslmode` (currently `require` per the current values.yaml; the live synced pod already runs `sslmode=disable` per t_9b337fed — see §6). Only the password component is added.

## 3. Design decision — single approach, with rationale

### Approach (chosen)
**Add the threads postgres password to the 1Password item `klgtclyw2ctf435fa65t4eb5be` under key `database-password`, then reference it in `values.yaml` via `secretKeyRef` to interpolate into the `DATABASE_URL` value.**

The interpolation is done by Helm's `tpl` function applied to the secret value, so the password never appears as plain text in git, ArgoCD, or `kubectl describe pod`.

#### values.yaml fragment after fix
```yaml
DATABASE_URL:
  value: "postgres://threads:{{ .Values.app-template.controllers.main.containers.main.env.DATABASE_PASSWORD }}@postgres.postgres.svc.cluster.local:5432/threads?sslmode=require"
DATABASE_PASSWORD:
  valueFrom:
    secretKeyRef:
      name: threads-canary-secrets
      key: database-password
```

Helm renders `{{ .Values.app-template.controllers.main.containers.main.env.DATABASE_PASSWORD }}` as a tpl against the secret's mounted value at chart render time. The bjw-s `app-template` chart's common helpers already support this pattern (see `common.tplvalues.render` in chart 5.0.1). **Important:** because `env` is a YAML map and rendering happens on each entry, the value-templating approach is the standard idiom. If render-time tpl turns out to be problematic with app-template 5.0.1, the fallback is the proven outline pattern (see §6).

### Alternative considered — cross-namespace secretKeyRef
Reference `secrets` in the `postgres` namespace directly:
```yaml
DATABASE_PASSWORD:
  valueFrom:
    secretKeyRef:
      name: secrets           # postgres namespace
      key: threads-postgres-password
```
This works in Kubernetes but **couples threads-canary to the postgres namespace's secret lifetime and naming**. The 1Password item already lives in the threads-canary namespace's secret, and all six other env vars already follow that pattern. Mixing patterns adds a second trust boundary for one env var.

### Alternative considered — DATABASE_URL as a single secret value
Store the full `postgres://threads:<pwd>@...` string in the 1Password item under `database-url` (the outline pattern at `apps/outline/values.yaml:38-42`).
This is cleanest, but it requires the password to be URL-encoded manually in 1Password and means the URL components (host, port, db, sslmode) are no longer visible in `values.yaml`. For a single-app fix this is overkill — the value-templating approach keeps the URL structure diffable in git.

## 4. Files to change

| Path | Change |
|---|---|
| `apps/threads-canary/values.yaml` | Replace the scalar `DATABASE_URL` line with the `DATABASE_URL` + `DATABASE_PASSWORD` pair shown in §3. Add `database-password: <sync-from-postgres>` to the 1Password item `klgtclyw2ctf435fa65t4eb5be` (item-name `threads-canary-secrets`). **1Password update is a manual/operator step; the chart change references the new key.** |

No other files change. No new chart dependencies. No new Secret manifests. The 1Password operator's auto-sync will materialize the new key into the existing `threads-canary-secrets` Secret once the item is updated in 1Password.

## 5. Step-by-step implementation

### Task 1 — Add `database-password` to the 1Password item
- **Owner:** Weaver (manual 1Password edit)
- **Action:** Open 1Password item `klgtclyw2ctf435fa65t4eb5be` (item-name `threads-canary-secrets`). Add a new field `database-password` whose value equals the current `THREADS_POSTGRES_PASSWORD` from the postgres `secrets` Secret (namespace `postgres`, key `threads-postgres-password`).
- **Source of truth for the password value:** `kubectl get secret -n postgres secrets -o jsonpath='{.data.threads-postgres-password}' | base64 -d`. The same value is already in the postgres pod's `THREADS_POSTGRES_PASSWORD` env var.
- **Acceptance:** Item has 7 fields (6 existing + `database-password`). The 1Password operator's auto-sync pushes the updated Secret to the cluster within ~60s (default sync interval).
- **Effort:** 5 min.

### Task 2 — Patch `apps/threads-canary/values.yaml`
- **Owner:** Weaver
- **File:** `apps/threads-canary/values.yaml`
- **Edit:** Replace the `DATABASE_URL` scalar (line 31) with the `DATABASE_URL` + `DATABASE_PASSWORD` pair from §3. No other lines change.
- **Acceptance:**
  - `yamllint apps/threads-canary/values.yaml` exits 0.
  - `helm template threads-canary apps/threads-canary/` renders a Deployment whose main container env contains both `DATABASE_URL` (with the literal value NOT containing the password — it will be a tpl placeholder that app-template resolves) and `DATABASE_PASSWORD` (with `valueFrom.secretKeyRef.name=threads-canary-secrets`, `key=database-password`).
  - `git diff apps/threads-canary/values.yaml` shows the two-line addition + one-line removal; no other files in the chart change.
- **Effort:** 10 min.

### Task 3 — Commit and push to origin/master
- **Owner:** Weaver
- **Action:** `git checkout master && git pull && git add apps/threads-canary/values.yaml && git commit -m "fix(threads-canary): interpolate threads postgres password into DATABASE_URL" && git push http-origin master`. (Use the `http-origin` remote — see the kanban memory note about repo remotes.)
- **Acceptance:** `git log -1 origin/master` shows the new commit on top. The `git diff HEAD~1 -- apps/threads-canary/values.yaml` is identical to the local diff.
- **Effort:** 5 min.

### Task 4 — Verify ArgoCD sync + pod health
- **Owner:** Vanguard (verification only, not part of this Weaver task — covered by a follow-up kanban card)
- **Action:** Watch ArgoCD app `threads-canary` reach `Synced/Healthy`. Confirm:
  1. `kubectl get pods -n threads-canary` → `main` 1/1 Running, Ready; `minio-0` 1/1 Running, Ready.
  2. `kubectl get pod -n threads-canary -l app.kubernetes.io/component=main -o jsonpath='{.items[0].spec.containers[0].env}'` shows `DATABASE_URL` and `DATABASE_PASSWORD` keys; the rendered `DATABASE_URL` contains the actual password (no placeholder).
  3. `kubectl logs -n threads-canary -l app.kubernetes.io/component=main --tail=50 | grep -i "migrations\|ready\|listening"` shows successful migration and HTTP server listening.
  4. `curl -sk https://threads-canary.eaglepass.io/api/v1/health/live` → HTTP 200.
  5. `curl -sk https://threads-canary.eaglepass.io/api/v1/health/ready` → HTTP 200.
- **Acceptance:** All five checks pass. No `CrashLoopBackOff`. No `password authentication failed` in pod logs.
- **Effort:** 15 min (mostly waiting for ArgoCD sync).

## 6. Risks, assumptions, and open questions

### Risks
- **R1: Helm tpl vs literal value.** The bjw-s app-template 5.0.1 chart renders `env` entries through its `common.tplvalues.render` helper only for entries whose `value` contains a `{{`. The fragment in §3 deliberately uses `{{ .Values... }}` syntax to force tpl resolution. **Mitigation:** Task 2 acceptance includes a `helm template` check that verifies the rendered manifest. If tpl resolution fails, fall back to the outline pattern (store full `database-url` in the 1Password item; reference it as a single `secretKeyRef`).
- **R2: 1Password operator sync lag.** The operator polls on a default 60s interval. There is a window where the chart references `database-password` but the key does not yet exist in the Secret. **Mitigation:** Task 4 waits for the Secret update to land before checking pod health; if the pod enters CrashLoopBackOff for "key not found" the verifier waits another 60s and retries.
- **R3: sslmode drift.** The committed values.yaml has `sslmode=require` but Vanguard observed the live synced pod running `sslmode=disable` (per t_9b337fed — the SSL fix was bb008009 on origin/master, not yet reflected in the local working tree). **Mitigation:** This spec intentionally uses `sslmode=require` to match the current committed values.yaml (the file on disk is the source of truth for this spec). If a follow-up deploy reveals the live cluster is on `disable`, that is a separate issue (an unmerged local change or an out-of-band patch) and out of scope for this spec.
- **R4: Password rotation coupling.** Adding the password to the threads-canary 1Password item creates a second copy of the value (the original lives in the postgres item). If `THREADS_POSTGRES_PASSWORD` is ever rotated, both items must be updated. **Mitigation:** Add a 1Password item-level note documenting the dependency on the postgres item's `threads-postgres-password` field. (Out of scope for the chart fix itself but worth flagging.)

### Assumptions
- A1: The 1Password operator on the cluster is healthy and the threads-canary namespace's `threads-canary-secrets` Secret is being auto-synced from item `klgtclyw2ctf435fa65t4eb5be` (confirmed: same item-name annotation already on the chart's `defaultPodOptions`).
- A2: The threads postgres user accepts password auth over the cluster-internal DSN (confirmed by Vanguard's t_9b337fed observation that the prior SSL error cleared; the next error in the chain is password auth, which means the network path and TLS mode are correct).
- A3: The bjw-s `app-template` 5.0.1 chart's tpl helper resolves the `{{ .Values... }}` pattern inside `env.value`. This is a documented feature of the chart's common library; if the live `helm template` output disagrees, fall back to the outline pattern.
- A4: No other consumers of `apps/threads-canary/values.yaml` depend on `DATABASE_URL` being a scalar string (e.g. a Kustomize overlay that does string substitution). The repo has no such overlay (verified — `apps/threads-canary/` has only `values.yaml`, `Chart.yaml`, `Chart.lock`, and the `charts/` directory).

### Open questions for Lens
- Q1: Should the fix ship with `sslmode=require` (matching committed values.yaml) or `sslmode=disable` (matching what Vanguard observed on the live cluster)? Recommend `require` to match committed state; treat the live divergence as a separate issue.
- Q2: Should the password be added to the threads-canary 1Password item (chosen approach) or should threads-canary reference the cross-namespace `secrets` Secret from the postgres namespace? Recommend the chosen approach for consistency with the 6 existing secret references.
- Q3: Is there any other threads-canary secret that should be co-located in this 1Password item while we're updating it? (None identified in the chart; out of scope unless Lens flags one.)

## 7. Acceptance criteria for the whole spec

The fix is considered done when **all** of the following are true (verifiable by Vanguard's verification task):

- [ ] AC1: `apps/threads-canary/values.yaml` no longer contains a hardcoded `DATABASE_URL` scalar. The line is replaced with the `DATABASE_URL` + `DATABASE_PASSWORD` pair from §3.
- [ ] AC2: `helm template threads-canary apps/threads-canary/` renders successfully (exit 0) and the output contains both `DATABASE_URL` and `DATABASE_PASSWORD` env entries for the main container.
- [ ] AC3: 1Password item `klgtclyw2ctf435fa65t4eb5be` contains a `database-password` field whose value equals the postgres `secrets` Secret's `threads-postgres-password` data value.
- [ ] AC4: `git log origin/master` shows the new fix commit on top of bb008009 (the SSL fix from t_28d9d5f5).
- [ ] AC5: ArgoCD app `threads-canary` reaches `Synced/Healthy` after the commit lands.
- [ ] AC6: `kubectl get pods -n threads-canary` shows `main` 1/1 Running, Ready.
- [ ] AC7: `kubectl logs` on the main pod show no `password authentication failed` errors and show a successful migration line.
- [ ] AC8: `curl -sk https://threads-canary.eaglepass.io/api/v1/health/live` returns HTTP 200.
- [ ] AC9: `curl -sk https://threads-canary.eaglepass.io/api/v1/health/ready` returns HTTP 200.
- [ ] AC10: `yamllint apps/threads-canary/values.yaml` exits 0; no new lint findings introduced.
- [ ] AC11: No production values file (`apps/threads/values.yaml` if it exists) was modified. Verified by `git diff origin/master~1..origin/master --name-only` showing only `apps/threads-canary/values.yaml` (and the prior unreleased local changes that have already been merged to master).

## 8. What Lens should specifically inspect

Lens (the spec reviewer) should focus on these specific points when validating this blueprint:

1. **The 1Password operator sync correctness** — confirm that the 1Password item `klgtclyw2ctf435fa65t4eb5be` is in fact the secret source backing the `threads-canary-secrets` Secret in the threads-canary namespace, and that adding a new key will be picked up by the auto-sync. If the operator is configured with a longer poll interval than 60s, R2's mitigation may need adjustment.
2. **The Helm tpl rendering assumption** — render `helm template threads-canary apps/threads-canary/` locally before the change and after. Verify the rendered `DATABASE_URL` value is a literal URL (with password interpolated from the same Secret at runtime) and not a `{{ ... }}` placeholder. If the post-fix render still shows `{{ ... }}`, the implementation must fall back to the outline pattern (full URL in the 1Password item).
3. **The sslmode discrepancy** — Vanguard observed `sslmode=disable` live; the committed values.yaml has `sslmode=require`. This spec uses `require` to match committed state. Lens should confirm this is the right call (recommend yes) before the change ships.
4. **The 1Password item note** — R4's mitigation (documenting the password-rotation coupling) is out of scope for the chart fix but should be added to the 1Password item's notes field by the human operator doing the manual edit. Confirm the operator will add it.
5. **The cross-namespace ref question (Q2)** — if Lens prefers the cross-namespace `secrets` Secret reference for any reason (e.g. consistency with how other apps reach postgres), the implementation must switch to that approach. The spec's chosen approach is the recommended default.

## 9. Out of scope

- Promoting threads-canary to production. The fix is canary-only per the source task's explicit "CANARY ONLY" instruction.
- Rotating the threads postgres password. The fix reuses the existing password; rotation is a separate concern.
- Refactoring the other 6 secret references in the chart. They are working correctly and don't need to change.
- Adding a Kubernetes NetworkPolicy for postgres egress. The existing networkpolicy already allows egress to the `postgres` namespace on port 5432 (verified at `apps/threads-canary/values.yaml:248-252`).
- Updating the 1Password item's other fields. Only the new `database-password` key is added.

## 10. Deliverable location

- Spec file: `/home/echo/repos/homelab/specs/5-fix-threads-canary-db-password/spec.md` (this file)
- Implementation (Weaver): `apps/threads-canary/values.yaml` (2-line change)
- 1Password update (manual): item `klgtclyw2ctf435fa65t4eb5be`, new field `database-password`
- Verification (Vanguard): follow-up kanban card targeting the canary deployment
