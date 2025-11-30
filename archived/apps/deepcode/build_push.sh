#!/usr/bin/env bash
set -euo pipefail

# Build and push docker.io/brimdor/deepcode:<tag>
IMAGE="docker.io/brimdor/deepcode"
TAG="${1:-latest}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

FULL_IMAGE_TAG="${IMAGE}:${TAG}"
echo "Building ${FULL_IMAGE_TAG}..."
docker build -f "$(dirname "$0")/Dockerfile" -t "${FULL_IMAGE_TAG}" "$(dirname "$0")"

echo "Pushing ${FULL_IMAGE_TAG} to Docker Hub..."
docker push "${FULL_IMAGE_TAG}"

echo "Done."
