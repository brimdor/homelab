# Retire exact, owner-authorized workloads

`scripts/retire-workloads.py` executes one source-controlled retirement plan. Its default mode checks prerequisites and current objects without mutating them. `--apply` selects the already-authorized execution mode; it never prompts for approval.

This is an exact-plan executor, not garbage collection, an EOL-remediation workflow, or a replacement for the existing PVC hygiene annotation/mode gate. EOL alone is a maintenance finding. The historical Renovate item is owner-closed history with subsequent healthy execution, not a repaired root cause. The executor never creates backups or changes issues, finalizers, or application source. It never individually targets CronJobs or Secrets; retired namespace deletion still invokes normal Kubernetes cascading deletion.

## Authority and irreversible data loss

The owner explicitly authorized **no backups** for intentionally purged archived, non-NFS data that active applications do not use. Unflagged, unused non-NFS storage from deleted-but-not-archived workloads may also be purged. Deleted-but-not-archived storage with retention/persistence flags must stay. NAS, NFS, active storage, and shared data are always protected.

Deleting a claim or changing an archived RBD PV's reclaim policy can permanently erase its backend through CSI. There is no data rollback for an intentionally unbacked purge. Restoring a chart from Git cannot restore erased data. Do not treat this document or `--apply` as authority for another owner's resources.

The parent operator must protect and quiesce Scribe **before** removing its active chart or deleting its Argo Application. An executor gate reached after Argo's cascade cannot protect data that the cascade already erased. This source-only implementation neither installs that protection nor performs the rollout.

### Required two-phase GitOps handoff

1. While the Application still exists, capture the live Namespace/PVC/PV UIDs, workload/controller UIDs, claim bindings, reclaim policies, CSI attributes, StorageClass provisioner/parameters, and exact backend image identities. Inventory deletion-effect resource metadata too. Resolve active/shared/NFS ownership before proceeding.
2. In the active Scribe chart's owning desired state, set workload replicas to `0` and declare `argocd.argoproj.io/sync-options: Delete=false,Prune=false` on the **actual Namespace and every retained PVC**. Application annotations alone are not Namespace/PVC protection. Keep the active chart and Application present during this phase.
3. Validate, commit, and push that protection/quiescence change to canonical Gitea `master`. Sync it through Argo. Verify the live annotations on the same Namespace/PVC UIDs, zero desired replicas, finished Pod termination/CSI detach, and unchanged claim/PV/backend identities. A source annotation without live readback is not protection. Stop if these gates fail.
4. Only after phase-one verification, archive Scribe in desired state and commit/push that separate change plus the exact retirement plan. Allow GitOps to delete the Application and its unprotected controllers. Wait until every Application targeting a planned namespace is completely absent, including Terminating Applications. Verify the protected Namespace/PVC UIDs and backend identities again before the executor runs.
5. Run the committed plan's check mode, then its already-authorized `--apply` mode. Record owning-controller cleanup and the parent's independent read-only backend image-absence proof.

Keep the protection in effect through Application removal; the executor's intentional archived namespace purge follows afterward. If a Namespace/PVC vanished during an unverified cascade, stop and investigate that loss. Do not reinterpret it as proof that protection worked. Missing goals are resumable only as executor idempotence, not retrospective evidence that the pre-archive gates passed. Ambiguous legacy namespaces remain protected rather than borrowing an unrelated archive path.

## Version-1 plan

Create a metadata-only JSON source file at `scripts/retirements/<run>.json`. `<run>` must start with a lowercase letter or digit and contain only lowercase letters, digits, and hyphens. All top-level collections, including `retired_workloads`, are required; use empty arrays for unused scopes. Earlier version-1 plans without that field now fail closed. Unknown fields, duplicate JSON keys, extra action fields, and duplicate namespace/PV/claim/workload goals are rejected.

The following illustrates field names only. Replace every example identity using the parent's exact runtime inventory; never use the example as a live plan.

