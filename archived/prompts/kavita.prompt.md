---
mode: agent
---
Initial Prompt to the AI (Kavita bjw-s Chart Task)

You are to autonomously implement a bjw-s style Helm Chart for the application "Kavita" following ONLY the specifications below—do not ask questions, do not propose investigations, do not modify any content under /home/coder/homelab/plan_create, and do not propose directory structures. Produce chart files and supporting artifacts directly.

Chart Type: bjw-s Chart
Reason (decision logic only): No maintained upstream Helm Chart meeting homelab conventions; therefore bjw-s Chart is required.

Authoritative Application Entry: /home/coder/homelab/plan_create/projects.yaml (section: Kavita)
Documentation references (for context only, no external fetches needed): 
- https://kavitareader.com
- https://github.com/Kareadita/Kavita
- https://github.com/Kareadita/Kavita/blob/develop/Dockerfile
- https://hub.docker.com/r/linuxserver/kavita
bjw-s references:
- https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
- common/values.yaml and common/values.schema.json in that branch

Tasks (execute all):
1. Create Chart.yaml referencing bjw-s common library (controller "main").
2. Create values.yaml with configurable keys:
   - image (repository=linuxserver/kavita, tag=latest default, pullPolicy)
   - controller/replicaCount
   - service (enabled, type, annotations, ports.http.port & targetPort)
   - ingress (enabled, className, annotations, hosts list with default host kavita.eaglepass.io, paths, tls list)
   - persistence.data (enabled, size, accessModes, storageClass, existingClaim, retain, mountPath=/config)
   - secretEnv list (each item: name, key) for mapping env vars to 1Password secret keys
   - config.configMap (enabled, data map), extraEnv, extraEnvFrom
   - backups (enabled=false, schedule default */15 * * * *, retentionDays=7, nfs.server=10.0.40.3, nfs.path=/exports/backups/kavita/CHANGE-ME, nfs.mountPath=/backup, image (specify minimal e.g. alpine), resources, history limits)
   - probes (liveness, readiness, startup) configurable
   - resources (requests/limits)
   - securityContext/podSecurityContext (runAsUser, runAsGroup, fsGroup, readOnlyRootFilesystem)
   - serviceAccount (create flag, name, annotations)
   - nodeSelector, tolerations, affinity, priorityClassName, schedulerName
   - strategy (rolling update parameters)
   - logging.level (if used)
3. Implement templates using bjw-s patterns:
   - Deployment (via common library values)
   - Service (conditional)
   - Ingress (networking.k8s.io/v1, conditional)
   - PVC (persistence.data)
   - Optional ConfigMap (config.configMap.enabled)
   - Secret placeholder with annotations only (name "secrets"):
        annotations:
          operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
          operator.1password.io/item-name: "secrets"
     (No data fields; rely on operator)
   - Env injection: iterate secretEnv to create valueFrom.secretKeyRef entries referencing name: secrets and key: <key>
   - CronJob for backups (conditional) that:
       * Mounts data PVC (read) and NFS volume (write)
       * Archives or syncs /config to NFS path with timestamp
       * Prunes backups older than retentionDays
4. Provide (extend or override) values.schema.json to validate new fields—derive trait patterns from bjw-s baseline.
5. Create /home/coder/homelab/tools/kavita-op-create.sh by adapting /home/coder/homelab/tools/example-op-create.sh to create a 1Password item named "secrets" (category Database) with placeholder fields (admin-password, api-key).
6. NEVER hardcode secret values; do not place sensitive data in values.yaml defaults.
7. Logging:
   - Append each significant action (file created, test run, schema validation) as a new line to /home/coder/homelab/reports/kavita/action-log.txt (include ISO 8601 timestamp).
   - Place any test/dry-run artifacts under /home/coder/homelab/reports/kavita/tests/.
8. Testing:
   - Run helm template (dry-run) with defaults and with altered toggles (disable ingress, enable backups) and store outputs or summaries in tests directory; log action lines.
   - Validate secretEnv entries render env vars referencing the "secrets" secret.
9. Backups disabled by default; enabling them must render exactly one CronJob and associated NFS volume mount.
10. Use existing linuxserver/kavita image; do not create a Dockerfile unless image field later points elsewhere (not in this task).
11. Ensure no modifications to /home/coder/homelab/plan_create.
12. Do not output any code in this initial prompt response; implement directly in repository context.

Key Conventions to Honor:
- First controller and container named "main".
- Primary PVC named "data".
- Secret name "secrets".
- Lowercase hyphenated secret keys (e.g., admin-password).
- Domain host default: kavita.eaglepass.io (configurable).
- NFS backup server fixed value default 10.0.40.3 but path customizable.

Completion Definition:
- Chart files, schema, values, templates, and scripts exist and validate.
- Action log and tests directory populated.
- All configurable toggles function in helm template output.
- No sensitive values committed.

Perform all steps now without further clarification requests.
End