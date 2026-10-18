# Retire the legacy Argo Dex objects

Maintenance #103's old `argocd/argocd-dex-server` is absent from the current chart.
The idle Argo v2.11.2 wrapper remains in a Dex v2.38.0 image. This retirement does
not enable SSO, change platform Dex, delete the namespace, or alter shared secrets.

`scripts/retire-legacy-argocd-dex.py` contains the exact five-UID retirement plan:
Deployment, Service, ServiceAccount, Role and RoleBinding. It directly submits
Kubernetes DELETE requests with both UID and resourceVersion preconditions.
ReplicaSet, Pod, CiliumEndpoint and EndpointSlice disappear only through proven
owner references. No other deletion path exists. The archived-namespace gate in
`retire-workloads.py` remains unchanged; only its read-only metadata transport is reused.

## Preparation and checks

Use the canonical checkout, compatible kubectl, PyYAML and Argo CD CLI. Supply
existing process-local `TMPDIR` and `KUBECACHEDIR` directories for scratch/cache.
The original repository kubeconfig is unchanged. The existing operator profile
`~/.config/homelab/argocd-core.kubeconfig` must verify the same API and support
authenticated core-mode Argo reads. Never copy credentials into evidence.

```sh
python3 -B scripts/test_retire_legacy_argocd_dex.py
python3 -B scripts/retire-legacy-argocd-dex.py
```

The default check may inspect local uncommitted executor changes, but identifies
them as not apply-eligible. HEAD must already equal canonical Gitea master. Before
execution, review, commit and push the executor, tests, runbook and governing
desired state. All scoped source must be clean and byte-identical to HEAD.

```sh
# Only the authorized parent/operator executes this after review and push.
python3 -B scripts/retire-legacy-argocd-dex.py --apply
```

Before each DELETE the executor repeats source, exact render, Argo health, SSO,
consumer, ownership and protected-state checks. While the legacy Pod exists it
requires an explicit idle log, an `argocd-dex` process but no `dex` process, and
both IPv4/IPv6 TCP tables showing no listener on 5556, 5557 or 5558. Logs, process
arguments, environments, auth state and Secret values are never emitted. Secret
inventory uses API metadata negotiation, with no full-object fallback.

All active Argo resources, namespace identity, RBAC/configuration, Secret metadata
and every PV/PVC identity/spec are compared. Existing optional disabled-Dex server
wiring is permitted; `argocd-dex-server-tls` remains protected because the active
server references it. New consumers, SSO configuration, UID replacement, opaque
evidence failures or concurrent protected changes stop execution.

Each submitted DELETE is observed for at most 180 seconds, including dependent
garbage collection. There is no overall maintenance deadline. Failed/uncertain
writes and stalled deletion are never retried, forced, or repaired by removing
finalizers. A finally check rechecks protected state and authenticated core health.
Partial execution requires investigation and a separately reviewed continuation;
the initial check requires all five original objects and their descendants.

## Limits and rollback

Core-mode authentication proves authorized Kubernetes-backed Argo access, not an
interactive browser/local-account login. Secret contents, external hard-coded
clients and opaque application data are not consumer-inspected. Keep these limits
in the parent maintenance record. Whole-cluster health and real application
acceptance remain separate gates; this tool never declares maintenance complete.

Recreating reviewed stateless manifests through GitOps can restore service if
needed, but cannot restore deleted Kubernetes UIDs. Do not enable the chart's Dex
component or roll back shared secrets/configuration merely to undo retirement.
Retain sanitized identity/results evidence. Do not retain authentication payloads.
