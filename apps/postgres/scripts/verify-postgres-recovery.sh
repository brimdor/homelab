#!/bin/bash
set -euo pipefail
umask 077
script_dir=${BASH_SOURCE[0]%/*}
# shellcheck source=apps/postgres/scripts/recovery-common.sh
source "$script_dir/recovery-common.sh"
bundle=${SOURCE_ROOT:-/source}
target=${RESTORE_ROOT:-/restore}
expected=${EXPECTED_MANIFEST_SHA256:?Pinned manifest is required}
keyset=${EXPECTED_DATABASE_SET_SHA256:?Reviewed database set is required}
if ! recovery_path "$bundle" || ! recovery_path "$target"; then
  recovery_fail 'Unsafe recovery paths.'
fi
[[ "$expected" =~ ^[0-9a-f]{64}$ && "$keyset" =~ ^[0-9a-f]{64}$ ]] \
  || recovery_fail 'Invalid pinned fingerprints.'
for directory in "$bundle" "$target"; do
  [[ -f "$directory/.owner" && ! -L "$directory/.owner" && "$(cat "$directory/.owner")" == "$recovery_owner" ]] \
    || recovery_fail 'Recovery ownership is unproven.'
done
[[ ! -e "$target/data" && ! -L "$target/data" ]] || recovery_fail 'Existing recovery database preserved.'
[[ -f "$bundle/.complete" && ! -L "$bundle/.complete" && "$(cat "$bundle/.complete")" == "$expected" ]] \
  || recovery_fail 'Recovery bundle is incomplete.'
[[ -f "$bundle/manifest.sha256" && ! -L "$bundle/manifest.sha256" ]] || recovery_fail 'Manifest is unavailable.'
line=$(sha256sum -- "$bundle/manifest.sha256")
[[ "${line%% *}" == "$expected" ]] || recovery_fail 'Pinned manifest changed.'
declare -a listed=()
while IFS= read -r line; do
  checksum=${line%% *}
  name=${line#*  }
  [[ "$checksum" =~ ^[0-9a-f]{64}$ && "$line" == "$checksum  $name" ]] \
    || recovery_fail 'Malformed manifest.'
  [[ "$name" == cluster.sql || "$name" == catalog.tsv || "$name" == roles.sha256 || "$name" =~ ^[0-9a-f]{64}\.schema\.sha256$ ]] \
    || recovery_fail 'Unsafe manifest path.'
  [[ -f "$bundle/$name" && ! -L "$bundle/$name" ]] || recovery_fail 'Missing or symlinked recovery input.'
  listed+=("$name")
done < "$bundle/manifest.sha256"
[[ ${#listed[@]} -eq 9 && "$(printf '%s\n' "${listed[@]}" | LC_ALL=C sort -u | wc -l)" -eq 9 ]] \
  || recovery_fail 'Unexpected manifest membership.'
for name in cluster.sql catalog.tsv roles.sha256; do
  [[ " ${listed[*]} " == *" $name "* ]] || recovery_fail 'Required manifest input is missing.'
done
(cd "$bundle" && sha256sum --strict --check --quiet manifest.sha256) \
  > "$target/checksums.log" 2>&1 || recovery_fail 'Recovery input checksum failed.'
[[ "$(recovery_keyset "$bundle/catalog.tsv")" == "$keyset" ]] || recovery_fail 'Unexpected database identities.'
count=0
while IFS='|' read -r key database; do
  [[ "$key" =~ ^[0-9a-f]{64}$ && "$database" =~ ^[A-Za-z0-9_-]+$ ]] || recovery_fail 'Unsafe catalog entry.'
  [[ "$(printf '%s' "$database" | sha256sum | cut -d ' ' -f 1)" == "$key" ]] || recovery_fail 'Database key mismatch.'
  [[ -f "$bundle/$key.schema.sha256" && ! -L "$bundle/$key.schema.sha256" ]] || recovery_fail 'Missing schema fingerprint.'
  [[ " ${listed[*]} " == *" $key.schema.sha256 "* ]] || recovery_fail 'Schema input is not checksummed.'
  count=$((count + 1))
done < "$bundle/catalog.tsv"
[[ "$count" -eq 6 ]] || recovery_fail 'Incomplete database coverage.'

stop_server() {
  if [[ -f "$target/data/postmaster.pid" ]]; then
    pg_ctl -D "$target/data" -m fast -w -t 60 stop > "$target/shutdown.log" 2>&1 || return 1
  fi
}
cleanup() {
  local result=$?
  trap - EXIT
  recovery_stop_clients
  if ! stop_server; then
    printf '%s\n' 'Isolated recovery shutdown failed; inspect private diagnostics.' >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
unset PGPASSWORD PGSERVICE PGSERVICEFILE PGOPTIONS
export PGHOST=/tmp PGPORT=5432 PGUSER="$recovery_admin" PGDATABASE="$recovery_control" PGCONNECT_TIMEOUT=10
initdb -D "$target/data" -U "$recovery_admin" --auth-local=trust --auth-host=reject \
  --encoding=UTF8 --locale=en_US.utf8 --data-checksums > "$target/initdb.log" 2>&1 \
  || recovery_fail 'Isolated initialization failed.'
pg_ctl -D "$target/data" -l "$target/server.log" -w -t 60 \
  -o '-c listen_addresses= -c unix_socket_directories=/tmp -c unix_socket_permissions=0700 -c shared_buffers=32MB -c max_connections=10' \
  start > "$target/start.log" 2>&1 || recovery_fail 'Isolated startup failed.'
recovery_client createdb --maintenance-db=postgres "$recovery_control" > "$target/control.log" 2>&1 \
  || recovery_fail 'Control database creation failed.'
recovery_client psql -X -w -v ON_ERROR_STOP=1 -f "$bundle/cluster.sql" \
  > "$target/restore.log" 2> "$target/restore.stderr" || recovery_fail 'Isolated SQL recovery failed.'
export PGOPTIONS='-c default_transaction_read_only=on -c timezone=UTC'
recovery_catalog > "$target/catalog.tsv" 2> "$target/catalog.stderr" || recovery_fail 'Restored catalog read failed.'
cmp -- "$bundle/catalog.tsv" "$target/catalog.tsv" || recovery_fail 'Restored database identities differ.'
recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -f "$script_dir/recovery-roles.sql" \
  > "$target/roles.sha256" 2> "$target/roles.stderr" || recovery_fail 'Restored role verification failed.'
cmp -- "$target/roles.sha256" "$bundle/roles.sha256" || recovery_fail 'Restored authorizations differ.'
while IFS='|' read -r key database; do
  PGDATABASE="$database" recovery_schema "$target/$key.schema.sql" "$target/$key.schema.sha256" \
    2> "$target/$key.schema.stderr" || recovery_fail 'Restored schema verification failed.'
  cmp -- "$target/$key.schema.sha256" "$bundle/$key.schema.sha256" || recovery_fail 'Restored schema differs.'
  PGDATABASE="$database" recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 \
    -f "$script_dir/recovery-row-counts.sql" > "$target/$key.rows.tsv" \
    2> "$target/$key.rows.stderr" || recovery_fail 'Restored data count failed.'
done < "$bundle/catalog.tsv"
relations=0
rows=0
while IFS='|' read -r key database; do
  while IFS='|' read -r relation kind amount; do
    [[ "$relation" =~ ^[0-9a-f]{64}$ && "$kind" =~ ^[rm]$ && "$amount" =~ ^[0-9]+$ ]] \
      || recovery_fail 'Invalid restored row-count evidence.'
    relations=$((relations + 1))
    if [[ "$kind" == r ]]; then rows=$((rows + amount)); fi
  done < "$target/$key.rows.tsv"
done < "$bundle/catalog.tsv"
copy_rows=$(awk '$1 == "COPY" && NF == 2 && $2 ~ /^[0-9]+$/ {n += $2} END {printf "%.0f\n",n+0}' "$target/restore.log")
[[ "$rows" == "$copy_rows" ]] || recovery_fail 'Restored base-table rows differ from acknowledged COPY rows.'
stop_server || recovery_fail 'Isolated server did not stop cleanly.'
[[ ! -e "$target/data/postmaster.pid" ]] || recovery_fail 'Isolated server PID file remains.'
pg_checksums --check -D "$target/data" > "$target/page-checksums.log" 2>&1 \
  || recovery_fail 'Restored data-page checksum verification failed.'
printf 'manifest_sha256=%s\ndatabases=6\nrelations=%s\nbase_table_rows=%s\ncopy_rows=%s\nserver_stopped=true\npage_checksums_verified=true\nrole_passwords_omitted=true\n' \
  "$expected" "$relations" "$rows" "$copy_rows" > "$target/verified.txt"
printf '%s\n' 'PostgreSQL isolated recovery verified; six databases; server stopped; page checksums passed.'
