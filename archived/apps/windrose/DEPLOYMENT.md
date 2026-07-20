# Windrose Server Deployment History

## v0.1.0 — 2026-07-19

Pivoted to the `indifferentbroccoli/windrose-server-docker` community image,
which wraps the Windows Steam depot server (AppID 4129620) in Debian 12 +
Wine + Xvfb and downloads the server on first boot via DepotDownloader.

- **Image pinned:** `registry.eaglepass.io/windrose/windrose-server-docker:644cc3901250`
- **OCI index digest:** `sha256:644cc3901250d14a10bcd58ffdfe7b88eb2cf6c7d6ff90d6ef01b8ce0dcfa51d`
- **amd64 manifest digest:** `sha256:b72c5032a9dcfb9f7ce75241b29bb520a8a1d740b814c386b1e5aee0a3eef63f`
- **Upstream image:** `indifferentbroccoli/windrose-server-docker:latest`
- **Chart framework:** bjw-s app-template v5.0.1
- **Node:** `cyndaquil` via `hostNetwork: true` on TCP/UDP 7777
- **Persistence:** `windrose-data` PVC, 50Gi, `nfs-rwx` StorageClass, mounted at `/home/steam/server-files`
- **Secrets:** 1Password operator, item `windrose-secrets` (`faayy3w4hnmhnifqsr7pmf5xxe`), keys `invite-code`, `server-password`, `owner-name`
- **Special notes:**
  - Container starts as `root` (`runAsUser: 0`) so the image's `init.sh` can `usermod` the steam user to the requested PUID/PGID and then `su - steam` before launching Wine.
  - `UPDATE_ON_START: "false"` avoids re-downloading the full ~3 GB server on every pod restart.
  - Startup/liveness/readiness probes use the image's own `pgrep wine` exec probe with a 5-minute startup budget.
  - Canary chart uses `replicas: 0` and a separate PVC (`windrose-canary-data`) so it can be scaled to 1 for smoke tests without conflicting with production.

### Verification status

- `helm lint` and `helm template` pass for both `apps/windrose` and `apps/windrose-canary`.
- Live cluster deploy and end-to-end game-client connection were NOT completed in this implementation pass; they are gated on registry push + ArgoCD sync by Vanguard (Task 8 onward).
- The `scripts/windrose/verify-server-boot.sh` smoke test script is committed for use after first deploy.
