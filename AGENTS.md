# AGENTS.md — Homelab repository guide

## Mission and source of truth

This repository is the durable source of truth for the Eagle Pass homelab. Treat every infrastructure or application change as Infrastructure as Code: understand the live symptom, encode the desired state here, validate the rendered change, commit it, and let the owning reconciler apply it. Direct cluster changes are diagnostic or emergency measures only; they are not a finished fix until the equivalent desired state is represented in this repo.

- Canonical local checkout: `~/Documents/Github/homelab`
- Canonical remote: `origin` → `git@git.eaglepass.io:ops/homelab.git`
- Deployment branch: `master`
- GitHub remote: `github` → `https://github.com/brimdor/homelab.git`; this is a backup mirror only. It is not the production deployment or reconciliation source.
- Never work from similarly named stale paths such as `~/homelab`, `~/homelab-ops`, or another clone without first proving it is the canonical checkout.

Before any work, read and obey:

1. `.agent/rules/foundational-rules.md` for completion and live-health requirements.
2. `.agent/rules/HOMELAB_applications.md` for application ownership, image builds, and the patch-over strategy.
3. Any narrower instructions in the directory being changed.

The executable manifests, inventory, and automation are authoritative when older narrative documentation or historical reports disagree. Update documentation when a change makes it inaccurate.

### Non-negotiable app and container change path

All changes to applications or running containers are made through this repository:

```text
edit apps/<app>/Chart.yaml, values.yaml, templates, or repo-owned scripts
  → render, lint, and review the desired-state diff
  → commit the change
  → push/merge it to Gitea master
  → Argo CD reads Gitea and reconciles the cluster
  → verify Argo sync, rollout, health, and application behavior
```

- Do not deploy an application change by editing a live Deployment, StatefulSet, Pod, ConfigMap, Secret, Application, or container.
- Do not use manual `helm upgrade`, `kubectl set image`, `kubectl edit`, or container-local file edits as the normal change path.
- A live emergency action is temporary mitigation only. Encode the resulting desired state in this repo, push it to Gitea, and verify Argo CD reconciliation before declaring the work complete.
- Gitea is the authoritative GitOps remote. GitHub receives a backup mirror and must not be treated as an alternate production source, promotion path, or place to land a homelab change instead of Gitea.

## Repository ownership map

| Path | Responsibility | Reconciler / execution path |
| --- | --- | --- |
| `metal/` | Bare-metal boot, Fedora installation, node configuration, k3s, kube-vip, Cilium | Ansible, invoked deliberately through `metal/Makefile` |
| `system/` | Cluster-critical services: Argo CD, ingress, certificates, DNS, tunnel, Ceph, monitoring, logs, upgrades, GPU operator, VolSync | Argo CD after the initial Ansible bootstrap |
| `platform/` | Shared hosting services: Gitea, registry, CI, identity, Grafana, Renovate, secret operators, Tailscale | Argo CD |
| `apps/` | User-facing workloads, including separate production and canary releases | Argo CD |
| `external/` | Cloudflare, ntfy, externally supplied secrets, and prerequisite namespaces | Terraform plus Ansible namespace creation |
| `network/` | OPNSense and switch configuration plus the detailed VLAN/network runbooks | Device-specific/manual application; changes are still documented here first |
| `test/` | Go/Terratest integration, smoke, and tool-version tests | `gotestsum`; most tests expect a reachable cluster |
| `.woodpecker/` | Pull-request static checks and rendered Helm diffs | Woodpecker CI |
| `scripts/`, `tools/` | Operational helpers; quality and safety vary, so inspect a script before running it | Manual |
| `docs/` | MkDocs operator and user documentation | `mkdocs serve` / `make docs` |
| `specs/`, `plans/`, `reports/` | Design records, rollout evidence, and historical operational context | Reference only; reports may describe a past state |
| `archived/` | Retired workloads and historical material | Not reconciled by Argo CD |

Moving a chart from `apps/` to `archived/apps/` is a production deletion, not housekeeping: Argo CD will prune the active release after the change reaches `master`.

