# Homelab OS Upgrade — Conditional In-Place Runbook

**Checkpoint: 2026-10-18. Execution: BLOCKED / INCOMPLETE.**

This replaces the superseded wipe/reinstall plan; Git history retains that plan.
It defines the requirements for a future executable workflow, not a tested
playbook or authorization to bypass an unmet gate.

## Maintenance contract and authority

[Maintenance #103](https://git.eaglepass.io/ops/homelab/issues/103) tracks `A1`,
`PXE_OS_TARGET`, `K3S_CILIUM`, and prerequisite `RECOVERY_PROOF`. Its “Autonomous
maintenance resumed” addendum at `2026-10-18T21:40:19+00:00` records the current
owner direction; earlier recon-only restrictions and unanswered permission
requests are historical.

- The owner commissioned validated maintenance commits, pushes, and deployments.
  Routine maintenance Git/deployment permission and issue-update permission are
  resolved. Exact-candidate application release gates remain separate.
- Upgrade **in place, exactly one node at a time**. No wipe, formatting,
  repartitioning, reinstall, PXE, Node deletion, PVC/PV deletion, or OSD removal.
  No NAS/NFS data mutation, cleanup, write probes, export changes, or restore drills.
- Preserve Node name/UID, labels, taints, network identity, etcd membership/state,
  k3s credentials/configuration, partition and filesystem identities, Ceph FSID/OSD
  identities, and PVC/PV UIDs, bindings, and backing-volume identities. Returning
  workloads must use their existing claims.
- Expected application outage is limited to workloads on `arcanine` and
  `sprigatito`. Prove availability for every other affected workload before a
  drain or CNI transition. A PDB-respecting drain alone does not prove availability.
- The owner declined separate recovery storage, accepts cluster-local data-loss
  risk, and has physical access. **Do not ask for storage permission or a new
  recovery destination again.** This resolves the owner decision, not technical
  safety proof. Existing backup/restore and rollback gates remain unsatisfied;
  physical access, risk acceptance, cordon/drain, and local snapshot files do not
  establish recoverability. Keep blocked work checkpointed without polling.

Repository-first execution remains mandatory: implement desired state, validate
and review it, commit/push to canonical Gitea `master`, then use the owning
workflow. This documentation edit performs none of those deployment steps.

## Baseline and compatibility policy

The issue's `2026-10-18T21:37:02Z` CORE snapshot reports nine nodes, 66 healthy/synced
Applications, 52 bound PVCs, and Ceph `HEALTH_OK`. It is dated CORE evidence, not
full six-layer certification. Earlier host evidence records Fedora 39,
`6.11.9-100.fc39.x86_64`, active `dnf-automatic.timer`, and local etcd snapshots.
It also records BlueStore signatures on `sda3` alongside OS `sda2`; signatures do
not prove which OSDs are active. Reconcile conflicting historical OSD counts before
planning an outage.

Read-only host checks at `2026-10-18T22:12Z` confirmed all nine hosts still use
Fedora 39, DNF 4.21.1, Python 3.12.7, and NetworkManager 1.44.2. Every active
Ethernet connection has a persistent NetworkManager keyfile; no `/system-update`
marker was present. Root free space ranged from 31,647,371,264 to 49,328,074,752
bytes. Both GPU hosts report NVIDIA driver 560.35.05 and DKMS 3.1.1. These are
readiness observations, not package-transaction or recovery proof. The active
interfaces on `cyndaquil`, `totodile`, and `growlithe` are `enp0s31f6`, unlike the
inventory's `eno1`; preserve the actual working network identity during upgrades.

Repository pins are k3s `v1.33.6+k3s1`, Cilium `1.15.1`, and GPU Operator `24.9.2`.
There is **no proven Fedora/kernel/k3s/Cilium/GPU/CSI compatibility tuple**.

1. **Fedora:** official documentation supports/tests at most two release
   increments per upgrade. Upgrading from an EOL source is unsupported even when
   split into short hops. `39 → 41 → 43 → 44` is a candidate sequence only, not a
   supported or validated end-to-end path. Fedora 44 is the issue's candidate
   destination; reconfirm its support window and exact packages at execution.
   Verify archived repositories, signing keys, package availability, every
   intermediate release's changes, and DNF4-to-DNF5 behavior. Do not skip directly
   from 39 to 43/44 or silently accept package erasure. [F1]
2. **Cilium before newer kernels:** design an adjacent-minor ladder beginning with
   the latest applicable `1.15.x` patch, then `1.16.x`, `1.17.x`, and subsequent
   adjacent minors only as the compatibility matrix requires. These are candidate
   series, not approved pins. Cilium requires consecutive minor transitions and
   current-series patching first. Prove Kubernetes and kernel compatibility at
   every intermediate state, including the already-old `1.15.1`/Kubernetes 1.33
   baseline; adjacency alone cannot establish a supported bridge. Preserve
   kube-proxy replacement, API endpoint, L2/IPAM, policies, and Hubble settings.
   Assess actual L7 traffic: upstream warns proxy connections can be disrupted.
   Do not promise zero outage from a rolling CNI update. [C1]
3. **k3s:** plan adjacent Kubernetes minors, with servers upgraded individually
   before agents for each k3s transition. Respect client/server skew, preserve
   install options and datastore identity, and prove overlap with Cilium at each
   step. Do not combine an OS hop and a k3s/CNI change into one unverified action.
   The k3s order is distinct from the OS canary order. [K1]
4. **GPU:** Operator `24.9.2`'s published matrix does not establish support for
   Fedora, Kubernetes 1.33, or containerd 2.1. Its chart's permissive `kubeVersion`
   is not certification. Operator-managed drivers are disabled here; inspect the
   host driver, module build/signing, kernel headers, toolkit/containerd integration,
   and both GPU models at every hop. Do not assume an older Fedora CUDA repository
   is a safe substitute. Prove GPU workloads and media transcoding separately. [N1]

## Owners and required evidence before execution

| Owner and repository path | Required gate |
| --- | --- |
| Metal: `metal/inventories/prod.yml`, `metal/roles/k3s/`, `metal/roles/cilium/` | Exact active host list, trusted SSH/console identity, per-transition compatibility matrix, pinned artifacts, narrow execution targets, and version-specific rollback limits. `metal/cluster.yml` is a broad bootstrap entry point, not a validated rolling upgrader. |
| Metal: `metal/nodes.yml`, `metal/roles/virtualization/tasks/gpu_install_drivers.yml` | Package/repository audit; root and `/boot` capacity; bootloader/initramfs recovery; NetworkManager/interface, firewall, SELinux, Python/Ansible/DNF, GPU and runtime readiness. Existing GPU tasks update packages and reboot independently; do not reuse them unreviewed. |
| Metal/System: `metal/roles/automatic_upgrade/`, `metal/roles/cronjobs/`, `system/kured/` | Repository-owned coordination of all package/reboot actors, including timers, cron sentinels, kured, driver roles, and manual operators. Prove no competing transaction or reboot is active. `serial: 1` and kured `concurrency: 1` are separate controls, not a shared lock. |
| Storage/control plane: `system/rook-ceph/`, `metal/roles/k3s/`, affected app backup definitions | Exact disk/partition/OSD/PVC/PV map; Ceph pool failure domains, replication/min_size, PG state and capacity; quorum and exact-node outage tolerance; independently usable recovery material, protected recovery credentials, and isolated restore receipts. Keep `RECOVERY_PROOF` blocked where these are absent. |
| Apps/Platform: affected `apps/*/values.yaml`, `platform/*/values.yaml`; GPU: `system/gpu-operator/` | Per-node pods, PDBs, affinity/taints, local data, RWO attachments, spare capacity, immutable running artifacts, and behavior checks. Document how every non-exempt service stays available. |

The active inventory currently contains masters `charmander`, `squirtle`,
`bulbasaur` and workers `pikachu`, `cyndaquil`, `totodile`, `growlithe`, `arcanine`,
`sprigatito`. Exclude retired `chikorita`. Select a general worker canary only after
capacity and storage mapping. Do not choose `cyndaquil` without accounting for
Budget's node pin, or assume any other general worker is free of pinned workloads.
Record the exact remaining single-node order from that evidence, with GPU/media
nodes last and masters never overlapping. Do not publish worker batches.

## Conditional single-node procedure

Execute only after the preceding gates pass and the implementation is validated
and present on Gitea `master`. Each Fedora hop is its own checkpoint; prove mixed
OS/kernel operation before moving between nodes or releases.

1. Record the repository revision, exact node/UID, source/target release and kernel,
   package transaction, baseline identities, health, and recovery receipts. Recheck
   the other nodes, etcd quorum, Ceph outage tolerance, PDBs, capacity, and workload
   availability. Missing evidence blocks this node.
2. Acquire the workflow's exclusive maintenance ownership and verify the coordinated
   hold on every competing updater/rebooter. Record original actor states and the
   eventual restoration procedure. Inspect pending transactions and sentinels;
   never merely wait for kured's normal schedule to end.
3. Cordon only the selected node. Drain using the eviction API and respect PDBs.
   Stop on blocked evictions, unmanaged pods, unknown local data, or a workload
   availability violation. Do not force eviction, bypass PDBs, or automatically
   delete `emptyDir` data. Handle daemonsets, static pods, OSDs, and control-plane
   services through their reviewed outage plan; drain does not stop all of them.
4. Prepare the reviewed source-release updates and next-hop download with verified
   repositories/signatures. Account for any prerequisite reboot under this same
   single-node lock. Inspect the complete transaction and free space; stop on
   unexpected removals, missing packages, kernel/driver incompatibility, or disk
   identity drift. Never invoke PXE/bootstrap as a fallback.
5. Perform the offline in-place transaction using the commands appropriate to the
   installed DNF generation. Account for both entry into the offline environment
   and the subsequent boot into the new release. Reconnect through trusted SSH or
   the verified physical console. Never reboot or kill an active package transaction
   merely because an overall time allowance elapsed.
6. While still cordoned, verify the intended OS/kernel, boot and host services,
   preserved identities, k3s readiness, etcd membership/quorum, Cilium datapath/DNS/
   policy/L2 behavior, Ceph OSDs/PGs and `HEALTH_OK`, CSI attachments, and GPU/runtime
   readiness where applicable. Preserve all original taints and labels.
7. Uncordon only after infrastructure checks pass and the recorded pre-maintenance
   scheduling state permits it. Verify returning workloads use the same claims,
   controller readiness and application behavior, including GPU inference and media
   transcoding on the applicable nodes without NAS write tests. A `Running` Pod or
   successful GPU validator alone is insufficient.
8. Record the hop's before/after evidence and evaluate the next checkpoint. Start
   no other node or component transition until this node and affected services pass.
   Restore normal updater/reboot actors only through the recorded safe release of
   maintenance ownership, after pending reboot requests have been reviewed.

### Failure and resume

Stop on a regression, failed command, identity mismatch, unavailable non-exempt
application, or missing gate evidence. Keep the failed node cordoned and other
nodes untouched. **Never automatically uncordon in an error handler or `finally`
block.** Keep competing reboot actors inhibited until a safe disposition is recorded.

Capture the last completed checkpoint and exact transaction/boot state. Resume
only after rechecking identities, actual state, ownership, and prerequisite gates;
do not blindly replay a package transaction. Physical-console repair or booting a
retained kernel is conditional on a reviewed recovery procedure: an old kernel
does not undo changed userspace. No automatic Fedora downgrade, datastore reset,
rejoin, reinstall, OSD evacuation, or data deletion is a rollback. A Git revert
restores desired state, not an upgraded filesystem or lost data.

## Current missing evidence and next development tasks

`A1` and `RECOVERY_PROOF` remain **technically blocked, not waiting for the owner
to repeat permission or provide declined storage**. The issue records no complete
exercised recovery evidence for etcd, Ceph PVCs, Gitea, shared PostgreSQL, Jovo,
Strata, or Sporecast. Neither this edit nor the dated CORE pass resolves that gap.

The next implementation work is to:

1. Produce the exact package/kernel/Cilium/k3s/GPU/CSI transition matrix, archived
   repository/key evidence, and rollback limits. Mark unsupported intersections
   explicitly; do not manufacture a guaranteed tuple or import the old plan's pins.
2. Complete the node/workload/storage identity and outage map, capacity calculations,
   console recovery procedure, and evidence-backed node order. Review existing
   protected recovery evidence without requesting new storage or mutating NAS.
3. Implement a dedicated repository-owned in-place workflow under `metal/`, with
   explicit one-host selection, global actor coordination, preflight assertions,
   staged DNF handling, fail-closed cordon behavior, and restartable checkpoints.
   Add narrow Cilium/k3s transition entry points rather than running broad bootstrap
   playbooks. No such validated release-upgrade workflow is established today.
4. Subsequently validate the implementation's transaction, failure/resume, identity
   preservation, and reboot serialization in an authorized isolated environment.
   Do not use a production node as the first recovery experiment. Attach exact
   revision and results before any deployment; this document claims no tests.

Update #103 with verified evidence through the audited issue workflow during
authorized maintenance. Keep unresolved tasks open. Final completion requires all
nine active inventory nodes at the proven target, every required maintenance item
resolved, and fresh **Metal, Network, Storage, System, Platform, and Apps GREEN**
with actual application behavior verified. Restore/backup gaps and other UNKNOWN
checks remain blockers; a CORE pass or accepted risk is not ALL GREEN.

## Evidence references

- **Owner decisions and baseline:** maintenance #103, addenda “Autonomous maintenance
  resumed — 2026-10-18T21:40:19+00:00”, “Owner clarification and policy update —
  2026-10-18T20:39:27+00:00”, and “Action preflight checkpoint —
  2026-10-18T14:53:27+00:00”. Earlier provisioning suggestions are superseded.
- **Repository:** [AGENTS.md](../AGENTS.md),
  [foundational rules](../.agent/rules/foundational-rules.md) Rules 1, 4, 6, 7;
  [inventory](../metal/inventories/prod.yml);
  [k3s pin/config](../metal/roles/k3s/defaults/main.yml);
  [Cilium pin/config](../metal/roles/cilium/defaults/main.yml);
  [GPU chart](../system/gpu-operator/Chart.yaml) and
  [driver ownership](../system/gpu-operator/values.yaml).
- **[F1]** [Fedora DNF system upgrade](https://docs.fedoraproject.org/en-US/quick-docs/upgrading-fedora-offline/),
  “Performing system upgrade”, “Can I upgrade from an End-of-Life (EOL) release?”,
  and “Can I do a single upgrade across many releases”. Policy checked against
  indexed official-page text on 2026-10-18; direct fetch returned a bot challenge.
- **[C1]** [Cilium upgrade guide](https://docs.cilium.io/en/stable/operations/upgrade/),
  consecutive-minor/latest-patch requirement, version-specific notes, and upgrade
  impact. Read on 2026-10-18; use each selected version's guide before execution.
- **[K1]** [K3s manual upgrades](https://docs.k3s.io/upgrades/manual), server-first
  order, no skipped minors, and configuration-preservation requirements; read on
  2026-10-18.
- **[N1]** [GPU Operator 24.9.2 platform support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/24.9.2/platform-support.html),
  OS/Kubernetes and container-runtime matrices; read on 2026-10-18. This is a
  version-specific historical matrix, not proof of current lifecycle support.
