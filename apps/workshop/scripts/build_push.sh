#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_DIR="${APP_DIR}/image"
CLUSTER_IMAGE="10.0.20.11:32309/workshop:latest"
REGISTRY_IMAGE="registry.eaglepass.io/workshop:latest"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
VCS_REF="$(git -C "${APP_DIR}/../.." rev-parse HEAD)"
VERSION="latest"

podman build --tls-verify=false \
  --format docker \
  --build-arg BUILD_DATE="${BUILD_DATE}" \
  --build-arg VCS_REF="${VCS_REF}" \
  --build-arg VERSION="${VERSION}" \
  -f "${IMAGE_DIR}/Containerfile" \
  -t "${CLUSTER_IMAGE}" \
  -t "${REGISTRY_IMAGE}" \
  "${IMAGE_DIR}"

podman push --tls-verify=false "${CLUSTER_IMAGE}"
podman push --tls-verify=false "${REGISTRY_IMAGE}"
