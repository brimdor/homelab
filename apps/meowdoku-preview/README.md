# Meowdoku preview

Application source: private Zuriel-Labs/meowdoku at `720d5d8ac30621f689994611a9791966aa9946e2`. This chart copies its reviewed deployment templates; infrastructure values are owned here.

One replica with required Bulbasaur hostname affinity, Recreate strategy, dedicated 2Gi Ceph RBD claim, approved active database-key projection, and certificate-verified HTTPS. Signing and recovery keys are never projected. The database claim is retained on ordinary chart deletion; this does not prevent namespace or manual storage destruction.

Online admission and HTTPS ingress are enabled after image, key, verifier, encrypted backup/isolated restore and TLS qualification. Public DNS is managed by external-dns with the app-specific existing homelab tunnel target. No unencrypted or bearer-only fallback is supported.

The initial read-only PVC backup Job could not traverse its mount (EACCES); no permissions were changed. The accepted manual path runs the existing snapshot routine in the owning backend, exports only ciphertext, and streams its reviewed size/SHA-256 to a separate keyless, PVC-less NAS writer Job. The writer uses exclusive creation and fsync; it never overwrites or prunes snapshots. The restore qualification mounts the NAS read-only and writes only a bounded emptyDir.

Encrypted manual backups use only `10.0.40.3:/mnt/user/meowdoku-backups` at `/backup`, in a separate nonroot writer Job on Bulbasaur. No schedule or retention deletion is configured. Never project the Android signer or recovery key, overwrite a good backup, or remove existing NAS files. Retain the original live claim during isolated restore qualification.

Canonical deployment is Gitea master through Argo CD. Revert the exact configuration commit for rollback; preserve data and verify compatibility before changing database images or promoting a restored claim.

Live encrypted NAS snapshot and isolated restore passed on 2026-11-01. Snapshot qa-1101t0635-owned.v1.sqlite.enc: 192512 bytes, SHA-256 946c4623af66793454311a3348dc961923bd80e66287f7bc699bc41aa191d8ce. Restore integrity was ok, authentication/sharing state was cleared, and the backup hash was unchanged. Initial database contains zero profiles; nonempty recovery is covered by synthetic packaged tests, not existing live user data. NAS NFSv4.2 sec=sys carries ciphertext only; no claim of off-site recovery or encrypted NFS transport is made. The server maps writes to UID99/GID100; root export mode777 and advertised wildcard access are unchanged. Keys remain separate in the approved vault. No automated retention, irreversible deletion or quota is configured.

Real phone hardware attestation and Google sign-in remain PM device acceptance steps; unsupported devices fail closed for online actions while offline play remains available.
