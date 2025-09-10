---
applyTo: '**'
---
Plan/Instructions (Elysia Helm Chart Creation)

Application: elysia
Reference Application Entry: /home/coder/homelab/plan_create/projects.yaml (section: Elysia)
Referenced Documentation (from projects.yaml Elysia entry):
  - https://github.com/weaviate/elysia
  - https://elysia.weaviate.io
  - https://weaviate.io/blog/elysia-agentic-rag
  - https://weaviate.github.io/elysia
Planned Chart Location (referenced only, not to be created here): apps/elysia

1. Chart Type Selection
Chosen Chart Type: bjw-s Chart
Justification (per determination logic only): No existing Helm chart path/content for Elysia is present in the repository (apps/elysia directory absent) and no maintained upstream chart is cited; therefore treat as application without an existing chart -> bjw-s Chart.
bjw-s References:
  - bjw-s-labs repo root: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
  - common values baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
  - common schema baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
Helm Best Practices References:
  - https://helm.sh/docs/topics/charts/
  - https://helm.sh/docs/chart_best_practices/

2. Kubernetes Objects Required (driven strictly by conditions)
(Assumptions—kept minimal and reasonable to proceed autonomously: Elysia is a service exposing an HTTP API/UI needing external access; it likely needs persistence for embeddings / state; it may require configuration and secrets for upstream Weaviate or vector backends. Adjust via values.yaml.)
  - Deployment/StatefulSet via bjw-s common controller: single controller named "main".
  - Service: ClusterIP (configurable) exposing primary HTTP port (configurable, default 8080).
  - Ingress: Required for external access under eaglepass.io domain (host configurable).
  - PVC: One persistent volume claim labeled "data" (storage parameters configurable) for application state if required; persistence can be disabled via values flag.
  - Secret: One Kubernetes Secret named "secrets" populated by 1Password Operator annotations; environment variables map via valueFrom.secretKeyRef.
  - ConfigMap: Optional for non-sensitive configuration (enable/disable via values).
  - Backup CronJob: Included (enable/disable via values). Uses NFS server 10.0.50.3 and placeholder export path; schedule and retention configurable.
  - Optional additional CronJobs avoided unless tied to backups; only one backup CronJob defined.
No other objects (e.g., ServiceMonitor, NetworkPolicy) are mandated by the spec; may add later outside this plan.

3. values.yaml Configurability (must NOT embed secrets)
Provide these top-level (or bjw-s conventional) keys with schema alignment referencing bjw-s common library patterns (e.g., controllers.main, service.main, ingress.main, persistence.data, cronjobs.backup, configMaps.*, secrets handled externally). Each item must be configurable per Helm docs to allow overriding via values or --set:
  - image.repository, image.tag, image.pullPolicy
  - controllers.main:
      type (Deployment vs StatefulSet if needed), replicas, strategy, pod labels/annotations, securityContext, resources, env, envFrom (only non-secret), probes (liveness/readiness), podAntiAffinity defaults
  - service.main:
      enabled (bool), type, annotations, labels, primary port name (http), port number (default 8080), targetPort, additionalPorts list
  - ingress.main:
      enabled (bool), className, annotations (map), hosts (array; default host: elysia.eaglepass.io), paths (path + serviceNameRef pattern per bjw-s), TLS (enabled, secretName configurable), extra rules list
  - persistence.data:
      enabled (bool), existingClaim (nullable), storageClass, accessModes (default [ReadWriteOnce]), size (default 10Gi), annotations, labels
  - configMaps:
      enabled flag plus one or more named data sections (e.g., app-config) with key/value non-sensitive configs
  - secretRefs:
      Indirect—environment variables reference "secrets" Secret via valueFrom.secretKeyRef; keys not defined in chart—only variable names listed under env mapping.
  - env:
      Map of environment variable definitions; values either plain (for non-sensitive) or placeholder referencing secret (e.g., valueFrom pattern). Sensitive values never in plain text.
  - backups:
      enabled (bool), nfs:
        server (default 10.0.50.3)
        path (placeholder: /export/path/elysia—user must change)
      schedule (default "*/15 * * * *")
      retentionDays (default 7)
      image (backup job image, repository/tag configurable)
      resources, securityContext, successfulJobsHistoryLimit, failedJobsHistoryLimit
  - cronjobs.backup (bjw-s pattern):
      enabled, schedule, pod template specs referencing nfs mount and retention logic
  - securityContext (pod and container levels)
  - resources (requests/limits) for main container and backup job
  - nodeSelector, tolerations, affinity
  - podAnnotations (allow adding restart triggers)
  - global (if required by bjw-s patterns) left extensible
  - metrics / serviceMonitor (disabled by default; only if later needed—do not implement now)
