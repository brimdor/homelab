# Meowdoku preview

Application source: private Zuriel-Labs/meowdoku at `720d5d8ac30621f689994611a9791966aa9946e2`. This chart copies its reviewed deployment templates; infrastructure values are owned here.

One replica with required Bulbasaur hostname affinity, Recreate strategy, dedicated 2Gi Ceph RBD claim, approved active database-key projection, and certificate-verified HTTPS. Signing and recovery keys are never projected. The database claim is retained on ordinary chart deletion; this does not prevent namespace or manual storage destruction.

Online admission and ingress remain disabled during initial storage, key, verifier and TLS qualification. Enable only after checking the exact image digest, dedicated signer allowlist, live verifier readiness and transport trust. No unencrypted or bearer-only fallback is supported.

Encrypted manual backups use only `10.0.40.3:/mnt/user/meowdoku-backups` at `/backup`, in a separate nonroot Job colocated with the backend for its RWO source. Backup mounting is disabled by default. Never project the Android signer or recovery key, overwrite a good backup, or remove existing NAS files. Retain the original live claim during isolated restore qualification.

Canonical deployment is Gitea master through Argo CD. Revert the exact configuration commit for rollback; preserve data and verify compatibility before changing database images or promoting a restored claim.