```json
{
  "version": 1,
  "reason": "Exact owner instruction and the explicitly authorized no-backup scope",
  "namespaces": [
    {
      "name": "retired-app",
      "uid": "namespace-uid-from-inventory",
      "archived_path": "archived/apps/retired-app"
    }
  ],
  "retired_workloads": [
    {
      "kind": "StatefulSet",
      "namespace": "retired-app",
      "name": "weaviate",
      "uid": "statefulset-uid-from-inventory"
    }
  ],
  "volumes": [
    {
      "name": "pv-name-from-inventory",
      "uid": "pv-uid-from-inventory",
      "claim_namespace": "retired-app",
      "claim_name": "data",
      "claim_uid": "pvc-uid-from-inventory",
      "driver": "rook-ceph.rbd.csi.ceph.com",
      "volume_handle": "exact-csi-volume-handle-from-inventory",
      "disposition": "archived"
    },
    {
      "name": "orphan-pv-name-from-inventory",
      "uid": "orphan-pv-uid-from-inventory",
      "claim_namespace": "deleted-unarchived-app",
      "claim_name": "data",
      "claim_uid": "orphan-pvc-uid-from-inventory",
      "driver": "rook-ceph.rbd.csi.ceph.com",
      "volume_handle": "exact-orphan-csi-volume-handle-from-inventory",
      "disposition": "deleted-unarchived"
    }
  ],
  "historical_jobs": [
    {
      "namespace": "renovate",
      "name": "renovate-29837640",
      "uid": "historical-job-uid-from-inventory",
      "cronjob_name": "renovate",
      "cronjob_uid": "cronjob-uid-from-inventory",
      "cronjob_timezone": "America/Chicago",
      "disposition": "owner-closed-historical"
    }
  ]
}
```

`archived_path` must identify a committed directory below `archived/`. The namespace must match that directory's basename or its explicit, unambiguous top-level `Chart.yaml` name. For example, `archived/apps/OLDsteam-headless/Chart.yaml` declares `name: steam-headless`, so that archive can identify namespace `steam-headless`. A dependency chart name or commented name does not grant an alias. Any active basename, alias, or release namespace still overrides retirement eligibility. Never map an ambiguous legacy namespace such as backlog-companion to an unrelated archive to bypass its active backlog replacement.

`archived` volumes must belong to an explicit namespace goal. `deleted-unarchived` volumes must not belong to a namespace goal; the executor never deletes those namespaces. `claim_uid` is required even when a claim has already disappeared. The parent must enumerate every non-NFS PV whose `claimRef.namespace` targets a planned namespace, including Released PVs whose PVCs are gone. An omitted PV, unknown backend, or NFS ownership blocks the whole namespace deletion. UIDs and volume handles are public object metadata, not authentication tokens. Do not include credentials, private values, or resource dumps in the plan.

Each `retired_workloads` entry has exactly `kind`, `namespace`, `name`, and `uid`. Allowed kinds are `Pod`, `Deployment`, `StatefulSet`, `DaemonSet`, `ReplicaSet`, `ReplicationController`, `Job`, and `CronJob`, using their actual core `v1`, `apps/v1`, or `batch/v1` APIs. The namespace must be an explicit archived namespace goal. Every present workload must match an explicit planned UID or have a valid, same-namespace controlling ownerReference chain through known objects to an explicitly planned controller. A planned Pod authorizes only itself, not descendants. Replacement UIDs, unknown/missing owners, ambiguous owners, cycles, and foreign unlabeled consumers block all writes. Known active labels or active source ownership override explicit retirement entries. This supports affirmative capture of legacy code/Weaviate controllers; it does not infer retirement from missing labels.

Every historical Job goal additionally requires `cronjob_timezone`, an available IANA timezone name. If the CronJob declares `spec.timeZone`, the plan must match it exactly. If that field is absent, the parent must verify the controller's effective timezone on the masters and record that verified value in the committed plan. For the actual `0 9 * * *` Renovate schedule with no explicit timezone, capture the verified `America/Chicago`; do not infer it from this workstation or silently default to UTC. Missing/unknown timezones and unsupported cron expressions refuse execution.

## Run after the parent completes the source and GitOps gates

The executor accepts only the canonical checkout `/Users/chris/Documents/Github/homelab`, branch `master`, and origin `git@git.eaglepass.io:ops/homelab.git`. The parent supplies an already-approved `GIT_SSH_COMMAND` through the process environment. The executor neither enrolls host keys nor chooses an alternate Git transport.

