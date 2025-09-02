---
applyTo: '**'
---
Project objective:
- Build an autonomous system to produce a Kubernetes-deployable Minecraft Bedrock "client" container that automates authentication (if needed), world creation/loading, server launch, and lifecycle (backups, upgrades, validation).
- All runtime/build/deploy inputs MUST be supplied through values.yaml keys (no hardcoded values in Dockerfile/Helm/templates/scripts). Sensitive values can be referenced but their names/flags must exist in values.yaml.
- Produce a plan that an AI agent can follow to iterate autonomously: modify code, build, test, deploy, validate, and repeat.

High-level architecture/components:
1. Container image (Dockerfile)
   - Base image, download Bedrock server release, install runtime helpers (health check, admin helper, backup tools).
   - Entrypoint script that reads configuration from mounted files/env (all configured via values.yaml) and performs: fetch world/template, apply config, authentication token setup, start server, expose admin socket for runtime commands.
2. Helm chart (templates in chart/)
   - Deployment/StatefulSet (single-replica), ConfigMap for server properties, Secrets for credentials (names provided in values.yaml), PVC for world data, Service for UDP/TCP ports, optional CronJob for backups.
   - Liveness/readiness hooks and preStop lifecycle to gracefully persist world.
3. Scripts (scripts/)
   - start-minecraft.sh (entrypoint): idempotent init, download world or generate, apply server.properties, boot server, emit health status, graceful shutdown support.
   - health-check helper, backup helper, admin interface helper (send console commands).
4. CI/CD and automation
   - Build pipeline that lints, tests, builds image, pushes image (digest pinned), runs helm lint + kubeval, deploys to cluster staging, runs integration tests, promotes to production on success.
   - Auto-update monitor (watch upstream Bedrock releases) and automated PR generation with image updates and chart bumps.

Phased plan (for autonomous AI agent to implement and iterate):

PHASE 0 — Discovery & Constraints
- Read current files in /home/coder/homelab/apps/bedrock: Chart.yaml, Dockerfile, values.yaml, templates/, scripts/.
- Identify missing inputs; create comprehensive values schema (below).
- Set constraints: single-replica server by default, world persisted on PVC, backups optional to S3/Minio, rollouts must be safe and reversible.

PHASE 1 — Define canonical values.yaml schema (ALL runtime/build/deploy values live here)
- Create a clear schema describing every key, type and usage (see "VALUES SCHEMA" section below).
- Ensure schema includes: image info, build-time flags (download URLs, license acceptance), world source, authentication tokens, resource requests/limits, PVC storage class/size, backup config, probes config, CI/CD settings, security flags, RBAC toggles, upgrade strategy, preStop/stop command config.
- Values.yaml must contain secret placeholders and secret names; actual secret contents may be provided at deploy time or via sealed secrets, but keys/names exist in values.yaml.

PHASE 2 — Dockerfile / Image design (agent tasks)
- Make Dockerfile accept build args from values.yaml (image base, bedrock version or download URL, license acceptance flag).
- Stage image: download official Bedrock server tarball (validate checksum provided via values.yaml), extract to /opt/bedrock, add entrypoint script and admin tools.
- Ensure non-root user execution; expose necessary ports via Dockerfile labels/inventory (but final exposure controlled by Helm).
- Provide image metadata labels with values from values.yaml (version, commit, build-time info).
- Create image build fingerprinting: tag with both semantic and digest; record digest in artifact outputs for deployment.

PHASE 3 — Entrypoint & scripts behavior (agent tasks)
- start-minecraft.sh responsibilities:
  - Read configuration from mounted configmap and values (via environment variables set by Helm).
  - Initialize world:
    - If values.world.source.type == "archive": download archive from values.world.source.url (credentials from values.yaml secrets), verify checksum, extract to WORLD_DIR.
    - If values.world.source.type == "template": copy template directory to WORLD_DIR.
    - If values.world.source.type == "seed": prepare an empty world seeded using server flags or helper tool (document seed limitations).
  - Apply server.properties and permissions from ConfigMap (all keys driven by values.yaml).
  - Setup authentication: if an external auth token is required, read secret name/key specified in values.yaml and configure file/token in expected path. If "auth.enabled: false" then ensure offline-mode settings are applied (and documented).
  - Start the bedrock_server binary and monitor logs; write health status to a health file for probes.
  - Implement trap handlers to respond to SIGTERM: run graceful-save sequence (run any admin "save" commands, stop server properly) — preStop hook should trigger this too.
