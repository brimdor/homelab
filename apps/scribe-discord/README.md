# scribe-discord

Helm chart for the **Scribe Discord voice transcription bot** on the homelab
Kubernetes cluster. Scribe is an outbound-only worker — it connects to Discord's
gateway, optionally to Ollama / Codex for analysis, and optionally to GitHub for
issue publication. It binds no port and serves no HTTP traffic.

The chart uses the bjw-s `app-template` library chart v5.0.1 (the homelab
standard) and produces a single-replica Deployment with an exec-based
healthcheck, a `ReadWriteOnce` PVC for durable state, an `emptyDir` for `/tmp`,
and 1Password-Operator-sourced secrets. It renders **zero Services, zero
Ingresses**, and an **egress-only** `NetworkPolicy`.

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
   | `DISCORD_DEV_GUILD_ID`    | Password | Optional | Restrict slash-command registration to a single guild. |
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

`helm install` (and `helm upgrade`) runs a `pre-install,pre-upgrade` Helm
hook Job (`scribe-discord-register`) before the bot's Deployment is
installed or upgraded. The Job runs the same
`dist/scripts/register-commands.js` binary the bot ships with, against the
same `scribe-discord-secrets` Secret, so the registration is automatic —
no `docker compose run`, no `npm run commands:register`, no manual
operator follow-up.

If anything in the hook fails (bad credentials, network blip, Discord
4xx/5xx), the Job's exit code is non-zero and Helm aborts the rollout.
The bot pod is NOT deployed until the hook completes successfully.

To verify the registration on a freshly-applied release:

1. Read the hook Job's logs:

   ```bash
   kubectl logs -n scribe job/scribe-discord-register --tail=50
   ```

   Expect a line like `Registered /scribe for the development guild.` (when
   `DISCORD_DEV_GUILD_ID` is set in the 1Password item) or `Registered
   /scribe globally.` (when it is not). Anything else, especially a
   `ScribeError(...)` line, indicates a real failure — investigate before
   retrying `helm upgrade`.

2. Re-run the release and watch the Job transition to `Complete`:

   ```bash
   helm upgrade scribe-discord . --namespace scribe
   kubectl get jobs -n scribe -l app.kubernetes.io/component=command-registration
   ```

   Expect one row `scribe-discord-register` with `COMPLETIONS 1/1`. The
   `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded`
   annotation removes the Job on success, so a missing row after a green
   release is the expected steady state.

3. In the target Discord guild, type `/scribe`. It appears within 60
   seconds for guild-scoped registrations (when `DISCORD_DEV_GUILD_ID`
   is set) or within roughly one hour for global registrations (this is
   a Discord-side propagation delay, not a chart delay).

To opt out of the automatic registration — for example during a
Discord-side incident or a coordinated credential rotation — set
`app-template.commands.register.enabled: false` in `values.yaml` and
re-render. The chart produces zero Jobs in that mode (verified byte-
identical to a baseline render without the hook). To keep the
registration running on install but skip the PUT on subsequent upgrades,
set `app-template.commands.register.skipOnUpgrade: true` instead; the
hook Job is rendered but exits 0 immediately without contacting Discord.

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

## Validation

Render the chart locally and run the spec's 14-point acceptance suite.

