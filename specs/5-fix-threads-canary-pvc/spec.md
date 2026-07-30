# Spec: Fix threads-canary PVC Multi-Attach Error

**Status:** Draft (Cartographer output, awaiting Lens review)
**Source task:** `t_6be51438` (cartographer)
**Research task:** `t_59671cf5` (researcher)
**Chart:** `apps/threads-canary` (Helm chart version 0.1.0, `app-template` v5.0.1)
**Target namespace:** `threads-canary`
**Risk class:** Low — single values.yaml edit, idempotent, no schema migration, no PVC data movement

---

## 1. Problem Statement

The `threads-canary` Deployment pod is stuck in `ContainerCreating` because the RWO PVC `threads-canary` (5 Gi, `standard-rwo`) is mounted by **two** workloads at once:

1. `threads-canary-minio-0` (StatefulSet, MinIO controller) — `Running`, owns the volume.
2. `threads-canary-<replicaset>-<pod>` (Deployment, main controller) — `ContainerCreating` for 90+ min, blocked on `Multi-Attach error for volume ... PVC is already exclusively attached by one node`.

### Observed runtime state (kubectl)

```
$ kubectl get pods -n threads-canary
NAME                              READY   STATUS              RESTARTS   AGE
threads-canary-5578945489-tzh4c   0/1     ContainerCreating   0          90m
threads-canary-minio-0            1/1     Running             0          90m

$ kubectl get pvc -n threads-canary
NAME             STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGEC   AGE
threads-canary   Bound    pvc-f5aeb710-6590-4bc2-acb8-e8031b01fb86   5Gi        RWO            standard-rwo  149m
```

### Root cause

`apps/threads-canary/values.yaml` declares the persistence block with `globalMounts`, which causes the bjw-s `app-template` to attach the resulting PVC to **every** container in the release — including the `main` controller's `main` container, which has no need for `/data`.

```yaml
# apps/threads-canary/values.yaml, lines 210-218 (current — BROKEN)
persistence:
  minio-data:
    enabled: true
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    storageClass: standard-rwo
    size: 5Gi
    globalMounts:
      - path: /data          # ← attached to main container AND minio container
```

`globalMounts` is the chart's "attach this everywhere it fits" shortcut. For a PVC that only one controller should see (MinIO's S3 datastore), this collides with the RWO `accessMode: ReadWriteOnce` constraint because the Deployment pod also gets the volume attached.

The `main` controller does not need `/data` — it talks to MinIO over HTTP at `http://threads-canary-minio:9000` (env `S3_ENDPOINT`). Mounting the PVC there serves no purpose and is the direct cause of the Multi-Attach block.

---

## 2. Fix

Replace the `globalMounts` list with `advancedMounts` scoped explicitly to the `minio` controller and the `minio` container only.

### 2.1 Precise diff (`apps/threads-canary/values.yaml`, lines 217-218)

```diff
   persistence:
     minio-data:
       enabled: true
       type: persistentVolumeClaim
       accessMode: ReadWriteOnce
       storageClass: standard-rwo
       size: 5Gi
-      globalMounts:
-        - path: /data
+      advancedMounts:
+        minio:
+          minio:
+            - path: /data
```

That is the **entire change** required to resolve the collision. No other lines in the file move; PVC metadata, network policy, controllers, and ingress are unaffected.

### 2.2 Why this syntax (bjw-s `app-template` v5)

The `advancedMounts` key takes a two-level map:

```
advancedMounts:
  <controller-name>:
    <container-name>:
      - path: <mount-path>          # required
        # subPath: <string>        # optional
        # readOnly: <bool>         # optional
        # type: <Directory|CreateDirectory>   # optional
```

The chart then emits `volumeMounts` only on the specified `(controller, container)` pair. For threads-canary:

- `controller-name` = `minio` (matches `app-template.controllers.minio` defined at line 108).
- `container-name` = `minio` (matches `app-template.controllers.minio.containers.minio` at line 113 — verified, see § 6).
- `path: /data` matches the `args: server /data` of the MinIO process (line 119), so MinIO writes to the PVC's data directory.

The `main` controller receives **no** mount for this PVC. ArgoCD/Helm rendering will not emit a `volumeMounts` entry on the Deployment's `main` container, so the kube-scheduler's Multi-Attach check passes.

### 2.3 Precedents in this repo

The same `controller → container → -path:` shape is already used elsewhere — copy the exact form, not paraphrase:

| File | Lines | Persistence type | Controller.Container pair |
|---|---|---|---|
| `apps/outline/values.yaml` | 248-256 | `persistentVolumeClaim` (RWO) | `postgres.main` |
| `apps/outline/values.yaml` | 239-247 | `nfs` (RWX) | `outline.main` |
| `apps/wolf/values.yaml` | 246-252 | `emptyDir` | `main.main` |
| `apps/wikijs/values.yaml` | 313-330 | (multiple, mixed) | `wikijs.main`, `wikijs.backup-db`, etc. |

