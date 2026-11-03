# Animal-aware schema4 recovery

Frozen source:9dd835686ef69d67e2608a31e09bd85c44e5aea1. Published OCI digest:sha256:85c6dd0e47daccdf24d43cd156466c694301869ebcd81c452c466ccf6861ed4e. Only descriptor media types changed; configuration bytes, Healthcheck and all layers stayed identical. Exact provenance and operational results are in PROVENANCE.json.

Fresh pre-rollout NAS anchor pd111-1103t0427-e5.v1.sqlite.enc:217088 bytes, SHA256a9b3eec7ad38e207adeb468d4720f238502610bd88eb6713ac08cd9ba29170eb. Isolated restore migrated3→4 and preserved profile/name/history/rewards/animal state, with integrity/foreign keys passing and original ciphertext unchanged.

Post-rollout NAS anchor pd114-1103t0438-8f.v1.sqlite.enc:266240 bytes, SHA256702047effe344ceb2b4cfb262709b671c4d32f826dc19791fd79ae328df85e99. Isolated schema4 restore passed the same checks. Historical auth/sharing was cleared only in the isolated recovery copy; no real account was deleted/reset.

Both anchors remain on10.0.40.3:/mnt/user/meowdoku-backups. The writer streams already encrypted ciphertext directly from the owning pod, is keyless/PVC-less, uses exclusive creation/fsync and never overwrites/prunes files. Restore mounts NAS read-only, projects only the existing active database key and writes bounded emptyDir. No operational database/key belongs in TESTING. Writer completion must precede restore; disable owned QA Jobs only after receipts are retained. Job pruning never deletes NAS files or the live claim.

Prefer a tested animal-aware schema4 forward fix. Old live schema3 image7fd2f186 cannot reopen schema4. Pending93b5124e lacks animal validation/merge safeguards and is not a safe semantic rollback. Never automatically overwrite/reset the active claim with an older backup; a reviewed restore to a new claim must reconcile intervening saves/deletions. Git rollback alone does not reverse migration.

Original claim UID remainsce19a819-a04d-4b1d-a218-f6aa24a9a3f3. Namespace, key, signing identity, TLS, Bulbasaur affinity and resource limits remain unchanged. No backup retention/deletion policy is configured.
