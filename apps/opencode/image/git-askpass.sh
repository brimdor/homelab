#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  *"Username for "*)
    printf '%s\n' 'x-access-token'
    ;;
  *"Password for "*)
    printf '%s\n' "${OPENCODE_GIT_TOKEN:-}"
    ;;
  *)
    printf '\n'
    ;;
esac
