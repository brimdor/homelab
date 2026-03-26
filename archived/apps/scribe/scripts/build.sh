#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${SCRIBE_REPO_URL:-https://github.com/brimdor/scribe.git}"
REPO_DIR="${SCRIBE_REPO_DIR:-$HOME/Documents/Github/scribe}"
REPO_REF="${SCRIBE_REF:-main}"
PUSH_IMAGE="${SCRIBE_PUSH_IMAGE:-registry.eaglepass.io/scribe}"
PULL_IMAGE="${SCRIBE_PULL_IMAGE:-10.0.20.11:32309/scribe}"
IMAGE_TAG="${SCRIBE_IMAGE_TAG:-latest}"
PULL_PROTOCOL="${SCRIBE_PULL_PROTOCOL:-http}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${SCRIBE_DOCKERFILE:-$SCRIPT_DIR/../Dockerfile}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd git
require_cmd curl
require_cmd rsync

if [ ! -f "$DOCKERFILE" ]; then
  printf 'Dockerfile not found: %s\n' "$DOCKERFILE" >&2
  exit 1
fi

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone "$REPO_URL" "$REPO_DIR"
  fi

  if [ -n "$(git -C "$REPO_DIR" status --porcelain)" ]; then
    printf 'Refusing to update dirty repo: %s\n' "$REPO_DIR" >&2
    exit 1
  fi

  git -C "$REPO_DIR" fetch --tags origin
  git -C "$REPO_DIR" checkout "$REPO_REF"

  if git -C "$REPO_DIR" show-ref --verify --quiet "refs/remotes/origin/$REPO_REF"; then
    git -C "$REPO_DIR" pull --ff-only origin "$REPO_REF"
  fi
}

clone_or_update_repo

BUILD_CONTEXT="$(mktemp -d)"
trap 'rm -rf "$BUILD_CONTEXT"' EXIT

rsync -a --delete --exclude '.git' "$REPO_DIR/" "$BUILD_CONTEXT/"

REVISION="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
SOURCE_IMAGE="$PUSH_IMAGE:$IMAGE_TAG"
SOURCE_REVISION_IMAGE="$PUSH_IMAGE:sha-$REVISION"
PULL_REGISTRY="${PULL_IMAGE%%/*}"
PULL_REPOSITORY="${PULL_IMAGE#*/}"
PULL_TAG_URL="$PULL_PROTOCOL://$PULL_REGISTRY/v2/$PULL_REPOSITORY/manifests/$IMAGE_TAG"
PULL_REVISION_URL="$PULL_PROTOCOL://$PULL_REGISTRY/v2/$PULL_REPOSITORY/manifests/sha-$REVISION"

printf 'Building Scribe from %s at %s\n' "$REPO_DIR" "$REVISION"
printf 'Push tag: %s\n' "$SOURCE_IMAGE"
printf 'Pull registry alias: %s:%s\n' "$PULL_IMAGE" "$IMAGE_TAG"

docker build \
  --pull \
  --file "$DOCKERFILE" \
  --tag "$SOURCE_IMAGE" \
  --tag "$SOURCE_REVISION_IMAGE" \
  "$BUILD_CONTEXT"

docker push "$SOURCE_IMAGE"
docker push "$SOURCE_REVISION_IMAGE"

curl -fsSL -H "Accept: application/vnd.oci.image.manifest.v1+json" "$PULL_TAG_URL" >/dev/null
curl -fsSL -H "Accept: application/vnd.oci.image.manifest.v1+json" "$PULL_REVISION_URL" >/dev/null

printf 'Done.\n'
printf '  %s\n' "$SOURCE_IMAGE"
printf '  %s\n' "$SOURCE_REVISION_IMAGE"
printf '  %s:%s\n' "$PULL_IMAGE" "$IMAGE_TAG"
printf '  %s:sha-%s\n' "$PULL_IMAGE" "$REVISION"