## How the homelab is built

The dependency stack is:

```text
hardware
  → metal/ (Fedora + k3s + kube-vip + Cilium)
  → system/ (Argo CD, storage, ingress, DNS, certificates, tunnel, observability)
  → platform/ (Git, registry, CI, identity, shared operators)
  → apps/ (user workloads)
external/ supplies Cloudflare and selected secrets to system/platform/apps
network/ supplies the VLAN, routing, firewall, and NAS substrate
```

### Bootstrap versus steady state

- `make -C system bootstrap` runs `system/bootstrap.yml`, renders the Argo CD chart, and applies it server-side.
- On a first installation, when no running Gitea pod exists, bootstrap uses `system/argocd/values-seed.yaml` and the GitHub backup mirror only as the seed needed to create Gitea.
- As soon as Gitea is available, `system/argocd/values.yaml` points Argo CD at the in-cluster Gitea URL `http://gitea-http.gitea:3000/ops/homelab`, revision `master`. This is the production source of truth.
- Argo CD then manages its own chart as well as all other discovered charts. Avoid editing the live Argo CD Application/ApplicationSet as a durable change.

### Argo CD discovery and reconciliation

`system/argocd/values.yaml` defines Git directory generators over direct children of:

- `system/*`
- `platform/*`
- `apps/*`

The directory basename becomes both the Argo CD Application name and destination namespace. Each direct child therefore needs to be a deployable Helm chart unless explicitly excluded.

Important behavior:

- Adding `apps/foo/Chart.yaml` and `apps/foo/values.yaml` causes a new `foo` Application and namespace to appear after the commit reaches `master`.
- Deleting or moving a discovered directory removes the generated Application and enables pruning of its resources. Review PVCs, retained PVs, external resources, and backups before doing this.
- Normal applications use automated sync with `prune: true`, `selfHeal: true`, namespace creation, server-side apply, and out-of-sync-only application.
- Live `kubectl edit`, `kubectl scale`, and manual Helm changes can be reverted by self-heal. Make the Git change first whenever possible.
- `platform/external-secrets` and `system/monitoring-system` use a separate ApplicationSet with replace/skip-hook behavior for CRD-heavy charts. Preserve those exclusions and special sync options unless the CRD rollout is explicitly being redesigned.
- Existing `ignoreDifferences` rules intentionally mask controller/defaulted fields. Do not expand them merely to hide unexplained drift.

## Current metal and network model

Always verify current values in code rather than copying an old report.

- `metal/inventories/prod.yml` is the canonical production node inventory. It currently models three masters and six active workers; commented removed nodes are historical context, not active capacity.
- Node addresses occupy the cluster VLAN (`10.0.20.0/24`). The Kubernetes API virtual IP is `10.0.20.50`; Cilium advertises load balancer addresses from `10.0.20.224/27` using L2 announcements.
- `metal/roles/k3s/defaults/main.yml` pins k3s. K3s disables flannel, kube-proxy, Traefik, ServiceLB, local-storage, the Helm controller, and the built-in network policy implementation. Do not configure workloads assuming those disabled components exist.
- kube-vip provides the control-plane VIP. Cilium provides the CNI, kube-proxy replacement, LoadBalancer IP allocation, L2 announcement, and Hubble.
- `metal/nodes.yml` applies host settings, NFS utilities, container runtimes, cron jobs, and conditional virtualization/display roles. GPU/display/virtualization assumptions come from inventory host variables.
- PXE installs Fedora from the version pinned in `metal/roles/pxe_server/defaults/main.yml` and creates a raw remaining-disk partition for Ceph.
- The network is segmented into management, cluster, extra, storage, and IoT VLANs. OPNSense routes them; the checked-in network docs currently describe permissive inter-VLAN access.
- The UNRAID NAS is `10.0.40.3` on the storage VLAN and is a critical dependency for direct NFS mounts, media, and backups.

### Destructive metal boundary

