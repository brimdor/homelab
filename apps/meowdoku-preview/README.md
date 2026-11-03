# PlushDoku preview backend

Source is private Zuriel-Labs/meowdoku; this existing technical namespace/hostname remains meowdoku-preview for API/data continuity. Exact frozen source, published image and operational receipts are in PROVENANCE.json.

Animal-aware schema4 is deployed by immutable OCI digest on Bulbasaur: one replica/Recreate, original2Gi Ceph claim, existing app-only key projection and verified origin HTTPS. Service-local health/time/animals-v1 checks pass; anonymous and fabricated private requests return401. Original profile progress/grants and name clocks passed preservation checks.

An external scripted HTTPS request from EaglePro is blocked403 by Cloudflare Browser Integrity Check, confirmed through its exact Ray ID. No security settings changed. Do not infer external/phone Google recovery acceptance from local health.

## Same controlled release pipeline

The signing/deployment controller owns this chart; the separate sole developer owns product code. Receive an immutable source/QA handoff and inspect intervening changes; no competing coding lane.

1. Build/qualify externally, never on Kubernetes nodes. Securely publish through the existing internal registry with approved authentication, verified TLS/no redirects. Record actual OCI digest and configuration/layer-byte provenance.
2. Create a fresh consistent encrypted snapshot. Review bytes/hash, then stream ciphertext directly to the keyless/PVC-less NAS writer. Keep operational keys/databases outside TESTING.
3. After writer completion, qualify the exact candidate in isolated emptyDir with read-only NAS/key. Assert integrity, foreign keys and preserved progress/history/animal metadata before promotion.
4. Render/lint/review apps/meowdoku-preview, commit/push canonical Gitea master, refresh Argo, verify exact image/original claim/health/features/request rejection.
5. Retain and independently restore a post-migration encrypted NAS anchor. Disable owned QA Jobs after receipts; never delete backup files or reset the live claim.

Argo already automatically reconciles Gitea master with self-heal/prune. It does not build/publish source images, qualify migrations or authorize releases. No CI publisher, new persistent credential or blind update watcher was installed. Future approved releases use this SAME controller→immutable digest→GitOps path.

Backups use only10.0.40.3:/mnt/user/meowdoku-backups; ciphertext and keys remain separate. No backup pruning/schedule or off-site claim. See RECOVERY.md for anchors and schema-aware rollback. APK delivery, PR merge and public/store release remain separate.