```bash
cd apps/scribe-discord
helm dependency update
helm template scribe-discord . --namespace scribe > /tmp/scribe-discord-rendered.yaml

# 1. Zero Services
helm template scribe-discord . -n scribe | grep -E '^kind: Service$' | wc -l       # expect 0
# 2. Zero Ingresses
helm template scribe-discord . -n scribe | grep -E '^kind: Ingress$' | wc -l      # expect 0
# 3. Exactly one Deployment
helm template scribe-discord . -n scribe | grep -E '^kind: Deployment$' | wc -l   # expect 1
# 4. No containerPort entries (Scribe binds nothing)
helm template scribe-discord . -n scribe | grep -E 'containerPort:' | wc -l       # expect 0
# 5. PVC: 10Gi, standard-rwo, retain (helm.sh/resource-policy: keep)
helm template scribe-discord . -n scribe | grep -E 'storage: "10Gi"|storageClassName: "standard-rwo"|helm.sh/resource-policy: keep' | sort -u
# 6. Probes are exec only
helm template scribe-discord . -n scribe | grep -E 'httpGet:|tcpSocket:' | wc -l  # expect 0
helm template scribe-discord . -n scribe | grep -E 'node.*healthcheck' | wc -l    # expect 3
# 7. Pod securityContext
helm template scribe-discord . -n scribe | grep -E 'runAsNonRoot: true|runAsUser: 1000|runAsGroup: 1000|fsGroup: 1000' | wc -l   # expect >= 4
# 8. Container securityContext
helm template scribe-discord . -n scribe | grep -E 'readOnlyRootFilesystem: true|allowPrivilegeEscalation: false|capabilities:|drop:' | wc -l   # expect >= 4
# 9. terminationGracePeriodSeconds: 60
helm template scribe-discord . -n scribe | grep 'terminationGracePeriodSeconds: 60' | wc -l   # expect 1
# 10. 1Password annotations
helm template scribe-discord . -n scribe | grep -E 'operator.1password.io/item-(name|path)' | wc -l   # expect 2
# 11. Secret env entries reference scribe-secrets
helm template scribe-discord . -n scribe | grep -E 'name: scribe-secrets' | wc -l   # expect >= 5 (one per sensitive env var)
# 12. postStart writes the PEM
helm template scribe-discord . -n scribe | grep -E 'base64 -d.*scribe-github-app.pem' | wc -l   # expect 1
# 13. NetworkPolicy: Egress only, no Ingress rule
helm template scribe-discord . -n scribe | grep -E 'policyTypes:|Ingress:'   # expect only policyTypes with Egress; no Ingress:
# 14. Zero literal secrets in chart sources
grep -rE 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN' apps/scribe-discord/ --exclude-dir=charts | wc -l   # expect 0
```

A green run on all 14 produces a chart that satisfies every acceptance
criterion in `scribe/spec/spec-discord-helm-deploy/spec.md` §"Acceptance Criteria".

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `CreateContainerConfigError` | 1Password `item-path` is wrong, item is empty, or the operator cannot read the item. | Verify the annotation in `values.yaml` matches the Operator UI's "Copy path" output for the `scribe-secrets` item. Check `kubectl describe op` for the OnePasswordItem CR. |
| `ImagePullBackOff` | `image.tag` is invalid or the registry denied pull. | `kubectl get pod -n scribe -o jsonpath='{.spec.containers[0].image}'`; verify the tag exists at `ghcr.io/brimdor/scribe:<tag>`. |
| Liveness/readiness probe fails | Discord token invalid, or the bot is rate-limited by Discord, or the 1Password `discord-token` field is mis-keyed. | `kubectl logs -n scribe deploy/scribe-discord`; the bot logs a clear `[discord] invalid token` or `[discord] rate limit exceeded` line. |
| First `scribe issue-propose` fails with `github_app_not_configured` | The `github-app-private-key` field is empty, or the postStart hasn't run yet. | Verify the 1Password field; wait one tick after pod ready and retry. |
| Codex ENOSPC in logs | `/tmp/scribe-codex-workspace` is filling the emptyDir. | `tmp.sizeLimit: 64Mi` is the current setting; raise it in `values.yaml` if the workspace regularly exceeds that. |
| PVC stuck in `Terminating` after `helm uninstall` | `helm.sh/resource-policy: keep` is doing its job (intentional). | Manual decommission only: `kubectl delete pvc -n scribe scribe-discord-data`. |

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
  with ingress + service; the Scribe chart deliberately omits both).
- `homelab/AGENTS.md` §"Helm Chart Standard" — why every homelab chart uses
  bjw-s app-template.
