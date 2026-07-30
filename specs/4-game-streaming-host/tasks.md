# Tasks: Containerized Game Streaming Host on Arcanine

**Branch**: `4-game-streaming-host` | **Spec**: `specs/4-game-streaming-host/spec.md` | **Plan**: `specs/4-game-streaming-host/plan.md`

This file groups tasks by the four homelab layers (Metal, System, Platform, Apps) plus cross-cutting (Docs, Polish). Within each layer, tasks are ordered so each one can be applied and verified before the next.

> **IMPORTANT**: The Metal layer changes (kernel cmdline update on arcanine) require a node reboot and may temporarily disrupt any GPU workloads running on arcanine (Ollama, etc.). Schedule this in a maintenance window. The arcanine node will reboot as part of task M-002.

---

## Phase 0: Setup (workspace, secrets, research handoff)

- [ ] T-001 [P] Add `specs/4-game-streaming-host/research.md` as a symlink to `../../plans/research/windows-gaming-on-arcanine-report.md` so the feature dir is self-contained for the spec reader while not duplicating the research output
- [ ] T-002 [P] Create the Tailscale reusable auth key in the Tailscale admin console (https://login.tailscale.com/admin/authkeys), description "homelab-k8s-operator", reusable=true, tags=`tag:k8s`; store the value in 1Password under the existing `secrets` item as `tailscale-auth-key`
- [ ] T-003 [P] Verify the existing `platform/global-secrets/files/secret-generator/config.yaml` already has the `ts-auth-key` slot (confirmed: yes — it generates a 48-char `tskey-auth-` prefixed key); ensure the generator's `secrets` chart in 1Password has the real value
- [ ] T-004 [P] On the workstation, run `make tools` and verify `kubectl` is reachable; this is the kubectl we'll use throughout

## Phase 1: Metal layer (arcanine kernel + udev)

> These tasks run on arcanine via the existing Ansible playbook. They require a node reboot.

- [ ] M-001 Modify `metal/roles/virtualization/tasks/gpu_install_drivers.yml` to add a new task block (after the existing driver install) that appends `nvidia-drm.modeset=1` to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub` (idempotent — use `lineinfile` with `regexp: '^GRUB_CMDLINE_LINUX_DEFAULT='`), then runs `grub2-mkconfig -o /boot/grub2/grub.cfg`
- [ ] M-002 Apply the metal playbook to arcanine (`ansible-playbook -i metal/inventories/prod.yml metal/cluster.yml --limit arcanine`); the node will reboot at the end; verify post-boot with `ssh root@10.0.20.19 'cat /sys/module/nvidia_drm/parameters/modeset'` (must return `Y`) and `nvidia-smi` (must succeed)
- [ ] M-003 Verify the existing display-config role on arcanine already sets `/dev/uinput` and `/dev/uhid` to mode 0666 (`metal/roles/display_config/tasks/main.yaml` lines 89-99) — if any of these are missing, add them in this task
- [ ] M-004 Create the NFS directory `/mnt/user/wolf` on the UNRAID NAS (10.0.40.3) and set ownership to `nobody:users` (UID 99 / GID 100) so the homelab's existing NFS exports can serve it; verify with `showmount -e 10.0.40.3`

## Phase 2: System layer (cluster, GPU operator — already there, just verify)

- [ ] S-001 Run `kubectl get nodes -o wide` and confirm `arcanine` is `Ready`, has the taint `dedicated=arcanine:NoSchedule`, and has the label `nvidia.com/gpu.present=true` (set by NFD); if any are missing, document and remediate before continuing
- [ ] S-002 Run `kubectl get pods -n gpu-operator` (or the actual namespace from the install) and confirm the `nvidia-device-plugin`, `nvidia-container-toolkit`, `gpu-feature-discovery`, and `dcgm-exporter` daemonsets have a Ready pod on arcanine; if not, troubleshoot before continuing
- [ ] S-003 Run `kubectl get runtimeclass nvidia` and confirm it exists; if not, reinstall from `system/gpu-operator/`
- [ ] S-004 Run `kubectl exec -n kube-system <nvidia-device-plugin-pod-on-arcanine> -- nvidia-smi -L` to confirm the operator sees the RTX 3090 on arcanine
- [ ] S-005 Verify `kubectl get externalsecret,secretstore -A` shows the 1Password-backed SecretStore `onepassword` (or whatever name the platform uses) is healthy and `Secret/external-secrets` (or equivalent) is populated

## Phase 3: Platform layer (Tailscale operator + Wolf chart + ArgoCD)

- [ ] P-001 [P] [US-2] Create `platform/tailscale/Chart.yaml` — name `tailscale`, version `0.1.0`, no dependencies (the operator has its own CRDs)
- [ ] P-002 [P] [US-2] Create `platform/tailscale/values.yaml` — operator image tag, operatorConfig stanza with `defaultTags: ["tag:k8s-homelab"]`, OAuth client id/secret placeholders (or `authKey` if using a key-only flow), and ProxyGroup defaults
- [ ] P-003 [US-2] Create `platform/tailscale/templates/externalsecret.yaml` — pulls `tailscale-auth-key` from the existing 1Password-backed SecretStore; populates a `Secret` in the `tailscale` namespace with key `TS_AUTH_KEY`
- [ ] P-004 [US-2] Create `platform/tailscale/templates/operator.yaml` — Deployment + ServiceAccount + ClusterRole + ClusterRoleBinding for the operator, plus the `tailscale.com/v1alpha1` CRDs (or rely on the operator helm chart's CRDs; check `https://github.com/tailscale/tailscale/tree/main/operator`); reference the `TS_AUTH_KEY` secret via env
- [ ] P-005 [US-2] Create `platform/tailscale/README.md` — why the operator is here, how the auth key was provisioned, how to add a new MagicDNS hostname to the tailnet from another chart
- [ ] P-006 [US-1] [P] Create `apps/wolf/Chart.yaml` — name `wolf`, version `0.1.0`, appVersion `stable`, dependency on `app-template` v5.0.1 from bjw-s
- [ ] P-007 [US-1] [P] Create `apps/wolf/values.yaml` — the full Wolf pod spec: `runtimeClassName: nvidia`, `hostNetwork: true`, `dnsPolicy: ClusterFirstWithHostNet`, `securityContext.privileged: true`, env (`PUID=1000`, `PGID=1000`, `TZ=America/Chicago`, `WOLF_RENDER_NODE=/dev/dri/renderD128`, `WOLF_DOCKER_SOCKET=/var/run/docker.sock`, `WOLF_STOP_CONTAINER_ON_EXIT=TRUE`), toleration `dedicated=arcanine:NoSchedule`, nodeAffinity to `kubernetes.io/hostname=arcanine`, service account with no special RBAC (privileged covers it)
- [ ] P-008 [US-1] [P] Create `apps/wolf/values.yaml` persistence section — `etc-wolf` NFS hostPath to `10.0.40.3:/mnt/user/wolf` at `/etc/wolf`; `docker-socket` hostPath `/var/run/docker.sock`; `dev` hostPath `/dev`; `udev` hostPath `/run/udev`; `wolf-runtime` hostPath `/var/run/wolf` (for `wolf.sock`)
- [ ] P-009 [US-1] Create `apps/wolf/configmap-wolf.yaml` — Wolf's `/etc/wolf/cfg/config.toml` with `[[profiles]]` defining a `default` profile and `[[profiles.apps]]` listing Steam (`ghcr.io/games-on-whales/steam:edge`), Wolf UI (`ghcr.io/games-on-whales/wolf-ui:main`), and the desktop fallback (`ghcr.io/games-on-whales/xfce:edge`)
- [ ] P-010 [US-3] [P] Create `apps/wolf/templates/service.yaml` — ClusterIP on port 47989 named `webui` (the pairing WebUI only)
- [ ] P-011 [US-3] [P] Create `apps/wolf/templates/ingress.yaml` — nginx Ingress for `wolf.eaglepass.io` → `webui:47989`, cert-manager `letsencrypt-prod`, external-dns annotation `cloudflare-proxied: "true"`; the cloudflared tunnel wildcard already routes this to ingress-nginx
- [ ] P-012 [US-2] Create `apps/wolf/templates/tailscale-proxygroup.yaml` — a `tailscale.com/v1alpha1` `ProxyGroup` resource with `type: ingress`, hostname `wolf`, tags `tag:streaming`, plus a `tailscale.com/v1alpha1` `Ingress` (or annotate the streaming Service with `tailscale.com/expose: "true"` and the operator will create the proxy) for TCP 48010 + UDP 47999/48100/48200
- [ ] P-013 [US-1] [P] Create `apps/wolf/templates/networkpolicy.yaml` — Cilium NetworkPolicy: allow ingress from `ingress-nginx` namespace to port 47989 (webui); allow ingress from `tailscale` namespace (operator proxy pods) to TCP 48010 and UDP 47999/48100/48200
- [ ] P-014 [US-3] Create `apps/wolf/templates/external-secret.yaml` — pulls `wolf-webui-password` from the 1Password-backed SecretStore (or generate a random one and put it in 1Password)
- [ ] P-015 [US-1] Create `apps/wolf/README.md` — explain every env var, why `hostNetwork: true`, why `privileged: true`, the Tailscale pairing flow, the `nvidia-drm.modeset=1` prerequisite, and link to the docs
- [ ] P-016 [US-1] Run `helm dependency update apps/wolf` to pull the bjw-s `app-template` chart into `apps/wolf/charts/` (so the chart will template correctly in CI)
- [ ] P-017 [US-2] [P] Run `make git-hooks` if not already done (install pre-commit hooks)
- [ ] P-018 [US-1] [US-2] Run `pre-commit run --all-files` on the new files; fix any yamllint, helmlint, shellcheck, terraform-fmt issues
- [ ] P-019 [US-1] [US-2] Commit the new charts on the `4-game-streaming-host` branch with separate commits per chart for easy review; push to `origin` (`git push origin 4-game-streaming-host`)
- [ ] P-020 [US-1] [US-2] Wait for ArgoCD to discover the new apps via the App-of-Apps ApplicationSet and confirm `argocd app list` shows `tailscale` and `wolf` in `Synced` + `Healthy` state

## Phase 4: Apps layer (validation + smoke tests)

- [ ] A-001 [US-1] Verify the Wolf pod is on arcanine: `kubectl get pod -n wolf -o wide` (must show `arcanine`); if it landed elsewhere, the nodeAffinity is wrong
- [ ] A-002 [US-1] Verify the pod is `Running`: `kubectl get pod -n wolf` (must be `1/1 Running`); check logs with `kubectl logs -n wolf <pod>` and look for Wolf startup messages ("Wolf started" or similar)
- [ ] A-003 [US-1] Verify the GPU is bound: `kubectl exec -n wolf <pod> -- nvidia-smi -L` (must show the RTX 3090)
- [ ] A-004 [US-1] Verify the Docker socket is mounted: `kubectl exec -n wolf <pod> -- ls -la /var/run/docker.sock` (must show the socket)
- [ ] A-005 [US-1] Verify the render node is reachable: `kubectl exec -n wolf <pod> -- ls -la /dev/dri/` (must show `renderD128` or whichever card)
- [ ] A-006 [US-1] Verify Wolf is listening on 47989: `curl -k https://wolf.eaglepass.io/pin/` from a workstation on the homelab network (should return Wolf's pairing page HTML)
- [ ] A-007 [US-1] Pair a Moonlight client (Moonlight Qt on a Linux laptop, or Moonlight Embedded on a Steam Deck) with the WebUI PIN; confirm the app list shows at least "Steam", "Wolf UI", and "Desktop"
- [ ] A-008 [US-1] Launch the "Wolf UI" app from Moonlight; verify the Wolf UI app loads (it should be the per-profile launcher)
- [ ] A-009 [US-4] Launch the "Steam" app; verify the child container is spawned (`docker ps` on arcanine should show a `WolfSteam_<session>` container) and Steam Big Picture loads in the Moonlight client
- [ ] A-010 [US-4] Log in to Steam; launch a Proton-compatible game (e.g. one in the ProtonDB Platinum tier that's already owned); verify it runs at playable framerate
- [ ] A-011 [US-1] Disconnect the Moonlight client; verify the child container is stopped (`docker ps` should no longer show `WolfSteam_<session>`)
- [ ] A-012 [US-2] From a remote tailnet client (a phone on cellular with Tailscale), repeat A-007 through A-010 using the MagicDNS hostname (e.g. `wolf.tail18136a.ts.net`) instead of the LAN IP
- [ ] A-013 [US-5] Pair a second Moonlight client; launch an app in each simultaneously; verify per-session isolation (typing in client A doesn't appear in client B)
- [ ] A-014 [SC-006] Run the homelab-recon equivalent: `kubectl get nodes` (all Ready), `kubectl get pods -A | grep -v Running | grep -v Completed` (empty), `argocd app list` (all Synced+Healthy), `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health` (HEALTH_OK)
- [ ] A-015 [SC-006] Soak test: leave a single streaming session running for 24 hours; verify no crashes, no resource leaks (`nvidia-smi` shows 0 MiB VRAM when session ends), ArgoCD remains Healthy

## Phase 5: Documentation (cross-cutting)

- [ ] D-001 [P] Create `docs/streaming/README.md` — index of the streaming docs
- [ ] D-002 [P] [US-3] Create `docs/streaming/pair-moonlight-client.md` — first-time pairing flow (install Moonlight, add PC, enter PIN, save cert)
- [ ] D-003 [P] [US-1] Create `docs/streaming/launch-a-game.md` — workflow for launching a Steam/Proton game, with screenshots of the Moonlight app list and the Big Picture UI
- [ ] D-004 [P] Create `docs/streaming/add-an-app.md` — how to add a new entry to `config.toml`'s `[[profiles.apps]]` (e.g. add Pegasus, RetroArch, or Heroic)
- [ ] D-005 [P] Create `docs/streaming/upgrade-wolf-and-operator.md` — `kubectl set image` / `helm upgrade` workflow, including how to roll back
- [ ] D-006 [P] Create `docs/streaming/troubleshooting.md` — common issues: NVENC not initializing (driver/kernel mismatch), no audio (PulseAudio not started), input lag (network issue), black screen on first launch (image still pulling)
- [ ] D-007 Update `docs/getting-started/vpn-setup.md` to add a "Tailnet hostname for streaming" section that points to `wolf.tail18136a.ts.net` as the streaming service name
- [ ] D-008 Update the root `README.md` "Live Applications" or "Infrastructure" section to mention the new streaming service

## Phase 6: Polish (final validation, archive old prior art)

- [ ] X-001 Verify the archived `archived/apps/wolf/` is still the prior-art reference; do NOT delete it (the spec mentions "revive the archived chart" but the homelab pattern is to keep the archive for history). Add a comment in `apps/wolf/README.md` pointing to the archive
- [ ] X-002 Verify the archived `archived/apps/OLDsteam-headless/` is still there; do NOT delete
- [ ] X-003 Run `make test` (full Go/Terratest suite) — should pass since we're not modifying Go code
- [ ] X-004 Run `pre-commit run --all-files` one more time on the entire repo
- [ ] X-005 Confirm ArgoCD shows all apps Synced+Healthy
- [ ] X-006 Confirm the homelab recon (Metal/System/Platform/Apps all GREEN) per HOMELAB_foundational_rules.md
- [ ] X-007 Commit any final doc updates; push; open a PR on Gitea from `4-game-streaming-host` to `master` for review

## Dependencies (DAG)

```
M-001 → M-002 → M-003 → M-004
                ↓
S-001, S-002, S-003, S-004, S-005 (parallel verification, can run anytime before P-019)
                ↓
T-001, T-002, T-003, T-004 (parallel prep)
                ↓
P-001, P-002, P-003, P-004, P-005 (tailscale chart — parallel, all before P-019)
P-006, P-007, P-008, P-009, P-010, P-011, P-012, P-013, P-014, P-015, P-016 (wolf chart — parallel, all before P-019)
                ↓
P-017, P-018 (commit-prep)
                ↓
P-019 (commit + push)
                ↓
P-020 (ArgoCD discovery)
                ↓
A-001 ... A-006 (Wolf pod health verification)
                ↓
A-007 ... A-013 (Moonlight + Tailscale smoke tests)
                ↓
A-014, A-015 (recon + soak)
                ↓
D-001 ... D-008 (docs — can be drafted in parallel with A-* but committed at the end)
                ↓
X-001 ... X-007 (polish + PR)
```

## Validation Gates

- **Gate 1 (after Phase 0/1)**: Workspace is on `4-game-streaming-host` branch; Tailscale auth key in 1Password; `make tools` works
- **Gate 2 (after Phase 2)**: Arcanine boots with `nvidia-drm.modeset=Y`; NFS share exists at `/mnt/user/wolf`
- **Gate 3 (after Phase 3)**: ArgoCD shows `tailscale` and `wolf` Synced+Healthy; Wolf pod Running on arcanine
- **Gate 4 (after Phase 4)**: A-001 through A-013 all pass (LAN + Tailscale streaming work)
- **Gate 5 (after Phase 5)**: All 8 Success Criteria from spec are verified
- **Gate 6 (after Phase 6)**: 24h soak passed; all homelab layers GREEN; PR opened
