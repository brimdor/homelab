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

echo ">>> Pinning PyTorch dependencies to compatible CUDA versions..."
# Remove unpinned torch lines from requirements.txt
sed -i '/^torch$/d' "$BUILD_DIR/requirements.txt"
sed -i '/^torchaudio$/d' "$BUILD_DIR/requirements.txt"
sed -i '/^torchvision$/d' "$BUILD_DIR/requirements.txt"

# Modify Dockerfile to install pinned versions
# We insert BEFORE the original pip block to avoid syntax errors with continuation characters
# Added --default-timeout=1000 to handle large wheel downloads
sed -i '/RUN pip3 install --no-cache-dir --upgrade pip/i RUN pip3 install --no-cache-dir --default-timeout=1000 torch==2.5.1+cu124 torchvision==0.20.1+cu124 torchaudio==2.5.1+cu124 --extra-index-url https://download.pytorch.org/whl/cu124' "$BUILD_DIR/Dockerfile"
# Also fix the existing requirements install line to use cu124 to be safe (this targets the original line 40)
sed -i 's|cu126|cu124|g' "$BUILD_DIR/Dockerfile"

echo ">>> Building Image: $FULL_IMAGE"
cd "$BUILD_DIR"
podman build --tls-verify=false -t "$FULL_IMAGE" .

echo ">>> Pushing Image to Registry..."
podman push --tls-verify=false "$FULL_IMAGE" 

echo ">>> Done! Image pushed to $FULL_IMAGE"