The top-level `make` is a full provisioning workflow, not a test command. Its default begins with `make -C metal`, whose default runs PXE boot/provisioning. The kickstart template contains `clearpart --all` on each inventory disk. Consequently:

- Never run bare `make`, `make metal`, `make -C metal`, `make -C metal boot`, or a PXE role as routine validation.
- Resolve and review the exact inventory hosts and `limit=` before any authorized metal action.
- Treat disk, PXE, node removal, Ceph device, network, and control-plane changes as high-risk operations requiring a backup/rollback plan and live post-change validation.
- `external/Makefile` defaults to `terraform apply -auto-approve`; use `make -C external plan` first and do not apply without explicit authority.
- Inspect legacy helpers before use. In particular, reset/prune/scale scripts may be destructive, hard-coded, incomplete, or intended only as examples.

### Tooling environment

- `nix develop` provides the pinned development shell from `flake.nix`.
- `make tools` opens the Docker-based tools environment. It mounts the Docker socket, repository, SSH directory, and Terraform credentials, so treat commands inside it as host-capable rather than sandboxed.
- `make git-hooks` installs the pre-commit hook.
- `argocd` and `kubectl` are expected operator tools for reconciliation and cluster verification. Check their current context before use.
- If the Argo CD CLI is missing or has no usable context, install and configure it as part of the task rather than waiting for the user. Use existing secure credential sources or Kubernetes/core mode as appropriate; never expose login passwords or tokens in output.
- Prefer the repository-provided toolchain when host tool versions differ from CI.

## Helm and application conventions

### Chart structure

An active application usually contains:

```text
apps/<lowercase-hyphenated-name>/
  Chart.yaml
  values.yaml
  templates/        # only when the dependency cannot express a required resource
  scripts/          # app-specific build/backup/restore helpers when needed
  README.md          # app-specific operational constraints when needed
```

- Prefer a reputable official Helm chart as a pinned dependency.
- Otherwise use the pinned `bjw-s` `app-template` dependency and follow that exact version's schema.
- `app-template` 4.6.2 and 5.0.1 coexist in this repo. They are not schema-interchangeable. Read the target `Chart.yaml` and a current same-version neighbor before editing `values.yaml`.
- Several charts are custom/template-heavy. Do not force their configuration into `app-template` conventions without understanding their templates.
- Pin chart dependencies and stable production images. Mutable tags such as `latest`, `main`, and `canary` already exist, but new changes should prefer immutable release or commit tags when the image pipeline supports them.
- `Chart.lock` is generally ignored and dependencies are usually fetched at render time. Do not commit generated dependency archives or `charts/` directories unless that chart already intentionally vendors them.

### Production and canary

Production and canary directories are independent Argo CD Applications with independent namespaces, URLs, values, images, and storage. The `-canary` suffix does not trigger automatic promotion. Promotion is an explicit Git change:

1. Prove the canary image and migration behavior.
2. Copy only the intended image/configuration changes into production.
3. Preserve production hostnames, secrets, PVCs, database settings, and resource sizing.
4. Render and diff the production chart.
5. Roll back by reverting the Git commit or restoring the previous immutable image/configuration; do not rely on an unrecorded live Helm rollback for an Argo-managed release.

### External source and custom images

- External application repositories remain upstream-authoritative. Local clones are disposable workspaces for source analysis and builds, not a second source of truth.
- Do not create permanent forks or commit homelab-specific changes to upstream histories without explicit approval.
- Repository-owned deployment state—including image repository/tag, environment, mounts, probes, networking, and patches—belongs under `apps/<app>/` here.
- Self-built images are pulled from `registry.eaglepass.io` or its cluster endpoint `10.0.20.11:32309`. The source build pipeline may live in the application's own repository; this repo must still pin the deployed artifact and contain any homelab-owned build/patch logic required by the application governance rules.
- For a required upstream code fix, follow `.agent/rules/HOMELAB_applications.md`: analyze and test upstream, build the final artifact, store the patch in this repo (normally a ConfigMap), and mount it over the container path. Remove the overlay when upstream includes the fix.
- Never alter code in `~/Documents/Github/paperclip`. For a Paperclip image, first update/pull that upstream checkout, then keep all homelab deployment/build changes in this repository.

