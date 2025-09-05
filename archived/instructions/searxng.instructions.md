---
applyTo: '**'
---
Plan/Instructions for creating the Helm Chart for app "searxng"

App name:
- searxng

Authoritative application reference:
- /home/coder/homelab/plan_create/projects.yaml
  - Application entry: "Searxng"
  - Documentation:
    - https://github.com/searxng/searxng-helm-chart
    - https://charts.searxng.org/index.yaml
  - Chart Files path:
    - /home/coder/homelab/apps/searxng

Selected Chart Type (per determination logic only):
- bjw-s Chart — There is an existing Helm chart, but alignment to homelab conventions is not guaranteed; therefore select bjw-s Chart.

bjw-s references (for conventions and options):
- Repo root: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
- Baseline values: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
- Baseline schema: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- Helm best practices:
  - Charts topics: https://helm.sh/docs/topics/charts/
  - Best practices: https://helm.sh/docs/chart_best_practices/

Required Kubernetes objects (strictly per Conditions):
- Service: Yes (internal access to the web app). Make fully configurable via values.yaml.
- Ingress: Yes (external access). Domain must support eaglepass.io and be configurable via values.yaml.
- Secrets: Yes (for SECRET_KEY and any engine API keys). Sourced exclusively via 1Password Operator. No secret literals in chart/values.
- ConfigMaps: Yes (for non-sensitive settings, e.g., settings.yml or environment config).
- PVC: Optional (default disabled). Searxng is generally stateless; offer persistence only if the operator wants to persist custom data.
- Backups: Optional (only if persistence enabled; default disabled). NFS-based CronJob when enabled.

Values.yaml configurability (reference Helm values/schema behavior for enforcement):
- image:
  - repository: default to upstream image (e.g., "searxng/searxng")
  - tag: configurable (default "latest" or a specific, known-good tag)
  - pullPolicy
- controller/container (bjw-s conventions):
  - First controller name: "main"
  - First container name: "main"
  - resources, probes (liveness/readiness/startup), securityContext, nodeSelector, tolerations, affinity
- service:
  - enabled: true
  - type: ClusterIP (default)
  - ports:
    - http: port 8080 (configurable)
  - annotations: {}
- ingress (networking.k8s.io/v1):
  - enabled: true
  - className: configurable
  - annotations: {} (configurable)
  - hosts:
    - host: "searxng.eaglepass.io" (default; must be configurable)
      - paths:
        - path: /
          pathType: Prefix
  - tls:
    - enabled: true/false
    - secretName: configurable
