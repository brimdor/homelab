---
applyTo: '**'
---
PLAN / INSTRUCTIONS FOR AI (Sim AI Helm Chart) — PLAIN TEXT ONLY

Context and non-negotiables:
- Work entirely autonomously. Do not ask the user for decisions or clarifications.
- Do not propose a directory structure. Use paths defined in the repository and in plan-create/projects.yaml.
- Investigate the application “Sim AI” and the repository to determine the best chart approach.
- All references to documentation and chart files must use absolute paths.
- Use homelab conventions and bjw-s-labs Helm Chart conventions when applicable:
  - bjw-s values reference: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml
  - bjw-s values schema: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.schema.json
- If sub-charting the bjw-s Helm chart (or using bjw-s as library):
  - The first controller and container must be labeled “main”
  - The first PVC must be labeled “data”
- Image build/push condition: If no image exists for Sim AI, create a minimal, secure Dockerfile and use the build_push.sh script to push to docker.io/brimdor/sim-ai:<tag> (default latest).
- Secrets must be managed exclusively via 1Password Operator with valueFrom secretKeyRef, lowercase-hyphen keys, and required annotations.
- Ingress is for external access only; Service is for internal access; both must be configurable via values.yaml, and follow homelab conventions.
- Persistence must be via PVCs if needed and configurable via values.yaml.
- Backups (if needed) must be implemented via CronJobs with default schedule */15 * * * * and 7-day retention, storing to NFS server 10.0.50.3 with a placeholder path in values.yaml.
- Do not output code in this plan. You will create the files/changes during execution, not as part of this plan text.
- Example apps to reference for conventions: /home/coder/homelab/apps/n8n, /home/coder/homelab/apps/emby, /home/coder/homelab/apps/localai

Authoritative repository location:
- Root: /home/coder/homelab
- Project mapping file (must be read first): /home/coder/homelab/plan-create/projects.yaml

High-level outcome you must deliver:
- A correctly selected chart type (Sub-Chart vs bjw-s Chart) for Sim AI, justified by your investigation.
- A functional Helm Chart that adheres to homelab and bjw-s-labs conventions.
- Image built and pushed if missing.
- ConfigMaps, Secrets (via 1Password Operator), Service, Ingress, Persistence, and Backups wired as required by the app.
- Absolute paths to the Sim AI documentation and chart files (as resolved from plan-create/projects.yaml), along with a concise summary of what you built.
- No sensitive data in repo files.

Workflow steps (execute in order):

1) Intake and resolve authoritative paths
- Open and parse /home/coder/homelab/plan-create/projects.yaml.
- Locate the Sim AI entry. Normalize the application key and name (accept keys like sim-ai, sim_ai, simai, or name: “Sim AI” under a projects list).
- From this entry, extract:
  - The absolute documentation path for Sim AI (e.g., docsPath, documentation, or similar field). Resolve to an absolute path under /home/coder/homelab.
  - The absolute chart file locations for Sim AI (e.g., chartPaths, chartFiles, or fields with explicit paths to Chart.yaml and values.yaml). Resolve to absolute paths.
  - The absolute application directory path if provided (e.g., appPath).
- Validate that the resolved documentation and chart file paths are absolute and exist (or are intended locations per the YAML). Do not invent a directory structure; if a path is missing from projects.yaml, first search the repo to discover whether a canonical path already exists for Sim AI. Only if projects.yaml lacks a chart/documentation path and the repo has no canonical existing path, update projects.yaml to include absolute paths that align with how other apps are recorded.

2) Investigate Sim AI to determine Helm Chart Type
- Determine whether “Sim AI” has an existing Helm Chart upstream:
  - Search artifact hubs (e.g., Artifact Hub), upstream repo (GitHub/GitLab), and container registries for an official or community Helm chart.
  - Assess maintenance status (recent releases, last commit recency, issue/pr activity), compatibility with homelab conventions, and whether it supports needed configuration (service, ingress, persistence, secrets via env).
- Decide chart type:
  - If Sim AI has an existing, well-maintained Helm Chart that meets homelab conventions: Chart Type = Sub-Chart (remote umbrella).
  - If an existing chart does not meet homelab conventions: Chart Type = bjw-s Chart.
  - If there is no chart, or it’s outdated/unmaintained: Chart Type = bjw-s Chart.
  - If Sim AI is custom and has no chart: Chart Type = bjw-s Chart.
- Record your decision and justification. If Sub-Chart is chosen, identify the remote chart name/repo and version you will depend on.

3) Container image verification and creation (if needed)
- Determine the container image to deploy:
  - Check projects.yaml and existing app artifacts for an image reference.
  - Search docker.io for docker.io/brimdor/sim-ai. If missing, search upstream images used by Sim AI.
- If no suitable image exists:
  - Create a Dockerfile in the apps/<sim-ai> directory defined by projects.yaml (do not propose a new directory structure; use the exact appPath or similar field).
  - Use an official slim base image if possible, run as non-root, minimize layers, install only required dependencies, set healthcheck, and drop capabilities to the minimum feasible.
  - Use the repository’s build_push.sh script to build and push to docker.io/brimdor/sim-ai:latest (or specified tag in projects.yaml). Locate the script by searching the repo (commonly under /home/coder/homelab/tools/build_push.sh). Adhere to its documented usage.
  - Confirm the image functions by running it locally (if test infra available) or via Kubernetes dry-run and probes.