- Provide small admin helper to send console commands into the running server (for save/backup pre-stop and on-demand admin operations).

PHASE 4 — Helm templates & Kubernetes primitives (agent tasks)
- Resource types:
  - Deployment or StatefulSet (choose StatefulSet if you want stable identity; otherwise Deployment with Recreate strategy for single replica).
  - PVC for world storage (size/storageClass from values.yaml).
  - ConfigMap for server.properties and any non-sensitive config (rendered from values.yaml keys).
  - Secrets for sensitive values; values.yaml must contain secret metadata (secretName) and, optionally, inline values if the operator wants to store directly (but recommend sealed secrets).
  - Service (UDP 19132 default, configurable via values.yaml) and optional NodePort/LoadBalancer settings.
  - CronJob for scheduled backups (schedule from values.yaml), or External backup to S3/Minio.
- Probes:
  - Liveness/readiness: implement using exec scripts that check server process and query server status (script included in image). Configure probe intervals/thresholds via values.yaml.
- Lifecycle hooks:
  - PreStop: call admin helper to gracefully stop/save. Values.yaml must include preStop command config and timeouts.
- Rolling update strategy:
  - Default to Recreate for single replica; document alternative strategies in values.yaml (e.g., maintain single pod for world continuity).
- Template all files so every value is templated from .Values.*.

PHASE 5 — Storage, backups, and migrations
- World persistence:
  - Use PVC with specified size and accessMode (values.yaml).
  - Allow optional mount of external world object via initContainer that downloads and extracts world (credentials in values.yaml secrets).
- Backups:
  - CronJob or sidecar that tars the world directory and uploads to object storage (S3/Minio) or copies to another PVC. Backups controlled by schedule, retention, compress/encrypt flags in values.yaml.
  - Backup retention and lifecycle rules in values.yaml.
- Upgrade/migration:
  - Before upgrade, run pre-upgrade job to snapshot world; specify migration hooks (scripts) in values.yaml to be run if major version change detected.

PHASE 6 — Authentication & security
- Authentication config:
  - Provide fields in values.yaml for auth.enabled (true/false), auth.method (token/xbox/none), secret metadata where token/credentials live.
  - If online Xbox Live integration is required, document that official API tokens and flows are out-of-band; values.yaml must contain placeholders but agent must validate legal/terms-of-service compliance before automating.
- Secrets handling:
  - values.yaml MUST include keys naming Kubernetes Secret objects and secret keys used. For security, agent should support sealed-secrets/HashiCorp Vault references; still the names must live in values.yaml.
- Network policy and ingress:
  - Provide values.yaml options for NetworkPolicy to restrict access, and for Service annotations for LoadBalancer/ingress if needed.

PHASE 7 — Validation, tests and linting (agent responsibilities)
- Static checks:
  - helm lint, kubeval on rendered manifests, yamllint, hadolint for Dockerfile, shellcheck for scripts.
- Unit tests:
  - Shell tests (bats) for start script logic, mocking file layout and configuration.
- Integration tests (CI):
  - Deploy to a disposable namespace in a test cluster (kind/k3s in CI) and run:
    - Health probe checks: container running, UDP port open, server returns version/uptime via query tool.
    - World validation: verify world files exist and new world is created with expected seed or template.
    - Graceful shutdown test: send TERM, ensure server stops cleanly and files are consistent.
- Security scans:
  - Trivy/Clair image scans; check for vulnerabilities and banned package lists.
- Acceptance criteria in values.yaml-driven thresholds (timeouts, expected log messages, probe results).

PHASE 8 — CI/CD pipeline & autonomous iteration loop
- Pipeline components:
  - On PR: run linters, unit tests, build image (with build args from values.yaml.build.*), run image scan, push to registry if allowed, run helm lint and render templates.
  - On merge to main: build and tag image, run integration deploy to staging namespace, run integration tests; on success, promote via Helm upgrade in production.
