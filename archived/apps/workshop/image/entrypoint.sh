#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_SENTINEL="/root/.local/share/workshop/bootstrap-complete"
CHEZMOI_SOURCE_DIR="/root/.local/share/chezmoi"
WORKSHOP_PORT="${WORKSHOP_PORT:-4096}"
WORKSHOP_HOSTNAME="${WORKSHOP_HOSTNAME:-0.0.0.0}"
WORKSHOP_CORS_ORIGINS="${WORKSHOP_CORS_ORIGINS:-https://workshop.eaglepass.io}"
WORKSHOP_STORAGE_ROOT="${WORKSHOP_STORAGE_ROOT:-/mnt/workshop-storage}"
WORKSHOP_CACHE_ROOT="${WORKSHOP_CACHE_ROOT:-/mnt/workshop-cache}"
WORKSHOP_CACHE_SUBDIR="${WORKSHOP_CACHE_SUBDIR:-opencode}"
WORKSHOP_GITHUB_USERNAME="${WORKSHOP_GITHUB_USERNAME:-brimdor}"
WORKSHOP_SSH_PORT="${WORKSHOP_SSH_PORT:-22}"
WORKSHOP_SSH_LISTEN_ADDRESS="${WORKSHOP_SSH_LISTEN_ADDRESS:-0.0.0.0}"
OP_CONNECT_VAULT="${OP_CONNECT_VAULT:-Server}"

log() {
  printf '[workshop] %s\n' "$*"
}

ensure_symlink_dir() {
  local target="$1"
  local link_path="$2"

  mkdir -p "$(dirname "${link_path}")" "${target}"

  if [[ -L "${link_path}" ]]; then
    rm -f "${link_path}"
  elif [[ -e "${link_path}" ]]; then
    rm -rf "${link_path}"
  fi

  ln -s "${target}" "${link_path}"
}

