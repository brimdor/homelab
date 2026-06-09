# jfa-go — Jellyfin Account Go + JellySeerr module

User-friendly web UI for Jellyfin invites, password resets, account management,
and (via the v0.6.0+ JellySeerr module) movie/TV requests routed to Sonarr/Radarr.

**URL:** https://jfa.eaglepass.io

**Version:** hrfee/jfa-go v0.6.0 (JellySeerr release)

## What it does

- **Invites:** Send invite links to new users so they sign themselves up with a
  Jellyfin account. Profiles let you apply library access / transcoding
  settings on signup. Limits by time or number of uses.
- **Password Resets:** Users reset their own passwords via the "My Account" page.
  Integrates with Jellyfin's "Forgot Password" flow.
- **JellySeerr (v0.6.0+):** A `/jellyseerr` route inside jfa-go that lets users
  search TMDB, request a movie/show, and have it auto-routed to Sonarr (TV) or
  Radarr (movie). When the media is available, the user gets notified.
- **Ombi compatibility:** Can sync usernames/passwords/contact info with
  existing Ombi installs (we don't run Ombi, so this is dormant).

## One-time setup after first deploy

The deployment starts in "needs setup" mode. The web UI walks you through
creating the first admin account. After that:

1. **Generate a Jellyfin API key** for the jfa-go service account:
   - Log into Jellyfin as the admin
   - Administration → API Keys → "New API Key"
   - App name: `jfa-go`
   - Copy the key
   - Save it to 1Password under the `jellyfin-api` item (in vault `Server`,
     item id `k7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2`)
   - The pod will pick it up on next restart, or you can run
     `kubectl rollout restart deploy/jfa-go -n jfa-go`

2. **Tell jfa-go about Jellyfin** via the web UI's "Settings" page:
   - Jellyfin URL: `http://jellyfin.jellyfin.svc.cluster.local:8096` (auto-filled from env)
   - Jellyfin API key: paste from step 1
   - Test connection → save

3. **Tell jfa-go about Sonarr/Radarr** in the JellySeerr module settings:
   - Sonarr URL: auto-filled (`http://sonarr.sonarr.svc.cluster.local:8989`)
   - Sonarr API: auto-filled from 1P secret
   - Radarr URL: auto-filled (`http://radarr.radarr.svc.cluster.local:7878`)
   - Radarr API: auto-filled from 1P secret
   - Save → "Test" button to verify

4. **Create your first invite profile:**
   - "Invites" tab → "New Profile"
   - Configure library access, transcoding, password policy
   - Create a single-use invite for yourself
   - Click the invite link → sign up → you're in Jellyfin with the right access

## Why a separate from Doplarr

Doplarr stays. The two are complementary:

- **Doplarr** = Discord bot. You request a movie in your Discord server.
- **jfa-go / JellySeerr** = Web UI. Family members sign in at jfa.eaglepass.io
  and request from any browser. No Discord required.

Both send requests to the same Sonarr/Radarr backends.

## Architecture

```
Browser (jfa.eaglepass.io)
    │
    ├─ jfa-go UI (port 8056) — invite mgmt, password reset, accounts
    └─ jfa-go /jellyseerr (port 8056) — movie/TV request UI
            │
            ├─ Jellyfin API (jellyfin.jellyfin.svc.cluster.local:8096)
            ├─ Sonarr API (sonarr.sonarr.svc.cluster.local:8989)
            └─ Radarr API (radarr.radarr.svc.cluster.local:7878)

All backends reachable via in-cluster DNS so jfa-go never leaves k3s.
```

## Files

- `Chart.yaml` — Helm chart metadata
- `values.yaml` — Configuration (env, secrets, ingress, volumes)
- `templates/deployment.yaml` — Pod spec with env + 1P secret refs
- `templates/service.yaml` — ClusterIP service on port 8056
- `templates/ingress.yaml` — Public ingress at jfa.eaglepass.io
- `templates/secrets.yaml` — OnePasswordItem CRDs for API keys

## Rollback

```bash
kubectl delete namespace jfa-go
# or
kubectl delete application jfa-go -n argocd
```

The `jfa-go_config` NFS directory on Unraid is preserved; nothing is deleted
from there. Safe to redeploy and recover.
