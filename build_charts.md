# build_charts.md

This document provides complete, reliable instructions for an average AI model to generate **exactly two files** for a given open-source application sourced from GitHub, ready to deploy immediately in the homelab:

- `apps/<app-name>/Chart.yaml`
- `apps/<app-name>/values.yaml`

The model must **sub-chart** either the application’s **official Helm chart** (preferred, when current and well-maintained) **or** the **bjw-s common** chart. No other files are permitted.

---

## Reference URLs (authoritative lookups & latest versions)

- **bjw-s Helm Charts (common library & releases):** https://github.com/bjw-s-labs/helm-charts  
  - Common chart values: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml  
  - Common chart schema: https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/common  
- **ArtifactHub (official/app charts discovery):** https://artifacthub.io/  
- **1Password Kubernetes Operator:** https://github.com/1Password/onepassword-operator  
- **Helm Chart dependencies (syntax & lock):** https://helm.sh/docs/topics/charts/#chart-dependencies  
- **Kubernetes Ingress (spec & keys):** https://kubernetes.io/docs/concepts/services-networking/ingress/  

Use these URLs to confirm **current versions**, valid **values keys**, and **schema expectations** before finalizing output.

---

## Inputs (Provided to the Model)

- **App (official name)**
- **Repo (GitHub URL)**

The model derives everything else from this document and the app’s repository.

---

## Produce only (Required Output)

Generate **exactly** these files and nothing else:

- `apps/<app-name>/Chart.yaml`
- `apps/<app-name>/values.yaml`

Both must be fully valid YAML, with no placeholders and deployment-ready.

---

## Repository & Naming Conventions

- `<app-name>` is derived from the official app name: **lowercase**, **single word or hyphenated** (e.g., `photo-view`, `nextcloud`).
- Path structure is always `apps/<app-name>/Chart.yaml` and `apps/<app-name>/values.yaml`.
- External-facing apps must use the host **`<app-name>.eaglepass.io`**.

---

## Source Selection Algorithm

