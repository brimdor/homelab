# Animal-aware schema4 recovery

Frozen app/server source9dd835686ef69d67e2608a31e09bd85c44e5aea1. The exact qualified image is recorded in PROVENANCE.json. Publication and fresh operational pre-rollout NAS restore qualification are complete; exact receipts are in PROVENANCE.json.

The pre-rollout live service was independently verified at schema3 on the original PVC. Although this change adds no SQL migration relative to the unpublished0.1.9 schema4 candidate, the real next deployment must still qualify schema3to4.

Immediately before rollout, take/verify a fresh consistent encrypted backup with the existing app-only key and keyless NAS writer. Keep original NAS ciphertext. No operational key/database goes to TESTING. Qualify the published animal-aware image in an isolated emptyDir with read-only NAS/key, no live PVC. Assert integrity/foreign keys, profile/name/history/rewards and private animal choice/cursor/receipts retention. Writer completion precedes restore Job. Blank snapshot ID fails closed.

After rollout retain a fresh schema4 encrypted NAS backup and run an isolated restore. Keep animal-aware schema4-compatible recovery code. The old live schema3 image cannot reopen schema4; the separately qualified93b5124e schema4 candidate lacks animal validators/merge safeguards and must not be assumed a safe semantic rollback once extended snapshots exist. Prefer a tested animal-aware forward fix; no automatic older-data restore or overwrite/reset of the active claim.

Current synthetic rehearsal used fixture-only data/keys and passed migration, encrypted backup/restore and animal metadata retention; it is not a live NAS/CSI/real-account drill. All existing namespace/PVC/key/TLS/affinity/resource/admission/min-version identities remain.