- Automated updates:
  - Release watch: monitor upstream bedrock release feed (values.yaml.upstream.checkInterval) and when new release detected create PR with new version and update build args.
  - Image digest pinning: store image digest in Helm values (values.yaml.image.digest).
  - Auto-rollback: if health checks fail post-upgrade within thresholds from values.yaml.rollbackThreshold, automatically rollback to last good Helm revision.
- AI agent loop for autonomous iteration:
  1. Detect change or scheduled check (e.g., upstream release or security advisory).
  2. Fork branch, update values.yaml (image tag/checksum/upstream URL).
  3. Run full CI pipeline (lint, build, tests).
  4. If CI passes, open PR; if configured for auto-merge, merge and deploy to staging.
  5. Run integration tests; on success, deploy to production using Helm with digest pin.
  6. Monitor health for N minutes (values.yaml.autodeploy.monitorWindow); if below thresholds, auto-rollback and open incident PR with logs.
  7. Record artifacts and metrics, create changelog entry (values.yaml.ci.changelogTarget).
- Failure handling: on test or deploy failure, store logs/artifacts centrally (values.yaml.ci.artifactStore) and create reproducible tickets with reproduction steps.

PHASE 9 — Observability & monitoring
- Logs: container emits structured logs; values.yaml controls log level and remote log target.
- Metrics: expose Prometheus metrics (exporter sidecar or embed), probe metrics and application-specific metrics (uptime, player count).
- Alerts: values.yaml contains alert thresholds for downtime, high error rate, backup failures.
- Dashboards: provide dashboard templates reference (document in chart README values.yaml.monitoring.*).

PHASE 10 — Documentation and runbook
- Produce chart README templates auto-filled from values.yaml keys and defaults.
- Create runbook steps for common operations: restore backup, force world import, handle server corruption, rotate credentials, run manual upgrade.
- Provide acceptance tests summary and how to run locally (minikube/kind) using values.yaml.

VALUES SCHEMA (every single value used for build/deploy MUST be listed here — agent will implement keys exactly):
Note: types shown (string/bool/int/object/list). Sensitive values are referenced by secretName/secretKey fields.

values:
  image:
    repository: string                # container image repository (e.g. myregistry/bedrock)
    tag: string                       # preferred tag (semantic) - CI will also set digest
    digest: string                    # optional pinned digest (set by pipeline)
    pullPolicy: string                # IfNotPresent/Always
    build:
      baseImage: string               # base image for Dockerfile build
      bedrock_download_url: string    # upstream tarball URL used at build-time (or runtime if prefer)
      bedrock_checksum: string        # checksum for validation
      accept_license: bool            # must be true to download official server
  replicaCount: int                   # number of replicas (default 1)
  podSecurity:
    runAsUser: int
    runAsGroup: int
    fsGroup: int
    allowRoot: bool
  resources:
    requests:
      cpu: string
      memory: string
    limits:
      cpu: string
      memory: string
  nodeSelector: object
  tolerations: list
  affinity: object

  service:
    enabled: bool
    type: string                       # ClusterIP/NodePort/LoadBalancer
    portUDP: int                       # default 19132
    portTCP: int                       # (if any)
    annotations: object

  world:
    path: string                       # mount inside container for world data (e.g., /data/world)
    source:
      type: string                     # archive|template|seed|none
      url: string                      # for archive/template
      checksum: string
      credentialsSecret:
        name: string                   # secret name containing access creds
        usernameKey: string
        passwordKey: string
      seed: string                     # if source.type == seed
      templateSubPath: string
    persist:
      pvc:
        enabled: bool
        storageClassName: string
        accessModes: list
        size: string

  serverProperties:                    # all server.properties values must be declared here
    motd: string
    serverName: string
    gamemode: string
    difficulty: string
    max-players: int
    online-mode: bool
    additional: object                  # map of other server.properties keys/values

  admin:
    rcon:
      enabled: bool
      secret:
        name: string
        key: string
      port: int
    consoleSocketPath: string           # path for local admin socket
    preStopCommands: list               # commands to run during graceful shutdown

  auth:
    enabled: bool
    method: string                      # token/xbox/none
    secret:
      name: string
      tokenKey: string
    requireTokenValidation: bool

  probes:
    liveness:
      enabled: bool
      initialDelaySeconds: int
      periodSeconds: int
      timeoutSeconds: int
      failureThreshold: int
    readiness:
      enabled: bool
      initialDelaySeconds: int
      periodSeconds: int
      timeoutSeconds: int
      successThreshold: int

  backups:
    enabled: bool
    schedule: string                    # cron schedule
    retention: int                      # number of backups to keep
    target:
      type: string                      # s3|pvc
      s3:
        bucket: string
        endpoint: string
        region: string
        credentialsSecret:
          name: string
          accessKey: string
          secretKey: string
      pvc:
        claimName: string
        path: string
    compression: string                 # gzip|none
    encrypt: bool
    encryptionKeySecret:
      name: string
      key: string

  upgrade:
    strategy: string                    # Recreate/RollingUpdate
    drainTimeoutSeconds: int
    preUpgradeJob:
      enabled: bool
      scriptConfigMapName: string       # name of job script configmap
    postUpgradeValidation:
      type: string                      # probes|integration-tests
      timeoutSeconds: int

  ci:
    enable: bool
    registry:
      url: string
      credentialsSecret:
        name: string
        usernameKey: string
        passwordKey: string
    buildArgs: object
    autoPublish: bool
    autoPromoteToProduction: bool
    monitorWindowSeconds: int
    artifactStore:
      type: string
      url: string
      credentialsSecret:
        name: string

  monitoring:
    prometheus:
      enabled: bool
      annotations: object
    logLevel: string
    remoteLog:
      enabled: bool
      endpoint: string
      secret:
        name: string

  security:
    networkPolicy:
      enabled: bool
      allowedCIDRs: list
    podDisruptionBudget:
      enabled: bool
      minAvailable: int
    secretManagement:
      strategy: string                 # kubernetes/sealed-secret/vault
      sealedSecretsKey: string

  metadata:
    chartVersion: string
    appVersion: string
    maintainer: string
    contact: string