## Configuration contracts

### Secrets

New application secrets use the 1Password Connect Operator pattern documented in `.agent/workflows/build_charts.md`:

- Authorized vault identifier is recorded in that workflow; item references may be committed, secret values may not.
- 1Password field names must match `^[a-z0-9]+(-[a-z0-9]+)*$`.
- Annotate the pod with `operator.1password.io/item-path` and `operator.1password.io/item-name`, then consume keys via `secretKeyRef`.
- Never print secret values into logs, reports, diffs, comments, or responses. Treat suspicious values already present in historical scripts/configs as secrets; do not repeat or propagate them.

The repo also has older/shared secret paths:

- `platform/global-secrets` generates cluster-owned random secrets.
- `platform/external-secrets` and chart templates replicate selected global secrets.
- `external/terraform.tfvars` (ignored) supplies third-party values to Terraform, which creates the `external` Secret in `global-secrets`.
- `system/connect` installs 1Password Connect and its operator. Its bootstrap credentials/tokens must remain Kubernetes Secrets and outside Git.

Use the existing mechanism of the target component unless intentionally migrating it. Never add plaintext credentials, private keys, kubeconfigs, Terraform state, or generated tokens to Git. `metal/kubeconfig.yaml`, Terraform state/variables, `Chart.lock`, and operational context packs are ignored for this reason.

### Storage and data safety

- Rook-Ceph defines `standard-rwo` (RBD, replicated size 2, default) and `standard-rwx` (CephFS).
- `standard-rwo` is single-writer. Mount it only into the controller/container that owns the data, using `advancedMounts` for multi-controller `app-template` charts. Global mounts can cause RBD multi-attach failures.
- Stateful single-replica workloads on RWO storage often need a `Recreate` strategy so old and new pods do not overlap attachments.
- Direct NAS mounts use NFS server `10.0.40.3` and an application-specific `/mnt/user/...` path.
- Some charts reference a live `nfs-rwx` dynamic provisioner. Its definition is not present in this repo; verify that external cluster dependency before relying on it or claiming the repo can recreate it.
- `pvcHygiene` is report-only by default and only deletes old orphan PVCs in delete mode when explicitly annotated. Do not weaken that safety gate.
- A chart move, rename, namespace change, persistence-key rename, StatefulSet name change, or storage-class change can orphan or recreate storage. Record existing PVC/PV identities, reclaim policies, snapshots/backups, migration steps, and rollback before making one.
- A mounted NAS path is durable data, not disposable chart state. Argo pruning a workload does not mean its external files are safe to delete.

### Ingress, DNS, and external access

- NGINX is the ingress class; ingress-nginx also forwards TCP port 22 to Gitea SSH.
- cert-manager uses the `letsencrypt-prod` ClusterIssuer and Cloudflare DNS-01.
- Public application ingresses normally carry TLS plus ExternalDNS annotations targeting `homelab-tunnel.eaglepass.io` with Cloudflare proxying enabled.
- Cloudflared has a wildcard `*.eaglepass.io` route to ingress-nginx plus a small number of explicit non-cluster routes. Add explicit routes before the wildcard when required.
- Services should remain `ClusterIP` unless the protocol/use case requires LoadBalancer, node-level, host-network, or direct Tailscale exposure.
- NetworkPolicy-enabled apps must explicitly allow DNS and every external dependency, including NAS NFS where applicable.

## Safe change workflow

### 1. Reconnaissance

- Start with `git status --short` and preserve all unrelated user changes.
- Read the target chart, its dependency version, templates, app README, recent commits, and the closest working peer.
- Search for all consumers before renaming a namespace, secret, service, ingress hostname, PVC, storage class, image, or node label.
- For live incidents, gather events, pod logs, Argo status, storage identity, and controller state before changing anything. Do not mutate the cluster during a recon-only request.

### 2. Implement desired state

