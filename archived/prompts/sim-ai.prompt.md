---
mode: agent
---
INITIAL PROMPT TO AI (to execute the plan) — PLAIN TEXT ONLY

You are operating in /home/coder/homelab. Work autonomously. Do not ask the user questions. Do not propose a directory structure. Follow homelab and bjw-s-labs conventions strictly.

Objective:
- Create a Helm Chart for the “Sim AI” application that adheres to homelab conventions, selecting the correct chart type based on investigation. Provide absolute paths to documentation and chart files as defined in /home/coder/homelab/plan-create/projects.yaml. Manage secrets via 1Password Operator. Implement Service/Ingress/Persistence/Backups only as required.

Authoritative references:
- Projects map: /home/coder/homelab/plan-create/projects.yaml (resolve Sim AI documentation and chart file absolute paths here).
- bjw-s-labs values: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml
- bjw-s-labs values schema: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.schema.json
- Example apps for conventions: /home/coder/homelab/apps/n8n, /home/coder/homelab/apps/emby, /home/coder/homelab/apps/localai

Chart Type decision rules:
- Existing, well-maintained Helm Chart that meets homelab conventions => Chart Type: Sub-Chart.
- Existing chart that does not meet homelab conventions => Chart Type: bjw-s Chart.
- No chart, outdated, unmaintained, or custom app => Chart Type: bjw-s Chart.

If sub-charting bjw-s helm chart:
- controllers.main is the first controller; containers.main is the first container.
- persistence.data is the first PVC.

Secrets via 1Password Operator (required if secrets are needed):
- Use valueFrom secretKeyRef to consume keys.
- Keys in 1Password must be lowercase-hyphen versions of the env keys.
- Add annotations:
  - operator.1password.io/item-path: vaults/<vault-id>/items/<item-id>
  - operator.1password.io/item-name: secrets
- Create/update the vault item using /home/coder/homelab/tools/op-create.sh and the 1Password CLI/web. Category must be “Database”. Do not hardcode sensitive values in the repo.

Backups (only if needed by Sim AI):
- Use a Kubernetes CronJob in the chart; default schedule */15 * * * * and 7 days retention.
- Store backups on NFS server 10.0.40.3. Use a placeholder path in values.yaml and note the operator must change it.
- All backup settings must be configurable via values.yaml.

Image build/push (only if needed):
- If no suitable image exists for Sim AI, create a minimal, secure Dockerfile under the Sim AI application directory from projects.yaml.
- Use an official slim base image, non-root user, minimal packages, healthcheck, least privileges.
- Use the repository’s build_push.sh (search the repo, commonly under /home/coder/homelab/tools/build_push.sh) to push docker.io/brimdor/sim-ai:latest (or tag specified in projects.yaml).
- Verify basic functionality through local run or Kubernetes dry-run with probes.

Network and storage:
- Service: internal access; configurable via values.yaml; follow homelab conventions.
- Ingress: external access only; configurable via values.yaml; follow homelab conventions.
- Persistence: use PVCs if needed; first PVC key must be persistence.data; configurable via values.yaml.

Tasks to perform:
1) Parse /home/coder/homelab/plan-create/projects.yaml to find the Sim AI entry. Resolve:
   - Documentation absolute path for Sim AI.
   - Chart file absolute paths (Chart.yaml and values.yaml) for Sim AI.
   - Application directory path (if defined).
   Use absolute paths for all outputs.

2) Investigate Sim AI:
   - Determine if there is an upstream Helm Chart; assess maintenance and compatibility with homelab conventions.
   - Select Chart Type (Sub-Chart or bjw-s Chart) per rules and record a concise justification.

3) Image:
   - Identify the container image to use. If none suitable exists, create a Dockerfile under the application directory and build/push docker.io/brimdor/sim-ai:latest using build_push.sh. Record the Dockerfile absolute path and the pushed tag.

4) Configuration:
   - Classify config into ConfigMaps (non-sensitive) and Secrets (sensitive via 1Password Operator). Update /home/coder/homelab/tools/op-create.sh to create the new 1Password item (Database category). Ensure env keys and 1Password keys follow the uppercase vs lowercase-hyphen convention.

5) Implement the Helm chart per selected type:
   - Sub-Chart: only Chart.yaml and values.yaml; use upstream chart’s schema; if using bjw-s as library, enforce controllers.main, containers.main, and persistence.data.
   - bjw-s Chart: conform to bjw-s values and schema links above. Implement image, env/envFrom, service, ingress (external only), persistence (if needed), resources, probes, securityContext (non-root), and optionally backups via CronJob with defaults and NFS 10.0.40.3 placeholder path.

6) Validate:
   - helm lint and helm template runs with representative overrides.
   - Optional kubeconform/kubeval if available.
   - Dry-run install to verify manifests are valid.
   - Ensure no sensitive values are present in any repo file.

7) Documentation:
   - In the documentation path resolved from projects.yaml, add/update Sim AI docs to describe chart type, install instructions, configuration (service, ingress, PVCs, secrets with 1Password Operator, backups), image details, and any homelab-specific notes.

8) Output a concise final report with:
   - Chart Type and justification.
   - Absolute documentation path and absolute chart file paths (Chart.yaml and values.yaml) as resolved from /home/coder/homelab/plan-create/projects.yaml.
   - Image status (existing or built), Dockerfile absolute path (if created), and pushed image reference.
   - Secrets integration summary (1Password vault item path placeholders and key mapping).
   - Which of Service/Ingress/Persistence/Backups were implemented and why.
   - Validation summary (helm lint/template outcomes and any fixes).

Constraints:
- Do everything without asking the user for input.
- Use absolute paths in all outputs.
- Do not propose a directory structure; rely on projects.yaml and existing repo patterns.
- Comply with homelab and