For a committed plan named `owner-retirement.json`:

```sh
python3 scripts/retire-workloads.py scripts/retirements/owner-retirement.json
python3 scripts/retire-workloads.py scripts/retirements/owner-retirement.json --apply
```

Both modes require tracked, clean, byte-identical HEAD copies of the executor, its tests/documentation, `metal/scripts/ssh-trust.py`, `system/argocd/values.yaml`, `.agent/rules/foundational-rules.md`, and the exact plan. The parent must commit the canonical policy rewrite with its correct synchronization metadata before execution. `AGENTS.md` is not part of this clean-file gate; unrelated dirty files remain outside the authorized source scope. `git ls-remote origin refs/heads/master` must match local HEAD. No fetch, commit, push, forge API, Git configuration change, or working-tree write is performed. Unrelated changes do not authorize destruction; uncommitted active chart directories and their source additionally protect resources.

Each source gate reads a fresh HEAD inventory with exact blob byte lengths and batches committed active YAML/text plus archived Chart metadata into `git show` calls of at most 64 blobs. Batched output is split by those lengths, including empty files and files without trailing newlines. Worktree active charts are reread, and HEAD is checked again after inspection. No source cache survives the gate or hides a changed HEAD.

The executor imports `API.establish`, `API.run`, and `API.json` from `metal/scripts/ssh-trust.py` using `importlib`. It never invokes enrollment or trust publication. That API verifies the canonical kubeconfig, exact API VIP, CA-backed TLS, authentication, and client/server version skew. Processes and Kubernetes requests are bounded to 20 seconds. Existing PyYAML is needed by the imported helper; no package installation occurs.

The parent process must also supply an existing absolute `TMPDIR` directory and an absolute non-symlink `KUBECACHEDIR` path through its approved process-local routing. The executor creates that cache directory if missing and passes it explicitly as kubectl's `--cache-dir` before establishing API identity. The metadata transport uses normal `tempfile` storage under that `TMPDIR`; it does not choose an internal fallback or embed a personal volume path. The metadata proxy inherits the explicit cache flag. Check mode makes no Kubernetes or Git mutations.

## Preflight and owning-controller deletion

Every prerequisite is evaluated before the first mutation and refreshed before each subsequent mutation:

- Discover direct-child active charts in `system/`, `platform/`, and `apps/` from HEAD and the worktree. Protect matching basenames, archive aliases, literal release namespaces, direct namespace dependencies, exact PV/handle source references, and active Helm/Argo ownership metadata. Active replacements such as backlog, nibble, and omni-tools stay protected automatically.
- Namespace source checks use anchored literal YAML `namespace`/`releaseNamespace` fields and service FQDNs such as `weaviate.code.svc` or `weaviate.code.svc.cluster.local`. Short `service.namespace` forms are also checked in endpoint-like YAML keys such as `DATABASE_HOST`, `DB_HOST`, `URL`, `endpoint`, and `dbHost`, including URL schemes and ports. Pure YAML parsing also checks native `env: [{name: DATABASE_HOST, value: db.old-app}]` and app-template `env: {DATABASE_HOST: {value: db.old-app}}`. Raw Helm uses a narrowly bounded literal-env fallback, not a general template evaluator. Already collected live Pod/controller templates are checked structurally for literal endpoint env values as well. Ordinary env names, prose, generic code words, Secret/valueFrom references, and policy-only permissions do not become literal short-name consumers. Env values are never printed or fetched from Secrets. Full-line YAML comments and policy-only egress blocks remain excluded; exact PV/handle checks remain enforced.
- Refuse any live Argo Application targeting a storage or namespace scope. A deletion timestamp does not make an Application absent.
- Check namespace, PV, PVC, claimRef, and Job identities. Absence is resumable; a replacement UID is a blocker. A query failure or malformed response is never interpreted as absence.
- Affirmatively validate all retired workload UIDs/owner chains. Active ownership always blocks, even when the object appears in the plan.
- Require every PVC in a retired namespace to map to an explicit PV and exact claim UID. Require every non-NFS PV with a matching `claimRef.namespace` to appear explicitly in the volume plan, even when Released or missing its former PVC. An unplanned, pending, unknown, or protected NFS claim/PV blocks namespace deletion. NFS PV ownership and inline NFS mounts also block the namespace, even when a former claim has disappeared.
- Protect native `spec.nfs`, storage class `nfs-rwx`, and CSI drivers containing `nfs`. Only exact driver `rook-ceph.rbd.csi.ceph.com` with `standard-rwo` supports data-erasing execution. Unknown backends block; names do not imply backend identity.
- Refuse duplicate backend `volumeHandle` references and resolved physical RBD aliases, another PVC pointing at the PV, inline CSI aliases, active chart ownership, and orphan Pod/controller claim references. Generic ephemeral Pod claims and live PVC owners are consumers too. StatefulSet claim templates protect future consumers even with zero replicas. Orphan VolumeAttachments block unretained deletion. Inline NFS and unsupported inline CSI effects in a retired namespace block its deletion rather than authorizing unplanned backend cleanup.
- Preserve deleted-but-not-archived PV/PVC storage carrying `Retain`, Helm `keep`, Argo `Prune=false`, `Delete=false`, confirmation options, or true-like retain/persist/keep/protect metadata. Default PVC-protection finalizers are not retention flags. Archived keep/Retain storage may be purged only after exclusive retired ownership and non-NFS checks pass.
- Apply the metadata-only namespace deletion-effect inventory and Renovate current-run checks described below before the first write and on refreshed preflights.

