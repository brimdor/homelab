#!/bin/bash
# Shared helpers; callers own the EXIT/signal traps.
# shellcheck disable=SC2034 # Identity constants are used by the sourcing scripts.
recovery_owner=homelab-postgres-recovery-20261019
recovery_admin=homelab_restore_admin_20261019
recovery_control=homelab_restore_control_20261019
recovery_client_pid=

recovery_fail() { printf '%s\n' "$1" >&2; exit 1; }
recovery_client() {
  local result=0
  setsid "$@" &
  recovery_client_pid=$!
  wait "$recovery_client_pid" || result=$?
  recovery_client_pid=
  return "$result"
}
recovery_stop_clients() {
  if [[ -n "$recovery_client_pid" ]]; then
    kill -TERM -- "-$recovery_client_pid" 2>/dev/null || true
    wait "$recovery_client_pid" 2>/dev/null || true
    recovery_client_pid=
  fi
}
recovery_path() {
  [[ "$1" == /* && "$1" != / && "$1" != */ && ! -L "$1" ]]
}
recovery_catalog() {
  recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT encode(sha256(convert_to(datname,'UTF8')),'hex'),datname FROM pg_database WHERE NOT datistemplate AND datname<>'$recovery_control' ORDER BY datname"
}
recovery_keyset() {
  local line
  line=$(cut -d '|' -f 1 "$1" | LC_ALL=C sort | sha256sum)
  printf '%s\n' "${line%% *}"
}
recovery_schema() {
  local temporary=$1 output=$2 line
  recovery_client pg_dump --no-password --schema-only --create --no-comments \
    --no-tablespaces --lock-wait-timeout=10s --file="$temporary" || return 1
  line=$(sha256sum -- "$temporary") || return 1
  rm -- "$temporary" || return 1
  printf '%s\n' "${line%% *}" > "$output"
}
