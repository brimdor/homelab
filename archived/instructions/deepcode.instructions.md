---
applyTo: '**'
---
App: DeepCode

Chart Type (selected using the defined determination logic only):
- bjw-s Chart — Reason: No existing, well-maintained Helm Chart for “DeepCode” that meets homelab conventions.

Key References:
- Application entry source of truth: /home/coder/homelab/plan-create/projects.yaml (Application: DeepCode). Use this file for the authoritative application-specific documentation and chart file paths. When implementing, read the DeepCode entry in this file and use the full paths defined there for documentation and chart file locations.
- bjw-s-labs repo root (context): https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
- bjw-s common values baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
- bjw-s common schema baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- Determine current release branch here: https://github.com/bjw-s-labs/helm-charts/releases
- Helm charts documentation: https://helm.sh/docs/topics/charts/
- Helm chart best practices: https://helm.sh/docs/chart_best_practices/

bjw-s Conventions to Apply:
- Use the app-template pattern via the bjw-s “common library”.
- First controller name: main
- First container name: main
- First PVC name: data

Kubernetes Objects to Include (per Conditions; all values-driven via values.yaml):
- Deployment/StatefulSet (controller: main) using bjw-s patterns.
- Service (internal access):
  - Provide a configurable Service. Defaults: enabled, type ClusterIP, port mapping configurable. All fields configurable via values.yaml (type, ports, annotations, labels).
- Ingress (external access, optional):
  - Provide a configurable networking.k8s.io/v1 Ingress. Defaults: disabled.
  - Host rules must be values-driven and support eaglepass.io by default (e.g., deepcode.eaglepass.io), with ability to override domain. Configure className, annotations, rules, tls from values.yaml per modern v1 patterns.
- Persistence (optional):
  - Provide a configurable PVC for persistent data. Defaults: disabled.
  - PVC name: data. Configurable fields: storageClass, accessModes, size, existingClaim, annotations.
- ConfigMaps:
  - Provide optional ConfigMaps for non-sensitive configuration files. Mount paths and filenames configurable via values.yaml.
- Secrets (1Password Operator):
  - No sensitive values in templates or values.yaml.
  - Workloads must reference secrets via valueFrom.secretKeyRef.
  - Use 1Password Operator to populate a Kubernetes Secret (named via values, default “secrets”) using annotations:
    - annotations:
        operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
        operator.1password.io/item-name: "secrets"
  - Key naming in 1Password item:
    - Lowercase, hyphenated, matching the wording used in values.yaml env mapping.
    - Example mapping convention:
      - Environment variable: ROOT_PASSWORD
      - 1Password key: root-password
  - Ensure operator updates are compatible with expected rollout behavior; workloads should re-read updated secrets and roll as needed.
  - Create a helper script based on the pattern:
    - tools/example-op-create.sh → tools/deepcode-op-create.sh
    - Use 1Password CLI or web UI to create a new item in the appropriate vault.
    - Item category: Database
    - Populate with custom key/value pairs matching the hyphenated naming convention.
- Backups (optional, only if needed):
  - Implement a CronJob managed by the chart (values-driven) to back up persistent data to NFS.
  - NFS server: 10.0.50.3
  - NFS path: placeholder path set in values.yaml; instruct users to modify it.
  - Configurable via values.yaml: enabled, schedule (default: */15 * * * *), retentionDays (default: 7), target NFS path, resource limits/requests, job history limits, securityContext, and destination subpath naming.
  - Ensure backup job mounts the PVC and writes to NFS; include a retention policy (e.g., prune files older than retentionDays).

values.yaml Requirements (configure all via values and validate via schema; cite Helm docs above for behavior and best practices):
- Global/metadata:
  - nameOverride, fullnameOverride
- Image:
  - repository, tag, pullPolicy
  - If using an external image, specify here.