### Namespace deletion-effect inventory

Metadata inventory uses **server-side PartialObjectMetadata**, not client-side JSONPath projection. A private `kubectl proxy` reads credentials directly from the original canonical kubeconfig and uses the explicit API VIP. Python never extracts TLS keys, writes credential files, or installs a Kubernetes client. The proxy binds only relative Unix socket `s` in its own `0700` temporary directory; the socket is checked as an owned Unix socket and changed to `0600`. It has no TCP listener. Its mutating methods are rejected; the Python transport issues GET only. Proxy stdin/stdout/stderr use DEVNULL. Finally cleanup terminates/reaps only the child proxy this invocation owns, then removes its private scratch directory. This is not an OS sandbox.

The AF_UNIX HTTP connection briefly changes directory only for `connect("s")`, restoring the previous directory by file descriptor even on failure. This single-threaded CLI avoids macOS's short Unix-socket address limit without changing global paths. Git still uses canonical `-C` and the existing helper uses canonical cwd. Startup and each complete metadata GET, including response headers/body, have **20-second** bounds; shutdown waits are separately bounded. There is no overall task deadline.

Public discovery GETs use `/api/v1`, `/apis`, and each group's preferred-version APIResourceList. Only namespaced resources with both `list` and `delete` verbs are registered. Subresources containing `/` and read-only virtual metrics are excluded. Public discovery structure may be cached for the process, but every resource metadata list is fetched fresh on every preflight. Each request uses `limit=500` and follows `metadata.continue` until empty. Repeated tokens, query errors, and HTTP 406 fail truthfully without a full-object fallback.

Every list request uses the exact Accept header `application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1`. Kubernetes 1.33 rejects the singular representation for a collection. Responses must be `meta.k8s.io/v1` PartialObjectMetadataList envelopes with metadata-only items. Full-object responses or unexpected fields are refused. The client immediately selects only original resource API/kind from discovery plus namespace, name, and UID. Labels, annotations, managedFields, and other metadata are neither persisted nor logged; annotations may themselves contain private material. Full Secrets and unknown CRD specs are never requested by this inventory. Failures, missing metadata, duplicate identities, or disagreement with checked PVC/workload UIDs block deletion. Valid unknown objects outside planned namespaces are ignored by the deletion-effect gate.

The exact permitted API/kind pairs are:

| API version | Kinds |
| --- | --- |
| `v1` | Pod, ReplicationController, PersistentVolumeClaim, ConfigMap, Secret, Service, Endpoints, ServiceAccount, Event, LimitRange, ResourceQuota |
| `apps/v1` | Deployment, StatefulSet, DaemonSet, ReplicaSet, ControllerRevision |
| `batch/v1` | Job, CronJob |
| `networking.k8s.io/v1` | Ingress, NetworkPolicy |
| `discovery.k8s.io/v1` | EndpointSlice |
| `events.k8s.io/v1` | Event |
| `cert-manager.io/v1` | Certificate, CertificateRequest, Issuer |
| `acme.cert-manager.io/v1` | Order, Challenge |
| `cilium.io/v2` | CiliumEndpoint |

