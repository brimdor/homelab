---
applyTo: '**'
---
Plan/Instructions (Kavita Helm Chart Creation)

Spec Reference: /home/coder/homelab/.github/prompts/kavita-init.prompt.md (Spec Version 1.1)
Application Reference Source: /home/coder/homelab/plan_create/projects.yaml (Kavita entry under key: "Kavita")

1. Chart Type Selection
Chosen Chart Type: bjw-s Chart
Justification (per determination logic only): Kavita has existing Docker images but no officially maintained upstream Helm Chart meeting homelab conventions; thus select bjw-s Chart.

2. Referenced Inputs and Documentation
- Application entry (full path for source of truth): /home/coder/homelab/plan_create/projects.yaml (section: Kavita)
- Application docs (from entry):
  - https://kavitareader.com
  - https://github.com/Kareadita/Kavita
  - Upstream Docker context (no official conformant Helm chart identified): https://github.com/Kareadita/Kavita/blob/develop/Dockerfile
  - Published image reference: https://hub.docker.com/r/linuxserver/kavita
- bjw-s-labs references (for library conventions):
  - Repo root: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
  - Baseline common values: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
  - Baseline schema: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- Helm best practices (for values.yaml configurability and schema): 
  - https://helm.sh/docs/topics/charts/
  - https://helm.sh/docs/chart_best_practices/

3. High-Level Objectives
Produce a bjw-s style chart (Chart.yaml + values.yaml + templates leveraging common library) enabling configuration of:
- Deployment (controller "main")
- Container image/customizations
- Service (internal)
- Ingress (external access to eaglepass.io domain)
- Persistence (PVC "data")
- Optional ConfigMaps (non-sensitive)
- Secrets via 1Password Operator (sensitive)
- Scheduled Backups (CronJob + NFS)
- Logging and testing action records under reports/kavita/

4. Kubernetes Objects Required (Conditions Applied)
- Deployment/Stateful controller (using bjw-s common library: controller type deployment unless stateful requirements dictate; Kavita mainly needs persistent storage for metadata so a Deployment + PVC suffices).
- Service: Yes (internal cluster access). Type: ClusterIP default. Ports configurable (app port, default 5000 if Kavita uses 5000; verify but keep configurable).
- Ingress: Yes (external web access). Host configurable; default host: kavita.eaglepass.io. TLS optional and configurable.
- PersistentVolumeClaim: Yes for application data (library metadata, thumbnails, config). Name key "data".
- ConfigMap: Optional for advanced non-sensitive overrides (e.g., appsettings-like config). Provide mechanism but disabled by default.
- Secret: Yes, produced by 1Password Operator -> Kubernetes Secret named "secrets" (referenced by pod env valueFrom). Potential keys: database-url (if external DB used later), api-key, admin-password (example placeholders only—do not hardcode).
- CronJob (Backups): Yes if enabled in values. Default enabled=false; when enabled: schedule "*/15 * * * *", retention 7 days. Writes to NFS mount.
- Volume for Backups: NFS volume (server 10.0.50.3, path configurable placeholder: /exports/backups/kavita CHANGE-ME).
- RBAC: Only if needed for backup job (if listing pods or accessing API not required—omit unless required).
- ServiceAccount: Configurable toggle (enabled: false by default) for least privilege.

5. Values.yaml Configurability (Map to Helm Best Practices)
All below must be keys in values.yaml to allow override:
- image:
  repository (default linuxserver/kavita)
  tag (default "latest")
  pullPolicy
- controller.type (deployment) and replicaCount
- podSecurityContext / containerSecurityContext (runAsUser, runAsGroup, fsGroup)
- resources (requests/limits)
- service:
  enabled (true)
  type (ClusterIP)
  annotations
  ports:
    http:
      port (containerPort)
      targetPort
- ingress:
  enabled (true)
  className
  annotations
  hosts:
    - host: kavita.eaglepass.io
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName (optional)
      hosts:
        - kavita.eaglepass.io
- persistence:
  data:
    enabled (true)
    existingClaim (optional)
    accessModes (default [ReadWriteOnce])
    size (e.g., 10Gi)
    storageClass (optional)
    retain (whether PVC deletion is retained)
- backups:
  enabled (false)
  nfs:
    server: 10.0.50.3
    path: /exports/backups/kavita/CHANGE-ME
    mountPath: /backup
  schedule: "*/15 * * * *"
  retentionDays: 7
  resources (job)
  successfulJobsHistoryLimit / failedJobsHistoryLimit
- config:
  extraEnv: [] (list of env var objects { name, value })
  extraEnvFrom: []
  configMap:
    enabled (false)
    data: {}
  secretRef:
    name: secrets (constant unless overridden)
- security:
  podAnnotations
  podLabels
  networkPolicy (optional future expansion flag)
- strategy (updateStrategy / rollingUpdate parameters)
- probes:
  liveness/readiness/startup customizable (paths/ports/initialDelaySeconds etc.)
- logging:
  level (if app supports)
- nodeSelector / tolerations / affinity
- serviceAccount:
  create (false)
  name (optional)
  annotations
- schedulerName (optional)
- priorityClassName (optional)

Schema Guidance:
- Provide values.schema.json (derivable from bjw-s baseline) referencing all added top-level keys for validation (do not duplicate entire baseline; extend logically).
- Justify: Helm schema ensures user feedback on invalid types (per Helm docs).

6. Secrets Handling (1Password Operator Integration)
- Do not store sensitive values in chart or defaults.
- Create a 1Password vault item named "secrets" (category: Database) with lowercase hyphenated keys.
- Example environment variable mapping convention:
  ENV VAR: ADMIN_PASSWORD -> key: admin-password
  ENV VAR: API_KEY -> key: api-key
