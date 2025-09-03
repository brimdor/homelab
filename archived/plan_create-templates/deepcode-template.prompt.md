---
mode: ask
---
# Notes to the AI
# - Follow this YAML exactly and perform all steps autonomously without asking for missing requirements or proposing new investigations.
# - DO NOT PROPOSE A DIRECTORY STRUCTURE.
# - You do the research and decision-making autonomously based on the criteria herein to establish the proper conditions for the plan/instructions and initial prompt.
# - Do not generate any code artifacts (YAML manifests, Helm templates, scripts) as output; only produce the requested plan/instructions and the separate initial prompt, each wrapped in its own single code block of plain text.
# - Never edit anything in the 'plan_create' folder at any time.
# - Do not propose items for independent investigation.
# - Respect homelab conventions stated herein when applicable.

Spec Version: 1.1
Purpose: Standardized autonomous plan/instructions and initial prompt to create a Helm Chart for a given Application per infrastructure as a service homelab conventions.

Inputs:
  - Application: DeepCode
  - plan-create/projects.yaml  # Must be referenced for application-specific documentation and chart files paths. Provide full pathing when citing.

Hard Constraints:
  - Autonomy: Generate the plan/instructions without external investigation requests or delegating tasks back to the requester.
  - Never modify 'plan_create' folder contents.
  - Do not propose a directory structure.
  - Do not add “things to investigate”; select chart type using the decision criteria herein only.
  - Output Packaging:
    - Wrap the entire Plan/Instructions in a single code block of plain text only.
    - Wrap the Initial Prompt (for downstream AI) in its own single code block of plain text only, separate from the plan/instructions.
  - Documentation and Chart Files:
    - Cite and reference the specific Application section/entry from plan-create/projects.yaml.
    - Provide full pathing to documentation and chart files when referenced.
  - Homelab Conventions:
    - Ingress, Service, PVC, and backups must be configurable via values.yaml; adhere to common Helm best practices and schema validation when noted.
  - Security:
    - No sensitive values hardcoded in chart or values.yaml; secrets must be sourced via 1Password Operator annotations and/or OnePasswordItem usage as described.

High-Level Goal:
  - Create a Helm Chart for the stated application.

Changes Tracking (Activity Logging):
  - Log all actions in the reports folder under a subfolder named after the application:
    - reports/<appname>/action-log.txt
    - reports/<appname>/tests/

Chart Type Options and Rules:
  Descriptions:  # Informational reference for average AI
    - Sub-Chart:
      - Applies only Chart.yaml and values.yaml to leverage an umbrella approach from a remote chart.
    - bjw-s Chart:
      - Use bjw-s-labs “common library” conventions with only Chart.yaml and values.yaml while adhering to bjw-s expectations.
      - Reference structure and options:
        - values.yaml baseline: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml
        - values.schema.json baseline: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.schema.json
  Determination Logic (do not invent new criteria):
    - If the application has an existing, well-maintained Helm Chart that meets homelab conventions:
      - Chart Type: Sub-Chart
    - If the application has an existing Helm Chart that does not meet homelab conventions:
      - Chart Type: bjw-s Chart
    - If the application does not have an existing Helm Chart (or it is outdated or unmaintained):
      - Chart Type: bjw-s Chart
    - If the application is a custom application without an existing Helm Chart:
      - Chart Type: bjw-s Chart
  If Sub-charting bjw-s helm chart:
    Controller and Container:
      - First controller and container must be labeled "main"
    Persistence:
      - First PVC must be labeled "data"

Config and Secret Handling:
  configMaps:
    Conditions:
      - Use ConfigMaps for non-sensitive configuration files required by the application.
      - Use Secrets for sensitive configuration files.
  Secrets:
    Conditions:
      - All secrets are provided through 1Password Operator using valueFrom: secretKeyRef (example below).
      - All secret keys in 1Password:
        - Lowercase
        - Hyphenated
        - Match wording of Key in values.yaml env (mapping convention example shown).
        - Example:
          - ROOT_PASSWORD  # environment variable name
          - root-password  # 1Password item field key
      - Required annotations for 1Password Operator on Kubernetes objects that must receive secrets:
        - annotations:
            operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
            operator.1password.io/item-name: "secrets"
      - Use existing script method to create a new 1Password vault item for application secrets (via 1Password CLI or web interface). New item category must be "Database" and support custom key/value pairs.
      - Reference tools/example-op-create.sh to produce tools/<app>-op-create.sh using the same method; place it in the tools folder.
      - Ensure no sensitive information is hardcoded in Helm templates or values.yaml.
    Example (valueFrom reference):
      - valueFrom:
          secretKeyRef:
            name: "secrets"
            key: "<key-in-1password>"
    Notes:
      - 1Password Operator can source secret data via annotations and/or OnePasswordItem CRD; ensure the flow results in a Kubernetes Secret referenced by the deployment.
      - Operator updates can trigger restarts; ensure compatibility with expected rollout behavior.

Service:
  Conditions:
    - If application requires internal access:
      - Use a Kubernetes Service and expose only internally as required.
      - Make all Service parameters configurable via values.yaml (type, ports, annotations).
      - Follow homelab conventions.
    - If not required:
      - Omit Service.

