#!/usr/bin/env bash
set -euo pipefail

export PATH="/root/.local/bin:/root/.opencode/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "${TOKEN}" ]]; then
  printf 'GITHUB_TOKEN or GH_TOKEN is required to install command-center at startup.\n' >&2
  exit 1
fi

export OPENCODE_GIT_TOKEN="${TOKEN}"
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/usr/local/bin/git-askpass-opencode

mkdir -p /root/.ssh
chmod 0700 /root/.ssh

if [[ -f /run/opencode-secrets/ssh-private-key ]]; then
  cp /run/opencode-secrets/ssh-private-key /root/.ssh/id_ed25519
  python3 - <<'PY'
from pathlib import Path
import re

path = Path('/root/.ssh/id_ed25519')
content = path.read_text()
match = re.search(r'-----BEGIN OPENSSH PRIVATE KEY-----\s*(.*?)\s*-----END OPENSSH PRIVATE KEY-----', content, re.S)
if match:
    body = ''.join(match.group(1).split())
    normalized = '-----BEGIN OPENSSH PRIVATE KEY-----\n'
    normalized += '\n'.join(body[i:i + 70] for i in range(0, len(body), 70))
    normalized += '\n-----END OPENSSH PRIVATE KEY-----\n'
    path.write_text(normalized)
PY
  chmod 0600 /root/.ssh/id_ed25519
fi

if [[ -f /run/opencode-secrets/ssh-public-key ]]; then
  cp /run/opencode-secrets/ssh-public-key /root/.ssh/id_ed25519.pub
  chmod 0644 /root/.ssh/id_ed25519.pub
fi

touch /root/.ssh/known_hosts
chmod 0600 /root/.ssh/known_hosts

export GIT_SSH_COMMAND="ssh -i /root/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/root/.ssh/known_hosts"

uv tool install --force command-center --from git+https://github.com/brimdor/command-center.git
ln -sf /root/.local/bin/cmdctl /usr/local/bin/cmdctl
cmdctl init --opencode

exec opencode web "$@"