Workloads and PVCs additionally require their full preflight identity/ownership/storage checks. Every other kind/API version is refused inside a planned namespace, including VolumeSnapshot, PushSecret, ObjectBucket/ObjectBucketClaim, operator resources, and RBAC resources. These require separate owner-governed investigation; this executor does not add generic cleanup actions. The entire metadata inventory finishes before any write and is refreshed before each Namespace DELETE. Public receipts report a checked-object count, never raw object data.

### Physical RBD identity

Collect cluster-scoped StorageClasses alongside PVs. Compare `(clusterID, pool, imageName)`, not only `volumeHandle`. An explicit CSI `volumeAttributes.imageName` requires explicit `clusterID` and `pool`. For default dynamic `standard-rwo` only, a handle of the form `0001-<four-hex-cluster-length>-<cluster>-<16-hex-pool-id>-<uuid>` may resolve to `csi-vol-<uuid>` only when the embedded cluster agrees with `clusterID`, the pool is present, the StorageClass provisioner matches the CSI driver, and StorageClass cluster/pool parameters agree. Any prefix parameter, static/custom ambiguity, or unsupported RBD namespace prevents derivation.

Every other potential RBD PV must resolve before an existing planned RBD backend may be purged. All candidates must use the same CSI `clusterID` as the planned target. Different IDs might name configurations for the same Ceph cluster; they do **not** prove physical disjointness and therefore block execution, even when pools/images differ. Within that one supported ID, another PV with the same pool/image blocks even when its handle differs. Native/static/custom RBD objects with missing identity metadata fail closed. Inline CSI handles and physical attributes use the same checks, including refusal of a different clusterID. No multi-cluster resolver or direct RBD command is added. The parent records exact image IDs before the handoff and independently proves image absence read-only after CSI cleanup.

### Historical Renovate closeout

Require exact Job/CronJob UIDs, the terminal Failed historical Job with its exact controlling CronJob owner, and a newer healthy Completed Job corroborating `lastSuccessfulTime` within **36 hours**. Also require `lastScheduleTime` within 36 hours and a completed or healthy recent newer Job representing that schedule. Prefer the Job's `batch.kubernetes.io/cronjob-scheduled-timestamp`; otherwise use creation time. Creation must follow that schedule within two minutes. An old successful run does not cover missing or unhealthy current work.

Only a fixed daily `minute hour * * *` expression is supported. Use the committed `cronjob_timezone` with stdlib `zoneinfo` to compute the latest due occurrence, allowing **five minutes** of scheduling grace. `lastScheduleTime` must cover that occurrence and match the fixed local minute/hour. A missed daily run blocks closure even when the previous success is less than 36 hours old. Unsupported expressions, a mismatch with explicit `spec.timeZone`, unavailable timezone data, or a workstation-local fallback are refused. DST spring gaps skip nonexistent local occurrences; fall-back folds consider both real occurrences. The parent must verify controller timezone authority before committing an absent-timeZone plan.

Reject newer Failed/FailureTarget Jobs, unsucceeded Jobs with `status.failed > 0`, failed/unknown Pods, unschedulable Pods, container retries, nonzero current/last exit codes, and unhealthy waiting reasons. Only ContainerCreating/PodInitializing are benign waiting reasons. Corroborate Pods through exact controlling Job owner UIDs/names. A current unsucceeded run must be at most **30 minutes** old, have the reported active Pods, and show ready running containers or bounded benign initialization. This is an expected Renovate execution window, not an overall task deadline. Missing active Pod evidence or an unverified CronJob active reference blocks closeout. Other Jobs, Pods, the CronJob, and unrelated failures are never targeted by the historical Job action.

On resume after the historical Job is absent, its creation time is unavailable. The corroborated successful run supplies the historical floor, while recent unfinished/failed work and older still-active work remain subject to the current-run checks. Closeout receipts still say `owner-closed-historical`, never root-cause repaired.