Schema:
  - Provide values.schema.json aligning types: booleans for enabled flags, strings for textual config, arrays for hosts/accessModes, integers for retentionDays, pattern for cron schedule, object maps for annotations/labels.
  - Reference Helm schema behavior for validation (Helm docs link already cited).

4. Secret Handling via 1Password Operator
Process:
  - Create (outside chart) a 1Password item in designated vault with item name "secrets" (category: Database) containing key/value pairs for sensitive settings. Keys: lowercase, hyphenated (e.g., api-key, db-url, weaviate-endpoint, ollama-url). Environment variables in container map upper-case underscore variant to secret keys (API_KEY -> api-key).
  - Kubernetes Secret named "secrets" produced by 1Password Operator.
  - Annotations applied to a placeholder Secret manifest or appropriate target object (if OnePasswordItem CRD used) with exact keys:
      operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
      operator.1password.io/item-name: "secrets"
  - In Deployment (controller), reference env variables:
      env:
        - name: API_KEY
          valueFrom:
            secretKeyRef:
              name: secrets
              key: api-key
  - No secret data or base64 values in values.yaml.
Script Creation:
  - Copy methodology from /home/coder/homelab/tools/example-op-create.sh to new script tools/elysia-op-create.sh (not created here, just instructed).
  - Script responsibility: create or update 1Password item with required keys (placeholders only), instruct user to manually populate secure values.
Logging:
  - Append an action log entry when script is run to: reports/elysia/action-log.txt (e.g., "YYYY-MM-DD HH:MM Created/updated 1Password item for secrets").
  - Test validations output (e.g., Helm template dry-run, schema validation) placed under: reports/elysia/tests/

5. Ingress Configuration
  - API/UI external exposure required: ingress.main.enabled true by default (can be disabled).
  - Host default: elysia.eaglepass.io (override hosts[0].host).
  - TLS: values to enable; secretName configurable; encourage cert-manager integration via annotations (e.g., cert-manager.io/cluster-issuer) user-supplied.
  - Use networking.k8s.io/v1; pathType: Prefix; path "/" referencing service.main primary port.
  - All annotation maps configurable; no hardcoded certificate issuers.

6. Service Configuration
  - ClusterIP by default; allow type override (NodePort, LoadBalancer).
  - Primary port: http (8080 default).
  - Additional ports array for metrics/debug optionally disabled by default.

7. Persistence
  - persistence.data.enabled default true if Elysia requires storing state (assumed).
  - Support disabling (stateless mode).
  - Provide size, storageClass, accessModes, annotations overrides.
  - Mount path configurable (e.g., /data) via persistence.data.mountPath.

8. Backups
  - backups.enabled default false (user opts in).
  - When enabled:
      - CronJob mounts NFS PV/PVC (or direct hostPath if bjw-s pattern supports; prefer PVC pointing to NFS via static provisioner).
      - Schedule default every 15 minutes (*/15 * * * *).
      - Retention logic: container script deletes files older than retentionDays.
      - Backup artifacts stored under NFS path /export/path/elysia/backups (placeholder).
      - Environment variables for retentionDays and target path passed to backup job.
      - Document that user must ensure NFS path exists and permissions set.
  - All parameters user-configurable through values.yaml consistent with Helm best practices (no hardcoding).

