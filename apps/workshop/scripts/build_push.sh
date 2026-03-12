#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_DIR="${APP_DIR}/image"
CLUSTER_IMAGE="10.0.20.11:32309/workshop:latest"
REGISTRY_IMAGE="registry.eaglepass.io/workshop:latest"

podman build --tls-verify=false \
  --format docker \
  -f "${IMAGE_DIR}/Containerfile" \
  -t "${CLUSTER_IMAGE}" \
  -t "${REGISTRY_IMAGE}" \
  "${IMAGE_DIR}"

podman push --tls-verify=false "${CLUSTER_IMAGE}"
podman push --tls-verify=false "${REGISTRY_IMAGE}"