Namespace and individual orphan PVC deletions use raw Kubernetes DELETE with UID **and** resourceVersion preconditions. No unconditional delete-by-name is used. Namespace deletion allows Kubernetes PVC protection and CSI lifecycle handling to complete. After namespace/claim absence and CSI detach, an archived Retain RBD PV receives a JSON Patch testing UID, resourceVersion, CSI driver, volume handle, storage class, and old policy before replacing only its reclaim policy with `Delete`.

CSI and the owning storage controllers reclaim the backend. The executor does not issue RBD commands, edit data files, delete PVs directly, remove finalizers, or force deletion. A Delete-policy PV that its owning controllers do not reclaim remains a blocker; this includes an Available PV that never enters the controller's deletion path. Inspect and repair the owning desired state separately rather than bypassing CSI.

Read-only polls allow 600 seconds per namespace or PV/claim/detach sequence; the historical Job also gets a 600-second absence wait. There is no overall task deadline. A write error triggers an exact UID GET and stops, even if the write may have succeeded. There are no blind write retries. Resume by checking the same committed plan, then selecting `--apply` again. New UIDs, changed protection decisions, changed HEAD, stale resourceVersion conflicts, failed queries, missing input, or unresolved attachments stop execution truthfully.

Final verification requires planned namespaces, PVCs, PVs, attachments, and the historical Job to be absent, except explicitly protected storage skips whose identities/presence must remain. JSON receipts contain public names, UIDs, revision, skipped PVs, and requested/verified outcomes. They never contain resource dumps, environment values, or credentials. Receipts do not claim physical bytes reclaimed from requested capacity and do not certify all six homelab layers GREEN. The parent separately owns read-only backend image-absence proof against its recorded exact image IDs after CSI cleanup, plus full health and application-behavior verification. The executor never invokes direct RBD deletion or adds generic cross-namespace RBAC cleanup.

These checks are conservative and can block on a literal source reference that needs operator investigation. They are not a cluster-wide transaction: the parent must prevent concurrent source changes, new consumers, and competing retirement writers during execution. UID/resourceVersion preconditions protect each target write; they cannot atomically lock every other Kubernetes resource.

## Parent plan-generation helpers

Version-1 plans require `retired_workloads` and each historical Job goal now additionally requires `cronjob_timezone`. `source_gate()` retains its `archive_aliases`, `head`, `active`, `directories`, and `texts` fields. Archive aliases remain derived from committed Chart metadata, not an extra JSON plan field.

`namespace_references(text)` handles flat/native/wrapped source env; `env_references(spec)` checks live literal env structures. `metadata_api(api)` is a context manager around an already established existing API. It yields `MetadataAPI`, forwarding the existing `run`/`json`/cluster identity interface while adding `metadata_resources()` and `metadata_list(resource)`. Resource descriptors contain exactly `resource`, original `apiVersion`, original `kind`, and registered `path`; lists return only sanitized identities. `namespace_metadata(api)` consumes those two methods, with no kubectl projection fallback. Core fake APIs implement the same methods without starting a proxy.

`workload_objects(snapshot)`, `retired_ownership(plan, snapshot, active)`, `rbd_identity(pv, storageclasses)`, and Git batching helpers retain their capture contracts. StorageClasses remain indexed under `storageclasses.storage.k8s.io` by `("", name)`. `latest_daily_due(schedule, timezone_name, now)` exposes the fixed-daily, five-minute-grace UTC occurrence for isolated checks. All live access still requires the executor's operating gates; these helpers do not grant mutation authority.

## Source tests

After the parent establishes its required external test routing, run:

```sh
python3 -B -m unittest discover -s scripts -p test_retire_workloads.py -v
```

Tests use pure functions and closed fakes. Real API construction, subprocesses, and sockets are patched to fail. Transport-specific checks replace connections, process lifecycle, temporary-directory creation, and filesystem operations with mocks; they never start the real proxy. Regressions cover native/wrapped/live env, server-side Accept/406/no-fallback/pagination/sanitization, relative UDS restoration/cleanup, clusterID ambiguity, and daily timezone/grace/DST behavior. No personal storage-policy paths are embedded in this repository.
