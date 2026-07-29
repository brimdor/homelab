# Launch a Game

A typical Wolf + Steam + Proton game launch workflow.

## Steps

1. **In a paired Moonlight client**, click the host. The app list
   appears.

2. **Click the *Steam* app.** Wolf will spawn a child container
   named `WolfSteam_<session-id>` (visible in `docker ps` on
   arcanine if you SSH in).

3. **Wait for Steam Big Picture** to load. First-time launch takes
   1-3 minutes (the `ghcr.io/games-on-whales/steam:edge` image is
   ~500 MB; Wolf pulls it on demand).

4. **Log in to Steam** with your account.

5. **Find your game** in the Steam library. Most modern Windows
   games run on Linux through Proton automatically.

6. **Launch.** The game starts in the containerized Sway session,
   the GStreamer pipeline captures the rendered frames, and
   Moonlight receives the encoded video.

7. **Play.** Latency should be under 100 ms perceived on the
   homelab LAN, under 150 ms over Tailscale (depending on
   upstream network).

8. **Quit the game** when done. Click *Quit Streaming* in the
   Moonlight client (or press *Stop Streaming* in the Steam
   overlay).

9. **Wolf tears down the child container.** You can verify with
   `docker ps` on arcanine — the `WolfSteam_<session-id>`
   container is gone within 30 seconds.

## Launching a specific game directly

If you want a Moonlight shortcut for a specific game (so it
appears as its own entry in the app list), edit the
`[[profiles.apps]]` block in `apps/wolf/values.yaml`'s ConfigMap:

```toml
[[profiles.apps]]
title = "Elden Ring"  # whatever the game is
image = "ghcr.io/games-on-whales/steam:edge"
mounts = [
  "/etc/wolf/profile_data/main/Steam:/home/retro:rw",
  "/mnt/user/games:/mnt/games:rw",
]
env = { STEAM_ARGS = "steam://rungameid/1245620" }  # the game's Steam app ID
```

Commit, push, wait for ArgoCD to sync (~60 seconds), and the new
app appears in Moonlight.

## Launching a non-Steam game

The Steam container can launch any executable on the mounted
`/mnt/games` directory. Two options:

1. **Add the game as a non-Steam shortcut in Steam.** This is
   the standard way; it just shows up in your library.

2. **Add the executable as its own app** with the `xfce:edge`
   image and a custom command. This is more advanced; see
   [`add-an-app.md`](add-an-app.md).

## Vulkan / DirectX / OpenGL

All three work out of the box inside the Steam container because
Wolf passes the GPU through to the child container via the
`Runtime: nvidia` Docker Engine field (set automatically by Wolf's
runner when the render node is NVIDIA).

- **Vulkan**: works. Native Linux Vulkan or via DXVK/VKD3D-Proton
  for Windows games.
- **DirectX 11 and 12**: works via DXVK (DX11) and VKD3D-Proton
  (DX12) inside Proton. Performance is near-native on the 3090.
- **OpenGL**: works natively on Linux games.

## Anti-cheat compatibility

| Anti-cheat | Status |
|---|---|
| None | ✓ All games work |
| EAC (Easy Anti-Cheat) | ✓ Most games work — EAC has a native Linux client (EAC must be enabled by the developer per-title) |
| BattlEye | ✓ Most games work — same as EAC, requires per-title enable |
| Vanguard (Riot) | ✗ Vanguard refuses to load in any container or VM (it detects hypervisors). League of Legends, Valorant, etc. will not work. **Requires a bare-metal Windows install.** |

If you have a specific game that doesn't work in Proton, check
<https://www.protondb.com/> for community reports.

## Performance tuning

If a game is stuttering, try these in order:

1. **Lower the bitrate** in Moonlight client settings (e.g. 20
   Mbps instead of 50).
2. **Set the resolution** to match your client's display
   resolution, not the source. 1080p is the sweet spot for the
   3090; 4K is possible but pushes the encoder harder.
3. **Check the network** — `ping 10.0.20.19` from the client
   (LAN) or `tailscale ping wolf.tail18136a.ts.net` (Tailscale).
   Latency spikes cause stutter.
4. **Check GPU utilization** on arcanine: `nvidia-smi`. If the
   GPU is at 99%, the game is CPU/GPU-bound (not streaming-
   bound). If the encoder utilization is high, lower the bitrate.
5. **Close other GPU users** on arcanine. If Ollama is
   running, it will compete for the 3090.
