# Blueprint: Add ITAD_API_KEY to backlog-companion canary backend

## Overview

The backlog-companion canary backend throws "ITAD_API_KEY is not configured" when the admin panel's ITAD scan button is pressed, returning HTTP 500 to the frontend. Root cause: `backend/jobs/itadScan.js` reads `process.env.ITAD_API_KEY` (line 206) and throws when missing, but the canary Helm values do not define that env var. This blueprint describes the minimum change to resolve the issue: add `ITAD_API_KEY` as a literal env var on the backend container in `apps/backlog-canary/values.yaml`, redeploy via ArgoCD, and confirm a scan trigger returns a valid (non-500) response.

## Architecture

- **Component touched**: `apps/backlog-canary` (Helm chart) — backend container env block only.
- **Code touched**: none. `backend/jobs/itadScan.js` already reads `process.env.ITAD_API_KEY` correctly. The bug is purely an env-var wiring gap.
- **Data flow (unchanged)**:
  1. User clicks "Run ITAD Scan" in admin panel (canary frontend).
  2. Frontend POSTs to backend `/api/admin/itad/scan`.
  3. Backend calls `runItadScanNow(...)` which reads `process.env.ITAD_API_KEY` from the pod's environment.
  4. With the key present, the worker proceeds: stale-row cleanup → upsert scan row → `isThereAnyDealClient.searchDeals(...)` → status updates → return `{ ok: true, scan_id }` to the admin panel.
- **Dependencies**: external `api.isthereanydeal.com` (already wired in code; just needs the key).
- **Tech stack**: unchanged — Node.js 18 / Express 5 backend deployed via app-template Helm chart on Kubernetes (ArgoCD-synced).

## Interface Definitions

### Helm values change (single insertion)

In `apps/backlog-canary/values.yaml`, the backend container's `env:` block (lines 62–93) gains one new key:

```yaml
        backend:
          image:
            repository: 10.0.20.11:32309/backlog_backend
            tag: "main-20260625-e4b7c34"
            pullPolicy: Always
          env:
            TZ: America/Chicago
            HOST_URL: https://backlog-canary.eaglepass.io
            PORT: "3000"
            DB_HOST: localhost
            DB_PORT: "3306"
            ADMIN_MODE: "true"
            ITAD_API_KEY: "29a6c15b033cf7ba61e7581ddfd9e78e8d28d5a6"   # <-- ADD THIS LINE
            DB_USER:
              valueFrom:
                secretKeyRef:
                  name: secrets
                  key: db-user
            ...
```

**Placement rationale**: inserted immediately after `ADMIN_MODE` and before the secretKeyRef block. This keeps all literal env vars (TZ, HOST_URL, PORT, DB_HOST, DB_PORT, ADMIN_MODE, ITAD_API_KEY) grouped together and preserves the existing boundary between literal values and 1Password-secret references.

**Convention check**: app-template's env schema accepts bare scalars as plain values (see `TZ`, `HOST_URL`, etc. on lines 63–68). Plain scalar works; no `value:` wrapper required.

**Secret-store note (out of scope)**: the other credentials use `secretKeyRef` against the `secrets` 1Password item. Routing ITAD_API_KEY through 1Password would be a stronger long-term pattern, but the task body explicitly specifies a literal env value, and that decision is owned by the user. Do not refactor to secretKeyRef as part of this change.

### Backend code: zero changes required

`backend/jobs/itadScan.js` lines 206–209:

```js
const apiKey = process.env.ITAD_API_KEY;
if (!apiKey) {
  throw new Error('ITAD_API_KEY is not configured.');
}
```

After the Helm change, `process.env.ITAD_API_KEY` is populated and the throw no longer fires on scan trigger.

### Public surface: unchanged

No API routes change. No frontend code change. Feature flag `VITE_FEATURE_ITAD_DEALS=true` already enabled (line 122 of values.yaml) and out of scope.

## Task Breakdown

| # | Task | Assignee | Depends On | Acceptance Criteria |
|---|------|----------|------------|---------------------|
| 1 | Add `ITAD_API_KEY` literal env to `apps/backlog-canary/values.yaml` backend container | implementer | — | (a) File diff shows exactly one new line: `            ITAD_API_KEY: "29a6c15b033cf7ba61e7581ddfd9e78e8d28d5a6"` inserted in the backend `env:` block. (b) `yamllint apps/backlog-canary/values.yaml` exits 0. (c) `helm template apps/backlog-canary apps/helm-templates/` (or equivalent render) shows `ITAD_API_KEY` present in the rendered backend container env. (d) Production `apps/backlog/values.yaml` is unmodified. (e) Image tag, probes, frontend env, ingress, services, and persistence all unchanged from the diff. |
| 2 | Commit and push the values change to homelab master, trigger ArgoCD sync for `backlog-canary` | implementer | #1 | (a) New commit on `master` in homelab repo with message `fix(backlog-canary): add ITAD_API_KEY env var to backend`. (b) ArgoCD app `backlog-canary` shows `Synced` / `Healthy` after the sync. (c) The backend pod is restarted with the new env (pod generation timestamp newer than the commit timestamp). |
| 3 | Verify scan endpoint returns 200 with no ITAD_API_KEY error in logs | verifier | #2 | (a) Hitting `POST https://backlog-canary.eaglepass.io/api/admin/itad/scan` with a valid admin JWT returns HTTP 200 (or 202) and a JSON body containing `ok: true` or a `scan_id` — NOT HTTP 500. (b) Backend pod logs for the 60 seconds surrounding the test contain no `ITAD_API_KEY is not configured` error. (c) A `running` row appears in the `itad_scans` table for canary (verifies the worker actually entered the scan path). |

