#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_SENTINEL="/root/.local/share/workshop/bootstrap-complete"
CHEZMOI_SOURCE_DIR="/root/.local/share/chezmoi"
WORKSHOP_PORT="${WORKSHOP_PORT:-4096}"
WORKSHOP_HOSTNAME="${WORKSHOP_HOSTNAME:-0.0.0.0}"
WORKSHOP_CORS_ORIGINS="${WORKSHOP_CORS_ORIGINS:-https://workshop.eaglepass.io}"
OP_CONNECT_VAULT="${OP_CONNECT_VAULT:-Server}"

log() {
  printf '[workshop] %s\n' "$*"
}

normalize_ssh_private_key() {
  python3 - <<'PY'
import os
import re
import textwrap

text = os.environ.get("WORKSHOP_SSH_PRIVATE_KEY", "").strip()
match = re.match(r'^(-----BEGIN [^-]+-----)\s+(.+?)\s+(-----END [^-]+-----)$', text, re.S)
if match:
    body = ''.join(match.group(2).split())
    print(match.group(1))
    print('\n'.join(textwrap.wrap(body, 70)))
    print(match.group(3))
elif text:
    print(text)
PY
}

configure_github_access() {
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"
  fi

  mkdir -p /root/.ssh
  chmod 700 /root/.ssh

  if [[ -n "${WORKSHOP_SSH_PRIVATE_KEY:-}" ]]; then
    normalize_ssh_private_key > /root/.ssh/id_ed25519
    chmod 600 /root/.ssh/id_ed25519
  fi

  if [[ -n "${WORKSHOP_SSH_PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "${WORKSHOP_SSH_PUBLIC_KEY}" > /root/.ssh/id_ed25519.pub
    chmod 644 /root/.ssh/id_ed25519.pub
  fi

  ssh-keyscan github.com > /root/.ssh/known_hosts 2>/dev/null
  chmod 644 /root/.ssh/known_hosts

  cat > /root/.ssh/config <<'EOF'
Host github.com
  IdentityFile /root/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking yes
EOF
  chmod 600 /root/.ssh/config

  export GIT_SSH_COMMAND="ssh -i /root/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
}

patch_dotfiles_for_service_account_mode() {
  python3 - <<'PY'
from pathlib import Path

path = Path("/root/.local/share/chezmoi/dot_dotfiles/functions/opAll.zsh.tmpl")
old = '{{- if (env "OP_CONNECT_HOST") }}'
new = '{{- if or (env "OP_CONNECT_HOST") (env "OP_SERVICE_ACCOUNT_TOKEN") }}'
text = path.read_text()
if old in text and new not in text:
    path.write_text(text.replace(old, new, 1))
PY
}

disable_dotfiles_externals() {
  if [[ -f "${CHEZMOI_SOURCE_DIR}/.chezmoiexternal.yaml" ]]; then
    : > "${CHEZMOI_SOURCE_DIR}/.chezmoiexternal.yaml"
  fi
}

apply_dotfiles() {
  if [[ ! -d "${CHEZMOI_SOURCE_DIR}" ]]; then
    log "Skipping dotfiles apply because ${CHEZMOI_SOURCE_DIR} is missing"
    return
  fi

  patch_dotfiles_for_service_account_mode
  disable_dotfiles_externals
  export OP_CONNECT_VAULT
  log "Applying selected dotfiles paths"
  (
    cd "${CHEZMOI_SOURCE_DIR}"
    chezmoi apply --init --source-path dot_config dot_dotfiles dot_local
  )

  if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
    mkdir -p /root/.dotfiles
    if ! op read -o /root/.dotfiles/misc.zsh "op://${OP_CONNECT_VAULT}/mahk57xrxjnndw6ew2kjncd6vq/misc.zsh"; then
      log "Skipping misc.zsh pull because the configured vault does not contain the source item"
    fi
  fi
}

install_command_center() {
  log "Installing command-center"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    uv tool install --force command-center --from "git+https://x-access-token:${GITHUB_TOKEN}@github.com/brimdor/command-center.git"
  else
    uv tool install --force command-center --from git+ssh://git@github.com/brimdor/command-center.git
  fi
}

bootstrap_command_center() {
  log "Bootstrapping command-center for OpenCode"
  cmdctl init --opencode
}

bootstrap_once() {
  if [[ -f "${BOOTSTRAP_SENTINEL}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${BOOTSTRAP_SENTINEL}")"
  configure_github_access
  apply_dotfiles
  install_command_center
  bootstrap_command_center
  touch "${BOOTSTRAP_SENTINEL}"
}

build_cors_args() {
  local origin
  local -a origins
  IFS=',' read -r -a origins <<< "${WORKSHOP_CORS_ORIGINS}"

  for origin in "${origins[@]}"; do
    origin="$(printf '%s' "${origin}" | xargs)"
    if [[ -n "${origin}" ]]; then
      printf '%s\0%s\0' --cors "${origin}"
    fi
  done
}

main() {
  configure_github_access
  bootstrap_once

  export OP_CONNECT_VAULT
  export HOME=/root

  log "Starting OpenCode server on ${WORKSHOP_HOSTNAME}:${WORKSHOP_PORT}"

  local -a cors_args=()
  while IFS= read -r -d '' arg; do
    cors_args+=("${arg}")
  done < <(build_cors_args)

  exec opencode serve --hostname "${WORKSHOP_HOSTNAME}" --port "${WORKSHOP_PORT}" "${cors_args[@]}"
}

main "$@"