- Kubernetes Secret produced by 1Password Operator using annotations on (a) a placeholder Secret manifest or (b) a OnePasswordItem CRD (choose annotation method for simplicity on Secret).
- Required annotations on the Kubernetes Secret (exact keys):
  operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  operator.1password.io/item-name: "secrets"
- Pod spec environment variable example (in values concept, not hardcoded):
  - name: ADMIN_PASSWORD
    valueFrom:
      secretKeyRef:
        name: secrets
        key: admin-password
- Provide configurable list under values.yaml: secretEnv:
  - name: ADMIN_PASSWORD
    key: admin-password
- Chart templates iterate secretEnv to inject env entries.
- Instruct creation of script: /home/coder/homelab/tools/kavita-op-create.sh derived from /home/coder/homelab/tools/example-op-create.sh replicating pattern to create the 1Password item with required key placeholders (no secret values).
- No plaintext secrets committed.

7. ConfigMaps
- Optional configMap for non-sensitive overrides (e.g., custom UI settings).
- values.config.configMap.enabled flag; data map for key/value files or inline content.
- Mounted via extraVolumes/extraVolumeMounts (bjw-s common patterns) or explicit persistence-like section (prefer common patterns: persistence.additionalVolumes / additionalMounts style if supported by current release; if not, define extraVolumes/extraVolumeMounts fields in values).

8. Persistence
- Primary PVC "data" with mountPath (default /config or /kavita/config depending on image—linuxserver uses /config). Set mountPath configurable: persistence.data.mountPath (default /config). This aligns with linuxserver image expectation.
- If additional content library paths needed, user can supply hostPath/NFS via additional persistence blocks (describe possibility but only declare primary in baseline plan).

9. Backups (CronJob)
- Controlled by backups.enabled.
- CronJob name derived from release name.
- Mount both data PVC (read) and NFS backup target (write).
- Command concept (not code) to tar/rsync /config to backup destination with timestamp; enforce retention by deleting older than retentionDays (value configurable).
- Values for:
  - backups.image (optionally reuse busybox or alpine)
  - backups.retentionDays
  - backups.schedule
  - backups.nfs.server/path/mountPath
  - backups.resources
- Security: run as non-root if feasible.

10. Ingress
- v1 networking API.
- host(s) array with at least one default host.
- TLS optional; if enabled, secretName provided.
- Annotations configurable (e.g., cert-manager.io/cluster-issuer, external-dns alpha annotations).
- pathType: Prefix; path: /

11. Logging and Activity Tracking
- All human-authored actions and testing notes appended (one line per action) to:
  - /home/coder/homelab/reports/kavita/action-log.txt
- Test artifacts (e.g., helm template output samples, dry-run notes) placed under:
  - /home/coder/homelab/reports/kavita/tests/
- Values file modifications or validation results summarized in action-log entries.
- Ensure chronological order (prepend timestamp or rely on append order; recommend timestamp format ISO 8601 in instructions).

12. Testing (Conceptual)
- Use helm template (dry-run) to validate schema and object generation; log outcomes to action-log.
- Validate that disabling ingress/service/backups removes objects.
- Validate secretEnv mapping generates env entries referencing 'secrets'.

13. Image Handling
- Use existing official image linuxserver/kavita (no Dockerfile creation needed).
- Provide values.image.* block.
- If future switch to custom image required, build_push.sh may be adapted; out of scope for initial chart, just mention path if custom needed: /home/coder/homelab/tools/build_push.sh.

14. Security / Hardening
- Encourage runAsNonRoot, specify UID/GID typical of linuxserver images (often PUID/PGID pattern); expose PUID/PGID as configurable env entries (not secrets) in values (e.g., 1000).
- Allow readOnlyRootFilesystem (false by default; can be user-enabled).
- Optional networkPolicy flag for later implementation.

15. Upgrade / Rollout Strategy
- Default rolling update; allow maxUnavailable / maxSurge via strategy settings in values.

16. Explicit Non-Actions
- No edits to /home/coder/homelab/plan_create contents (policy).
- No directory structure proposals—only planning instructions above.
- No code manifests or template YAML output here (spec constraint).
- No hardcoded sensitive data.

17. Execution Steps Summary (Narrative for Implementer)
- Create Chart.yaml referencing bjw-s common library.
- Author values.yaml with all keys listed.
- (Optional) Extend values.schema.json from bjw-s baseline declaring new properties.
- Implement templates using bjw-s patterns for persistence, service, ingress, env, secretEnv iteration, backups CronJob (conditional).
- Add optional ConfigMap template (conditional).
- Add Secret placeholder template with 1Password annotations (no data; rely on operator).
- Append action logs and produce test outputs under reports/kavita/.
- Validate with helm template using sample overrides.

18. References (Full Paths Reiterated)
- Source application entry: /home/coder/homelab/plan_create/projects.yaml (section: Kavita)
- Tools reference script example: /home/coder/homelab/tools/example-op-create.sh
- Target secrets creation script: /home/coder/homelab/tools/kavita-op-create.sh
- Reports logging directory root: /home/coder/homelab/reports/kavita/
- Common existing build script (if future custom image): /home/coder/homelab/tools/build_push.sh

19. Completion Criteria
- All required objects conditionally rendered via values toggles.
- No secrets leaked.
- Action log and test directory populated.
- Ingress host defaults to kavita.eaglepass.io but user-configurable.
- Backups disabled by default but fully configurable.