- Make the smallest coherent change in the owning layer.
- Keep production and canary state isolated.
- For image updates, inspect upstream release notes/migrations and pin the intended artifact in `values.yaml`.
- Add comments only for non-obvious operational constraints, especially data safety, controller/container mount scoping, hardware scheduling, or temporary upstream patches.
- Update relevant docs/specs when the operational contract changes.

### 3. Static validation

Use the narrowest relevant checks first:

```sh
pre-commit run --files <changed-files>
helm dependency update <chart-dir>
helm lint <chart-dir>
helm template <release> <chart-dir> --namespace <namespace> > /tmp/<release>.rendered.yaml
git status --short
git diff --check
```

Inspect the rendered YAML, not just Helm's exit code. Confirm names, namespaces, images, probes, services, ingress/TLS, security context, PVC identity, access mode, storage class, and mount ownership. Remove or leave untracked any generated dependency artifacts; do not accidentally add them.

Additional checks by area:

```sh
# Go/Terratest formatting and targeted test
gofmt -w test/<file>.go
make -C test filter='<ExactTestRegex>'
gotestsum --format testname -- -timeout 30m -run '<ExactTestRegex>'

# Ansible syntax (does not authorize execution)
ansible-playbook --syntax-check -i metal/inventories/prod.yml metal/<playbook>.yml

# Terraform
terraform -chdir=external fmt -check -recursive
make -C external plan

# Documentation
mkdocs build --strict
```

`make test` and `make smoke-test` are live integration tests and require the repo kubeconfig plus reachable services. They are not substitutes for chart rendering. Do not run the top-level default `make` as a test.

- `make test` runs the full Go/Terratest suite.
- `make smoke-test` runs the `Smoke` filter.
- `pre-commit run --all-files` runs the repository-wide safety, YAML, Helm, shell, and Terraform hooks.

Woodpecker performs pre-commit checks on pull requests and renders semantic Helm diffs for changed `system`, `platform`, or `apps` stacks. Local validation should catch failures before CI.

### 4. GitOps rollout

Unless the user explicitly authorizes commit/push/merge, stop after producing and validating the local diff. When rollout is authorized:

1. Review the final diff for secrets and destructive resource identity changes.
2. Commit with a scoped message and push/merge the change to `origin` on Gitea. Only the Gitea `master` state is deployed.
3. Force an immediate Argo CD refresh so the rollout does not wait for the normal Git polling interval:

   ```sh
   argocd app get <application> --refresh
   argocd app wait <application> --sync --health --timeout 600
   ```

   Automated sync should begin after the refresh. Use `--hard-refresh` instead of `--refresh` only when the target-manifest/repository cache is demonstrably stale. If an authorized rollout still needs an explicit sync, inspect the diff first and run `argocd app sync <application>` with any required prune behavior understood.
4. If `argocd` is unavailable or unconfigured, install/configure it and continue. `kubectl` may be used for cluster-side observation and for secure Argo CD access/core mode where appropriate; lack of a preconfigured CLI is not by itself a blocker.
5. Watch the target Application sync/health, workload rollout, events, PVCs, certificate, ingress, and app-specific health endpoint.
6. If the desired state is wrong, fix or revert it in Git. Use live intervention only to protect data or restore service while Git catches up.

### 5. Live completion gate

For deployment, troubleshooting, action, or maintenance work, `.agent/rules/foundational-rules.md` defines completion. The work is not complete until all layers are green and every discovered issue is resolved or an allowed external/human blocker is explicitly reported.

Use `metal/kubeconfig.yaml` through the repo-local environment:

```sh
export KUBECONFIG="$PWD/metal/kubeconfig.yaml"
kubectl get nodes
kubectl get pods -n kube-system
kubectl get applications -n argocd
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health
kubectl get pods -A
```

Green means:

- Metal: every expected node is `Ready`, with no pressure or hardware warnings.
- System: Ceph is `HEALTH_OK`; system pods are Running or legitimately Completed.
- Platform: every Argo CD Application is both `Synced` and `Healthy`.
- Apps: all expected workloads are ready, with no Pending, Error, CrashLoopBackOff, failed jobs, bad events, or broken health endpoints.

