# PlushDoku schema5 recovery

## Current economy-v2 release

Source00e730f206bc367c624481640b87fabfcfe1ae56; accepted image10.0.20.11:32309/meowdoku-preview@sha256:4920fb23393f07d7768f9a4f084d53b5e5b6d82b10651f035aaf85997ce37f31. Fresh independent encrypted schema4 NAS anchorpd115-1103t1856-af10.v1.sqlite.enc, SHA25653c8c09e821fb5a0439b391d4c66ddb24bb267a6c58e0e851dd82f7a9b7f6d8c. Actual isolated4-to5 migration, exact-once point scaling, unchanged challenge/history/private data, reopening and encrypted5 restore passed before live publication. Existing original claim/key retained. Old4 binaries reject5: prefer a compatible forward fix; no automatic restore over active data. Any reviewed new-claim recovery must reconcile intervening saves/deletions. No retention deletion is configured.

## Historical schema4 instructions and anchors (retained)

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

## Verified post-migration anchor

pd115-1103t1902-5786.v1.sqlite.enc;315392bytes;SHA256257ad709ebbee4fe6bfca7db26ca8dbfe40123984fe6d3ae8ebada4c795eb5ff. Independent encrypted NAS write and actual5-to5 isolated restore passed: all3profiles/private balances/history retained, challenge values unchanged, marker2 and integrity/foreign keys valid. Authentication/sharing reset affected only the disposable restored copy. Pre4 and older anchors remain retained; no original data or NAS file was deleted. Owned qualification Jobs are disabled after receipts are saved.

## Schema 5 preparation anchor for 0.1.17

Verified at 2026-11-03T23:27:20.116573+00:00. NAS file: pd117-1103t2322-7459.v1.sqlite.enc. Size: 331,776 bytes. SHA256: ddf0ea3ca0defefef4b7411b18545e8c70bbc78bb4df1eac47acca26554fc27e.

The keyless writer at commit df2cb0fbbcc2cb927f3a51e9008089961f76b3c4 completed before the isolated restore at commit 8366d83150a1aad9fec4fb4c79cb62d6e88bd679. The actual schema 5-to-5 restore passed integrity and foreign-key checks and retained all 3 profiles, private gameplay, rewards, history, animal metadata and challenge values. Authentication and public consent were reset only in the disposable restored copy. Live account rows, the original claim and previous NAS anchors remain intact. Owned temporary Jobs are disabled after completion evidence is retained.

This does not establish schema 5-to-6 acceptance. Candidate source a2555ea7df35595ae549aa82ba6cbb68984d0706 and prepared OCI digest sha256:5f83a1f0abf188a760b14ccd22ce9fffd92baf20b02050978921c5273892b9e0 remain unpublished at this checkpoint. Keep the schema 5 service until exact-image publication, operational migration/recovery qualification and native one-CPU readiness pass. Old schema 5 binaries refuse schema 6. Do not automatically revert to old code or overwrite active data. Revalidate backup freshness and intervening saves before promotion.

The unchanged verifier passed a cold native AMD64 ping in 345.7 ms under the existing one-CPU/512 MiB limit. Dependency bytes and verifier class payload match the candidate. This component check does not prove full schema 6 server readiness. No registry credential was transmitted during this preparation.
