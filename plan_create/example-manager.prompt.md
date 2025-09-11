---
mode: agent
---
# Manager Prompt (Event 1 only)

Purpose:
- Produce two outputs and add them to their respective locations for Event 2 execution by an average AI Worker Model:
  1) Worker Prompt (plain text, single code block)
  2) Worker Instructions (plain text, single code block)
- Do not perform any building or testing in Event 1.
- Gather all data exclusively from plan_create/projects.yaml and the references it cites.

Strict Requirements:
- Autonomy: Generate complete Worker Prompt and Worker Instructions without asking follow‑ups or proposing independent investigations.
- Source of Truth: Use only the matching Application entry in plan_create/projects.yaml (full paths for documentation/chart references must be cited explicitly within outputs).
- File Safety: Never modify or instruct modification of contents in the 'plan_create' folder.
- Output Packaging: Emit exactly two outputs as two separate single code blocks of plain text only; no extra code blocks or formatting.
- No Code Artifacts: Do not generate or include executable code or YAML in Event 1 outputs; only directives and instructions.
- Conventions: Respect homelab and bjw-s app-template/common library conventions, Helm chart best practices, and 1Password Operator patterns.

Environment and Domain:
- Host: ZSH shell, Kubernetes cluster managed by Argo CD, Helm CLI, 1Password CLI.
- Domain: eaglepass.io.

Event Model:
- Event 1 (this prompt): Discovery, decision, and authoring only; gather all inputs from plan_create/projects.yaml and produce the two outputs.
- Event 2 (Worker): Build and Test only; no new investigations or requests for additional information are allowed.

Chart Type Decision Logic (apply strictly):
- If a well‑maintained existing chart meets homelab conventions → Use Sub‑Chart.
- Else → Use bjw-s Chart (including if no chart exists, chart is outdated/unmaintained, or application is custom).
- If using bjw-s charts, determine the current app-template release branch and reference its common library values and schema for validation.
  - Use the current app-template release branch (format: app-template-<current-release>).
  - Reference the repo’s app-template branch root for context (no code, just references).
  - Use the common library values and values.schema.json from the corresponding app-template branch as the baseline for values and validation.

Security and Secrets (1Password Operator):
- All sensitive data must come from 1Password Operator and be referenced via Kubernetes Secret populated through OnePasswordItem and/or annotations.
- Required annotations on K8s objects receiving secrets:
  - operator.1password.io/item-path: "vaults/<vault-id>/items/<item-id>"
  - operator.1password.io/item-name: "secrets"
- Secret key naming convention: environment variable ROOT_PASSWORD maps to 1Password field root-password (lowercase, hyphenated).
- Tools: Require a tools/<app-name>-op-create.sh (based on tools/example-op-create.sh) that creates an item in the “Database” category and outputs JSON with vault and item ids, to be copied into values.yaml annotations.
- No sensitive values appear in charts or values.yaml; only references and annotations, with workloads consuming values via valueFrom.secretKeyRef.
- Operator updates may trigger restarts; ensure compatibility with rollout behavior in the Worker Instructions.

Kubernetes Objects (values‑driven):
- Service: Define only if internal access is needed; make all parameters configurable in values.yaml (type, ports, annotations).
- Ingress: Define only if external access is needed; domain eaglepass.io (configurable); use networking.k8s.io/v1 with values‑driven className, annotations, rules, and TLS; follow modern host/rules patterns and pathType.
  - Public DNS annotations to include when enabled:
    - external-dns.alpha.kubernetes.io/target: "homelab-tunnel.eaglepass.io"
    - external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
    - cert-manager.io/cluster-issuer: letsencrypt-prod
  - Private DNS annotation:
    - cert-manager.io/cluster-issuer: letsencrypt-prod
- Persistence: PVCs for data; values.yaml must control storageClass, accessModes, size, existingClaim.
- Backups: Implement CronJobs within the chart; default schedule every 15 minutes and retention 7 days; NFS Server 10.0.50.3 and a placeholder path configurable via values.yaml.
- Logging and Testing: Worker must log actions and output test artifacts under reports/<app-name>/ paths; include human‑readable notes during actions and tests.

