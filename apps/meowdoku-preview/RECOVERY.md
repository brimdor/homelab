# PlushDoku schema4 recovery

Current compatible validator:0.1.13 source9ef2b44fefebfde3da608c875d22d605f7c4e7b3; current live digestsha256:4ffde2781271d5c8e6d1336ba2a46544cf1e6586cfe7540e3bf4b0b88557ffc6. Actual live verification and preserved baseline evidence are in PROVENANCE.json. No SQL/key/storage migration occurred in0.1.13.

## Retained0.1.11 migration history

Frozen source:9dd835686ef69d67e2608a31e09bd85c44e5aea1. Published OCI digest:sha256:85c6dd0e47daccdf24d43cd156466c694301869ebcd81c452c466ccf6861ed4e. Only descriptor media types changed; configuration bytes, Healthcheck and all layers stayed identical. Exact provenance and operational results are in PROVENANCE.json.

Fresh pre-rollout NAS anchor pd111-1103t0427-e5.v1.sqlite.enc:217088 bytes, SHA256a9b3eec7ad38e207adeb468d4720f238502610bd88eb6713ac08cd9ba29170eb. Isolated restore migrated3→4 and preserved profile/name/history/rewards/animal state, with integrity/foreign keys passing and original ciphertext unchanged.

Post-rollout NAS anchor pd114-1103t0438-8f.v1.sqlite.enc:266240 bytes, SHA256702047effe344ceb2b4cfb262709b671c4d32f826dc19791fd79ae328df85e99. Isolated schema4 restore passed the same checks. Historical auth/sharing was cleared only in the isolated recovery copy; no real account was deleted/reset.

Both anchors remain on10.0.40.3:/mnt/user/meowdoku-backups. The writer streams already encrypted ciphertext directly from the owning pod, is keyless/PVC-less, uses exclusive creation/fsync and never overwrites/prunes files. Restore mounts NAS read-only, projects only the existing active database key and writes bounded emptyDir. No operational database/key belongs in TESTING. Writer completion must precede restore; disable owned QA Jobs only after receipts are retained. Job pruning never deletes NAS files or the live claim.

Prefer a tested animal-aware schema4 forward fix. Old live schema3 image7fd2f186 cannot reopen schema4. Pending93b5124e lacks animal validation/merge safeguards and is not a safe semantic rollback. Never automatically overwrite/reset the active claim with an older backup; a reviewed restore to a new claim must reconcile intervening saves/deletions. Git rollback alone does not reverse migration.

Original claim UID remainsce19a819-a04d-4b1d-a218-f6aa24a9a3f3. Namespace, key, signing identity, TLS, Bulbasaur affinity and resource limits remain unchanged. No backup retention/deletion policy is configured.

## Compatible0.1.13 validator update

Source9ef2b44fefebfde3da608c875d22d605f7c4e7b3; immutable image10.0.20.11:32309/meowdoku-preview@sha256:4ffde2781271d5c8e6d1336ba2a46544cf1e6586cfe7540e3bf4b0b88557ffc6. SQL schema4, key, original claim and security unchanged. Fresh encrypted NAS anchorpd113-1103t1505-e7f3.v1.sqlite.enc; SHA25631b56f79351565541b11a5742e3f76256e730324e37ec0598e933b4a240acbaf. Isolated restore preserved all3profiles/history and passed the new snapshot validator. Synthetic encrypted recovery retained red cells, paid receipt and exact pending move. Previous validator rejects the optional new fields, so prefer a compatible forward fix after updated clients sync; never strip data, reset the live claim or automatically overwrite with an older backup.
