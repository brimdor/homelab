# Doplarr

Discord bot that bridges to Radarr/Sonarr for one-click media requests.

## Why this chart looks the way it does

The upstream Doplarr image (`lscr.io/linuxserver/doplarr`) is a Clojure JVM
app that talks to Discord via a WebSocket gateway. Two long-standing
behaviors of that app surface as "errors" in the pod logs:

### 1. "Got invalid session payload, reconnecting shard 0" (WARN)

This is `discljord` (the Discord library) recovering from a stale
gateway session. It happens every 50–120 minutes in a long-lived
session and is **not** caused by anything in our cluster. The pod
itself never restarts (restartCount stays 0).

What we *do* control at the chart level:

- **`image.tag` is pinned** (`v3.8.0-ls140`). `latest` would cause the
  pod to re-roll every time the upstream image is rebuilt, which
  hard-kills the gateway session and forces an immediate reconnect —
  the very thing we are trying to avoid.
- **`terminationGracePeriodSeconds: 60`** gives the JVM time to send
  a clean WebSocket close frame on `SIGTERM` instead of being SIGKILL'd
  mid-handshake.
- **`lifecycle.preStop: sleep 15`** buys the same grace during the
  ArgoCD re-sync that triggered the termination.
- **`strategy.type: Recreate`** is intentional. With a single replica
  and a stateful Discord session, a rolling update is a race against
  the gateway's session-affinity heuristic. A clean recreate with a
  graceful shutdown is what Discord's gateway actually wants.
- **`startupProbe` / `livenessProbe`** use `pgrep` against the JVM
  process. The image does not bind a public TCP port, so a TCP-socket
  probe would always fail and the kubelet would cycle the pod every
  few minutes — which would create the invalid-session loop instead
  of fixing it. The exec probe only checks the JVM is alive, which
  catches the rare "JVM wedged" case without causing false positives.

### 2. "FATAL: Attempted to :edit-original-interaction-response with invalid parameters / code: 10015 / Unknown Webhook"

Discord expires the interaction token **15 minutes** after the user
initiates a slash command. Doplarr tries to edit its original reply
(search results) when the user clicks a result; if the user walks away
and comes back >15 min later, the token is gone and Discord returns
`10015 Unknown Webhook`. Doplarr logs this as FATAL.

This is **upstream doplarr behavior** — it does not catch the 10015
gracefully. The chart cannot patch the application code. The mitigations
we *can* apply:

- Keep the pod up and stable (Issue 1 above) so users are more likely
  to complete the request flow within the 15-min window.
- `resources.requests` ensure the JVM is never throttled or OOM-killed
  mid-request, which would force users to start over.

If this FATAL becomes user-visible noise, the proper long-term fix is
upstream — file an issue against
[github.com/kiranshila/Doplarr](https://github.com/kiranshila/Doplarr).

### 3. "Non 403 error on request ... 409 / UNIQUE constraint failed: MovieMetadata.TmdbId"

This is a **Radarr bug**, not Doplarr. When Radarr receives a duplicate
add for a movie it already tracks, its SQLite DB throws a UNIQUE
constraint failure on `MovieMetadata.TmdbId` and returns HTTP 409. Doplarr
logs the 4xx response as FATAL because the response handler treats any
non-2xx as fatal.

Out of chart scope. Track Radarr version + this upstream report
for a real fix.

## Upgrading the image

```bash
# 1. Check the latest tag the LSIO team has pushed:
curl -s https://hub.docker.com/v2/repositories/linuxserver/doplarr/tags/ \
  | python3 -c "import json,sys; [print(t['name'],t['last_updated'][:10]) for t in json.load(sys.stdin)['results']]"

# 2. Bump the tag in values.yaml and commit
$EDITOR values.yaml   # change `tag: v3.8.0-ls140` to the new tag

# 3. Commit + push
cd /home/echo/Documents/Github/homelab
git add apps/doplarr/
git commit -m "chore(doplarr): bump to vX.Y.Z-lsNNN"
git push gitea master

# 4. ArgoCD will resync automatically; verify the new pod reaches
#    "Discord connection successful" within 90s:
kubectl logs -n doplarr -l app=doplarr --tail=20
```
