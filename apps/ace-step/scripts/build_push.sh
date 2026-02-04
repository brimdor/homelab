#!/bin/bash
set -e

# Configuration
REPO_URL="https://github.com/ace-step/ACE-Step.git"
BUILD_DIR="/tmp/ace-step-build"
REGISTRY="registry.eaglepass.io"
IMAGE_NAME="ace-step"
TAG="latest"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo ">>> Setting up build environment..."
rm -rf "$BUILD_DIR"
git clone "$REPO_URL" "$BUILD_DIR"

echo ">>> Fixing Dockerfile for Podman (fully qualified names)..."
sed -i 's|FROM nvidia/|FROM docker.io/nvidia/|g' "$BUILD_DIR/Dockerfile"

echo ">>> Building Image: $FULL_IMAGE"
cd "$BUILD_DIR"
podman build --tls-verify=false -t "$FULL_IMAGE" .

echo ">>> Pushing Image to Registry..."
podman push --tls-verify=false "$FULL_IMAGE" 

echo ">>> Done! Image pushed to $FULL_IMAGE"