- Controller (bjw-s conventions):
  - type (e.g., deployment/statefulset as required), replicas, strategy, pod annotations/labels
  - podSecurityContext, securityContext
  - resources (requests/limits)
  - nodeSelector, tolerations, affinity
  - probes (liveness, readiness, startup)
- Service:
  - enabled (bool), type, annotations, labels
  - ports (name, port, targetPort, protocol)
- Ingress:
  - enabled (bool)
  - className
  - annotations
  - hosts:
    - host: deepcode.eaglepass.io (default; values-driven to allow overrides)
      - paths with path: "/", pathType: Prefix, service backend port reference
  - tls: enabled flag, secrets list, and hosts mapping
- Persistence:
  - data:
    - enabled (bool)
    - existingClaim (string, optional)
    - storageClass, accessModes (list), size (e.g., 10Gi), annotations
    - mountPath (e.g., /data)
- Config:
  - configMaps: list/map of files and mount points for non-sensitive configuration
- Secrets/Environment:
  - secretName: defaults to “secrets” (the K8s Secret populated by 1Password Operator)
  - secretAnnotations (to include the 1Password operator annotations above)
  - env:
    - non-sensitive variables as plain values
    - sensitive variables as:
      - valueFrom:
          secretKeyRef:
            name: "secrets"
            key: "<lowercase-hyphenated-key>"
- Backups:
  - enabled (bool)
  - nfs:
    - server: "10.0.50.3"
    - path: "/replace/with/valid/nfs/path"  # placeholder; instruct user to change
  - schedule: "*/15 * * * *"
  - retentionDays: 7
  - job:
    - annotations, labels
    - resources
    - securityContext
    - successfulJobsHistoryLimit, failedJobsHistoryLimit
- Schema:
  - Provide a values.schema.json aligned with bjw-s common schema patterns to validate types and required fields (refer to bjw-s common values.schema.json above). Ensure booleans, strings, and arrays are validated; require essential fields like service.ports when service.enabled, ingress.hosts when ingress.enabled, persistence.size when persistence.enabled, etc.

Image Build and Push (follow Conditions exactly):
- If no external image exists for DeepCode:
  - Create a minimal, secure Dockerfile at apps/deepcode using an appropriate official slim base image.
  - Use a non-root user, minimal packages, and expose the correct port (default 8080 unless overridden by the application requirements).
  - Provide a build_push.sh that builds and pushes to docker.io/brimdor/deepcode:<tag> (default tag “latest” if unspecified).
- If the application provides a Dockerfile:
  - Use that Dockerfile and build/push via build_push.sh to docker.io/brimdor/deepcode:<tag>.
- If an external image exists:
  - Use the existing image (configure in values.yaml) and skip building.

Testing and Validation:
- Lint and schema-validate the chart.
- Render manifests with helm template using representative values for:
  - service-only (no ingress/pvc),
  - ingress-enabled with TLS,
  - persistence-enabled with backups,
  - secrets wired via 1Password annotations.
- Ensure manifests use networking.k8s.io/v1 for Ingress and follow v1 Service API.
- Verify first controller/container are named main and first PVC is named data.

Activity Logging (must be maintained):
- Append human-readable action notes to: reports/deepcode/action-log.txt
- Store rendered manifests, lint outputs, and validation artifacts under: reports/deepcode/tests/

Constraints and Guardrails:
- Do not modify anything under /home/coder/homelab/plan-create/.
- Do not propose a directory structure.
- Do not add independent investigations; chart type has been selected per the predefined logic.
- Do not hardcode any sensitive values in templates or values.yaml; all secrets must flow via 1Password Operator as described.
- Ensure all Ingress/Service/PVC/Backup configurations are values-driven and validated per Helm best practices.

Implementation Pointers (non-code):
- Use the DeepCode entry in /home/coder/homelab/plan-create/projects.yaml to determine the exact documentation path(s) and chart file destination path(s) (include and adhere to those full paths when creating files).
- Follow bjw-s common library structure and conventions; rely only on Chart.yaml and values.yaml with bjw-s app-template expectations.