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

- Kubernetes namespace `scribe` exists (the chart will not create it).
- The [1Password Operator](https://github.com/1Password/onepassword-operator)
  is installed cluster-wide and has permission to materialize Secrets in the
  `scribe` namespace.
- `standard-rwo` StorageClass is present (Longhorn or equivalent; supports
  `ReadWriteOnce` with `retain` semantics).
- `helm` v3.14+ on the operator's PATH.
- Network access from the cluster to `ghcr.io` to pull
  `ghcr.io/brimdor/scribe` (no auth required; the image is public).

## 1Password setup

Scribe pulls all sensitive config from a single Secret named `scribe-secrets`,
materialized by the 1Password Operator from an item of the same name.

1. In 1Password, create a new item:
   - **Title:** `scribe-secrets`
   - **Vault:** the same vault used for other homelab apps
     (`vaults/4uaua4a45yuhnwhehp5bwylmti/` is the common cluster-wide choice).
2. Add the following fields, one per Secret key. The Secret key matches the
   field name verbatim.

   | Field name                  | Type     | Required | Notes                                                  |
   | --------------------------- | -------- | -------- | ------------------------------------------------------ |
   | `discord-token`             | Password | Yes      | Discord bot token.                                     |
   | `discord-application-id`    | Password | Yes      | Discord application (snowflake) ID.                    |
   | `ollama-api-key`            | Password | Optional | Empty if `OLLAMA_BASE_URL` points at the in-cluster Ollama. |
   | `github-token`              | Password | Optional | Legacy fallback. Empty if GitHub App is used.          |
   | `github-app-private-key`    | Password | Optional | Base64-encoded PEM. The operator does not transform; the chart decodes. Empty if GitHub App is not used. |
   | `scribe-operator-user-ids`  | Password | Optional | Comma-separated numeric Discord user IDs allowed to issue commands. Can also be a plain env in `values.yaml`. |

3. Open the item in the Operator UI and **Copy path**. The path is the
   string `vaults/<vault-id>/items/<item-id>`.
4. **Paste into `defaultPodOptions.annotations.operator.1password.io/item-path`**
   in `apps/scribe-discord/values.yaml`, replacing the
   `vaults/<vault-id>/items/<item-id>` placeholder.
5. Set `image.tag` in `values.yaml` to an immutable tag (a version or
   `<sha256-abbrev>`). Never `latest`.

## Install

```bash
cd apps/scribe-discord
helm dependency update        # one-time: pulls app-template-5.0.1.tgz
helm install scribe-discord . --namespace scribe --create-namespace
```

Check pod readiness:

```bash
kubectl -n scribe get pods -l app.kubernetes.io/name=scribe-discord -w
kubectl -n scribe describe deploy scribe-discord
```

A successful boot shows `1/1 Running` and the exec healthcheck passing every
60 seconds. The Discord gateway handshake completes during the first
`initialDelaySeconds: 90` window of the liveness probe.

## Upgrade image

```bash
# 1. Edit values.yaml: set image.tag to the new immutable SHA.
# 2. Apply.
helm upgrade scribe-discord . --namespace scribe
```

Rolling tags cause Discord session invalidation (the bot reconnects but loses
voice channel binding; see the doplarr postmortem). **Always pin to an
immutable SHA.** The chart does not enforce this — operator discipline only.

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
