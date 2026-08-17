# Doplarr_rs

Discord bot that bridges to Radarr/Sonarr for one-click media requests.
This is the **Rust rewrite** ([activexray/doplarr_rs](https://github.com/activexray/doplarr_rs))
of the original Clojure [Doplarr](https://github.com/kiranshila/Doplarr) that
previously shipped from this repo at `apps/doplarr/` (now archived under
`archived/apps/doplarr/`). The original project is archived upstream and
no longer receives updates; this chart replaces it.

## Why this exists

The original Doplarr (`lscr.io/linuxserver/doplarr`, Clojure/JVM) reached
end-of-life upstream in 2026. The Rust rewrite by `activexray` is the
active fork: it has the same Discord-slash-command UX, native support
for the legacy `RADARR__URL` / `SONARR__URL` / `DISCORD__TOKEN` env vars
(so we don't have to redo our secret wiring), and adds features
(`allow_specials`, `series_type`, `monitor_type`, `minimum_availability`)
the Clojure version never had.

## How it differs from `apps/doplarr` (the archived chart)

| Concern | `archived/apps/doplarr` (Clojure, retired) | `apps/doplarr-rs` (this) |
|---|---|---|
| Image | `lscr.io/linuxserver/doplarr:v3.8.0-ls140` | `ghcr.io/activexray/doplarr_rs:v4.6.0` |
| Language | Clojure/JVM | Rust (single static binary) |
| Namespace | `doplarr` (now pruned by ArgoCD) | `doplarr-rs` (active) |
| Config | Env vars only | `config.toml` mounted from a ConfigMap, with `${VAR}` interpolation for secrets at runtime |
| Discord library | `discljord` (JVM, needs long shutdown grace) | `twilight` (Rust, clean SIGTERM) |
| Secrets | Same 1Password items: `discord-token`, `radarr-api`, `sonarr-api` | Same 1Password items, different K8s Secret names (`discord-token-rs`, etc.) because they live in a different namespace |
| `/request` commands | `/movie`, `/series` | `/movie`, `/series` (same names; no collision now that the old bot is gone) |

## Why the TOML config (instead of env-only)

Doplarr_rs accepts the legacy Clojure env vars (`DISCORD__TOKEN`,
`SONARR__URL`, `SONARR__API`, `RADARR__URL`, `RADARR__API`, `LOG_LEVEL`)
and will run with no config file at all. We use a `config.toml` anyway
because:

1. Several of the old env vars were **removed** in the rewrite
   (`DISCORD__MAS_RESULTS`, `RADARR__LANGUAGE_PROFILE`, `SONARR__LANGUAGE_PROFILE`,
   `PARTIAL_SEASONS`, plus the per-backend `*__QUALITY_PROFILE` keys).
2. The Rust rewrite adds **new per-backend options** we want to use
   (`allow_specials`, `series_type`, `monitor_type`, `minimum_availability`,
   `allow_all_seasons`) that the Clojure env-var interface never exposed.
3. The TOML supports `${VAR}` interpolation natively (no sed wrapper needed)
   so secrets stay in 1Password, never in the chart.

## How secrets stay out of the chart

1. The ConfigMap in `templates/configmap.yaml` renders a TOML with literal
   `${DISCORD_TOKEN}`, `${RADARR_API_KEY}`, `${SONARR_API_KEY}`
   placeholders.
2. The deployment in `templates/deployment.yaml` sets those env vars via
   `secretKeyRef` against K8s Secrets in the `doplarr-rs` namespace.
3. Those K8s Secrets are created by the 1Password Connect Operator from
   the `OnePasswordItem` CRs in `templates/secrets.yaml`.
4. At process start, `doplarr_rs` reads `/config.toml`, expands every
   `${VAR}` against the environment, and connects to Discord.

There is no plaintext secret anywhere in this chart.

## Coexistence with `apps/doplarr` (migration history)

The original Doplarr chart (`apps/doplarr/`) was archived to
`archived/apps/doplarr/` once doplarr_rs was verified working in
production. The two coexisted side-by-side during the migration window
because **Discord only allows one bot to register a given slash-command
name per guild**. The migration sequence was:

1. Deploy `apps/doplarr-rs/` (this chart). Both bots run; old Clojure bot
   owns `/movie` and `/series`; new Rust bot registers the same names.
   Discord's behavior in this overlap is "last writer wins" — which is
   why we keep them on different namespaces but the **old bot's
   commands take precedence in Discord until the old pod is gone**.
2. Verify a real `/movie` and `/series` request in Discord through
   `kubectl logs -n doplarr-rs -l app=doplarr-rs --tail=20` — the
   request lands on whichever bot Discord picks for that name.
3. Move `apps/doplarr/` → `archived/apps/doplarr/`. ArgoCD prunes the
   old namespace automatically (the `root` ApplicationSet only watches
   `apps/*`, `platform/*`, `system/*`), so the old pod terminates and
   the old bot's slash-command registrations disappear from Discord
   within ~60s.
4. Update cross-references in `apps/jfa-go/README.md`,
   `apps/emby/README.md`, and `network/docs/kubernetes/applications.md`.

## Why this chart looks the way it does

- **`image.tag` is pinned** to `v4.6.0`. `latest` would roll the pod on
  every upstream image push, which severs the Discord gateway session
  and forces an immediate reconnect.
- **`command: ["/bin/doplarr"]`** runs the Rust binary directly
  (no shell wrapper), so SIGTERM from Kubernetes hits the process
  cleanly. The Nix-built image puts the binary at `/bin/doplarr`,
  *not* `/usr/local/bin/doplarr` (the LSIO convention). The old
  Clojure doplarr needed a 15s preStop sleep because `discljord`
  took ~10s to flush its gateway state; doplarr_rs (using `twilight`)
  doesn't need that — we still set `preStopSleepSeconds: 5` for
  symmetry.
- **`terminationGracePeriodSeconds: 30`** (vs. 60 in the old chart) — the
  Rust binary shuts down in <2s under normal conditions.
- **Probes are exec-based**, invoking `/bin/doplarr --help` directly.
  The Nix-built image ships **no shell** (no `/bin/sh`), so the
  `pgrep` pattern the old chart used would fail. `/bin/doplarr --help`
  exits 0 cleanly, so it's a cheap sanity check that the binary is
  present and runnable. As with the old chart, a TCP-socket probe is
  not viable — doplarr_rs does not bind a TCP port (Discord bot only;
  gateway is an outbound WebSocket).
- **No NFS volume.** Doplarr_rs is stateless — the only persistent
  state is in the user's Radarr/Sonarr instances, which it talks to
  over HTTP. The `/config.toml` mount is read-only from a ConfigMap.

## Upgrading the image

```bash
# 1. Find the latest doplarr_rs release tag:
curl -s https://api.github.com/repos/activexray/doplarr_rs/releases?per_page=5 \
  | python3 -c "import json,sys; [print(r['tag_name'], r['published_at'][:10]) for r in json.load(sys.stdin)]"

# 2. Bump the tag in values.yaml and commit
$EDITOR apps/doplarr-rs/values.yaml    # change `tag: vX.Y.Z`
$EDITOR apps/doplarr-rs/Chart.yaml    # change `appVersion: "X.Y.Z"`

# 3. Commit + push to Gitea
git add apps/doplarr-rs/
git commit -m "chore(doplarr-rs): bump to vX.Y.Z"
git push gitea master

# 4. ArgoCD will resync automatically; verify the new pod reaches
#    "Discord connection successful" within ~30s:
kubectl logs -n doplarr-rs -l app=doplarr-rs --tail=20
```

## Troubleshooting

- **"no discord_token configured"** — the `${DISCORD_TOKEN}` expansion
  failed. Check that the `discord-token-rs` Secret exists in the
  `doplarr-rs` namespace:
  ```bash
  kubectl get onepassworditems -n doplarr-rs
  kubectl get secret -n doplarr-rs
  ```
  If the Secret exists but the deployment logs this, the ConfigMap was
  rendered with `${DISCORD_TOKEN}` literal (correct) but the deployment's
  `DISCORD_TOKEN` env var is empty (broken `secretKeyRef`).

- **Commands don't appear in Discord** — wait 60s after the pod first
  becomes Ready; if still missing, check that the old `apps/doplarr`
  pod is at 0 replicas (or already archived). Discord only allows one
  app to register a given slash-command name per guild.

- **Radarr/Sonarr connection errors** — verify the cluster-internal or
  public URL in the ConfigMap is reachable from the pod:
  ```bash
  kubectl exec -n doplarr-rs -l app=doplarr-rs -- curl -sI https://radarr.eaglepass.io
  ```
