#!/bin/bash
set -euo pipefail
umask 077
script_dir=${BASH_SOURCE[0]%/*}
# shellcheck source=apps/postgres/scripts/recovery-common.sh
source "$script_dir/recovery-common.sh"
root=${RECOVERY_ROOT:-/backup/recovery-postgres-20261019}
expected=${EXPECTED_DATABASE_SET_SHA256:?Reviewed database set is required}
recovery_path "$root" || recovery_fail 'Unsafe recovery destination.'
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || recovery_fail 'Invalid database-set fingerprint.'
mkdir -- "$root" || recovery_fail 'Recovery destination already exists or is inaccessible; preserved.'
printf '%s\n' "$recovery_owner" > "$root/.owner"
mkdir -- "$root/restored"
printf '%s\n' "$recovery_owner" > "$root/restored/.owner"
cleanup() {
  local result=$?
  trap - EXIT
  recovery_stop_clients
  exit "$result"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
export PGAPPNAME=homelab-recovery-export-20261019
export PGOPTIONS='-c default_transaction_read_only=on -c lock_timeout=10s -c timezone=UTC'
available=$(df -Pk -- "$root" | awk 'END {print $4}')
[[ "$available" =~ ^[0-9]+$ && "$available" -ge 1048576 ]] \
  || recovery_fail 'At least 1 GiB of free NAS space is required for this recovery.'
PGDATABASE=template1 recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -c \
  "SELECT count(*)=0 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','m')" \
  > "$root/template-prerequisites.tsv" 2> "$root/template-prerequisites.stderr" \
  || recovery_fail 'Template database review failed.'
[[ "$(cat "$root/template-prerequisites.tsv")" == t ]] \
  || recovery_fail 'Template database now contains user relations; review required.'

recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -c \
  "SELECT current_setting('server_version_num')='170005' AND bool_and(datallowconn AND datname ~ '^[A-Za-z0-9_-]+$' AND pg_encoding_to_char(encoding)='UTF8' AND datcollate='en_US.utf8' AND datctype='en_US.utf8' AND datlocprovider='c') AND count(*)=6 AND count(*) FILTER(WHERE datname='$recovery_control')=0 AND (SELECT count(*)=0 FROM pg_roles WHERE rolname='$recovery_admin') AND (SELECT count(*)=0 FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global')) FROM pg_database WHERE NOT datistemplate" \
  > "$root/prerequisites.tsv" 2> "$root/prerequisites.stderr" || recovery_fail 'Prerequisite query failed.'
safe=$(cat "$root/prerequisites.tsv")
[[ "$safe" == t ]] || recovery_fail 'Reviewed PostgreSQL prerequisites changed.'
recovery_catalog > "$root/catalog.tsv" 2> "$root/catalog.stderr" \
  || recovery_fail 'Database catalog could not be captured.'
[[ "$(recovery_keyset "$root/catalog.tsv")" == "$expected" ]] \
  || recovery_fail 'Database identities changed; export refused.'
recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -f "$script_dir/recovery-roles.sql" \
  > "$root/roles.sha256" 2> "$root/roles.stderr" || recovery_fail 'Role fingerprint failed.'
while IFS='|' read -r key database; do
  [[ "$key" =~ ^[0-9a-f]{64}$ && "$database" =~ ^[A-Za-z0-9_-]+$ ]] \
    || recovery_fail 'Unsafe catalog entry.'
  PGDATABASE="$database" recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -c \
    'SELECT (SELECT count(*)=0 FROM pg_foreign_table) AND (SELECT count(*)=0 FROM pg_largeobject)' \
    > "$root/$key.features.tsv" 2> "$root/$key.features.stderr" || recovery_fail 'Database feature query failed.'
  safe=$(cat "$root/$key.features.tsv")
  [[ "$safe" == t ]] || recovery_fail 'Reviewed database features changed.'
  PGDATABASE="$database" recovery_schema "$root/$key.before.sql" "$root/$key.schema.sha256" \
    2> "$root/$key.schema.stderr" \
    || recovery_fail 'Source schema fingerprint failed.'
done < "$root/catalog.tsv"

# These DROP/CREATE statements are backup bytes, never executed against production.
recovery_client pg_dumpall --no-password --database="$PGDATABASE" --no-role-passwords \
  --no-tablespaces --clean --if-exists --lock-wait-timeout=10s --file="$root/cluster.sql" \
  2> "$root/export.stderr" || recovery_fail 'Logical export failed; private recovery material retained.'
[[ -s "$root/cluster.sql" && ! -s "$root/export.stderr" ]] \
  || recovery_fail 'Logical export is empty or reported warnings.'
while IFS='|' read -r key database; do
  PGDATABASE="$database" recovery_schema "$root/$key.after.sql" "$root/$key.after.sha256" \
    2> "$root/$key.after.stderr" || recovery_fail 'Post-export schema check failed.'
  cmp -- "$root/$key.after.sha256" "$root/$key.schema.sha256" \
    || recovery_fail 'Schema changed during export; bundle remains incomplete.'
done < "$root/catalog.tsv"
recovery_client psql -X -w -Atq -v ON_ERROR_STOP=1 -f "$script_dir/recovery-roles.sql" \
  > "$root/roles-after.sha256" 2> "$root/roles-after.stderr" || recovery_fail 'Post-export role check failed.'
cmp -- "$root/roles-after.sha256" "$root/roles.sha256" || recovery_fail 'Roles changed during export.'
recovery_catalog > "$root/catalog-after.tsv" 2> "$root/catalog-after.stderr" \
  || recovery_fail 'Post-export catalog check failed.'
cmp -- "$root/catalog.tsv" "$root/catalog-after.tsv" || recovery_fail 'Catalog changed during export.'
files=(cluster.sql catalog.tsv roles.sha256)
while IFS='|' read -r key _; do files+=("$key.schema.sha256"); done < "$root/catalog.tsv"
(cd "$root" && sha256sum -- "${files[@]}") > "$root/manifest.sha256"
line=$(sha256sum -- "$root/manifest.sha256")
printf '%s\n' "${line%% *}" > "$root/.complete"
printf '%s\n' 'PostgreSQL recovery export complete; databases: 6; role passwords omitted.'