## Task Specification

### Task 1: Edit canary Helm values

**Objective**: Add ITAD_API_KEY as a literal env var on the backend container in apps/backlog-canary/values.yaml.

**Files to Create/Modify**
- `apps/backlog-canary/values.yaml` — insert one line in the backend `env:` block

**Acceptance Criteria**
- [ ] Diff against `master` shows exactly one new line: `            ITAD_API_KEY: "29a6c15b033cf7ba61e7581ddfd9e78e8d28d5a6"`
- [ ] Insertion point is between `ADMIN_MODE: "true"` and the `DB_USER:` secretKeyRef block (lines 68–69 in the current file)
- [ ] `yamllint apps/backlog-canary/values.yaml` exits 0
- [ ] Helm render shows `ITAD_API_KEY` in the backend container env, and the value matches the literal in the source (sanity check that app-template is not silently dropping it)
- [ ] Production file `apps/backlog/values.yaml` is byte-identical to its pre-change state
- [ ] Image tag, probes, frontend env, ingress, services, and persistence are byte-identical

**Deliverable Location**: commit on `master` in `~/Documents/Github/homelab`

**Expected Effort**: ~10 minutes

### Task 2: Deploy via ArgoCD

**Objective**: Get the new env into the running canary pod.

**Files to Create/Modify**
- (No code change — this is the operational push through git + ArgoCD)

**Acceptance Criteria**
- [ ] Commit pushed to homelab `master`
- [ ] ArgoCD `backlog-canary` app transitions to `Synced` / `Healthy`
- [ ] Backend pod's env contains `ITAD_API_KEY` (verifiable via `kubectl exec ... -- printenv ITAD_API_KEY` returning a non-empty, 40-char hex string)

**Deliverable Location**: live canary cluster (`backlog-canary.eaglepass.io`)

**Expected Effort**: ~5 minutes (assuming ArgoCD auto-sync is on; longer if manual sync needed)

### Task 3: Verify the fix end-to-end

**Objective**: Confirm the original 500 is gone and the scan path actually executes.

**Files to Create/Modify**
- (No code change — this is end-to-end validation)

**Acceptance Criteria**
- [ ] `curl -X POST https://backlog-canary.eaglepass.io/api/admin/itad/scan -H "Authorization: Bearer <admin-jwt>"` returns HTTP 200 (or 202) with `{"ok": true, "scan_id": <id>}` or equivalent success body — NOT HTTP 500
- [ ] Backend logs for the 60 seconds around the test request contain zero occurrences of `ITAD_API_KEY is not configured`
- [ ] `itad_scans` table in canary DB has a new row with `status='running'` (proves the worker entered the scan path past the env check)

**Deliverable Location**: comment on this kanban task with curl output and log snippet as evidence

**Expected Effort**: ~10 minutes

## Risks & Edge Cases

- **ArgoCD sync timing**: if auto-sync is disabled or has a sync window, the change may not reach the cluster immediately. Task 2 includes the sync check explicitly so we don't silently fail.
- **Pod recycle behavior**: backend uses `strategy: Recreate` (line 4), so the update will take the pod down briefly. Readiness probe `/health/ready` on port 3000 should bring traffic back once the new pod is ready.
- **Key rotation**: this blueprint hard-codes a specific key. If the key is rotated in the future, the same edit pattern applies (update the literal). Long-term, routing through the 1Password `secrets` item like the other credentials would be cleaner — flag for follow-up, do not bundle into this change.
- **Production parity**: production (`apps/backlog`) does NOT have ITAD_API_KEY either. Per the task's out-of-scope rules, we deliberately do not mirror the change to production in this task. If production is expected to expose the admin scan button, that is a separate decision and ticket.

## Out of Scope (Explicit)

- Modifying `apps/backlog/values.yaml` (production)
- Modifying backend code (`backend/jobs/itadScan.js` and friends)
- Modifying frontend code or feature flags
- Migrating ITAD_API_KEY to the 1Password `secrets` secret-store (separate ticket)
- Adding automated tests for the env-presence check (defer; current `itad-controller.test.js` already exercises the missing-key path)

## References

- Task body: kanban task t_07027dba
- Backend env read: `~/repos/backlog-companion/backend/jobs/itadScan.js` lines 206–209
- Backend test coverage of missing-key path: `~/repos/backlog-companion/backend/tests/itad-scan.test.js` line 166–169
- Helm values (canary): `~/repos/homelab/apps/backlog-canary/values.yaml` lines 57–112 (backend block)
- Helm values (production, untouched): `~/repos/homelab/apps/backlog/values.yaml` lines 56–92