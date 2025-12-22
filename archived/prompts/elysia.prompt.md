---
mode: agent
---
Initial Prompt to the AI (Elysia Helm Chart Execution)

You are to autonomously implement a bjw-s Chart for the application "elysia" per the predefined plan. Do not ask questions—act. Use only the determination logic: Elysia lacks an existing maintained chart in the repo, so Chart Type = bjw-s Chart.

Strict Constraints:
- Do NOT modify anything under /home/coder/homelab/plan_create/
- Do NOT produce or commit secrets; rely on 1Password Operator annotations to surface a Kubernetes Secret named "secrets"
- Do NOT hardcode credentials, tokens, or certificates
- Do NOT invent investigation items or propose a directory structure

References (do not alter):
- Application entry: /home/coder/homelab/plan_create/projects.yaml (Elysia section)
- Documentation links from that entry
- bjw-s-labs common library references:
  * Repo root: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
  * Baseline values: common/values.yaml
  * Baseline schema: common/values.schema.json
- Helm best practices: https://helm.sh/docs/topics/charts/ and https://helm.sh/docs/chart_best_practices/

Tasks (perform in order):
1. Create chart under apps/elysia using bjw-s common library conventions (Chart.yaml, values.yaml, values.schema.json, templates/ as needed).
2. Populate values.yaml with configurable sections: image, controllers.main, service.main, ingress.main, persistence.data, backups (cronjobs.backup), configMaps, env (non-sensitive), resource settings, security contexts, node scheduling fields.
3. Include persistence.data (enabled true by default), with mountPath, size (10Gi default), accessModes, storageClass, existingClaim overrides.
4. Implement ingress.main (enabled by default) with host default elysia.eaglepass.io, TLS configurable, annotations map, path "/" mapping to service main port. Use networking.k8s.io/v1 format.
5. Implement service.main with ClusterIP default, port 8080 (http), allow port override, additional ports list.
6. Implement backups (disabled by default) using a CronJob (cronjobs.backup) referencing NFS server 10.0.40.3 and placeholder path /export/path/elysia; schedule default */15 * * * *; retentionDays default 7; all configurable.
7. Add optional configMaps.app-config (disabled by default) for non-sensitive configuration.
8. Integrate 1Password Operator:
   - Provide a Secret manifest or OnePasswordItem reference pattern with annotations:
       operator.1password.io/item-path: vaults/<vault-id>/items/<item-id>
       operator.1password.io/item-name: secrets
   - Ensure env vars reference secret via valueFrom.secretKeyRef (e.g., API_KEY -> api-key).
   - Do not include secret data.
9. Create tools/elysia-op-create.sh by adapting /home/coder/homelab/tools/example-op-create.sh to scaffold a 1Password item named "secrets" (category: Database) with placeholder keys (api-key, db-url, weaviate-endpoint, ollama-url, etc.).
10. Add README within chart referencing original documentation links and usage, including secret handling and backups configuration overview.
11. Add values.schema.json enforcing types, required fields, enums, regex for host and cron schedule, and integer min for retentionDays.
12. Run helm lint and helm template (dry-run) capturing outputs into:
    - reports/elysia/tests/lint.txt
    - reports/elysia/tests/template.txt
    - reports/elysia/tests/schema-validation.txt (if separate)
13. Append timestamped action entries to reports/elysia/action-log.txt after each major step (chart scaffold, schema added, secret integration, backups config, lint run, template run).
14. Ensure no sensitive values appear in git changes (search for likely patterns before finalizing).
15. Provide reasonable resource requests/limits and securityContext (runAsNonRoot, fsGroup if needed, drop capabilities).
16. Confirm secret references do not break helm template (absence of data is acceptable).

Key Conventions:
- Controller and container named "main"
- First PVC named "data"
- Secret name fixed as "secrets"
- Environment variable naming: UPPER_SNAKE_CASE; corresponding 1Password keys: lowercase-hyphenated
- Backups disabled unless user enables; schedule and retention fully values-driven

Deliverables:
- apps/elysia/Chart.yaml
- apps/elysia/values.yaml
- apps/elysia/values.schema.json
- apps/elysia/templates/* (controllers, service, ingress, persistence, cronjob, secret/configmap constructs as required)
- apps/elysia/README.md
- tools/elysia-op-create.sh
- reports/elysia/action-log.txt (with entries)
- reports/elysia/tests/* (lint/template/schema outputs)

Do not output code here—perform the work directly. Act autonomously until all tasks complete in compliance with the plan and constraints.

End Initial Prompt