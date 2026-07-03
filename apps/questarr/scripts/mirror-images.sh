#!/usr/bin/env bash
# Mirror upstream Questarr images from GHCR to the local homelab registry.
#
# This is a one-time (but idempotent) mirror. Re-running it is safe: skopeo
# copy will no-op if the source and destination manifests already match.
#
# Usage:
#   ./apps/questarr/scripts/mirror-images.sh
#
# Requires:
#   - skopeo (uses ~/.docker/config.json or $REGISTRY_AUTH_FILE for auth)
#   - write access to registry.eaglepass.io/questarr
#
# Notes:
#   - Upstream tags the stable release as `v1.3.1`; the cluster chart expects
#     the local tag `1.3.1`, so the script maps `ghcr.io/doezer/questarr:v1.3.1`
#     to `registry.eaglepass.io/questarr:1.3.1`.
#   - Set SKOPEO_DEST_TLS_VERIFY=false and SKOPEO_SRC_TLS_VERIFY=false only if
#     the registry certificates are not trusted by the host CA bundle.

set -euo pipefail

SOURCE_REPO="ghcr.io/doezer/questarr"
DEST_REPO="registry.eaglepass.io/questarr"

# associative source->destination tag mapping
TAGS=(
    "v1.3.1:1.3.1"
    "dev:dev"
)

DEST_TLS_VERIFY="${SKOPEO_DEST_TLS_VERIFY:-true}"
SRC_TLS_VERIFY="${SKOPEO_SRC_TLS_VERIFY:-true}"

for pair in "${TAGS[@]}"; do
    src_tag="${pair%%:*}"
    dst_tag="${pair##*:}"
    echo "Mirroring ${SOURCE_REPO}:${src_tag} -> ${DEST_REPO}:${dst_tag} ..."
    skopeo copy \
        --all \
        "docker://${SOURCE_REPO}:${src_tag}" \
        "docker://${DEST_REPO}:${dst_tag}"
    echo "Mirror complete for ${DEST_REPO}:${dst_tag}"
    echo "---"
done

for pair in "${TAGS[@]}"; do
    dst_tag="${pair##*:}"
    echo "Verifying manifest: ${DEST_REPO}:${dst_tag}"
    skopeo inspect --raw "docker://${DEST_REPO}:${dst_tag}" | jq -r '.digest'
done
