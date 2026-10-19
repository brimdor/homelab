#!/bin/bash
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
root=${BACKUP_DIR:?BACKUP_DIR is required}
[[ "$root" == /* && "$root" != / && "$root" != */ ]] || fail 'Invalid backup directory.'
owner=homelab-postgres-threads-v1
[[ ! -L "$root" ]] || fail 'Backup directory is a symlink.'
if mkdir -- "$root" 2>/dev/null; then
  printf '%s\n' "$owner" > "$root/.owner"
fi
[[ -d "$root" && -f "$root/.owner" && ! -L "$root/.owner" ]] || fail 'Backup directory ownership is unproven.'
[[ "$(cat -- "$root/.owner")" == "$owner" ]] || fail 'Backup directory belongs to another owner.'

work=$(mktemp -d "$root/.partial.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
name="threads-$(date -u +%Y%m%dT%H%M%SZ)-${work##*.}.dump"
if ! pg_dump --no-password --format=custom --lock-wait-timeout=10s \
  --file="$work/$name" 2> "$work/dump.stderr"; then
  fail 'Threads pg_dump failed; no backup published. Check database access privately.'
fi
[[ -s "$work/$name" && ! -s "$work/dump.stderr" ]] || fail 'Threads dump is empty or reported warnings; no backup published.'
if ! pg_restore --list "$work/$name" > /dev/null 2> "$work/restore.stderr"; then
  fail 'Threads archive listing failed; no backup published.'
fi
[[ ! -s "$work/restore.stderr" ]] || fail 'Threads archive listing reported warnings; no backup published.'
(cd "$work" && sha256sum -- "$name") > "$work/$name.sha256"
printf '%s\n' "$owner" > "$work/$name.owner"
# A hard link publishes the complete archive atomically and refuses an existing name.
ln -- "$work/$name" "$root/$name"
ln -- "$work/$name.sha256" "$root/$name.sha256"
ln -- "$work/$name.owner" "$root/$name.owner"

find "$root" -mindepth 1 -maxdepth 1 -name 'threads-*.dump' -mtime +14 -print0 > "$work/expired"
removed=0
while IFS= read -r -d '' old; do
  base=${old##*/}
  [[ "$base" =~ ^threads-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]{6}\.dump$ ]] || fail 'Unrecognized expired backup; preserved.'
  for file in "$old" "$old.sha256" "$old.owner"; do
    [[ -f "$file" && ! -L "$file" ]] || fail 'Incomplete or symlinked expired backup; preserved.'
  done
  [[ "$(cat -- "$old.owner")" == "$owner" ]] || fail 'Unowned expired backup; preserved.'
  line=$(cat -- "$old.sha256")
  checksum=${line%% *}
  [[ "$checksum" =~ ^[0-9a-f]{64}$ && "$line" == "$checksum  $base" ]] || fail 'Malformed backup checksum; preserved.'
  actual=$(sha256sum -- "$old")
  [[ "${actual%% *}" == "$checksum" ]] || fail 'Backup checksum mismatch; preserved.'
  rm -- "$old" "$old.sha256" "$old.owner"
  removed=$((removed + 1))
done < "$work/expired"
printf 'Threads backup published; expired owned generations removed: %s\n' "$removed"