- env (all sensitive via valueFrom.secretKeyRef; non-sensitive via literal values):
  - Example env names (non-exhaustive; align keys and hyphenation rules below):
    - SECRET_KEY (sensitive; required by Searxng)
    - INSTANCE_NAME (non-sensitive)
    - BASE_URL (non-sensitive; e.g., https://searxng.eaglepass.io)
    - SEARCH_DEFAULT_LANGUAGE (non-sensitive)
    - Any engine API keys (sensitive), e.g., GOOGLE_API_KEY, BING_API_KEY, etc.
- envFromSecret (1Password Operator populated):
  - name: "secrets" (the Kubernetes Secret name referenced by workloads)
- config (ConfigMap-backed, non-sensitive):
  - settingsYaml: multi-line string for searxng settings.yml content (non-sensitive portions only)
- persistence (PVC):
  - enabled: false (default)
  - existingClaim: optional
  - accessModes: [ReadWriteOnce] (configurable)
  - storageClass: configurable
  - size: "1Gi" (configurable)
  - First PVC name must be "data" (bjw-s convention)
- backups (CronJob; only applicable when persistence.enabled):
  - enabled: false (default)
  - schedule: "*/15 * * * *" (default, configurable)
  - retentionDays: 7 (default, configurable)
  - nfs:
    - server: "10.0.50.3" (fixed per homelab convention)
    - path: "/exports/backups/searxng" (placeholder; must be configurable)
  - job resources and annotations configurable
- serviceMonitor/metrics (optional): configurable if metrics endpoints are exposed
- podAnnotations/podLabels: configurable

Secrets and 1Password Operator handling (no hardcoded secrets anywhere):
- All sensitive values must be sourced via 1Password Operator.
- Create a Kubernetes Secret named "secrets" by annotating it for 1Password Operator:
  - Required annotations (exact keys):
    - operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
    - operator.1password.io/item-name: "secrets"
- Secret keys in 1Password must:
  - be lowercase
  - be hyphenated
  - mirror env var names in wording
- Example mapping (convention shown; adjust keys as needed):
  - ENV var: SECRET_KEY        -> 1Password key: secret-key
  - ENV var: GOOGLE_API_KEY    -> 1Password key: google-api-key
  - ENV var: BING_API_KEY      -> 1Password key: bing-api-key
- Workload references use valueFrom.secretKeyRef in the Deployment/StatefulSet:
  - name: "secrets"
  - key: "<lowercase-hyphenated-key>"
- Script creation (no secrets in repo):
  - Based on /home/coder/homelab/tools/example-op-create.sh, create tools/searxng-op-create.sh to create/update the 1Password item (category "Database") with required key/value pairs per above. Do not include secret values in the repo; rely on Operator annotations to populate the Kubernetes Secret.

ConfigMaps (non-sensitive):
- Provide a values.yaml field (e.g., config.settingsYaml) to inline non-sensitive searxng settings.yml.
- Render as a ConfigMap and mount/read by the container (per bjw-s common patterns for configMaps).

Service:
- Required to expose http internally. Full configurability (type, ports, annotations) via values.yaml per homelab conventions.

Ingress:
- Required for external access.
- Use networking.k8s.io/v1 with host rules for eaglepass.io.
- ClassName, annotations (e.g., for cert-manager/ingress-controller), rules, and TLS must be values-driven.
- Default host: searxng.eaglepass.io (configurable).

Persistence:
- Default disabled.
- If enabled, create a PVC named "data" with parameters configurable in values.yaml (storageClass, accessModes, size, existingClaim).
- If omitted (default), deploy statelessly with ConfigMap-only configuration.

Backups:
- Only applicable if persistence.enabled = true.
- NFS server: 10.0.50.3 (required by homelab convention).
- Placeholder path default in values.yaml (e.g., /exports/backups/searxng); operator must change it.
- Implement a CronJob to snapshot/copy relevant data to NFS.
- Cron schedule configurable (default: every 15 minutes).
- Retention configurable (default: 7 days), with cleanup logic in the job.

Image build and push:
- An external upstream image exists; use it:
  - repository: searxng/searxng (configurable)
  - tag: configurable (default could be "latest" or a pinned version)
- Do not create a Dockerfile or build image; do not invoke build_push.sh for this app.

Activity logging (must be maintained by the automation implementing this plan):
- Append human-readable action notes to:
  - /home/coder/homelab/reports/searxng/action-log.txt
- Store test artifacts (logs, screenshots, curl outputs) under:
  - /home/coder/homelab/reports/searxng/tests/

Testing (high-level, record outputs in reports paths):
- Post-render lint: Validate values with bjw-s schema and Helm lints (no errors).
- Smoke test:
  - Confirm Service endpoints respond on the configured port in-cluster.
  - Confirm Ingress returns 200 for "/" at host searxng.eaglepass.io (or configured host) after deployment.
- Secret wiring:
  - Verify pod environment contains variables that were mapped from 1Password keys.
  - Ensure no secrets are logged or stored in values.yaml/ConfigMaps.
- Optional: If persistence.enabled, write a small file to the mount and verify backup CronJob writes to NFS path.

Constraints and reminders:
- Never modify anything in /home/coder/homelab/plan_create.
- Do not propose a directory structure.
- Do not embed any secrets in chart or values.yaml.
- Follow bjw-s conventions: first controller and container labeled "main"; first PVC labeled "data".
- Only produce Chart.yaml and values.yaml (plus standard bjw-s compatible templates as needed by the implementing automation); this document does not include code.

Acceptance:
- A bjw-s-convention Helm chart for searxng under /home/coder/homelab/apps/searxng with values-driven Service/Ingress/ConfigMap/Secrets, optional PVC and NFS backups, references 1Password Operator correctly, and all actions/tests logged under /home/coder/homelab/reports/searxng.
