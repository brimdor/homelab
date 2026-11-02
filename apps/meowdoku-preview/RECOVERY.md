# Schema3 recovery
The 0.1.7-preview backend adds profiles.username_changed_at with a zero default for historical profiles. The encrypted schema2 snapshot pm6-1102t1103 was restored on a separate emptyDir and migrated with the exact deployed image; integrity, foreign keys and all restored rows passed.

Do not revert to schema2 image 802b245f after migration. It refuses schema3, and a Git image rollback would not reverse the data migration. Retain schema3-capable image sha256:7fd2f186765128ec32217bded95f0e6287df054f1d50cf27d6d365aac2456c91. Prefer a tested schema3-compatible forward fix. A backup restore requires a separately reviewed new claim and reconciliation of intervening saves/account deletions; never overwrite or reset the active claim automatically.

Backups are encrypted before NAS transfer. Restore qualification is isolated, clears historical authentication/sharing deliberately, and never mounts the live claim. The post-migration recovery anchor will be recorded after rollout verification. No backup retention or deletion is authorized.
