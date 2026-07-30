# Upgrade Wolf and the Tailscale Operator

Both Wolf and the Tailscale operator are versioned via Helm charts
in this repo. Upgrades are GitOps-driven: bump the version in
`Chart.yaml` and/or `values.yaml`, commit, push, and ArgoCD
syncs the change.

## Upgrade Wolf

Wolf is pinned to a tag in `apps/wolf/values.yaml`:

```yaml
image:
  repository: ghcr.io/games-on-whales/wolf
  tag: stable
  pullPolicy: Always
```

Two upgrade modes:

1. **Track the upstream `:stable` tag (default).** Wolf's
   maintainers publish `:stable` as a stable, tested version.
   The current deployment already uses this. To pull a new
   version, just restart the pod:
   ```bash
   kubectl rollout restart deploy/wolf -n wolf
   ```
   The new image is pulled on startup.

2. **Pin to a specific version** (recommended for production):
   ```yaml
   image:
     tag: "v0.1.0"  # or whatever tag the upstream release page lists
   ```
   Commit, push, and ArgoCD syncs.

To find the latest stable version, see the Wolf releases page:
<https://github.com/games-on-whales/wolf/releases>.

## Upgrade the Tailscale operator

The Tailscale operator chart version is in
`platform/tailscale/Chart.yaml`:

```yaml
dependencies:
  - name: tailscale-operator
    version: "1.86.0"
    repository: https://pkgs.tailscale.com/helmcharts
```

To upgrade:

1. Check the Tailscale operator release notes for breaking
   changes: <https://github.com/tailscale/tailscale/blob/main/cmd/k8s-operator/CHANGELOG.md>
2. Bump the version in `Chart.yaml`.
3. Run `helm dependency update platform/tailscale/` to update the
   lock file.
4. Commit and push.
5. ArgoCD syncs; the operator deployment is upgraded in place.

## Pre-upgrade checklist

- [ ] Check upstream release notes for breaking changes
- [ ] Verify the existing deployment is healthy (ArgoCD
      `Synced+Healthy` for both `wolf` and `tailscale` apps)
- [ ] If Wolf is being upgraded, drain active streaming sessions
      first: `kubectl get pods -n wolf` and check for any
      `WolfSteam_*` containers; ask users to quit
- [ ] If the Tailscale operator is being upgraded, the operator
      pod will restart; in-flight proxy connections drop for ~10
      seconds, then the new pod takes over

## Rollback

Helm keeps a history of every release in the cluster. To roll
back to a previous revision:

```bash
helm history wolf -n wolf
helm rollback wolf <revision> -n wolf
```

For ArgoCD-managed charts, the rollback is a `kubectl rollout
undo` or an ArgoCD sync to an earlier git commit.

For the Tailscale operator, the rollback is similar:
```bash
helm history tailscale -n tailscale
helm rollback tailscale <revision> -n tailscale
```

## Post-upgrade validation

After upgrading either Wolf or the Tailscale operator:

1. `kubectl get pods -n wolf` — should show `1/1 Running`
2. `kubectl get pods -n tailscale` — should show `1/1 Running`
3. `kubectl get proxygroup ingress-proxies` — should show 2/2
   Ready replicas
4. `kubectl get svc wolf-streaming -n wolf` — should show an
   `EXTERNAL-IP` (a tailnet 100.x address)
5. From a Tailscale client: `tailscale ping wolf.tail18136a.ts.net`
   should succeed
6. From the cloudflared route: `curl -k https://wolf.eaglepass.io/pin/`
   should return HTML

If any of these fail, see [`troubleshooting.md`](troubleshooting.md).
