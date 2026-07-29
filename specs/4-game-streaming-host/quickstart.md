# Quickstart: Game Streaming on Arcanine

A 10-minute operator runbook for the deployed `wolf` (Games-on-Whales) streaming host. For deep reference, see `docs/streaming/`.

## Prerequisites

- A Moonlight client (Moonlight Qt on Linux/macOS/Windows, Moonlight Embedded on a Steam Deck, Moonlight iOS/Android, or a Steam Link / Razer device). Install from https://moonlight-stream.org/ or your platform's app store.
- Tailscale installed on the client *and* joined to the homelab tailnet (`tail18136a.ts.net`). Install from https://tailscale.com/download/.
- The Wolf pod is `Running` on arcanine. Verify with `kubectl get pod -n wolf -o wide` (must show `arcanine`).

## Pair a Client (one-time per client)

1. Find the streaming service's MagicDNS hostname:
   ```bash
   kubectl get svc -n wolf
   # Should show a LoadBalancer service managed by the Tailscale operator
   # The hostname is `wolf.tail18136a.ts.net`
   ```

2. Open Moonlight on the client, click **Add PC manually**, and enter the hostname `wolf.tail18136a.ts.net`.

3. Moonlight will show a PIN. Open a browser (anywhere — LAN, Tailscale, or `https://wolf.eaglepass.io/pin/`) and enter the PIN. The first client paired to the host is automatically granted full permissions.

4. Moonlight will return to the app list. You should see at least **Wolf UI**, **Steam**, and **Desktop** (Xfce).

## Launch a Game (LAN)

1. From the Moonlight app list, click **Steam**.

2. Wolf will pull the Steam app image on first run (one-time, ~500MB, may take 1-2 minutes).

3. Steam Big Picture will appear. Log in with your Steam account.

4. Pick any game — Proton-compatible Windows games will run on Linux automatically. Most modern games work; the ProtonDB tier (Platinum/Gold/Silver/Bronze) gives a quick estimate.

5. Play.

## Launch a Game (Tailscale remote)

Same as LAN, but the Moonlight client connects via the tailnet instead of the LAN. The operator's L3 Ingress does WireGuard encapsulation; the experience is the same as LAN (latency dominated by the home network, not Tailscale).

## Stop a Session

Close Moonlight or press the **Quit** button in the Wolf UI. Wolf will stop the child container within 30 seconds and the RTX 3090's VRAM will be released.

## Add a New App to the Catalog

Edit `apps/wolf/configmap-wolf.yaml` — add a new `[[profiles.apps]]` block — then `git commit` and `git push`. ArgoCD will pick up the change and re-deploy Wolf (~60 seconds). See `docs/streaming/add-an-app.md`.

## Common Issues

| Issue | Cause | Fix |
|---|---|---|
| Moonlight can't find the host | Tailscale not running on client | Start Tailscale; check MagicDNS resolves `wolf.tail18136a.ts.net` |
| Black screen on first launch | Image still pulling | Wait 1-2 minutes; check `kubectl logs -n wolf <pod>` |
| No audio | PulseAudio failed to start in the spawned container | Restart the Wolf pod (`kubectl rollout restart deploy -n wolf wolf`) |
| Input lag > 100ms | Network issue, not server | Check the home network / ISP; Tailscale shows latency in the client UI |
| `docker: command not found` in spawned container | Docker socket not mounted in the spawned container | This is normal — Wolf's spawned game containers should not have Docker. Only the Wolf pod itself has the socket. |

## Deep Docs

- `docs/streaming/pair-moonlight-client.md` — detailed first-time pairing
- `docs/streaming/launch-a-game.md` — gameplay workflow
- `docs/streaming/add-an-app.md` — catalog extension
- `docs/streaming/upgrade-wolf-and-operator.md` — version bumps
- `docs/streaming/troubleshooting.md` — full issue catalog

## Architecture Summary (one-line)

A privileged K3s pod on arcanine runs Wolf, which speaks the Moonlight protocol and spawns per-session Docker containers with GPU access; the WebUI is exposed via cloudflared on `wolf.eaglepass.io`, the streaming ports are exposed into the Tailscale tailnet via the Tailscale Kubernetes Operator's L3 Ingress, and Moonlight clients connect to `wolf.tail18136a.ts.net`.
