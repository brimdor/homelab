#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${PAPERCLIP_REPO_URL:-https://github.com/paperclipai/paperclip.git}"
REPO_DIR="${PAPERCLIP_REPO_DIR:-$HOME/Documents/Github/paperclip}"
REPO_REF="${PAPERCLIP_REF:-master}"
PUSH_IMAGE="${PAPERCLIP_PUSH_IMAGE:-registry.eaglepass.io/paperclip}"
PULL_IMAGE="${PAPERCLIP_PULL_IMAGE:-10.0.20.11:32309/paperclip}"
IMAGE_TAG="${PAPERCLIP_IMAGE_TAG:-latest}"
PULL_PROTOCOL="${PAPERCLIP_PULL_PROTOCOL:-http}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${PAPERCLIP_DOCKERFILE:-$SCRIPT_DIR/../Dockerfile}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd git
require_cmd curl

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

REVISION="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
SOURCE_IMAGE="$PUSH_IMAGE:$IMAGE_TAG"
SOURCE_REVISION_IMAGE="$PUSH_IMAGE:sha-$REVISION"
PULL_REGISTRY="${PULL_IMAGE%%/*}"
PULL_REPOSITORY="${PULL_IMAGE#*/}"
PULL_TAG_URL="$PULL_PROTOCOL://$PULL_REGISTRY/v2/$PULL_REPOSITORY/manifests/$IMAGE_TAG"
PULL_REVISION_URL="$PULL_PROTOCOL://$PULL_REGISTRY/v2/$PULL_REPOSITORY/manifests/sha-$REVISION"

printf 'Building Paperclip from %s at %s\n' "$REPO_DIR" "$REVISION"
printf 'Push tag: %s\n' "$SOURCE_IMAGE"
printf 'Pull registry alias: %s:%s\n' "$PULL_IMAGE" "$IMAGE_TAG"

docker build \
  --pull \
  --file "$DOCKERFILE" \
  --tag "$SOURCE_IMAGE" \
  --tag "$SOURCE_REVISION_IMAGE" \
  "$REPO_DIR"

docker push "$SOURCE_IMAGE"
docker push "$SOURCE_REVISION_IMAGE"

curl -fsSL -H "Accept: application/vnd.oci.image.manifest.v1+json" "$PULL_TAG_URL" >/dev/null
curl -fsSL -H "Accept: application/vnd.oci.image.manifest.v1+json" "$PULL_REVISION_URL" >/dev/null

printf 'Done.\n'
printf '  %s\n' "$SOURCE_IMAGE"
printf '  %s\n' "$SOURCE_REVISION_IMAGE"
printf '  %s:%s\n' "$PULL_IMAGE" "$IMAGE_TAG"
printf '  %s:sha-%s\n' "$PULL_IMAGE" "$REVISION"