1. **Discover official chart**
   - Search the app’s docs, GitHub, and **ArtifactHub** (https://artifacthub.io/).
   - If a current, reputable **official (or primary)** chart exists → **use it** as a dependency in `Chart.yaml`.
2. **Otherwise use bjw-s common**
   - Depend on **bjw-s common** library chart (https://github.com/bjw-s-labs/helm-charts) to define the workload via values.

> The chosen source dictates the valid keys and structure in `values.yaml`. Always conform to the selected chart’s schema (consult the chart’s README/values on ArtifactHub or GitHub).

---

## Secrets, Environment, and 1Password Operator (Mandatory)

- **All sensitive values are sourced via 1Password Operator** (https://github.com/1Password/onepassword-operator). Never commit secrets in plain text.

### 1) Pod Annotations (controller/pod template)
Add **both** annotations exactly in this format (replace IDs with real values):
```
annotations:
  operator.1password.io/item-path: "vaults/<vaultID>/items/<itemID>"
  operator.1password.io/item-name: "secrets"
```

### 2) Environment Variables
- **Sensitive env** must reference the `secrets` Secret (keys match 1Password item field names):
```
env:
  <ENV_VAR>:
    valueFrom:
      secretKeyRef:
        name: "secrets"
        key: "<key-name>"
```
- **Non-secret env** (e.g., `TZ`, `PUID`, `PGID`) may be literal values.

> Ensure every required configuration/env the app needs is present—derived from docs and any `docker-compose` in the repo.

---

## Storage Configuration

Choose per application need (one or both):

### A) Long-term / large data → NFS
Use when data must persist on NAS or be shared across nodes.
```
nfs:
  type: nfs
  server: 10.0.50.3
  path: /mnt/user/<app-name>
  advancedMounts:
    main:
      main:
        - path: /path/inside/container
```

### B) Fast local read/write → PVC
Use for smaller state/config, caches, or when default StorageClass is sufficient.
```
data:  # single-word key describing the data
  accessMode: ReadWriteOnce
  size: <size>Gi
  advancedMounts:
    <controller-name>:
      <container-name>:
        - path: /path/inside/container
```

**bjw-s rule:** the **first PVC key must be `data`**. Use `advancedMounts` (or `mountPath` if supported) to align with the container’s expected paths.

---

## Ingress (External Access)

- Enable only for web UI/API apps.
- Host **must** be `**<app-name>.eaglepass.io**`.
- Configure:
  - `ingressClassName` (e.g., `nginx`) or equivalent chart annotation.
  - Path `/` with `Prefix` (unless app requires sub-path).
  - TLS per cluster policy (e.g., cert-manager) if applicable.

> Official charts and bjw-s common have different keys—use the correct schema for ingress. See Kubernetes Ingress spec: https://kubernetes.io/docs/concepts/services-networking/ingress/

---

## Services & Ports

- Map service ports to the container’s listening ports.
- Prefer `ClusterIP` and expose externally via Ingress.
- Confirm health probes align with the app’s endpoints when the chart supports them.

---

## Official Chart Workflow

1. **Chart.yaml**
   - Add a dependency with `name`, `repository`, and a **specific** `version` of the official chart (follow Helm deps: https://helm.sh/docs/topics/charts/#chart-dependencies).
2. **values.yaml**
   - Configure **only** keys that exist in that chart’s values schema (image, env, service, ingress, persistence).
   - For secrets, prefer native `existingSecret`/secretRef fields if provided; otherwise use pod annotations plus `secretKeyRef` pattern.
   - Disable bundled extras (e.g., embedded DB) if not required.

> Always validate keys against the official chart’s current documentation (ArtifactHub → chart page → README/values).

---

## bjw-s Common Workflow

- The first **controller**, **container**, and **service** must be named **`main`**.
- The first **PVC** must be named **`data`**.
- Typical sections to set:
  - `controllers.main` (image, env, pod annotations, replicas)
  - `service.main` (ports, type)
  - `ingress.main` (host, paths, class, TLS)
  - `persistence.data` (NFS or PVC)

Consult bjw-s common values/schema for valid keys:  
- Values: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml  
- Schema: https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/common

**Derive from the repo:** use docs and `docker-compose` to determine image, env, ports, and mounts. Translate compose volumes/env to Helm values.

---

## Docker-Compose Translation Guidance (when present)

- **services.*.image** → container image repository:tag  
- **environment:**  
  - Non-secret → literal env  
  - Secret → `secretKeyRef`  
- **ports:** → service port(s) and targetPort  
- **volumes:** → `persistence` entries + `advancedMounts` to correct in-container paths

---

## Validation Checklist (Must Pass)

1. **Exactly two files** exist and are produced:  
   - `apps/<app-name>/Chart.yaml`  
   - `apps/<app-name>/values.yaml`
2. **Chart name** equals `<app-name>` (lowercase, hyphenated if needed). `apiVersion: v2`, `type: application`, sensible `version` (e.g., `0.1.0`).
3. **Dependency chosen correctly**: official chart (with explicit version) **or** bjw-s common library (current, appropriate version).
4. **Secrets:** 1Password annotations present; **all sensitive env** use `secretKeyRef` to `secrets`; key names match 1Password fields.
5. **Storage:** NFS and/or PVC configured to match the app’s documented data paths; **`data`** is the first PVC (bjw-s).
6. **Ingress:** enabled only when applicable; host set to `<app-name>.eaglepass.io`; class and TLS configured per cluster.
7. **Service/ports:** container listen ports mapped correctly; probes valid if used.
8. **Schema correctness:** every key in `values.yaml` exists in the selected chart’s schema; **no invalid keys**.
9. **No placeholders remain** (IDs, keys, paths, versions, hosts all resolved).
10. **Immediate deployability:** files pass `helm lint` and `helm template` (render sanity) using provided values.

---

## Output Rules

- Output only the two final files’ contents as complete YAML.  
- Do **not** print secrets; only references.  
- Do **not** include templates, examples, or extra files.  
- Keep comments minimal and strictly useful to deployment/maintenance.