Agent operational rules and heuristics (for autonomous iteration):
- Always run lint and unit tests before building images.
- Always pin image digests in values.yaml.image.digest after successful build; Helm releases must use digest when deploying production.
- Before any disruptive change (image major version), run a pre-upgrade snapshot; if snapshot fails, abort merge.
- For any failures in integration tests or post-deploy health checks, automatically rollback and open a detailed incident issue/PR with logs and diffs.
- Enforce "everything in values.yaml" rule: any new variable introduced in code must have an entry in values.yaml; otherwise fail build.
- Respect legal constraints: do not automate signing into third-party services without explicit operator consent in values.yaml (accept_license must be true).

Validation & acceptance criteria (automated checks the AI must perform):
- Helm lint passes and kubeval validates the rendered templates against target API version.
- Container image scans show no critical CVEs (threshold configurable in values.yaml.security.cveThreshold).
- Integration deploy: pod reaches ready state within values.yaml.probes.readiness.initialDelaySeconds + some slack.
- Health checks consistently pass for a configurable window values.yaml.ci.monitorWindowSeconds.
- World data exists at values.world.path and contains expected metadata (UUID, level.dat equivalent — verify depending on format).
- Successful graceful shutdown: server responds to preStop sequence within drainTimeoutSeconds and leaves world consistent (post-restore test succeeds).

Deliverables the agent should produce (but not code here):
- Updated/complete values.yaml (with defaults and placeholders).
- Helm chart templates updated to only read .Values.*.
- Dockerfile parameterized by build args referenced from values.yaml.
- start-minecraft.sh with idempotent init and graceful shutdown behavior.
- Tests (unit/integration), pipeline config (GitHub Actions or similar), and runbook.

Notes and risks:
- Xbox Live authentication and any "official" player authentication flows may require human approval and legal review before automating. values.yaml must contain flags for operator approval.
- Probing UDP services in Kubernetes is non-trivial; prefer in-container exec probes for accuracy.
- Single-replica server implies downtime during upgrades unless advanced migration/hand-off mechanisms are implemented.

This plan is sufficient for an AI agent to iterate autonomously: it defines where to make changes, what keys must exist in values.yaml, validation criteria, CI/CD workflow, and rollback/autonomy rules. Implementations must obey legal constraints for upstream downloads and