Ingress:
  Conditions:
    - If application needs external access:
      - Provide Ingress for external access only.
      - Domain: eaglepass.io (ensure host rules use this domain or configurable variants via values.yaml).
      - Make Ingress configurable via values.yaml (className, annotations, rules, tls).
      - Follow homelab conventions and modern v1 Ingress patterns with host/rules and pathType.
    - If not required:
      - Omit Ingress.

Persistence:
  Conditions:
    - If persistent storage is needed:
      - Use PVCs for data persistence.
      - Make PVC parameters configurable via values.yaml (storageClass, accessModes, size, existingClaim).
      - Follow homelab conventions.
    - If not required:
      - Omit PVCs.

Backups:
  Conditions:
    - If backups are needed:
      - Use NFS for backup storage.
      - NFS Server: 10.0.50.3
      - Place a placeholder path in values.yaml and instruct user to change it.
      - Ensure backup configuration is configurable via values.yaml and follows homelab conventions.
      - Implement CronJobs within the Helm Chart for scheduling backups.
      - CronJob schedule must be configurable via values.yaml. Default: every 15 minutes.
      - Backup retention configurable via values.yaml. Default: 7 days.
    - If not required:
      - Omit backup configuration.

Image Build and Push:
  Conditions:
    - If no external image exists and no Dockerfile is provided by the application:
      - Create a Dockerfile in apps/<app> directory.
      - Use an official compatible slim base image if possible.
      - Use build_push.sh to build and push to docker.io/brimdor/<app-name>:<tag> (default tag "latest" if unspecified).
      - Ensure the image is minimal, secure, and functional.
    - If no external image exists but a Dockerfile is provided by the application:
      - Use the provided Dockerfile.
      - Use build_push.sh to build and push to docker.io/brimdor/<app-name>:<tag> (default "latest").
      - Ensure minimal, secure, functional image.
    - If an image exists in an external registry/repo:
      - Use the existing image.

Example Applications:
  - apps/n8n
  - apps/emby
  - apps/localai

Required References (when writing the plan/instructions output):
  - plan-create/projects.yaml: Reference the specific Application entry and include full path(s) to any documentation and chart files cited.
  - For bjw-s conventions (if applicable), reference:
    - bjw-s-labs repo root for context: https://github.com/bjw-s-labs/helm-charts
    - common/values.yaml: https://github.com/bjw-s-labs/helm-charts/blob/main/charts/library/common/values.yaml
    - common/values.schema.json (schema validation notes and dereferencing context in releases): https://github.com/bjw-s-labs/helm-charts/releases
  - Helm Best Practices:
    - Charts guide and values/schema behavior to justify values.yaml configurability and schema usage: https://helm.sh/docs/topics/charts/
    - Best practices guide for chart design conventions: https://helm.sh/docs/chart_best_practices/

Plan/Instructions Authoring Checklist (to be followed when generating the Plan/Instructions section):
  - State the selected Chart Type with a one-line justification based strictly on the determination logic above (no additional criteria).
  - Identify required Kubernetes objects (Service, Ingress, PVC, Secrets, ConfigMaps, CronJobs for backups) strictly per the Conditions sections.
  - Specify which values must be configurable in values.yaml, referencing Helm’s values and schema behavior; do not embed credentials or sensitive data.
  - For Secrets:
    - Describe how to rely on 1Password Operator via annotations and/or OnePasswordItem to populate a Kubernetes Secret, and how workloads will reference it via valueFrom.secretKeyRef.
    - Include the exact annotation keys and example formats.
    - Instruct the creation of tools/<app>-op-create.sh based on tools/example-op-create.sh, noting 1Password item category “Database” and key naming conventions.
  - For Ingress:
    - Use networking.k8s.io/v1 and values-driven host rules for eaglepass.io; ensure annotations and TLS can be set from values.yaml per modern patterns.
  - For Backups:
    - Define NFS server 10.0.50.3, placeholder path, schedule default (15 min), retention default (7 days), all configurable.
  - Include a logging section instructing to append human-readable action notes and test artifacts to the reports/<appname>/ paths.
  - Provide explicit full paths from plan-create/projects.yaml for any documentation and chart files referenced.
  - Do not propose a directory structure; focus only on the plan and references.
  - Do not generate code; only describe steps, configurations expected in values.yaml, and references.

Initial Prompt Authoring Checklist (to be followed when generating the Initial Prompt section):
  - Address an average AI that will execute the plan autonomously.
  - Include the chosen Chart Type and concise reasoning based on the defined decision logic only.
  - Enumerate the tasks to perform autonomously (without asking questions), including:
    - Configure values.yaml fields for Service/Ingress/PVC/Backups as needed.
    - Integrate 1Password Operator annotations/OnePasswordItem and reference via valueFrom.secretKeyRef with the key naming conventions.
    - Use provided image or build/push using build_push.sh and Dockerfile rules as applicable.
    - Log actions and tests to reports/<appname> paths.
  - Remind the AI not to edit the 'plan_create' folder and not to propose directories.
  - Ensure the prompt is wrapped in a single code block of plain text only.

Output Sections to Produce (exactly two, in this order):
  1) Plan/Instructions:
     - Wrap in one code block of plain text only.
     - Must require fully autonomous execution per this spec.
     - Include full paths to docs and chart files from plan-create/projects.yaml.
  2) Initial Prompt to the AI:
     - Wrap in one code block of plain text only.
     - No code artifacts; only instructions