#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

REGISTRY="${REGISTRY:-registry.eaglepass.io}"
IMAGE_NAME="${IMAGE_NAME:-opencode}"
TAG="${TAG:-latest}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"
CONTAINERFILE="${CONTAINERFILE:-${SCRIPT_DIR}/Containerfile}"
CONTEXT_DIR="${CONTEXT_DIR:-${SCRIPT_DIR}}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-}"

pick_engine() {
  if [[ -n "${CONTAINER_ENGINE}" ]]; then
    command -v "${CONTAINER_ENGINE}" >/dev/null 2>&1 || {
      printf 'Container engine not found: %s\n' "${CONTAINER_ENGINE}" >&2
      exit 1
    }
    printf '%s\n' "${CONTAINER_ENGINE}"
    return
  fi

  if command -v podman >/dev/null 2>&1; then
    printf 'podman\n'
    return
  fi

  if command -v docker >/dev/null 2>&1; then
    printf 'docker\n'
    return
  fi

  printf 'Neither podman nor docker is installed.\n' >&2
  exit 1
}

ENGINE=$(pick_engine)
BUILD_ARGS=(--pull --file "${CONTAINERFILE}" --tag "${FULL_IMAGE}")

if [[ "${ENGINE}" == "podman" ]]; then
  BUILD_ARGS=(--format docker "${BUILD_ARGS[@]}")
fi

printf '>>> Using container engine: %s\n' "${ENGINE}"
printf '>>> Building image: %s\n' "${FULL_IMAGE}"

if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
  printf '>>> Logging into registry: %s\n' "${REGISTRY}"
  printf '%s' "${REGISTRY_PASSWORD}" | "${ENGINE}" login "${REGISTRY}" --username "${REGISTRY_USERNAME}" --password-stdin
fi

"${ENGINE}" build "${BUILD_ARGS[@]}" "${CONTEXT_DIR}"

printf '>>> Pushing image: %s\n' "${FULL_IMAGE}"
"${ENGINE}" push "${FULL_IMAGE}"

printf '>>> Done: %s\n' "${FULL_IMAGE}"