Also prove the changed application's actual behavior. Kubernetes readiness alone does not validate database migrations, login flows, API behavior, media/GPU functions, backup jobs, DNS, or public TLS.

## Code and repository standards

- YAML follows `.yamllint.yaml`: document start is optional, line length is not enforced, indentation must be valid, and files end with one newline.
- Helm/Kubernetes names are lowercase hyphenated. Ansible variables/files are lowercase underscored.
- Shell scripts require a shebang, executable bit, `shellcheck` cleanliness, quoted variables, and fail-fast behavior. Do not add a new script by copying the weaker style of a legacy helper.
- Go tests use package `test`, `Test<Feature>` names, `gofmt`, explicit typed/table-driven cases, actionable failures, and `t.Parallel()` only when live-resource concurrency is safe. Group imports as standard library then third-party and use aliases only for clarity or conflicts.
- Terraform must be formatted; never commit `.terraform/`, state, plans containing secrets, credentials, or `terraform.tfvars`.
- Do not ignore errors. Make failures actionable and avoid broad retries that hide persistent faults.
- Preserve the dirty worktree and unrelated changes. Never use destructive Git cleanup/reset commands to make validation pass.
- Do not commit generated kubeconfigs, logs, screenshots, Helm archives, local reports, build caches, or secret-bearing context packs.
- When editing a workflow/rule that declares `sync_locations`, update every declared copy in the same change. Do not edit global synchronized copies unless that rule itself is in scope.

## High-value reference files

| `apps/<app>/Chart.yaml`, values.yaml, templates, or repo-owned scripts
  → render, lint, and review the desired-state diff
  → commit the change
  → push/merge it to Gitea master
  → Argo CD reads Gitea and reconciles the cluster
  → verify Argo sync, rollout, health, and application behavior
```

- Do not deploy an application change by editing a live Deployment, StatefulSet, Pod, ConfigMap, Secret, Application, or container.
- Do not use manual `helm upgrade`, `kubectl set image`, `kubectl edit`, or container-local file edits as the normal change path.
- A live emergency action is temporary mitigation only. Encode the resulting desired state in this repo, push it to Gitea, and verify Argo CD reconciliation before declaring the work complete.
- Gitea is the authoritative GitOps remote. GitHub receives a backup mirror and must not be treated as an alternate production source, promotion path, or place to land a homelab change instead of Gitea.

## Agent-specific rules
- Apply mandatory homelab rules from `.agent/rules/foundational-rules.md` and app governance in `.agent/rules/HOMELAB_applications.md`.
- Cursor rules: none found (`.cursor/rules/`, `.cursorrules`). Copilot rules: none found (`.github/copilot-instructions.md`).
- Never alter any code in ~/Documents/Github/paperclip
- When building a new image for paperclip, always pull from the upstream in ~/Documents/Github/paperclip to make sure we have the latest codebase/features/etc.

## Helm charts (app-template v5.0.1)

New and migrated apps use the bjw-s `app-template` library chart v5.0.1.
Apps currently on 5.0.1:

- backlog-tracker
- budget, budget-canary
- eaglepass-news
- emby
- explorers-hub
- humbleai, humbleai-canary, humbleai-demo
- jellyfin
- jovo, jovo-canary
- nibble, nibble-canary
- omni-tools, omni-tools-canary
- openwebui
- outline
- pages, pages-canary
- podwave, podwave-canary
- postgres
- radarr
- sabnzbd
- scribe-discord
- searxng
- second-brain, second-brain-canary
- sonarr
- sporecast, sporecast-canary
- strata, strata-canary
- threads-canary
- tipsbot-canary
- wikijs
- wolf

Still on the legacy 4.6.2 layout (migration candidates; not broken, just
pre-v5):

- backlog, backlog-canary
- questarr-canary

The `*-canary` siblings mirror their stable counterparts and follow the
same template version when the stable chart is on 5.0.1.