The `outline` Postgres block is the closest analog: an RWO PVC attached to a single controller's single container via `advancedMounts`. The fix for threads-canary is a 1:1 structural mirror of that pattern, swapped to the `minio/minio` names.

---

## 3. Acceptance Criteria

Each criterion below is **falsifiable** — a test or observation proves it pass or fail.

### 3.1 Static (file-level, verifiable on the working copy)

- [ ] **AC-S1** — `apps/threads-canary/values.yaml` line 217 (under `persistence.minio-data`) does **not** contain the substring `globalMounts:`. Verified by `grep -n globalMounts apps/threads-canary/values.yaml` returning zero matches.
- [ ] **AC-S2** — The `persistence.minio-data` block contains an `advancedMounts:` key followed by the literal two-level map `minio:` → `minio:` → `- path: /data`. Verified by `yq '.app-template.persistence."minio-data".advancedMounts.minio.minio[0].path' apps/threads-canary/values.yaml` returning `/data`.
- [ ] **AC-S3** — No other block in the file introduces new `advancedMounts` or removes existing entries — diff against `git HEAD` shows exactly two lines changed (one `-`, one `+`-thru-the-end-of-block) under the `persistence.minio-data` heading.
- [ ] **AC-S4** — `yamllint apps/threads-canary/values.yaml` exits 0 (no new violations).
- [ ] **AC-S5** — `helm template threads-canary apps/threads-canary --namespace threads-canary` exits 0 and the rendered `Deployment/threads-canary` manifest contains **no** `volumeMounts` entry referencing `minio-data`.

### 3.2 Rendered-manifest (after `helm template`, verifiable by Weaver)

