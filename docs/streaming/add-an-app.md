# Add an App to the Wolf Catalog

Wolf's app catalog is a list of `[[profiles.apps]]` entries in its
`config.toml`. The default config (in `apps/wolf/values.yaml` under
`configMaps.wolf-config.data.config.toml`) ships with three apps:
Wolf UI, Steam, and Desktop. You can add more.

## How the catalog is loaded

1. `apps/wolf/values.yaml` defines a ConfigMap with the
   `config.toml` content.
2. The ConfigMap is mounted read-only at
   `/etc/wolf/cfg/config.toml` inside the Wolf pod.
3. Wolf reads the file on startup. Changes require a pod restart.

## Steps to add a new app

1. **Pick the app from the Wildlife catalog.** Browse
   <https://games-on-whales.github.io/wildlife/> for the full
   list. Each app has a documented image, mounts, and env
   variables. Common additions:

   - `ghcr.io/games-on-whales/heroic-games-launcher:edge` —
     Epic Games / GOG / Amazon Prime
   - `ghcr.io/games-on-whales/prismlauncher:edge` — Minecraft
     multi-instance
   - `ghcr.io/games-on-whales/retroarch:edge` — retro game
     emulation
   - `ghcr.io/games-on-whales/pegasus:edge` — game library
     frontend (Pegasus / EmulationStation-style)
   - `ghcr.io/games-on-whales/lutris:edge` — game launcher
   - `ghcr.io/games-on-whales/es-de:edge` — EmulationStation-DE
   - `ghcr.io/games-on-whales/firefox:edge` — generic browser

2. **Add the `[[profiles.apps]]` block** to
   `apps/wolf/values.yaml`. Find the `configMaps.wolf-config`
   section, locate the existing `[[profiles.apps]]` blocks, and
   add a new one. Example — adding Heroic:

   ```toml
   [[profiles.apps]]
   title = "Heroic"
   image = "ghcr.io/games-on-whales/heroic-games-launcher:edge"
   mounts = [
     "/etc/wolf/profile_data/main/Heroic:/home/retro:rw",
     "/mnt/user/games:/mnt/games:rw",
   ]
   env = {}
   ```

3. **Commit and push.** ArgoCD will sync the change.

4. **Wait for Wolf to restart.** The ConfigMap checksum change
   triggers a rolling update (the bjw-s chart auto-restarts on
   ConfigMap change).

5. **Re-pair or refresh Moonlight.** The new app appears in the
   Moonlight app list within 90 seconds of the Wolf pod becoming
   Ready.

## What the per-app fields mean

- `title` — shown in Moonlight's app list
- `image` — the Docker image Wolf pulls and spawns
- `mounts` — list of `host_path:container_path[:options]` bind
  mounts. The `host_path` is on the arcanine node (because of
  `hostNetwork: true`). Common host paths:
  - `/etc/wolf/profile_data/main/<app_title>/` — per-app
    persistent state. Created by Wolf on first launch.
  - `/mnt/user/games` — the game library on the NAS (you
    may need to create the directory on the NAS first).
- `env` — environment variables passed to the spawned container.
  Some GoW images expect specific env vars (e.g. `STEAM_ARGS`).
- `run_in_x11` — defaults to true. Set to false for apps that
  need raw Wayland (most don't).
- `privileged` — defaults to false. Some apps need root in the
  container (e.g. Pegasus for PS3 ISOs). Set to true carefully.

## Adding a non-Wildlife app

If you want to use a Docker image that isn't in the official
Wildlife catalog:

1. The image must be a Wayland app (most modern Linux apps are)
   or an X11 app (Wolf will use XWayland, with reduced
   performance).
2. The image must NOT need Docker access (Wolf does not pass
   `/var/run/docker.sock` to child containers).
3. The image's ENTRYPOINT must be a long-running process that
   accepts a windowed UI input. Daemon-mode services (databases,
   web servers) won't work.
4. Test the image with a `docker run` on arcanine first to
   verify it works with the NVIDIA runtime:
   ```bash
   docker run --rm --runtime=nvidia --gpus all <image>
   ```

## Removing an app

Edit the same `[[profiles.apps]]` block out of the ConfigMap
content, commit, push, wait. The app disappears from Moonlight
within 90 seconds.

Wolf does NOT delete the per-app state directory
(`/etc/wolf/profile_data/main/<removed_app>/`). To free up
space, manually remove the directory from the NFS share
after the app is no longer in the catalog.

## Adding a new profile (e.g. "Kids")

A profile is a grouping of apps. To add a *Kids* profile with a
subset of the apps:

```toml
[[profiles]]
name = "kids"

[[profiles.apps]]
title = "Steam (Kids)"
image = "ghcr.io/games-on-whales/steam:edge"
mounts = [
  "/etc/wolf/profile_data/kids/Steam:/home/retro:rw",
  "/mnt/user/games-kids:/mnt/games:rw",
]
env = { STEAM_ARGS = "-silent" }
```

The *Kids* profile appears as a separate entry in Moonlight's
profile picker, with only the apps you list.
