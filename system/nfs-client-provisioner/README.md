# NFS provisioner ownership

## Deployment contract

This chart declares the existing `nfs-rwx` provisioner, not the NAS itself.
The explicit Argo Application in `system/argocd/values.yaml` uses namespace
`kube-system` and Helm release `nfs-client-provisioner`. Both production and seed
directory generators exclude this path; do not let the directory basename select
a new namespace. Seed bootstrap disables the explicit Application.

Initial adoption is staged with automatic synchronization disabled. Review the
actual Argo diff before enabling reconciliation. No Namespace, PV, or PVC belongs
to this chart. Its seven resources are the existing Deployment, ServiceAccount,
namespaced Role/RoleBinding, ClusterRole/ClusterRoleBinding, and StorageClass.

The published chart `4.0.18` ships application `v4.0.2`; these are not interchangeable
version numbers. Both already ran before adoption. The observed running image
digest is `sha256:63d5e04551ec8b5aae83b6f35938ca5ddc50a88d85492d9731810c31591fa4c9`.
The existing image text and pod restart annotation deliberately remain unchanged
to avoid restarting the controller. Current published versions do not establish
an active upstream security-maintenance commitment.

## Protected storage contract

- Server: `10.0.40.3`; root export: `/mnt/user/heartlib`.
- Provisioner identity: `cluster.local/nfs-client-provisioner-nfs-subdir-external-provisioner`.
- StorageClass: `nfs-rwx`, RWX use, `Immediate`, reclaim `Delete`, `archiveOnDelete: "true"`, `nosharecache`.
- Keep the existing controller's direct NFS volume. The upstream chart's nonempty
  `nfs.mountOptions` creates a root PV/PVC and changes that mount; the local
  StorageClass template preserves consumer mount options without doing this.
- Preserve `allowVolumeExpansion: true` during adoption, but do not treat it as
  enforced directory capacity or working NFS-subdirectory resize support.
- Deleting a dynamic PV can rename its directory to `archived-<PV name>`.
  `archiveOnDelete` is not a backup or permission to mutate NAS data.

### Kubernetes ownership observed 2026-10-18

Storage operators own the provisioner and export contract. Each application owns
its data and recovery. Preserve these mappings, not merely the namespace count:

| PVC | PVC UID | PV |
| --- | --- | --- |
| builder/builder-backups | e1ca34cc-f3d3-4b65-b497-062be127282a | pvc-e1ca34cc-f3d3-4b65-b497-062be127282a |
| builder-canary/builder-canary-backups | 42d56d12-2f25-4cde-b228-846a1615eab1 | pvc-42d56d12-2f25-4cde-b228-846a1615eab1 |
| sporecast/sporecast-backup | 7e5b9333-33b8-4e11-a17f-6ed8798ed250 | pvc-7e5b9333-33b8-4e11-a17f-6ed8798ed250 |
| sporecast-canary/sporecast-canary-backup | afc14bb3-01c3-44f2-8fdc-4ed2156390f8 | pvc-afc14bb3-01c3-44f2-8fdc-4ed2156390f8 |
| zot/zot-nfs-pvc | 728fbc24-a589-483f-8833-855c863b4f04 | pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6 |

The first four paths are `/mnt/user/heartlib/<namespace>-<PVC name>-<PV name>`.
They use `nfs-rwx` and PV reclaim `Delete`. Builder claims have explicit
Helm/Argo retention annotations; Sporecast backup claims currently do not.
Record that risk; do not change reclaim or application retention during adoption.

Zot's active registry path is
`/mnt/user/heartlib/zot-zot-nfs-pvc-pvc-0ce8a5c9-b53a-4b2d-920a-a9efcf82e7a6`.
Its PV is `Retain`; its current PVC has an empty StorageClass and a different UID
from the PV suffix. It is deliberately prebound and mounted by `zot-0` at
`/var/lib/registry`. Never treat it as an orphan or regenerate its path from the
current PVC UID. An archived application named Heartlib does not retire this
shared export.

Direct exports outside this StorageClass also remain protected: Budget and its
canary, Emby/media, HumbleAI, Outline, Postgres backups, Radarr/Sonarr/SABnzbd,
Strata backups, and the `pages` export shared by Pages production and canary.
Derive exact current paths from their owning charts before any storage operation.

## Verification and rollback

Adoption must preserve Deployment, StorageClass, ServiceAccount/RBAC, PV and PVC
UIDs; the active ReplicaSet/pod UID and restart count; pod template, export and
provisioner identity; all bindings; and controller readiness. Stop on unexpected
pod-template changes, pruning, competing Argo ownership, or new root PV/PVCs.
Do not create synthetic PVCs: even a provisioning test writes to the protected NAS.

The explicit Application has no deletion finalizer, disables pruning, and uses
Prune/Delete protection. Keep the old Helm release records; **never run Helm
uninstall** to transfer ownership. Retire the imperative deployment path, not its
live resources. Roll back configuration through Git while retaining the same
Application/chart, names, namespace, export and protections. To stop reconciliation,
disable automation in Git without deleting the Application or managed resources.

This desired state does not prove NAS recovery. The cache-only placement contract
in [the network inventory](../../network/docs/network/devices.md#unraid-nfs-storage-contract)
must be verified separately. Directory integrity/capacity, backup contents,
isolated restores, and historical-directory disposition remain unverified.
Existing successful backup Jobs do not establish recoverability.

Disaster recovery restores the NAS/export and protected data first, then existing
binding records and the identical provisioner identity. A new PVC creating a new
directory is not restoration. API UIDs cannot be recreated after datastore loss;
distinguish recovery rebinding from identity-preserving in-place adoption.