- [ ] **AC-R1** — In the rendered `StatefulSet/threads-canary-minio`, container `minio` has a `volumeMounts` entry `{ name: threads-canary-minio-data, mountPath: /data }`.
- [ ] **AC-R2** — In the rendered `Deployment/threads-canary`, container `main` has **no** `volumeMounts` entry referencing a volume named `*minio-data*` (grep the rendered manifest for `volumeMounts` blocks belonging to `container.name: main`).
- [ ] **AC-R3** — In the rendered `Deployment/threads-canary`, the Pod spec lists **no** `volume` of kind `PersistentVolumeClaim` that references the MinIO PVC. (A shared `volumes[]` entry is acceptable if and only if it is not mounted into the `main` container — emulated mounts that don't bind are harmless, but `volumeMounts` in `main` is the bug.)
- [ ] **AC-R4** — The rendered PVC `threads-canary-minio-data` retains `accessModes: [ReadWriteOnce]`, `storageClassName: standard-rwo`, `resources.requests.storage: 5Gi` — unchanged from the pre-fix render.

### 3.3 Live cluster (after ArgoCD sync, verifiable by Prism)

- [ ] **AC-L1** — `kubectl get pods -n threads-canary` shows `threads-canary-minio-0` as `1/1 Running` and `threads-canary-<rs>-<pod>` as `1/1 Running` (or at least `Running`, not `ContainerCreating` or `Pending`).
- [ ] **AC-L2** — `kubectl describe pod threads-canary-<rs>-<pod> -n threads-canary | grep -E 'Multi-Attach|already attached'` returns zero matches.
- [ ] **AC-L3** — `kubectl get pvc -n threads-canary threads-canary` remains `Bound` with the same `VOLUME` UID (`pvc-f5aeb710-6590-4bc2-acb8-e8031b01fb86`) — the PVC is **not** recreated; data is preserved.
- [ ] **AC-L4** — `kubectl exec -n threads-canary deploy/threads-canary -- curl -fsS http://threads-canary-minio:9000/minio/health/live` returns `200 OK` (MinIO still reachable from main).
- [ ] **AC-L5** — `kubectl exec -n threads-canary threads-canary-minio-0 -- ls /data` succeeds and shows the expected `minio/` tree (or whatever existed pre-fix). No data loss.
- [ ] **AC-L6** — ArgoCD app `threads-canary` shows `Healthy` and `Synced` within 5 minutes of the commit being pushed to `master`.

### 3.4 Negative / regression (must hold)

- [ ] **AC-N1** — No other chart's PVC mount configuration is modified by this change. `git diff --stat master..HEAD -- apps/` shows exactly one file changed: `apps/threads-canary/values.yaml`.
- [ ] **AC-N2** — The `minio` container still binds port `9000` (api) and `9001` (console) and the liveness/readiness probes still hit `/minio/health/{live,ready}` — these are unaffected but Weaver must re-check that the container section is unchanged.
- [ ] **AC-N3** — `globalMounts` does not appear anywhere else in `apps/threads-canary/values.yaml` after the fix (grep returns zero hits). Future maintainers shouldn't add it back to this chart.

---

## 4. Tasks

| # | Task | Assignee | Depends on | Effort |
|---|------|----------|------------|--------|
| 1 | Apply the values.yaml edit (`globalMounts` → `advancedMounts`) per § 2.1 | `implementer` (Weaver) | — | 5 min |
| 2 | Run `helm template`, `yamllint`, and `pre-commit run --files apps/threads-canary/values.yaml` | `implementer` (Weaver) | #1 | 5 min |
| 3 | Commit + push to `master` (do **not** skip pre-commit hooks); verify ArgoCD picks up the change | `implementer` (Weaver) | #2 | 5 min |
| 4 | Verify AC-L1 through AC-L6 on the cluster after ArgoCD sync | `verifier` (Prism) | #3 | 10 min |
| 5 | Report PASS/FAIL with concrete kubectl output for AC-L1..L6 | `verifier` (Prism) | #4 | 5 min |

### 4.1 Task details

**Task 1 — Edit values.yaml**

- Files: `apps/threads-canary/values.yaml`
- Replace lines 217-218 (the `globalMounts: - path: /data` pair) with the `advancedMounts: minio: minio: - path: /data` block shown in § 2.1.
- Do not touch any other line. Do not reformat. Do not reorder.

**Task 2 — Static + render verification**

- `cd /home/echo/repos/homelab`
- `yamllint apps/threads-canary/values.yaml`
- `helm template threads-canary apps/threads-canary --namespace threads-canary > /tmp/threads-canary.rendered.yaml`
- `grep -n 'volumeMounts\|minio-data' /tmp/threads-canary.rendered.yaml` — confirm `main` container has zero `minio-data` references.
- `pre-commit run --files apps/threads-canary/values.yaml`

**Task 3 — Commit + push**

- Branch: stay on `master` (ArgoCD tracks `master` per AGENTS.md).
- Commit message: `fix(threads-canary): scope minio-data PVC to minio controller (Multi-Attach fix)`.
- Push via the `http-origin` remote (the only reachable Gitea remote from this host, per working memory). Unauthenticated push is expected.
- Wait for ArgoCD to detect the change (poll interval ~3 min).

**Task 4 — Cluster verification**

- Run the kubectl commands listed in § 3.3 verbatim.
- If AC-L1 fails after 10 min (e.g., `ContainerCreating` persists), check `kubectl describe pod` for a different error and re-open the task rather than force-syncing.

**Task 5 — Report**

- Paste full `kubectl get pods`, `kubectl describe pod ... | grep -i multi`, `kubectl get pvc`, and the minio health-check curl output into the verifier handoff.
- PASS iff all 6 AC-L criteria pass. FAIL otherwise — Prism must not paper over a partial fix.

---

## 5. Risks, Constraints, and Assumptions

### 5.1 Risks

- **R1 — Data loss** if the PVC is accidentally deleted during the edit. **Mitigation:** the edit touches only the `mounts:` sub-key, not the PVC definition (`type`, `accessMode`, `storageClass`, `size`). Helm treats this as an in-place update of the StatefulSet; the PVC is not recreated. AC-L3 enforces this with a UID check.
- **R2 — ArgoCD ComparisonError** if the new `advancedMounts` shape has wrong nesting. **Mitigation:** the exact `outline` Postgres block (lines 248-256 of `apps/outline/values.yaml`) is the precedent; if `outline` renders, so will this. AC-S4 + AC-S5 catch schema errors at template time.
- **R3 — App-template v5 vs v4 syntax drift.** The chart pins `app-template` v5.0.1 in `Chart.yaml`. v5 still supports `advancedMounts.<controller>.<container>[- path: …]`. (v5 *removed* inline `volumeMounts` on init containers — the persistence-block `advancedMounts` shape is unchanged.) No version bump needed.
- **R4 — Container name typo.** If `containers.minio` is misspelled, `advancedMounts.minio.minio` will silently fail to match and the volume will not be mounted into the StatefulSet. AC-R1 catches this at render time, AC-L1 catches it at runtime. **Verified:** line 113 of the current `values.yaml` is `containers: minio:`.

### 5.2 Constraints

- **C1** — Single-file change. Do not modify `Chart.yaml`, `templates/`, network policies, services, ingress, secrets, or any other file. Scope creep is forbidden.
- **C2** — No PVC migration, no data copy, no MinIO restart. MinIO stays up; the PVC stays `Bound`. Main pod just stops asking for the volume.
- **C3** — Branch = `master`. Do not create a feature branch; ArgoCD tracks `master` for this app (per AGENTS.md).
- **C4** — `pre-commit` must pass (yamllint, helmlint, shellcheck). Don't bypass hooks.
- **C5** — Do not introduce `globalMounts` anywhere new in this chart (AC-N3).

### 5.3 Assumptions (Lens must verify)

- **A1** — The `main` controller has no application-level dependency on a `/data` path inside its container. Inspect `apps/threads-canary/values.yaml` lines 18-107 and the threads container image at `10.0.20.11:32309/threads:22547a6` — neither the env (`S3_ENDPOINT=http://threads-canary-minio:9000`) nor the args/lifecycle hooks reference `/data`.
- **A2** — The PVC is only ever mounted by the threads release's workloads — no other Pod, Job, or DaemonSet in the namespace attaches it. Verify with `kubectl get pods -A -o json | jq '.items[] | select(.spec.volumes[]?.persistentVolumeClaim?.claimName=="threads-canary") | {ns: .metadata.namespace, name: .metadata.name}'`.
- **A3** — `app-template` v5.0.1 honors `advancedMounts` exactly as documented in `apps/outline/values.yaml` and `apps/wolf/values.yaml`. The same shape is already in production for `outline`'s Postgres PVC, so this is empirically confirmed.
- **A4** — ArgoCD will auto-sync the canary chart on `master` push within ~3 minutes. If it does not, Prism triggers a manual sync after verifying the diff is correct.

---

## 6. Reference Appendix

### 6.1 Pre-edit values.yaml excerpt (lines 210-218)

```yaml
persistence:
  minio-data:
    enabled: true
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    storageClass: standard-rwo
    size: 5Gi
    globalMounts:
      - path: /data
```

### 6.2 Post-edit values.yaml excerpt (lines 210-220)

```yaml
persistence:
  minio-data:
    enabled: true
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    storageClass: standard-rwo
    size: 5Gi
    advancedMounts:
      minio:
        minio:
          - path: /data
```

### 6.3 Container-name verification

```
$ grep -nE '^\s+(minio|main):' apps/threads-canary/values.yaml
5:    main:                # controller name = main
19:        main:            # main controller's container name = main
108:    minio:              # controller name = minio
113:        minio:          # minio controller's container name = minio
```

The `advancedMounts.minio.minio` keypair in § 2.1 matches `controllers.minio.containers.minio`. Confirmed.

### 6.4 Reference precedent — `apps/outline/values.yaml` lines 248-256

```yaml
postgres-data:
  type: persistentVolumeClaim
  accessMode: ReadWriteOnce
  size: 20Gi
  storageClass: standard-rwo
  advancedMounts:
    postgres:
      main:
        - path: /var/lib/postgresql
```

This is the canonical RWO-PVC-via-advancedMounts shape in the homelab repo. The threads-canary fix mirrors it with `minio`/`minio` instead of `postgres`/`main`.

### 6.5 Related prior work

- `t_073d1960` — `SPEC-prod-pvc-fix.md` for the prod `tipsbot` chart (mirror fix; prod already migrated).
- `t_5bd641d9` (commit) — `fix(wikijs): migrate fix-git-sync mount paths to app-template v5 advancedMounts`. Same pattern, different chart — confirms v5 advancedMounts shape.
- `t_6a47991c` (commit) — `fix(citadel): use advancedMounts instead of volumeMounts for app-template schema`. Same pattern, different chart.
- Research task `t_59671cf5` validated this fix path; this spec is the implementation blueprint derived from that research.

---

## 7. What Lens Should Verify

When reviewing this spec, Lens should specifically check:

1. **§ 2.1 diff is exact.** No off-by-one (the edit replaces two lines: `      globalMounts:` and `        - path: /data`, then appends three lines under the `advancedMounts:` key). Confirm there is no trailing-key collision with `accessMode`/`storageClass`/`size`.
2. **§ 3 acceptance criteria are falsifiable.** Every `- [ ]` line has a concrete command or observation that proves pass or fail. Vague "should work" criteria must be rejected.
3. **§ 4 tasks are scoped (5-30 min each).** Each task is small enough to complete in one sitting without scope creep.
4. **§ 5 risks and assumptions are honest.** R1-R4 are the real failure modes; A1-A4 are the load-bearing beliefs. Lens should mark any it cannot confirm and route back to the researcher.
5. **§ 6 references are accurate.** The line numbers, file paths, and precedent code blocks must match the repo at the time of review. Spot-check `apps/outline/values.yaml:248-256` against the live file.
6. **No silent PVC migration or data movement.** The fix must not include any rsync, kubectl cp, PVC clone, or MinIO bucket-sync step. If it does, that's scope creep and the spec should be rejected.

---

**End of spec.**