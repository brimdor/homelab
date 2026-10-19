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

temporary=()
cleanup() {
  status=$?
  trap - EXIT
  if (( ${#temporary[@]} )) && ! rm -f -- "${temporary[@]}"; then
    printf '%s\n' 'Threads temporary-file cleanup failed; inspect the reserved partial files.' >&2
    exit 1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
reserve_file() {
  local reserved
  reserved=$(mktemp "$root/.partial.XXXXXX") || fail 'Cannot reserve private backup work.'
  temporary+=("$reserved")
  printf -v "$1" '%s' "$reserved"
}
# Independent files avoid the observed NFS temporary-directory removal failure.
archive='' dump_stderr='' restore_stderr='' checksum_file='' owner_file='' expired_file=''
reserve_file archive
reserve_file dump_stderr
reserve_file restore_stderr
reserve_file checksum_file
reserve_file owner_file
reserve_file expired_file
name="threads-$(date -u +%Y%m%dT%H%M%SZ)-${archive##*.}.dump"
if ! pg_dump --no-password --format=custom --lock-wait-timeout=10s \
  --file="$archive" 2> "$dump_stderr"; then
  fail 'Threads pg_dump failed; no backup published. Check database access privately.'
fi
[[ -s "$archive" && ! -s "$dump_stderr" ]] || fail 'Threads dump is empty or reported warnings; no backup published.'
if ! pg_restore --list "$archive" > /dev/null 2> "$restore_stderr"; then
  fail 'Threads archive listing failed; no backup published.'
fi
[[ ! -s "$restore_stderr" ]] || fail 'Threads archive listing reported warnings; no backup published.'
line=$(sha256sum -- "$archive")
printf '%s  %s\n' "${line%% *}" "$name" > "$checksum_file"
printf '%s\n' "$owner" > "$owner_file"
# A hard link publishes the complete archive atomically and refuses an existing name.
ln -- "$archive" "$root/$name"
ln -- "$checksum_file" "$root/$name.sha256"
ln -- "$owner_file" "$root/$name.owner"

find "$root" -mindepth 1 -maxdepth 1 -name 'threads-*.dump' -mtime +14 -print0 > "$expired_file"
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
done < "$expired_file"
printf 'Threads backup published; expired owned generations removed: %s\n' "$removed"
