#!/bin/bash
set -euo pipefail
phase=identity
trap 'printf "HOMELAB103:STARTUP-FAILED:%s\n" "$phase" >&2' ERR
export PGDATA=/bitnami/postgresql/data
[[ $(id -u) == 1001 && $(id -g) == 1001 && $(uname -m) == x86_64 ]]
phase=existing-pgdata
[[ -d "$PGDATA" && ! -L "$PGDATA" && ! -L /bitnami && ! -L /bitnami/postgresql ]]
[[ -f "$PGDATA/PG_VERSION" && ! -L "$PGDATA/PG_VERSION" && $(cat "$PGDATA/PG_VERSION") == 16 ]]
[[ $(stat -c '%u:%g' "$PGDATA") == 1001:1001 ]]
phase=pgdata-mode
case $(stat -c '%a' "$PGDATA") in 700|2700|770|2770) ;; *) false ;; esac
# Kubelet fsGroup may add group bits; match the existing vendor's root-only preparation.
identity=$(stat -c '%d:%i:%u:%g' "$PGDATA")
chmod go-rwx "$PGDATA"
[[ $(stat -c '%d:%i:%u:%g' "$PGDATA") == "$identity" ]]
phase=private-runtime
umask 077
runtime=$(mktemp -d /tmp/postgres-runtime.XXXXXXXX)
printf 'postgres:x:1001:1001:PostgreSQL:/bitnami/postgresql:/bin/false\n' > "$runtime/passwd"
printf 'postgres:x:1001:\n' > "$runtime/group"
export NSS_WRAPPER_PASSWD="$runtime/passwd" NSS_WRAPPER_GROUP="$runtime/group"
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libnss_wrapper.so
phase=nss-and-config
[[ -f "$LD_PRELOAD" && ! -L /configuration/postgresql.conf && ! -L /configuration/pg_hba.conf ]]
phase=postgres-exec
exec /usr/lib/postgresql/16/bin/postgres -D "$PGDATA" \
  -c config_file=/configuration/postgresql.conf \
  -c hba_file=/configuration/pg_hba.conf \
  -c external_pid_file=/opt/bitnami/postgresql/tmp/postgresql.pid \
  -c unix_socket_directories=/tmp
