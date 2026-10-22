#!/bin/bash
set -euo pipefail
export PGDATA=/bitnami/postgresql/data
[[ $(id -u) == 1001 && $(id -g) == 1001 && $(uname -m) == x86_64 ]]
[[ -d "$PGDATA" && ! -L "$PGDATA" && ! -L /bitnami && ! -L /bitnami/postgresql ]]
[[ -f "$PGDATA/PG_VERSION" && ! -L "$PGDATA/PG_VERSION" && $(cat "$PGDATA/PG_VERSION") == 16 ]]
[[ $(stat -c '%u:%g' "$PGDATA") == 1001:1001 ]]
case $(stat -c '%a' "$PGDATA") in 700|2700) ;; *) exit 1 ;; esac
umask 077
runtime=$(mktemp -d /tmp/postgres-runtime.XXXXXXXX)
printf 'postgres:x:1001:1001:PostgreSQL:/bitnami/postgresql:/bin/false\n' > "$runtime/passwd"
printf 'postgres:x:1001:\n' > "$runtime/group"
export NSS_WRAPPER_PASSWD="$runtime/passwd" NSS_WRAPPER_GROUP="$runtime/group"
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libnss_wrapper.so
[[ -f "$LD_PRELOAD" && ! -L /configuration/postgresql.conf && ! -L /configuration/pg_hba.conf ]]
exec /usr/lib/postgresql/16/bin/postgres -D "$PGDATA" \
  -c config_file=/configuration/postgresql.conf \
  -c hba_file=/configuration/pg_hba.conf \
  -c external_pid_file=/opt/bitnami/postgresql/tmp/postgresql.pid \
  -c unix_socket_directories=/tmp
