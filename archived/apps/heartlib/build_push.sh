#!/usr/bin/env bash
set -euo pipefail

# Build and push heartlib to local registry
REGISTRY="10.0.20.11:32309"
IMAGE_NAME="heartlib"
TAG="${1:-latest}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required" >&2
  exit 1
fi

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "============================================="
echo "Building HeartLib Docker Image"
echo "============================================="
echo "Registry:  ${REGISTRY}"
echo "Image:     ${IMAGE_NAME}"
echo "Tag:       ${TAG}"
echo "Full:      ${FULL_IMAGE}"
echo "============================================="

# Build the image
echo ""
echo "[1/2] Building image..."
docker build -t "${FULL_IMAGE}" "${SCRIPT_DIR}"

# Push to registry
echo ""
echo "[2/2] Pushing to ${REGISTRY}..."
docker push "${FULL_IMAGE}"

echo ""
echo "============================================="
echo "✅ Successfully pushed ${FULL_IMAGE}"
echo "============================================="
echo ""
echo "Next steps:"
echo "  1. Ensure models are downloaded to NFS: /mnt/user/heartlib/models"
echo "  2. Commit and push to trigger ArgoCD sync"
echo "  3. Monitor deployment: kubectl get pods -n heartlib"
