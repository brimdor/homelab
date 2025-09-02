# Weaviate (Sub-Chart Wrapper)

This folder provides a minimal Helm sub-chart that wraps the official Weaviate chart. It pins the upstream dependency and exposes homelab-focused overrides in `values.yaml`.

- Upstream chart repository: https://weaviate.github.io/weaviate-helm
- Upstream source: https://github.com/weaviate/weaviate-helm
- Weaviate docs:
  - https://docs.weaviate.io/academy/deployment/k8s/setup_weaviate
  - https://docs.weaviate.io/deploy/installation-guides/k8s-installation

## What this chart contains

- `Chart.yaml` with a dependency on the upstream `weaviate` chart (Helm 3)
- `values.yaml` containing only overrides relevant to homelab usage
- No templates. Rendering is delegated to upstream.

## Version pinning

`Chart.yaml` pins upstream `weaviate` chart to version `17.5.1` (appVersion `1.32.3`). Update the dependency when you wish to upgrade upstream.

To update locally:
- Edit `apps/weaviate/Chart.yaml` and bump `dependencies[0].version`
- Run `helm dependency update ./apps/weaviate`

## Key values and conventions

- Image: Defaults to `cr.weaviate.io/semitechnologies/weaviate:1.32.3`. Avoid floating `latest` unless you opt-in.
- Persistence: Set under `upstream.storage` (default `size: 10Gi`). You can set a storage class via `upstream.storage.storageClassName`.
- Ingress: This wrapper ships no Ingress templates. Use `ingress.*` here only as inputs for your umbrella/platform chart to render an Ingress. Upstream exposes a LoadBalancer Service by default; switch to `ClusterIP` at `upstream.service.type` in advanced overrides if needed.
- Resources: Empty by default; set requests/limits under `upstream.resources` as needed.
- Env: Non-sensitive env via `upstream.env`. Sensitive values should come from 1Password Operator (see below) and be referenced via `upstream.envSecrets`.
- Config: Use upstream `custom_config_map` to point Weaviate at a custom ConfigMap if you need to inject a custom conf.yaml. See upstream docs.

## 1Password Operator integration (secrets)

Do not commit secrets.

Pattern for env to consume secrets:

- In `upstream.env` add an entry:
  - name: SOME_PASSWORD
    valueFrom:
      secretKeyRef:
        name: secrets
        key: some-password

- Ensure your workload receives the 1Password Operator annotations (on Pod/Deployment/StatefulSet):
  - operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  - operator.1password.io/item-name: "secrets"

- Keys in 1Password should use lowercase-hyphen format matching the `secretKeyRef.key` values (example mapping: `ROOT_PASSWORD` -> `root-password`).

### Creating the 1Password item

Use the existing helper at `tools/op-create.sh` as a reference. To create a `Database` item named `secrets` in the `Server` vault with Weaviate-related keys, run (adjust keys as needed):

- op item create --vault "Server" --category "Database" --title "secrets" --format json <<'JSON'
  { "title": "secrets", "fields": [
      {"label":"weaviate-admin-api-key","value":"<set-or-rotate>","type":"CONCEALED"},
      {"label":"weaviate-bearer-token","value":"<optional>","type":"CONCEALED"}
    ]
  }
  JSON

Replace values with real secrets through 1Password only. Then add Pod annotations pointing to this item. No secret values should appear in git.

## Backups (CronJob)

This wrapper does not ship templates. For backups, deploy a platform-level CronJob that:
- Mounts the Weaviate data PVC read-only
- Mounts an NFS volume at `nfsServer: 10.0.50.3`, `nfsPath: /path/to/backup` (change the path!)
- Tars/rsyncs data on schedule `*/15 * * * *`
- Deletes files older than `retentionDays` (default 7)

The values under `backup:` provide the required parameters, but you must wire a CronJob in your umbrella/platform to consume them.

## Upstream snapshot

- Pinned chart: weaviate 17.5.1 (Helm v3)
- Upstream appVersion: 1.32.3
- Repo index indicates recent builds around 2025-08; consult the index.yaml for exact timestamps
  https://weaviate.github.io/weaviate-helm/index.yaml

## Lint, template, and install (local checks)

- helm dependency update ./apps/weaviate
- helm lint ./apps/weaviate
- helm template weaviate-test ./apps/weaviate --namespace weaviate-test

Optional install for a smoke test (requires a cluster context):
- kubectl create namespace weaviate-test
- helm install weaviate ./apps/weaviate -n weaviate-test
- kubectl rollout status -n weaviate-test deploy/weaviate
- Port-forward or configure ingress and curl the health endpoint: /v1/.well-known/ready

## Incompatibilities and notes

- Secret name: Upstream templates might not expose a direct override for a unified secret name. Our convention uses a single secret named `secrets`. If upstream diverges, set env with `valueFrom.secretKeyRef.name: secrets` under `values.env` and ensure 1Password Operator annotations are on the Pod template.
- PVC naming: Upstream uses `weaviate-data` as the default volume claim template; if you need a specific PVC name, bind via an existing claim at the umbrella/platform layer.
- This sub-chart intentionally contains no templates; any additional wiring (ingress class defaults, backup CronJob) should be applied at umbrella/platform level.

## Images

We use the official Weaviate container image. No custom build is required.

---

Maintained for homelab use; contributions welcome.
