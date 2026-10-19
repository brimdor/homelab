#!/usr/bin/env bash
# Restore only a fresh, independently qualified archive into a separate PG18 directory.
set -euo pipefail
umask 077

case "$POSTGRES_USER" in pointguide|pointview) ;; *) exit 10 ;; esac
case "$MIGRATION_ID" in 20261019-a) ;; *) exit 11 ;; esac
operation="migration-103-$MIGRATION_ID"
destination="pg18-maintenance-103-$MIGRATION_ID"

tree_hash() {
  (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1)
}

case "$1" in
  prepare)
    test "$(cat /volume/pgdata/PG_VERSION)" = 17
    test ! -e /volume/pgdata/postmaster.pid
    test ! -L /volume/pgdata
    test -z "$(find /volume/pgdata -type l -print -quit)"
    pg_controldata /volume/pgdata | grep -Eq '^Database cluster state: +shut down$'
    test ! -e "/volume/$operation"
    test ! -e "/volume/$destination"
    original=$(tree_hash /volume/pgdata)
    mkdir -m 700 "/volume/$operation" "/volume/$destination"
    printf '%s\n' "$original" > "/volume/$operation/original.sha256"
    printf '%s\n' prepared > "/volume/$operation/state"
    ;;
  receive)
    test "$(cat /recovery/state)" = prepared
    case "$2" in
      globals.sql) expected=$GLOBALS_SHA256 ;;
      database.dump) expected=$ARCHIVE_SHA256 ;;
      *) exit 12 ;;
    esac
    test ! -e "/recovery/$2"
    test ! -e "/recovery/$2.partial"
    (set -C; cat > "/recovery/$2.partial")
    test "$(sha256sum "/recovery/$2.partial" | cut -d ' ' -f 1)" = "$expected"
    sync "/recovery/$2.partial"
    mv "/recovery/$2.partial" "/recovery/$2"
    ;;
  seal)
    test "$(cat /recovery/state)" = prepared
    test "$(sha256sum /recovery/globals.sql | cut -d ' ' -f 1)" = "$GLOBALS_SHA256"
    test "$(sha256sum /recovery/database.dump | cut -d ' ' -f 1)" = "$ARCHIVE_SHA256"
    test "$(tree_hash /original)" = "$(cat /recovery/original.sha256)"
    printf '%s\n' sealed > /recovery/state
    ;;
  accept)
    test "$(cat /recovery/state)" = awaiting-verification
    test "$2" = "$MANIFEST_SHA256"
    printf '%s\n' accepted > /recovery/state
    ;;
  restore)
    test "$(postgres --version)" = 'postgres (PostgreSQL) 18.6'
    test "$PGDATA" = "/var/lib/postgresql/$destination"
    test -z "$(ls -A "$PGDATA")"
    test "$(cat /original/PG_VERSION)" = 17
    test ! -e /original/postmaster.pid
    test "$(tree_hash /original)" = "$(cat /recovery/original.sha256)"
    while test "$(cat /recovery/state)" = prepared; do sleep 2; done
    test "$(cat /recovery/state)" = sealed
    test "$(sha256sum /recovery/globals.sql | cut -d ' ' -f 1)" = "$GLOBALS_SHA256"
    test "$(sha256sum /recovery/database.dump | cut -d ' ' -f 1)" = "$ARCHIVE_SHA256"
    started=false
    cleanup() {
      if "$started"; then pg_ctl -D "$PGDATA" -w -m fast stop >/recovery/shutdown.log 2>&1; fi
      rm -f /tmp/postgres-password
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    # The pinned image supplies nss_wrapper for the chart's existing UID999.
    POSTGRES_INITDB_ARGS='' POSTGRES_HOST_AUTH_METHOD=scram-sha-256 bash -ec 'source /usr/local/bin/docker-entrypoint.sh; docker_init_database_dir \
      --auth-local=trust --auth-host=scram-sha-256 --encoding=UTF8 --locale=en_US.utf8 \
      --data-checksums; pg_setup_hba_conf postgres' >/recovery/initdb.log 2>&1
    pg_ctl -D "$PGDATA" -l /recovery/postgres.log -o \
      "-c listen_addresses='' -c unix_socket_directories=/tmp -c unix_socket_permissions=0700" -w start \
      >/recovery/startup.log 2>&1
    started=true
    # initdb already created exactly the original application role; retain every ALTER/GRANT.
    test "$(grep -Fxc "CREATE ROLE $POSTGRES_USER;" /recovery/globals.sql)" = 1
    sed "/^CREATE ROLE $POSTGRES_USER;$/d" /recovery/globals.sql > /recovery/globals-existing-role.sql
    psql -X -h /tmp -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 --single-transaction \
      -f /recovery/globals-existing-role.sql >/recovery/globals.log 2>&1
    pg_restore -h /tmp -U "$POSTGRES_USER" --exit-on-error --create -d postgres \
      /recovery/database.dump >/recovery/restore.log 2>&1
    printf '%s\n' awaiting-verification > /recovery/state
    while test "$(cat /recovery/state)" = awaiting-verification; do sleep 2; done
    test "$(cat /recovery/state)" = accepted
    pg_ctl -D "$PGDATA" -w -m fast stop >/recovery/shutdown.log 2>&1
    started=false
    test ! -e "$PGDATA/postmaster.pid"
    pg_checksums --check -D "$PGDATA" >/recovery/checksums.log 2>&1
    test "$(tree_hash /original)" = "$(cat /recovery/original.sha256)"
    test "$(sha256sum /recovery/globals.sql | cut -d ' ' -f 1)" = "$GLOBALS_SHA256"
    test "$(sha256sum /recovery/database.dump | cut -d ' ' -f 1)" = "$ARCHIVE_SHA256"
    printf '%s\n' complete > /recovery/state
    printf '%s\n' 'PG18_RESTORE_COMPLETE original_unchanged=true checksums=true shutdown=true'
    ;;
  *) exit 13 ;;
esac
