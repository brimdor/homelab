# Rook-Ceph operations

## Snapshot conversion TLS

The snapshot-controller dependency uses cert-manager for its conversion webhook.
A namespace-local CA signs the serving certificate so routine leaf renewal does
not rotate the trust anchor. Cainjector manages the CRD CA bundle; the webhook
watches its mounted Secret and reloads renewed certificates.

Keep the serving Certificate and Secret named `rook-ceph-conversion-webhook`.
The pinned chart uses the Secret name in its `inject-ca-from` annotation, which
must identify the Certificate. Do not enable Helm TLS autogeneration: offline
rendering cannot look up existing Secrets and generates a different key on every
render.

The existing serving Secret was handed over without deletion. Its retained
`Prune=false` and `IgnoreExtraneous` annotations prevent Argo CD from deleting it
after cert-manager adoption. The temporary Argo `/data` preservation rule and
one-time renewal Job were removed after verified issuance. Do not remove Secret
protection or restore the old Helm-generated Secret as a rollback.

During migration, cert-manager accepted the old certificate without checking its
issuer chain. A repository-defined `cmctl renew` Job triggered initial issuance
using only get access to this Certificate and update access to its status. The
Job used a token-file kubeconfig because cmctl did not select in-cluster access
automatically. No renewal Job or its RBAC is needed for normal certificate renewal.

After changes, verify both Issuers and Certificates are Ready, the serving Secret
UID remains unchanged, hostname-verified TLS succeeds against the CRD CA bundle,
and a ConversionReview succeeds. Recheck after another Argo refresh. Readiness
alone does not prove conversion trust.

The CA certificate lasts ten years and renews ninety days before expiry without
rotating its key. Monitor certificate readiness and expiration. A deliberate CA
key replacement requires coordinated leaf reissuance, trust injection, and live
conversion validation; do not delete either TLS Secret to force rotation.
