---
mode: agent
---
NUMBER 1 RULE:
- Follow this YAML exactly and perform all steps autonomously without asking for missing requirements or proposing new investigations.

You are to autonomously create a Helm Chart for the application “DeepCode” following homelab and bjw-s-labs conventions. Do not ask questions. Do not edit anything under /home/coder/homelab/plan-create/. Do not propose a directory structure.

Chart Type (decision already made using the required logic): bjw-s Chart, because there is no existing, well-maintained Helm Chart for DeepCode that meets homelab conventions.

Authoritative references you MUST use:
- Application entry: /home/coder/homelab/plan-create/projects.yaml (Application: DeepCode). Read this file to obtain the full documentation path(s) and the chart file path(s) for DeepCode, and use those exact full paths in your work.
- bjw-s-labs app-template root (select current release branch): https://github.com/bjw-s-labs/helm-charts/releases and repo: https://github.com/bjw-s-labs/helm-charts/tree/app-template-<current-release>
- bjw-s common values baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.yaml
- bjw-s common schema baseline: https://github.com/bjw-s-labs/helm-charts/blob/app-template-<current-release>/charts/library/common/values.schema.json
- Helm documentation: https://helm.sh/docs/topics/charts/ and best practices: https://helm.sh/docs/chart_best_practices/

Implementation tasks (perform all autonomously):
1) Use the bjw-s app-template approach with only Chart.yaml and values.yaml, adhering to bjw-s expectations:
   - First controller name: main
   - First container name: main
   - First PVC name: data
2) Configure values.yaml (with a validating values.schema.json) to make the following fully configurable:
   - Image: repository, tag, pullPolicy
   - Controller: type, replicas, strategy, pod annotations/labels, podSecurityContext, securityContext, resources, nodeSelector, tolerations, affinity, probes
   - Service: enabled, type, annotations, labels, ports (name, port, targetPort, protocol)
   - Ingress (networking.k8s.io/v1): enabled, className, annotations, hosts (default deepcode.eaglepass.io using the eaglepass.io domain, but fully overrideable), TLS secrets/hosts
   - Persistence: data.enabled, existingClaim, storageClass, accessModes, size, annotations, mountPath
   - ConfigMaps: non-sensitive configuration files and mounts
   - Secrets integration:
     - secretName (default “secrets”)
     - secretAnnotations to include 1Password Operator:
       operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
       operator.1password.io/item-name: "secrets"
     - env mapping:
       - Plain values for non-sensitive entries
       - Sensitive entries via:
         valueFrom.secretKeyRef.name: "secrets"
         valueFrom.secretKeyRef.key: "<lowercase-hyphenated-key>"
       - Key naming rules: lowercase, hyphenated, matching env mapping wording (e.g., ROOT_PASSWORD → root-password)
   - Backups (optional CronJob):
     - enabled
     - nfs.server: 10.0.40.3
     - nfs.path: "/replace/with/valid/nfs/path" (placeholder default)
     - schedule: "*/15 * * * *" (default)
     - retentionDays: 7 (default)
     - job: annotations, labels, resources, securityContext, successful/failed history limits
3) Do not hardcode sensitive values anywhere. All secrets must flow via 1Password Operator to a Kubernetes Secret that the workload references via valueFrom.secretKeyRef.
4) If no external image exists:
   - Create apps/deepcode/Dockerfile using an appropriate official slim base image, non-root user, minimal packages; expose the correct port (default 8080 unless overridden).
   - Create build_push.sh to build/push docker.io/brimdor/deepcode:<tag> (default “latest”).
   If an external image exists or an app-provided Dockerfile exists, use it according to the rules above.
5) Implement optional Ingress (external access only) with eaglepass.io host defaults and optional TLS; optional Service (internal) with full configurability; optional PVC; optional ConfigMaps; optional backup CronJob to NFS with retention.
6) Ensure Helm schema validation matches values and enforces required fields when features are enabled (e.g., require hosts when ingress.enabled, require size when persistence.enabled, etc.), following Helm best practices.
7) Determine the current bjw-s app-template release branch and reference it for conventions.
8) Testing and validation:
   - helm lint
   - helm template with representative values for: service-only, ingress-enabled with TLS, persistence+backups, and secrets via 1Password
   - Validate manifests use networking.k8s.io/v1 for Ingress and that controller/container are named main and first PVC is data
9) Activity logging (must do):
   - Append human-readable notes of each action to: reports/deepcode/action-log.txt
   - Save test artifacts (lint output, rendered templates, validation logs) under: reports/deepcode/tests/
10) Never modify anything in /home/coder/homelab/plan-create/.
11) Do not propose a directory structure. Create only the files and paths explicitly required by these instructions and those specified by the DeepCode entry in /home/coder/homelab/plan-create/projects.yaml.

Proceed autonomously and complete the work according