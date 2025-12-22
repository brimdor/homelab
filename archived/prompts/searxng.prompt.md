---
mode: agent
---
Initial Prompt to the AI implementing the plan for "searxng"

You will autonomously create or update a bjw-s-convention Helm chart for the app "searxng" using only the information below. Do not ask questions. Do not edit anything under /home/coder/homelab/plan_create. Do not propose any directory structure. Perform all steps and log actions and tests as specified.

Chart Type and justification (decision logic only):
- bjw-s Chart — An existing Helm chart exists but alignment to homelab conventions is not guaranteed.

Authoritative references:
- Application entry: /home/coder/homelab/plan_create/projects.yaml -> "Searxng"
- Chart files path to use: /home/coder/homelab/apps/searxng
- bjw-s references:
  - Repo root: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
  - Baseline values: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
  - Baseline schema: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- Helm best practices:
  - https://helm.sh/docs/topics/charts/
  - https://helm.sh/docs/chart_best_practices/

Autonomous tasks to perform:
1) Implement a bjw-s style chart at /home/coder/homelab/apps/searxng:
   - Controller/container names: "main".
   - If a PVC is created, its name must be "data".
   - Use upstream image (configurable): repository "searxng/searxng"; tag configurable; pullPolicy configurable.
2) Configure values.yaml with the following fields (make all configurable and schema-validated):
   - image: repository, tag, pullPolicy.
   - service: enabled (default true), type (ClusterIP default), ports.http (default 8080), annotations.
   - ingress (networking.k8s.io/v1): enabled (default true), className, annotations, hosts[0].host default "searxng.eaglepass.io", hosts[0].paths[0] { path "/", pathType "Prefix" }, tls { enabled, secretName }.
   - env: support both non-sensitive literals (e.g., INSTANCE_NAME, BASE_URL, SEARCH_DEFAULT_LANGUAGE) and sensitive keys via valueFrom.secretKeyRef.
   - envFromSecret: name "secrets".
   - config: configMap-backed non-sensitive settings (e.g., settingsYaml multi-line string).
   - persistence: enabled (default false), existingClaim, storageClass, accessModes, size; first PVC named "data".
   - backups: enabled (default false), schedule default "*/15 * * * *", retentionDays default 7, nfs.server "10.0.40.3", nfs.path default "/exports/backups/searxng"; configure CronJob only when persistence.enabled is true.
   - resources, probes, podAnnotations/podLabels, securityContext, nodeSelector, tolerations, affinity.
3) Secrets via 1Password Operator (no hardcoded secrets):
   - Create/expect a Kubernetes Secret named "secrets" annotated exactly with:
     - operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
     - operator.1password.io/item-name: "secrets"
   - In values/env wiring, reference sensitive envs via:
     - valueFrom.secretKeyRef: { name: "secrets", key: "<lowercase-hyphenated-key>" }
   - Example key mappings:
     - SECRET_KEY -> secret-key
     - GOOGLE_API_KEY -> google-api-key
     - BING_API_KEY -> bing-api-key
   - Create a helper script based on /home/coder/homelab/tools/example-op-create.sh:
     - Write to /home/coder/homelab/tools/searxng-op-create.sh
     - 1Password item category: "Database"
     - No secrets are committed; the Operator populates the K8s Secret.
4) Service:
   - Implement a values-driven Service exposing HTTP internally on the configured port.
5) Ingress:
   - Implement a values-driven v1 Ingress for external access to eaglepass.io (default host searxng.eaglepass.io; fully configurable).
   - Ensure annotations and TLS are values-driven.
6) ConfigMaps:
   - Render non-sensitive configuration (e.g., settings.yaml) from values.config.settingsYaml as a ConfigMap mounted/consumed by the container.
7) Persistence (optional):
   - Default disabled. If enabled, create a PVC named "data" using configurable size/accessModes/storageClass/existingClaim.
8) Backups (optional; only if persistence.enabled):
   - Create an NFS-based CronJob using server 10.0.40.3 and a configurable path defaulting to /exports/backups/searxng.
   - Schedule default every 15 minutes; retentionDays default 7.
9) Image usage:
   - Use existing upstream image (no Dockerfile; do not run build_push.sh).
10) Logging (mandatory):
   - Append clear action notes to /home/coder/homelab/reports/searxng/action-log.txt for each step (chart creation, values fields added, secret wiring, tests).
   - Store test artifacts under /home/coder/homelab/reports/searxng/tests/.
11) Tests (record outputs under reports paths):
   - Helm lint/schema validation shows no errors.
   - After deploy, Service responds on the configured port.
   - Ingress returns HTTP 200 on "/" for the configured host.
   - Verify sensitive envs are present in the pod via secretKeyRef, and no secrets exist in values.yaml/ConfigMaps.
12) Constraints:
   - Do not modify anything under /home/coder/homelab/plan_create.
   - Do not propose or create new directories beyond what is necessary for the chart path cited above.
   - No code artifacts should be included in this prompt’s output; implement everything directly in the repo as described.

Execute autonomously and complete all tasks above. Log every action and test artifact to the specified reports