4) Configuration classification: ConfigMaps vs Secrets
- Identify all configuration required by Sim AI (env vars, config files).
- Non-sensitive configuration files => ConfigMaps.
- Sensitive values => Secrets only via 1Password Operator using valueFrom secretKeyRef.
  - Keys must follow the conventions:
    - .env uppercase style e.g., ROOT_PASSWORD maps to 1Password key root-password (lowercase, hyphens), matching the wording of env keys in values.yaml.
  - Required annotations on the Secret manifest:
    - operator.1password.io/item-path: vaults/<vault-id>/items/<item-id>
    - operator.1password.io/item-name: secrets
- Use the existing 1Password creation flow:
  - Use or update /home/coder/homelab/tools/op-create.sh to create the new 1Password “Database” category item for Sim AI (supporting custom key/value pairs).
  - Ensure it follows the repository’s established method; do not hardcode sensitive values anywhere in the repo.
  - Ensure your Helm values.yaml uses valueFrom secretKeyRef exclusively for sensitive keys.

5) Helm chart authoring based on chart type
- If Chart Type = Sub-Chart (remote umbrella):
  - Provide only Chart.yaml and values.yaml as required by the repo’s conventions.
  - Follow Sub-Chart homelab conventions.
  - If sub-charting bjw-s common:
    - controllers.main is the primary controller; containers.main is the primary container.
    - persistence.data is the first PVC.
  - Configure image, env, envFrom (secrets), volumes/persistence, service, ingress, resources, probes, securityContext, and scheduling constraints via values.yaml per the upstream chart’s schema.

- If Chart Type = bjw-s Chart:
  - Adhere strictly to bjw-s-labs common library schema and conventions:
    - values reference: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml
    - values schema: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.schema.json
  - Use controllers.main / containers.main for the primary workload.
  - Persistence:
    - persistence.data is the first PVC if storage is required.
  - Configure:
    - image.repository and image.tag using the verified/published image (docker.io/brimdor/sim-ai:latest if built).
    - env and envFrom secrets according to the 1Password integration rules.
    - ConfigMaps for non-sensitive files and mounts.
    - Service (internal access), ensuring homelab defaults.
    - Ingress (external only), ensuring homelab defaults (class, TLS, host, annotations configurable via values.yaml).
    - Resources, probes, securityContext (non-root), and pod-level policies.
    - Node selectors, tolerations, and affinity if your homelab requires them (follow examples from /home/coder/homelab/apps/n8n, /home/coder/homelab/apps/emby, /home/coder/homelab/apps/localai for patterns).
  - Backups (only if Sim AI requires data backups):
    - Configure a Kubernetes CronJob inside the chart (using bjw-s patterns if available or a separate cronjob controller section).
    - Defaults:
      - Schedule: */15 * * * *
      - Retention: 7 days
    - Store on NFS server 10.0.50.3; use a placeholder path in values.yaml (e.g., /path/to/replace) and instruct the operator to change it.
    - Ensure the entire backup configuration is configurable via values.yaml.

6) Services and Ingress rules
- Determine if Sim AI exposes network services:
  - If yes, define a Kubernetes Service for internal access, configurable via values.yaml (type, ports, targetPorts, annotations as needed).
  - If external access is needed, define Ingress for external traffic only; make everything configurable via values.yaml (host(s), TLS secret reference, class, annotations).
- If the application does not require a service or ingress, omit them.

7) Persistence rules
- Determine whether Sim AI requires persistent storage (state, models, data).
- If required, define PVCs configurable via values.yaml. The first PVC key must be persistence.data.
- If not required, do not include PVCs.

8) Validate and test
- Lint and validate:
  - helm lint against the chart path.
  - helm template with representative values overrides to ensure manifests are valid.
  - kubeconform/kubeval if available to validate rendered manifests against your cluster version.
- Dry-run:
  - helm upgrade --install with --dry-run --debug in a test namespace.
- Security checks:
  - Confirm the container runs as non-root, with readOnlyRootFilesystem when possible, and least privileges.
  - Ensure no sensitive values are present in Chart.yaml, values.yaml, or ConfigMaps.

9) Documentation
- Using the absolute documentation path for Sim AI from projects.yaml, update or create content that includes:
  - Chart Type decision and justification.
  - Installation commands (helm repo/add if using a remote sub-chart; local path installation if bjw-s Chart).
  - Configuration documentation (service, ingress, persistence, secrets with 1Password Operator, backups).
  - Image details (repository and tag).
  - Any homelab-specific toggles required.
- Keep documentation consistent with patterns in other example apps’ docs within the repo.

10) Final deliverables (must output these)
- Chart Type selected and justification.
- Absolute paths (from /home/coder/homelab/plan-create/projects.yaml) to Sim AI documentation and chart files:
  - Documentation absolute path (e.g., /home/coder/homelab/...).
  - Chart files absolute paths (Chart.yaml and values.yaml).
- Image details:
  - Whether a new image was built; if so, Dockerfile absolute path and pushed image tag (docker.io/brimdor/sim-ai:<tag>).
- Secrets integration summary:
  - 1Password vault item created/updated (vault id/item id placeholders), operator annotations used, and list of env keys (uppercase) and their 1Password key names (lowercase-hyphen).
- Configuration summary:
  - Whether Service/Ingress/PVC/Backups were implemented and the rationale.
- Validation summary:
  - helm lint/template results and any fixes made.

Guardrails and checks:
- Never include sensitive values in repo files.
- Always use absolute paths in your output.
- Do not create or suggest new directory structures—use the paths and patterns defined in /home/coder/homelab/plan-create/projects.yaml and existing repo conventions.
- Follow bjw-s-labs common chart schema when Chart Type = bjw-s Chart; when Sub-Chart, follow the remote chart’s schema and homelab conventions.
- For backups, default schedule */15 * * * * and 7-day retention unless overridden in values.yaml by the operator.

End of plan.