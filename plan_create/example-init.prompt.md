---
mode: agent
---
#### Requirements
    - Follow this YAML exactly and perform all steps autonomously without asking for missing requirements or proposing new investigations
    - Generate outputs as two separate single code blocks of plain text only (no other formatting)
    - Never edit anything in the 'plan_create' folder at any time
    - Do not propose a directory structure and do not propose items for independent investigation within the instructions
    - Respect homelab conventions and bjw-s-labs chart conventions or Sub Chart conventions stated herein when applicable
    - Use the latest bjw-s app-template version (determine from releases) when referencing bjw-s charts
    - Integrate 1Password Operator patterns for secret management as specified
    - Reference plan-create/projects.yaml with full pathing when citing application documentation and chart files

---

### Specification Overview

Version: 1.2
Purpose: Standardized autonomous instructions and prompt to create a Helm Chart for a given Application per homelab conventions
Host Environment: ZSH shell, Kubernetes Cluster managed by Argo CD, Helm CLI, 1Password CLI
Domain: eaglepass.io

### Hard Constraints

- Autonomy: Generate instructions without external investigation requests or delegating tasks
- File Protection: Never modify 'plan_create' folder contents
- Structure: Do not propose directory structures or add "things to investigate"
- Output Packaging: Wrap Instructions and Initial Prompt in separate single code blocks of plain text only
- Documentation: Cite specific Application entries from plan-create/projects.yaml with full pathing
- Conventions: Adhere to homelab and Helm best practices with schema validation

### Chart Type Determination

Available Types:
- Sub-Chart: Uses Chart.yaml and values.yaml to leverage umbrella approach from remote chart
- bjw-s Chart: Uses bjw-s-labs "common library" conventions with Chart.yaml and values.yaml

Selection Logic:
- Well-maintained existing chart meeting homelab conventions → Sub-Chart
- Existing chart not meeting conventions → bjw-s Chart
- No existing/outdated/unmaintained chart → bjw-s Chart
- Custom application → bjw-s Chart

bjw-s Chart Requirements (If using bjw-s charts):
- Determine the current release branch for the app-template charts
- Use the current app-template release branch (app-template-<current-release>)
- Reference baselines:
  - Repo root for context: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
  - Download and reference the current common/values.yaml baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
  - Download and test with the current common/values.schema.json baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- If sub-charting the bjw-s helm chart:
  - First controller and container labeled "main"
  - First PVC labeled "data"

### Security and Secret Management

1Password Operator Integration:
- All secrets sourced via 1Password Operator using valueFrom: secretKeyRef
- Required annotations on Kubernetes objects receiving secrets:
  annotations:
    operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
    operator.1password.io/item-name: "secrets"
- Secret key naming convention:
  - Environment variable: ROOT_PASSWORD
  - 1Password field: root-password (lowercase, hyphenated)
- Create tools/<app-name>-op-create.sh based on tools/example-op-create.sh
- Use "Database" category for 1Password items
- No sensitive values hardcoded in charts or values.yaml
- Operator updates may trigger restarts; ensure compatibility with rollout behavior

### Kubernetes Objects Configuration
Always:
- Follow homelab conventions

Service:
- Configure only if internal access needed
- Make parameters configurable via values.yaml (type, ports, annotations)

Ingress:
- Configure only if external access needed
- Domain: eaglepass.io (configurable via values.yaml)
- Use networking.k8s.io/v1 with modern host/rules patterns and pathType
- Configurable via values.yaml: className, annotations, rules, tls

Persistence:
- Use PVCs for data persistence when needed
- Configure via values.yaml: storageClass, accessModes, size, existingClaim
- public dns annotations:
    external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    cert-manager.io/cluster-issuer: letsencrypt-prod
- private dns annotation:
    cert-manager.io/cluster-issuer: letsencrypt-prod


Backups:
- NFS Server: 10.0.50.3
- Placeholder path in values.yaml for user customization
- Implement as CronJobs within Helm Chart
- Schedule default: every 15 minutes (configurable via values.yaml)
- Retention default: 7 days (configurable via values.yaml)