9. ConfigMaps
  - Optional configMaps.app-config with non-sensitive items (e.g., application mode flags).
  - Enabled flag; each key stored as a file or literal.
  - Mounted or injected via envFrom (non-secret only).
  - Changes to ConfigMap should trigger rolling restart via annotation hash pattern (bjw-s library typically supports checksums).

10. Image Strategy
  - If official Elysia image exists (expected at ghcr.io/weaviate/elysia or similar) then use it; repository configurable. If not, user may create Dockerfile under apps/elysia and use /home/coder/homelab/tools/build_push.sh targeting docker.io/brimdor/elysia:latest (tag configurable).
  - values.image fields control repository, tag, pullPolicy.
  - Document fallback: create minimal Dockerfile (not here) FROM appropriate lightweight base (e.g., node:slim or distroless if compiled) following security best practices.

11. Action Logging Requirements
  - Every autonomous action (chart creation steps, script creation, backup test, helm template validation) append a line to: reports/elysia/action-log.txt
  - Test outputs (helm template --debug, helm lint, schema validation results) stored under: reports/elysia/tests/ (e.g., template.txt, lint.txt, schema-validation.txt).
  - Human-readable, timestamped.

12. Testing & Validation Steps (described, not executed here)
  - Run helm lint on the chart (ensuring values.schema.json presence).
  - Run helm template with default values to confirm object generation (especially Secret references unresolved but placeholders acceptable).
  - If backups.enabled temporarily set true in a test values override, template CronJob to confirm schedule, volume mounts.
  - Validate schema: helm install --dry-run --debug referencing values and schema (Helm automatically validates).
  - Record outputs into reports/elysia/tests/.

13. values.schema.json Guidance
  - Define required fields: image.repository, controllers.main, service.main.ports[0].port, ingress.main.hosts[0].host (if ingress enabled), persistence.data.size (if persistence enabled).
  - Provide enum constraints for service.main.type (ClusterIP, NodePort, LoadBalancer), accessModes entries (ReadWriteOnce, ReadWriteMany, ReadOnlyMany).
  - Regex for cron schedule (basic validation) and host (e.g., ^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$ ).
  - Integer minimum for retentionDays ≥ 1.

14. Security & Resource Considerations
  - No root container: runAsNonRoot true, runAsUser configurable (e.g., 1000), readOnlyRootFilesystem true unless app needs write.
  - Drop all capabilities by default.
  - Add network policy later if needed (not in current scope).
  - Provide resource requests (cpu: 100m, memory: 256Mi) and allow overrides.

15. Implementation Order (for autonomous execution)
  1) Create chart skeleton (Chart.yaml with bjw-s common library dependency if needed or annotate library usage per bjw-s guidance).
  2) Add values.yaml with all keys and safe defaults (no secrets).
  3) Add values.schema.json for validation.
  4) Add templates referencing bjw-s library constructs (controllers, service, ingress, persistence, cronjob).
  5) Add README snippet referencing /home/coder/homelab/plan_create/projects.yaml (Elysia section) and documentation links.
  6) Create tools/elysia-op-create.sh from example script pattern.
  7) Perform helm lint + template; capture logs in reports/elysia/tests/.
  8) Append actions to reports/elysia/action-log.txt after each significant step.

16. Do NOT:
  - Do not modify anything inside /home/coder/homelab/plan_create/
  - Do not embed secret literals, certificates, tokens, passwords.
  - Do not propose new directories beyond those referenced.
  - Do not output YAML manifests or script code in this plan.

17. Completion Criteria
  - All required configurable sections present in values.yaml and validated by schema.
  - Logging structure populated with action log and test artifacts.
  - Secret integration instructions clearly documented using 1Password Operator annotations.
  - Backups optional and fully values-driven.

End of Plan/Instructions