prepare_persistent_layout() {
  if [[ -d "${WORKSHOP_STORAGE_ROOT}" ]]; then
    mkdir -p \
      "${WORKSHOP_STORAGE_ROOT}/workspace" \
      "${WORKSHOP_STORAGE_ROOT}/state/opencode" \
      "${WORKSHOP_STORAGE_ROOT}/state/ssh" \
      "${WORKSHOP_STORAGE_ROOT}/config/opencode"

    ensure_symlink_dir "${WORKSHOP_STORAGE_ROOT}/workspace" /workspace
    ensure_symlink_dir "${WORKSHOP_STORAGE_ROOT}/state/opencode" /root/.local/share/opencode
    ensure_symlink_dir "${WORKSHOP_STORAGE_ROOT}/config/opencode" /root/.config/opencode
  fi

  if [[ -d "${WORKSHOP_CACHE_ROOT}" ]]; then
    ensure_symlink_dir "${WORKSHOP_CACHE_ROOT}/${WORKSHOP_CACHE_SUBDIR}" /root/.cache
  fi
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
    export GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-$GITHUB_TOKEN}"
  fi

  mkdir -p /root/.ssh
  chmod 700 /root/.ssh

  if [[ -n "${WORKSHOP_SSH_PRIVATE_KEY:-}" ]]; then
    normalize_ssh_private_key > /root/.ssh/id_ed25519
    chmod 600 /root/.ssh/id_ed25519
  fi

  if [[ -n "${WORKSHOP_SSH_PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "${WORKSHOP_SSH_PUBLIC_KEY}" > /root/.ssh/id_ed25519.pub
    printf '%s\n' "${WORKSHOP_SSH_PUBLIC_KEY}" > /root/.ssh/authorized_keys
    chmod 644 /root/.ssh/id_ed25519.pub /root/.ssh/authorized_keys
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

configure_kubeconfig() {
  local sa_dir="/var/run/secrets/kubernetes.io/serviceaccount"
  local token_file="${sa_dir}/token"
  local namespace_file="${sa_dir}/namespace"

  if [[ ! -f "${token_file}" || ! -f "${namespace_file}" || -z "${KUBERNETES_SERVICE_HOST:-}" ]]; then
    return
  fi

  mkdir -p /root/.kube /home/brimdor/.kube

  python3 - <<'PY'
from pathlib import Path
import os

token = Path('/var/run/secrets/kubernetes.io/serviceaccount/token').read_text().strip()
namespace = Path('/var/run/secrets/kubernetes.io/serviceaccount/namespace').read_text().strip()
server = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', os.environ.get('KUBERNETES_SERVICE_PORT', '443'))}"
config = f"""apiVersion: v1
kind: Config
clusters:
  - cluster:
      certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
      server: {server}
    name: in-cluster
contexts:
  - context:
      cluster: in-cluster
      namespace: {namespace}
      user: workshop
    name: in-cluster
current-context: in-cluster
users:
  - name: workshop
    user:
      token: {token}
"""
for path in ('/root/.kube/config', '/home/brimdor/.kube/config'):
    Path(path).write_text(config)
    Path(path).chmod(0o600)
PY
}

install_opencode_config() {
  mkdir -p /root/.config/opencode
  cp /usr/local/share/workshop/opencode.json /root/.config/opencode/opencode.json
}

patch_dotfiles_for_service_account_mode() {
  python3 - <<'PY'
from pathlib import Path

path = Path('/root/.local/share/chezmoi/dot_dotfiles/functions/opAll.zsh.tmpl')
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

sync_dotfiles_source() {
  local repo_url="https://github.com/${WORKSHOP_GITHUB_USERNAME}/dotfiles.git"

  log "Syncing dotfiles from ${repo_url}"
  rm -rf "${CHEZMOI_SOURCE_DIR}"
  mkdir -p "$(dirname "${CHEZMOI_SOURCE_DIR}")"
  git clone --depth=1 "${repo_url}" "${CHEZMOI_SOURCE_DIR}"
}

apply_dotfiles() {
  sync_dotfiles_source

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

prepare_runtime() {
  export HOME=/root
  export OP_CONNECT_VAULT

  prepare_persistent_layout
  configure_github_access
  configure_kubeconfig
  install_opencode_config
  apply_dotfiles
}

bootstrap_opencode_once() {
  if [[ -f "${BOOTSTRAP_SENTINEL}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${BOOTSTRAP_SENTINEL}")"
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

ensure_sshd_host_keys() {
  local ssh_state_dir="${WORKSHOP_STORAGE_ROOT}/state/ssh"

  mkdir -p /run/sshd "${ssh_state_dir}"

  if [[ ! -f "${ssh_state_dir}/ssh_host_ed25519_key" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${ssh_state_dir}/ssh_host_ed25519_key"
  fi

  if [[ ! -f "${ssh_state_dir}/ssh_host_rsa_key" ]]; then
    ssh-keygen -q -t rsa -b 4096 -N '' -f "${ssh_state_dir}/ssh_host_rsa_key"
  fi

  chmod 600 "${ssh_state_dir}/ssh_host_ed25519_key" "${ssh_state_dir}/ssh_host_rsa_key"
  chmod 644 "${ssh_state_dir}/ssh_host_ed25519_key.pub" "${ssh_state_dir}/ssh_host_rsa_key.pub"
}

install_sshd_config() {
  local ssh_state_dir="${WORKSHOP_STORAGE_ROOT}/state/ssh"

  cat > /etc/ssh/sshd_config <<EOF
Port ${WORKSHOP_SSH_PORT}
ListenAddress ${WORKSHOP_SSH_LISTEN_ADDRESS}
Protocol 2
HostKey ${ssh_state_dir}/ssh_host_ed25519_key
HostKey ${ssh_state_dir}/ssh_host_rsa_key
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM no
X11Forwarding no
PermitTunnel no
AllowAgentForwarding yes
AllowTcpForwarding yes
GatewayPorts no
ClientAliveInterval 120
ClientAliveCountMax 2
AuthorizedKeysFile .ssh/authorized_keys
PidFile /run/sshd.pid
PrintMotd no
Subsystem sftp /usr/lib/openssh/sftp-server
EOF
}

start_sshd() {
  ensure_sshd_host_keys
  install_sshd_config

  log "Starting sshd on ${WORKSHOP_SSH_LISTEN_ADDRESS}:${WORKSHOP_SSH_PORT}"
  /usr/sbin/sshd -D -e &
  local sshd_pid=$!
  sleep 1
  if ! kill -0 "${sshd_pid}" 2>/dev/null; then
    log "sshd failed to start"
    wait "${sshd_pid}"
  fi
}

run_opencode_server() {
  prepare_runtime
  bootstrap_opencode_once
  start_sshd

  log "Starting OpenCode server on ${WORKSHOP_HOSTNAME}:${WORKSHOP_PORT}"

  local -a cors_args=()
  while IFS= read -r -d '' arg; do
    cors_args+=("${arg}")
  done < <(build_cors_args)

  exec opencode serve --hostname "${WORKSHOP_HOSTNAME}" --port "${WORKSHOP_PORT}" "${cors_args[@]}"
}

main() {
  case "${1:-opencode-serve}" in
    opencode-serve)
      shift || true
      run_opencode_server "$@"
      ;;
    *)
      exec "$@"
      ;;
  esac
}

main "$@"
