#!/bin/bash
set -e

# Configuration
REPO_DIR="$HOME/Documents/Github/moltbot"
# NOTE: The cluster pulls Moltbot from the in-cluster registry address.
# Keep both tags in sync to avoid ImagePullBackOff when values.yaml uses
# 10.0.20.11:32309/moltbot but local tooling pushes to registry.eaglepass.io.
IMAGE_NAME_INTERNAL="10.0.20.11:32309/moltbot"
IMAGE_NAME_EXTERNAL="registry.eaglepass.io/moltbot"
TAG="latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
CUSTOM_DOCKERFILE="$APP_DIR/Dockerfile"

# Check if repo exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Error: Repository not found at $REPO_DIR"
    exit 1
fi

echo "Building Moltbot image..."

# Handle custom Dockerfile
if [ -f "$CUSTOM_DOCKERFILE" ]; then
    echo "Applying custom Dockerfile from $CUSTOM_DOCKERFILE..."
    cp "$CUSTOM_DOCKERFILE" "$REPO_DIR/Dockerfile"
else
    echo "Using upstream Dockerfile..."
fi

cd "$REPO_DIR"

# Build the image using the repository's Dockerfile
podman build -t "${IMAGE_NAME_INTERNAL}:${TAG}" -f Dockerfile .

# Publish under both names (internal cluster pulls + external/dev convenience)
podman tag "${IMAGE_NAME_INTERNAL}:${TAG}" "${IMAGE_NAME_EXTERNAL}:${TAG}"

echo "Pushing image to ${IMAGE_NAME_INTERNAL}:${TAG}..."
podman push --tls-verify=false "${IMAGE_NAME_INTERNAL}:${TAG}"

echo "Pushing image to ${IMAGE_NAME_EXTERNAL}:${TAG}..."
podman push "${IMAGE_NAME_EXTERNAL}:${TAG}"

echo "Build and push complete!"