### Image Handling

Decision Matrix:
- No external image + no Dockerfile → Create Dockerfile in apps/<app-name>
- No external image + provided Dockerfile → Use provided Dockerfile
- External image exists → Use existing image
- Build and push using build_push.sh to docker.io/brimdor/<app-name>:<tag> (default "latest")

### Activity Logging

- Log all actions: reports/<app-name>/action-log.txt
- Test artifacts: reports/<app-name>/tests/
- Human-readable notes appended as actions/tests are performed

### Required References in Instructions

- plan-create/projects.yaml: Reference the specific Application entry and include full path(s) to any documentation and/or chart files cited
- For bjw-s conventions (if applicable), reference:
  - bjw-s-labs repo root for context
  - common/values.yaml
  - common/values.schema.json
- Helm Best Practices:
  - Charts guide and values/schema behavior: https://helm.sh/docs/topics/charts/
  - Best practices guide: https://helm.sh/docs/chart_best_practices/

### Instructions Authoring Checklist

- State the selected Chart Type with a one-line justification based strictly on the determination logic above (no additional criteria).
- Identify required Kubernetes objects (Service, Ingress, PVC, Secrets, ConfigMaps, CronJobs for backups) strictly per the Conditions sections.
- Specify which values must be configurable in values.yaml, referencing Helm’s values and schema behavior; do not embed credentials or sensitive data.
- For Secrets:
  - Describe reliance on 1Password Operator via annotations and/or OnePasswordItem to populate a Kubernetes Secret, and how workloads reference it via valueFrom.secretKeyRef.
  - Include the exact annotation keys and example formats.
  - Instruct creation of tools/<app-name>-op-create.sh based on tools/example-op-create.sh, noting 1Password item category “Database” and key naming conventions.
  - Instruct making tools/<app-name>-op-create.sh executable.
  - Instruct using the output of the <app-name>-op-create.sh script to add the vault and item ids to the annotations in the values.yaml.
    Example output from the <app-name>-op-create.sh script:
    {
      "id": "<item-id>",
      "title": "<App-name> Secrets",
      "version": 1,
      "vault": {
        "id": "<vault-id>",
        "name": "Server"
      }
    }
- For Ingress:
  - Use networking.k8s.io/v1 and values-driven host rules for eaglepass.io; ensure annotations and TLS can be set from values.yaml per modern patterns.
- For Backups:
  - Define NFS server 10.0.50.3, placeholder path, schedule default (15 min), retention default (7 days), all configurable.
- Include a logging section instructing to append human-readable action notes and test artifacts to the reports/<app-name>/ paths.
- Provide explicit full paths from plan-create/projects.yaml for any documentation and chart files referenced.
- Do not propose a directory structure; focus only on the plan and references.
- Do not generate code; only describe steps, configurations expected in values.yaml, and references.

### Initial Prompt Authoring Checklist

- Address an average AI that will execute the plan autonomously.
- Include the chosen Chart Type and concise reasoning based on the defined decision logic only.
- Enumerate the tasks to perform autonomously (without asking questions), including:
  - Configure values.yaml fields for Service/Ingress/PVC/Backups as needed.
  - Integrate 1Password Operator annotations/OnePasswordItem and reference via valueFrom.secretKeyRef with the key naming conventions.
  - Use provided image or build/push using build_push.sh and Dockerfile rules as applicable.
  - Log actions and tests to reports/<app-name> paths.
- Remind the AI not to edit the 'plan_create' folder and not to propose directories.
- Ensure the prompt is wrapped in a single code block of plain text only.

### Output Sections to Produce (exactly two, in this order)

1) Instructions:
   - Wrap in one code block of plain text only.
   - Must require fully autonomous execution per this spec.
   - Include full paths to docs and chart files from plan-create/projects.yaml.

2) Initial Prompt to the AI:
   - Wrap in one code block of plain text only.
   - No code artifacts; only instructions