Image Handling:
- If no external image and no Dockerfile → Worker will create Dockerfile in apps/<app-name>.
- If no external image but a Dockerfile exists → Use provided Dockerfile.
- If external image exists → Use it directly.
- When building: Worker uses build_push.sh to push to docker.io/brimdor/<app-name>:<tag> (default “latest”).

bjw-s Conventions (when applicable):
- Use app-template current release branch (app-template-<current-release>) as the baseline.
- If sub‑charting bjw-s app-template, ensure:
  - First controller and container named “main”.
  - First PVC named “data”.
- Validate values.yaml against the corresponding common values.schema.json; structure values per the common values.yaml baseline.

Helm Best Practices:
- Follow Helm charts and best practices guidance for chart composition, values design, and schema validation.

Activity Logging:
- Require Worker to append action notes to reports/<app-name>/action-log.txt and write test artifacts under reports/<app-name>/tests/.

Worker Output Artifacts (Event 2 only):
- Worker performs Build and Test only; includes error handling with loop/rollback awareness and root cause focus; logs all steps; produces evidence before proceeding.
- If gaps/missing info are encountered, Worker must create reports/assumptions/<app-name>-assumptions.md documenting assumptions made to continue.

What You Must Produce Now (Event 1):
- Output A: Worker Prompt (single code block, plain text), addressed to an average AI Worker, containing:
  - Clear mission statement and boundaries (Build/Test only; no new investigations).
  - Chart type chosen with a one‑line justification strictly per the decision logic.
  - Explicit references to data sources under plan_create/projects.yaml (use full paths).
  - Requirements to configure and validate values.yaml for Service/Ingress/PVC/Backups and 1Password Operator secrets via annotations and secretKeyRef.
  - Image handling directive based on decision matrix.
  - Logging, error handling, test evidence, and artifacts requirements.
- Output B: Worker Instructions (single code block, plain text), including:
  - Step‑by‑step tasks to build and test the chart per the chosen type and homelab conventions.
  - Exactly what must be configurable in values.yaml (Service/Ingress/PVC/Backups/Annotations/TLS/Rules/etc.) aligned to Helm schema validation.
  - 1Password Operator integration steps: creating tools/<app-name>-op-create.sh (based on tools/example-op-create.sh), making it executable, running it, and copying resulting vault/item ids into values.yaml annotations; usage of valueFrom.secretKeyRef referencing the secret created by OnePasswordItem/annotations; secret key naming conventions.
  - Backups CronJob configuration with defaults (15 minutes, retention 7 days) and NFS settings, all values‑driven.
  - Image handling actions per decision matrix.
  - Logging and testing procedures, including evidence gating and loop detection/mitigation.
  - Never edit the 'plan_create' folder; never propose directory structures.

Packaging Rules for Your Two Outputs:
- Emit exactly two code blocks in this order and nothing else then add them to their respective locations:
  1) Worker Prompt (plain text only)
    - Location: .github/prompts/<app-name>-worker.prompt.md
  2) Worker Instructions (plain text only)
    - Location: .github/instructions/<app-name>-worker.instructions.md

Checklist Before Emitting Outputs:
- Chart Type selected strictly via decision logic and stated with one‑line justification.
- All required Kubernetes objects and values.yaml configurables enumerated.
- 1Password Operator annotations, secretKeyRef use, and tools/<app-name>-op-create.sh fully specified, including expected JSON output fields and how to apply them to values.yaml.
- Ingress for eaglepass.io: modern networking.k8s.io/v1 rules, values‑driven class/annotations/rules/tls; public/private DNS annotations noted.
- Backups CronJobs with defaults and NFS 10.0.50.3 placeholder path.
- Logging to reports/<app-name>/action-log.txt and test artifacts to reports/<app-name>/tests/.
- Full paths to plan_create/projects.yaml entries and any docs/chart files from that tree are cited inside both outputs.
- No code or directory proposals; do not modify plan_create; outputs are plain text code blocks only.