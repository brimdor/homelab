#!/bin/bash
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
source=/backup/db/threads/threads-20261019T050021Z-1OIPAn.dump
expected=b99deae771c2f4002d0cba0a7f520674487acf732f4bc6fe59b0eaf5fbd00d44
target=/backup/recovery-threads-20261019
[[ -f "$source" && ! -L "$source" ]] || fail 'Exact source archive is unavailable.'
actual=$(sha256sum -- "$source")
[[ "${actual%% *}" == "$expected" ]] || fail 'Source archive changed; restore refused.'
mkdir -- "$target" || fail 'Recovery destination already exists or is inaccessible; preserved.'
printf '%s\n' homelab-threads-restore-20261019 > "$target/.owner"

stop_server() {
  if [[ -f "$target/data/postmaster.pid" ]]; then
    pg_ctl -D "$target/data" -m fast -w -t 60 stop > "$target/shutdown.log" 2>&1 || return 1
  fi
}
cleanup() {
  status=$?
  trap - EXIT
  if ! stop_server; then
    printf '%s\n' 'Recovery server shutdown failed; inspect private recovery diagnostics.' >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

initdb -D "$target/data" -U recovery --auth-local=trust --auth-host=reject \
  --encoding=UTF8 --locale=en_US.utf8 --data-checksums > "$target/initdb.log" 2>&1 \
  || fail 'Isolated initialization failed; recovery material retained.'
pg_ctl -D "$target/data" -l "$target/server.log" -w -t 60 \
  -o '-c listen_addresses= -c unix_socket_directories=/tmp -c unix_socket_permissions=0700 -c shared_buffers=16MB -c max_connections=10' \
  start > "$target/start.log" 2>&1 || fail 'Isolated server startup failed; recovery material retained.'
export PGHOST=/tmp PGUSER=recovery PGDATABASE=threads_verify PGCONNECT_TIMEOUT=10
unset PGPASSWORD PGSERVICE PGSERVICEFILE
createdb --maintenance-db=postgres --template=template0 threads_verify > "$target/create.log" 2>&1 \
  || fail 'Isolated database creation failed.'
pg_restore --no-password --exit-on-error --no-owner --no-privileges --dbname=threads_verify \
  "$source" > "$target/restore.log" 2>&1 || fail 'Isolated restore failed; recovery material retained.'
metadata=$(psql -X -w -At -v ON_ERROR_STOP=1 -c "SELECT current_setting('server_version_num'),pg_encoding_to_char(encoding),datcollate,datctype,(SELECT count(*) FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'),(SELECT count(*) FROM pg_extension) FROM pg_database WHERE datname=current_database()" 2> "$target/metadata.stderr")
[[ "$metadata" == '170005|UTF8|en_US.utf8|en_US.utf8|1|1' ]] || fail 'Restored version/locale/catalog metadata differs from source.'
relations=$(psql -X -w -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FILTER (WHERE relkind IN ('r','p')),count(*) FILTER (WHERE relkind='S'),count(*) FILTER (WHERE relkind IN ('v','m')) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'" 2> "$target/relations.stderr")
[[ "$relations" == '0|0|0' ]] || fail 'Restored user-relation counts differ from source.'
stop_server || fail 'Recovery server did not stop cleanly.'
[[ ! -e "$target/data/postmaster.pid" ]] || fail 'Recovery server PID file remains.'
printf 'archive_sha256=%s\nmetadata=%s\nuser_relations=%s\nserver_stopped=true\nempty_application_schema=true\n' \
  "$expected" "$metadata" "$relations" > "$target/verified.txt"
printf '%s\n' 'Threads isolated restore verified; server stopped; durable recovery retained.'
