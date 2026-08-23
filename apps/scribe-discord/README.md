# scribe-discord

Helm chart for the **Scribe Discord voice transcription bot** on the homelab
Kubernetes cluster. Scribe is an outbound-only worker — it connects to Discord's
gateway, optionally to Ollama / Codex for analysis, and optionally to GitHub for
issue publication. It additionally exposes a single, read-mostly **configuration
WebUI** at `https://scribe.eaglepass.io` for the deploying operator, gated by
Cloudflare Access (email allowlist enforced at the edge). See
[Configuration WebUI](#configuration-webui) below.

The chart uses the bjw-s `app-template` library chart v5.0.1 (the homelab
standard) and produces a single-replica Deployment with an exec-based
healthcheck, a `ReadWriteOnce` PVC for durable state, an `emptyDir` for `/tmp`,
and 1Password-Operator-sourced secrets. The WebUI binding (port 3000) is
served by a ClusterIP `Service` fronted by an `Ingress` (class `nginx`); the
Pod's `NetworkPolicy` admits traffic from the `ingress-nginx` namespace on
TCP/3000 and nothing else.

The directory `apps/scribe-discord/` is distinct from `apps/scribe/` (the
markdown vault viewer, served at `scribe.eaglepass.io`). They are separate
products with different code bases, secrets, and topology.

## Prerequisites

- Kubernetes namespace `scribe-discord` exists (the chart will not create it
  automatically; create with `kubectl create namespace scribe-discord`).
- The [1Password Operator](https://github.com/1Password/onepassword-operator)
  is installed cluster-wide and has permission to materialize Secrets in the
  `scribe-discord` namespace.
- `standard-rwo` StorageClass is present (Longhorn or equivalent; supports
  `ReadWriteOnce` with `retain` semantics).
- `helm` v3.14+ on the operator's PATH.
- Network access from the cluster to the local zot registry at
  `10.0.20.11:32309` (anonymous pull).

## 1Password setup

Scribe pulls all sensitive config from a single Secret named
`scribe-discord-secrets`, materialized by the 1Password Operator from an
item of the same name.

1. In 1Password, the item already exists at
   `vaults/4uaua4a45yuhnwhehp5bwylmti/items/fy3v2ffvtmfvnsc2mhlbdujh24`
   (title `scribe-discord-secrets`, created 2026-08-21). This is SEPARATE
   from the legacy `scribe-secrets` item
   (`icq2m4uzu6niy5o44uzckhvpem`) owned by the archived markdown-vault-viewer
   `scribe` chart.
2. Add the following fields, one per Secret key. The Secret key matches the
   field name verbatim.

   | Field name                | Type     | Required | Notes                                                  |
   | ------------------------- | -------- | -------- | ------------------------------------------------------ |
   | `DISCORD_TOKEN`           | Password | Yes      | Discord bot token.                                     |
   | `DISCORD_APPLICATION_ID`  | Password | Yes      | Discord application (snowflake) ID.                    |
   | `DISCORD_DEV_GUILD_ID`    | Password | Yes (empty-string OK) | Restrict slash-command registration to a single guild. Empty string (`""`) registers globally — see [How do I know command registration succeeded?](#how-do-i-know-command-registration-succeeded) §Prerequisites. |
   | `OPENAI_API_KEY`          | Password | Optional | Codex/OpenAI provider key.                             |
   | `OLLAMA_API_KEY`          | Password | Optional | Empty if `OLLAMA_BASE_URL` points at the in-cluster Ollama. |
   | `GITHUB_TOKEN`            | Password | Optional | Legacy fallback. Empty if GitHub App is used.          |
   | `GITHUB_APP_PRIVATE_KEY_BASE64` | Password | Optional | Base64-encoded PEM. Re-add this field AND the corresponding env entry in `values.yaml` to enable GitHub App integration. |

   Note: field names are UPPER_SNAKE_CASE per the existing 1Password item
   convention (this chart's `secretKeyRef.key` values match these field
   names verbatim). Env var names in the running pod are independent of
   the Secret key.
3. The `operator.1password.io/item-path` annotation in
   `defaultPodOptions.annotations` is pre-populated to the path above;
   no manual paste is required.
4. Set `image.tag` in `values.yaml` to an immutable tag (a version or
   `<sha256-abbrev>`). Never `latest`.

## Install

```bash
cd apps/scribe-discord
helm dependency update        # one-time: pulls app-template-5.0.1.tgz
helm install scribe-discord . --namespace scribe-discord --create-namespace
```

Check pod readiness:

```bash
kubectl -n scribe-discord get pods -l app.kubernetes.io/name=scribe-discord -w
kubectl -n scribe-discord describe deploy scribe-discord
```

A successful boot shows `1/1 Running` and the exec healthcheck passing every
60 seconds. The Discord gateway handshake completes during the first
`initialDelaySeconds: 90` window of the liveness probe.

## Upgrade image

```bash
# 1. Edit values.yaml: set image.tag to the new immutable SHA.
# 2. Apply.
helm upgrade scribe-discord . --namespace scribe-discord
```

Rolling tags cause Discord session invalidation (the bot reconnects but loses
voice channel binding; see the doplarr postmortem). **Always pin to an
immutable SHA.** The chart does not enforce this — operator discipline only.

## How do I know command registration succeeded?

`helm install` (and `helm upgrade`) renders a `pre-install,pre-upgrade` Helm
hook Job (`scribe-discord-register`) before the bot's Deployment is
installed or upgraded. The Job runs the same
`dist/scripts/register-commands.js` binary the bot ships with, against the
same `scribe-discord-secrets` Secret, so the registration is automatic — no
`docker compose run`, no `npm run commands:register`, no manual operator
follow-up.

If anything in the hook fails (bad credentials, network blip, Discord
4xx/5xx), the Job's exit code is non-zero and Helm aborts the rollout. The
bot pod is NOT deployed until the hook completes successfully.

### Verifying a successful registration

1. Read the hook Job's logs:

   ```bash
   kubectl logs -n scribe-discord job/scribe-discord-register --tail=50
   ```

   Expect a line like `Registered /scribe for the development guild.` (when
   `DISCORD_DEV_GUILD_ID` is set in the 1Password item) or `Registered
   /scribe globally.` (when it is not). Anything else, especially a
   `ScribeError(...)` line, indicates a real failure — investigate before
   retrying `helm upgrade`.

2. Re-run the release and watch the Job transition to `Complete`:

   ```bash
   helm upgrade scribe-discord . --namespace scribe-discord
   kubectl get jobs -n scribe-discord
   ```

   Expect one row `scribe-discord-register` with `COMPLETIONS 1/1`. The
   `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded`
   annotation removes the Job on success, so a missing row after a green
   release is the expected steady state.

3. In the target Discord guild, type `/scribe`. It appears within 60 seconds
   for guild-scoped registrations (when `DISCORD_DEV_GUILD_ID` is set in
   the 1Password item) or within roughly one hour for global registrations
   (this is a Discord-side propagation delay, not a chart delay).

### Prerequisites

The 1Password item must contain three Secret keys (the chart references
all three via `valueFrom.secretKeyRef`):

| Secret key            | Required | Notes                                                              |
| --------------------- | -------- | ------------------------------------------------------------------ |
| `DISCORD_TOKEN`       | Yes      | Discord bot token.                                                 |
| `DISCORD_APPLICATION_ID` | Yes   | Discord application (snowflake) ID.                                |
| `DISCORD_DEV_GUILD_ID` | Yes     | **Must be present even when running the bot globally.** Empty string (`""`) is fine — the script treats an empty value as undefined and registers globally. The bjw-s schema forbids `optional: true` on `secretKeyRef`, so a missing key (vs. an empty-string key) is a hard Job startup failure. |

To provision an empty-string `DISCORD_DEV_GUILD_ID` in the 1Password item:

```bash
op item edit 'scribe-discord-secrets' \
  'DISCORD_DEV_GUILD_ID='
```

This makes the bot register globally (no per-guild restriction).

### Disabling registration

To temporarily drop the registration Job (e.g., during a Discord-side
incident or a coordinated credential rotation), pass `false` to the
controller's `enabled` flag on the helm command line:

```bash
helm upgrade scribe-discord . --namespace scribe-discord \
  --set app-template.controllers.register.enabled=false
```

This renders zero Jobs (verified at render time). The sibling
`networkpolicies.register` NetworkPolicy still renders (using
`podSelector: app.kubernetes.io/controller: register`) so any leftover Job
pods from prior runs can still reach Discord for cleanup retries; the policy
becomes a no-op once those pods terminate.

The `app-template.commands.register.enabled` key in `values.yaml` is a
documented intent flag — it does NOT affect the rendered manifest on its
own because the bjw-s `app-template` library reads the render-time
`controllers.<name>.enabled` flag, not a sibling `commands.*.enabled`
toggle. The kill switch is the controller's own `enabled` flag.

### skipOnUpgrade escape hatch

To keep the registration running on install but skip the PUT on subsequent
upgrades, edit the literal-comment toggle in `values.yaml`:

```yaml
containers:
  register:
    # Default mode (skipOnUpgrade: false): re-PUT on every install/upgrade.
    command:
      - node
      - dist/scripts/register-commands.js
    # ---- skipOnUpgrade: true (uncomment this block and comment the block above) ----
    # command:
    #   - sh
    #   - -c
    #   - "echo 'skipOnUpgrade=true; registration skipped on upgrade' && exit 0"
```

Comment the first `command:` block and uncomment the second.
`controllers.X.command` is not a Helm-templated block, so a
`{{- if ... }}` wrapper cannot switch between the two at render time; the
literal-comment toggle is the only library-compliant way to do this. The
`app-template.commands.register.skipOnUpgrade` flag in `values.yaml` is
grep-able documentation of intent but does not affect the rendered
manifest.

### Architectural notes

- **No hand-authored `templates/` file.** The chart uses only
  `Chart.yaml` and `values.yaml`; the bjw-s `app-template` library
  renders the Job. This is mandated by the parent Helm spec's
  constitution §2.
- **Image inheritance.** The Job's container image is set via
  `controllers.register.defaultContainerOptions.image` with
  `defaultContainerOptionsStrategy: merge`. The library does not support
  `image: {}` (it rejects empty image maps at render time), so the
  image tag MUST mirror `controllers.main.containers.main.image.tag` in
  `values.yaml`. Bump in lockstep on deploys.
- **NetworkPolicy.** A sibling `networkpolicies.register` block (using
  `podSelector` rather than `controller:` to keep the policy decoupled
  from the controller's enabled state) mirrors the main controller's
  egress rules so the Job can reach Discord's REST API.

## GitHub App PEM

Scribe reads the GitHub App private key from
`/run/secrets/scribe-github-app.pem` (mode 0600, owner UID 1000) on every
`/scribe issue-propose` invocation.

- The chart expects the 1Password item field `github-app-private-key` to
  contain the **base64-encoded** PEM (not the raw PEM). The `postStart`
  lifecycle hook decodes it on pod start and writes it to the file path.
- If the field is empty, the `postStart` is a no-op and `issue-propose`
  fails with `github_app_not_configured` — no crash loop.
- To rotate the PEM, update the field in 1Password and either wait for the
  operator restart-on-change or `kubectl rollout restart deploy/scribe-discord
  -n scribe`.

## PVC retention

`retain: true` (rendered as the `helm.sh/resource-policy: keep` annotation on
the PVC) means **`helm uninstall` will leave `scribe-discord-data` behind**.
This is intentional — `/app/data` contains the SQLite database, retained
FLAC audio (no expiry per `scribe/AGENTS.md`), and the Codex OAuth cache,
all of which are irreplaceable.

To fully decommission (destructive):

```bash
kubectl delete pvc -n scribe scribe-discord-data
```

Back up `/app/data` (a `kubectl cp` snapshot of the PVC, or a Velero backup)
before deleting the PVC.

## Configuration WebUI

The Scribe process embeds a small `node:http` server (stdlib only) that
serves the configuration WebUI on TCP/3000 inside the bot Pod. The WebUI
is the **operator-facing** surface for the deployment: it lets the
operator (Chris) review and edit per-guild settings, see session
history, manage storage (audio purge), and inspect the audit log. It
does **not** start/stop/retry voice sessions and does **not** publish
GitHub issues — those paths are Discord-only.

### Topology

```
Cloudflare Access (brimdor.cloudflareaccess.com, Google IdP, allowlist)
  -> homelab-tunnel.eaglepass.io (Cloudflare Tunnel)
  -> ingress-nginx (cluster)
  -> scribe-discord ClusterIP Service (port 3000)
  -> scribe-discord Pod (container port 3000, embedded node:http)
```

- The Service is `ClusterIP` only (no `LoadBalancer`).
- The Ingress is `class: nginx`, host `scribe.eaglepass.io`, TLS via
  cert-manager (`letsencrypt-prod`); the cert is materialized in the
  `scribe-webui-tls` Secret on first successful issuance.
- The `NetworkPolicy` `policyTypes: [Ingress, Egress]` admits only
  traffic from the `ingress-nginx` namespace on TCP/3000. Direct
  pod-to-pod ingress from any other namespace is denied.
- The bot consumes the `Cf-Access-User-Email` header injected by
  Cloudflare Access. Spoofed headers on the public path are stripped
  by the Cloudflare Tunnel. The allowlist is **not** duplicated in the
  bot's code; it is the operator's responsibility to maintain the
  email allowlist in the Cloudflare Access dashboard.

### Enabling / disabling

The WebUI is controlled by the `SCRIBE_WEBUI_ENABLED` env var on the
bot container. The chart sets it to `"true"` so the WebUI is on by
default. To turn it off (e.g., during a Cloudflare-side incident),
override at install/upgrade time:

```bash
helm upgrade scribe-discord . --namespace scribe-discord \
  --set-json 'app-template.controllers.main.containers.main.env.SCRIBE_WEBUI_ENABLED={"value":"false"}'
```

When `SCRIBE_WEBUI_ENABLED=false`, the embedded server does not bind
port 3000 and the chart's `Service` and `Ingress` still render but
serve 503 from the upstream (no Pod is ready on the port). The chart
does not currently render the Service/Ingress conditionally on
`SCRIBE_WEBUI_ENABLED`; if a future change makes the Service
conditional, the existing `service.main.controller: main` annotation
keeps the library-compliant binding against the bot Pod.

### Cloudflare Access dashboard steps

1. Open the Cloudflare Zero Trust dashboard for the
   `brimdor.cloudflareaccess.com` zone.
2. Add a new application of type **Self-hosted**.
3. Application domain: `scribe.eaglepass.io`.
4. Identity providers: Google (the IdP that authenticates the
   operator's Google account).
5. Allowlist: `chrisnelsonx@gmail.com` (the only address that may
   reach the WebUI today; add new addresses here, NOT in the bot
   code).
6. Session duration: 24h (or as preferred).

The bot only enforces that the `Cf-Access-User-Email` header is
present; it does not validate the email against an allowlist. The
allowlist lives at the edge and is the sole gate.

### Health and readiness

- The existing exec-based healthcheck (`node dist/scripts/healthcheck.js`)
  remains in place; it checks the in-container readiness file
  (`/tmp/scribe-ready`) and is the source of truth for "the process
  started."
- The embedded HTTP server exposes `GET /api/v1/ready` (unauthenticated)
  and `GET /api/v1/health`. The `ready` endpoint returns `200` only when
  both the Discord client is `ready` AND the embedded server is bound.
  Operators can curl it from inside the cluster to verify the WebUI
  side of the deployment:
  ```bash
  kubectl exec -n scribe-discord deploy/scribe-discord-main -c main -- \
    curl -s http://localhost:3000/api/v1/ready
  ```

### What the WebUI does NOT do

- It does not start, stop, or retry voice sessions.
- It does not publish GitHub issues.
- It does not accept secret material as input (no API key, token, or
  password fields).
- It does not return secret material in any response. The
  `/api/v1/host-config` endpoint returns only booleans
  (`<secretName>Configured: true|false`).

## Validation

Render the chart locally and run the spec's 14-point acceptance suite.

```bash
cd apps/scribe-discord
helm dependency update
helm template scribe-discord . --namespace scribe > /tmp/scribe-discord-rendered.yaml

# 1. ONE Service (the WebUI ClusterIP)
helm template scribe-discord . -n scribe | grep -E '^kind: Service$' | wc -l       # expect 1
# 2. ONE Ingress (the WebUI ingress)
helm template scribe-discord . -n scribe | grep -E '^kind: Ingress$' | wc -l      # expect 1
# 3. Exactly one Deployment
helm template scribe-discord . -n scribe | grep -E '^kind: Deployment$' | wc -l   # expect 1
# 4. ONE containerPort entry (3000/tcp on the main container; the hook Job has none)
helm template scribe-discord . -n scribe | grep -E 'containerPort:' | wc -l       # expect 1
# 5. PVC: 10Gi, standard-rwo, retain (helm.sh/resource-policy: keep)
helm template scribe-discord . -n scribe | grep -E 'storage: "10Gi"|storageClassName: "standard-rwo"|helm.sh/resource-policy: keep' | sort -u
# 6. Probes are exec only
helm template scribe-discord . -n scribe | grep -cE 'httpGet:|tcpSocket:'  # expect 0
helm template scribe-discord . -n scribe | grep -cE 'dist/scripts/healthcheck\.js'  # expect 3
# 7. Pod securityContext
helm template scribe-discord . -n scribe | grep -cE 'runAsNonRoot: true|runAsUser: 1000|runAsGroup: 1000|fsGroup: 1000'  # expect >= 4
# 8. Container securityContext
helm template scribe-discord . -n scribe | grep -cE 'readOnlyRootFilesystem: true|allowPrivilegeEscalation: false|capabilities:|drop:'  # expect >= 4
# 9. terminationGracePeriodSeconds: 60
helm template scribe-discord . -n scribe | grep -cE 'terminationGracePeriodSeconds: 60'  # expect 1
# 10. 1Password annotations
helm template scribe-discord . -n scribe | grep -cE 'operator.1password.io/item-(name|path)'  # expect 2 (one name, one path) per pod
# 11. Secret env entries reference scribe-discord-secrets
helm template scribe-discord . -n scribe | grep -cE 'name: scribe-discord-secrets'  # expect >= 4 (one per sensitive env var + the 1Password annotation)
# 12. postStart writes the PEM
helm template scribe-discord . -n scribe | grep -cE 'base64 -d.*scribe-github-app\.pem'  # expect 1
# 13. NetworkPolicy: Ingress AND Egress; the Ingress rule matches ingress-nginx on TCP/3000
helm template scribe-discord . -n scribe | grep -E 'policyTypes:|kubernetes.io/metadata.name: ingress-nginx'  # expect both
# 14. Zero literal secrets in chart sources
grep -rE 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN' apps/scribe-discord/ --exclude-dir=charts | wc -l  # expect 0
# 15. WebUI env entries (SCRIBE_WEBUI_ENABLED, SCRIBE_PUBLIC_HOSTNAME, SCRIBE_CF_ACCESS)
helm template scribe-discord . -n scribe | grep -E 'name: SCRIBE_WEBUI_ENABLED|name: SCRIBE_PUBLIC_HOSTNAME|name: SCRIBE_CF_ACCESS'  # expect 3 names
helm template scribe-discord . -n scribe | grep -E 'value: "true"|value: scribe\.eaglepass\.io' | grep -E 'SCRIBE_WEBUI_ENABLED|SCRIBE_PUBLIC_HOSTNAME|SCRIBE_CF_ACCESS'  # expect 3 values (true, scribe.eaglepass.io, true)
```

A green run on all 15 produces a chart that satisfies every acceptance
criterion in `scribe/spec/spec-webui-configuration/spec.md` §"Acceptance
Criteria".

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `CreateContainerConfigError` | 1Password `item-path` is wrong, item is empty, or the operator cannot read the item. | Verify the annotation in `values.yaml` matches the Operator UI's "Copy path" output for the `scribe-secrets` item. Check `kubectl describe op` for the OnePasswordItem CR. |
| `ImagePullBackOff` | `image.tag` is invalid or the registry denied pull. | `kubectl get pod -n scribe-discord -o jsonpath='{.spec.containers[0].image}'`; verify the tag exists at `10.0.20.11:32309/scribe:<tag>`. |
| Liveness/readiness probe fails | Discord token invalid, or the bot is rate-limited by Discord, or the 1Password `discord-token` field is mis-keyed. | `kubectl logs -n scribe-discord deploy/scribe-discord`; the bot logs a clear `[discord] invalid token` or `[discord] rate limit exceeded` line. |
| First `scribe issue-propose` fails with `github_app_not_configured` | The `github-app-private-key` field is empty, or the postStart hasn't run yet. | Verify the 1Password field; wait one tick after pod ready and retry. |
| Codex ENOSPC in logs | `/tmp/scribe-codex-workspace` is filling the emptyDir. | `tmp.sizeLimit: 64Mi` is the current setting; raise it in `values.yaml` if the workspace regularly exceeds that. |
| PVC stuck in `Terminating` after `helm uninstall` | `helm.sh/resource-policy: keep` is doing its job (intentional). | Manual decommission only: `kubectl delete pvc -n scribe-discord scribe-discord-data`. |
| WebUI returns 502/503 | The `scribe-discord` Pod is not yet ready, or the embedded server is not yet bound. | `kubectl logs -n scribe-discord deploy/scribe-discord-main`; expect a `WebServer listening on port 3000` line within the first ~5s of pod startup. Verify `SCRIBE_WEBUI_ENABLED=true` in the rendered env. |

## Canary / dev-typed variant

The constitution notes that **there is no canary deployment environment or
canary release path** for Scribe. If a dev-typed canary is needed in the
future (e.g., to point at a developer Discord server), add the following
plain env to `values.yaml` (not a secret) before `helm install`:

```yaml
env:
  DISCORD_DEV_GUILD_ID: "<dev-server-snowflake-id>"
```

This is intentionally not in the production chart.

## References

- `scribe/spec/spec-discord-helm-deploy/spec.md` — full spec with the 1Password
  contract, risks, and acceptance criteria.
- `scribe/spec/spec-discord-helm-deploy/plan.md` — implementation plan with the
  validation block.
- `scribe/docs/container-deployment.md` — Scribe's container-deployment
  expectations (PEM path, env contract).
- `scribe/AGENTS.md` — product-level deployment topology and constraints.
- `homelab/apps/podwave/` — closest pattern reference (app-template v5.0.1
  with ingress + service; the Scribe chart now follows the same pattern
  for the configuration WebUI).
- `homelab/AGENTS.md` §"Helm Chart Standard" — why every homelab chart uses
  bjw-s app-template.
