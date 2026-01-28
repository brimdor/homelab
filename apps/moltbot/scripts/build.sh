#!/bin/bash
set -e

# Configuration
REPO_DIR="$HOME/Documents/Github/clawdbot"
IMAGE_NAME="registry.eaglepass.io/clawdbot"
TAG="latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
CUSTOM_DOCKERFILE="$APP_DIR/Dockerfile"

# Check if repo exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Error: Repository not found at $REPO_DIR"
    exit 1
fi

echo "Building Clawdbot image..."

# Handle custom Dockerfile
if [ -f "$CUSTOM_DOCKERFILE" ]; then
    echo "Applying custom Dockerfile from $CUSTOM_DOCKERFILE..."
    cp "$CUSTOM_DOCKERFILE" "$REPO_DIR/Dockerfile"
else
    echo "Using upstream Dockerfile..."
fi

cd "$REPO_DIR"

# Build the image using the repository's Dockerfile
podman build -t "${IMAGE_NAME}:${TAG}" -f Dockerfile .

echo "Pushing image to ${IMAGE_NAME}:${TAG}..."
podman push "${IMAGE_NAME}:${TAG}"

echo "Build and push complete!"
