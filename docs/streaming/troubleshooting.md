# Troubleshooting

Common issues and their fixes. If your problem isn't here, check:

- `kubectl logs -n wolf <pod>` — Wolf's stdout
- `kubectl logs -n wolf <pod> -c main` — same as above (single
  container)
- `kubectl logs -n tailscale <pod>` — operator logs
- `docker ps` and `docker logs <container>` on arcanine — for
  spawned game containers
- `nvidia-smi` on arcanine — for GPU issues
- `tailscale status` on the client — for Tailscale ACL issues

## "Pod stays in Pending"

**Symptom:** `kubectl get pod -n wolf` shows `Pending`.

**Causes:**

1. Taint not tolerated — arcanine has the
   `dedicated=arcanine:NoSchedule` taint. The chart's
   `tolerations:` must match. Verify:
   ```bash
   kubectl get node arcanine -o jsonpath='{.spec.taints}'
   kubectl get pod -n wolf -o jsonpath='{.spec.tolerations}'
   ```

2. Node selector mismatch — the chart's `nodeAffinity` requires
   the pod to land on `kubernetes.io/hostname=arcanine`. Verify:
   ```bash
   kubectl get node arcanine --show-labels
   ```

3. GPU runtime class missing — `runtimeClassName: nvidia` is
   provided by the GPU operator. Verify:
   ```bash
   kubectl get runtimeclass nvidia
   kubectl get pods -n gpu-operator -l app=nvidia-device-plugin
   ```

## "CrashLoopBackOff: Permission denied on /var/run/docker.sock"

**Symptom:** Wolf pod restarts every 30 seconds with
`Permission denied` errors trying to reach the Docker socket.

**Cause:** The Docker socket on arcanine is owned by `root:docker`
with mode 0660. The Wolf pod is `privileged: true` and runs as
root, so this should work. If it doesn't:

1. SSH to arcanine: `ls -la /var/run/docker.sock`
2. It should be: `srw-rw---- 1 root docker ...`
3. If it's owned by a different group, the `docker` role in
   `metal/roles/docker/tasks/main.yml` is misconfigured. Re-run
   the metal playbook against arcanine.

## "Image pull error: pull access denied for ghcr.io/games-on-whales/..."

**Symptom:** Pod stuck in `ImagePullBackOff`.

**Cause:** The cluster does not have credentials to pull from
`ghcr.io`. The default behavior of Gitea + K3s should allow
anonymous pulls of public images. If not:

1. Verify the image is public: open
   `https://github.com/games-on-whales/wolf/pkgs/container/wolf`
   in a browser.
2. If public, check the K3s registries config:
   `/etc/rancher/k3s/registries.yaml` on arcanine. For anonymous
   public pulls, the default is fine.

## "Wolf UI: blank screen on first launch"

**Symptom:** Moonlight connects, Wolf UI launches, but shows a
black/blank screen.

**Cause:** The Wolf UI image is being pulled for the first time.
First-time pulls of `ghcr.io/games-on-whales/wolf-ui:main` take
30-90 seconds.

**Fix:** Wait 1-2 minutes. Check `kubectl logs -n wolf <pod>` for
"image pull complete" or similar messages.

## "No audio"

**Symptom:** Video streams, but no audio.

**Cause:** Wolf's embedded PulseAudio failed to start. The
embedded PA is supervised by supervisord in the Wolf image.

**Fix:** Restart the Wolf pod: `kubectl rollout restart deploy/wolf
-n wolf`. Check the logs for `pulseaudio` startup errors.

## "Input lag > 100ms"

**Symptom:** Streaming works, but mouse/keyboard input is laggy.

**Diagnosis:**

1. **Network issue:** `ping 10.0.20.19` from the client (LAN) or
   `tailscale ping wolf.tail18136a.ts.net` (Tailscale). Latency
   should be < 30ms LAN, < 80ms Tailscale.
2. **Tailscale DERP relay:** `tailscale status` on the client
   shows whether the connection is direct or relayed. If relayed,
   the user-to-node DERP path is in use. Try restarting the
   client's Tailscale to force a re-handshake.
3. **Moonlight client settings:** Lower the bitrate (20 Mbps
   instead of 50). The lower bitrate means less buffering.
4. **CPU contention on arcanine:** SSH in, run `top`. If another
   workload (Ollama) is consuming CPU, the GStreamer pipeline
   can't keep up. Drain the other workload.

## "Vanguard anti-cheat: 'This game cannot run in a virtual machine'"

**Cause:** Riot Vanguard detects that it's running in a
container/VM and refuses to load. This is by design.

**Fix:** This chart cannot fix this. Vanguard games
(Valorant, League of Legends) require bare-metal Windows. The
Steam app container is a Linux user-namespace container; Vanguard
detects that and exits.

For a Windows VM with bare-metal GPU access, see the
`archived/specs/kvm-windows-vm/` directory (future feature, not
in this chart).

## "Tailscale: 'connection denied'"

**Symptom:** Tailscale client on a remote device can resolve
`wolf.tail18136a.ts.net` but cannot connect.

**Cause:** Tailscale ACLs in the admin console do not permit the
client's source to reach `tag:k8s-homelab` on the streaming
ports.

**Fix:** See `platform/tailscale/README.md` for the ACL snippet.
Add the user/group to the `acls` section with the right ports.

## "Tailscale: 'no peer for X'"

**Symptom:** `tailscale status` on the client shows
`no peer for wolf`.

**Cause:** The Tailscale operator hasn't created the proxy pods
yet, or the ProxyGroup is not yet created.

**Fix:**

1. Check the operator: `kubectl get pods -n tailscale`
2. Check the proxy: `kubectl get proxygroup ingress-proxies`
3. Check the service: `kubectl get svc wolf-streaming -n wolf` —
   look at the `EXTERNAL-IP`. If it's blank, the operator hasn't
   processed the Service yet.
4. Force a reconciliation: `kubectl annotate svc wolf-streaming -n
   wolf tailscale.com/hostname=wolf --overwrite`

## "Steam: 'Failed to initialize Vulkan'"

**Symptom:** When launching a game in the Steam container, you
see `Failed to initialize Vulkan` in the Steam logs.

**Cause:** Wolf's runner did not pass `Runtime: nvidia` to the
child container. This happens when the render node is not
detected as NVIDIA. Verify on arcanine:

```bash
ls -l /sys/class/drm/renderD*/device/driver
# The line containing `nvidia` is the right render node.
```

Update `WOLF_RENDER_NODE` in `apps/wolf/values.yaml` if needed.

## "argo app wolf: OutOfSync"

**Symptom:** ArgoCD shows the wolf app as OutOfSync.

**Fix:**

1. Click *Sync* in the ArgoCD UI (or `argocd app sync wolf` from
   the CLI).
2. If the sync fails, check the ArgoCD application controller
   logs: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`
3. If the diff shows a Helm template error, run `helm template
   apps/wolf` locally to debug.
