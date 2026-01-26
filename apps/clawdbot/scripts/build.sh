#!/bin/bash
set -e

# Configuration
REPO_DIR="$HOME/Documents/Github/clawdbot"
IMAGE_NAME="registry.eaglepass.io/clawdbot"
TAG="latest"

# Check if repo exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Error: Repository not found at $REPO_DIR"
    exit 1
fi

echo "Building Clawdbot image..."
cd "$REPO_DIR"

# Build the image using the repository's Dockerfile
podman build -t "${IMAGE_NAME}:${TAG}" -f Dockerfile .

echo "Pushing image to ${IMAGE_NAME}:${TAG}..."
podman push "${IMAGE_NAME}:${TAG}"

echo "Build and push complete!"
