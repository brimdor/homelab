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

uv tool install --force command-center --from git+https://github.com/brimdor/command-center.git
ln -sf /root/.local/bin/cmdctl /usr/local/bin/cmdctl
cmdctl init --opencode

exec opencode web "$@"
