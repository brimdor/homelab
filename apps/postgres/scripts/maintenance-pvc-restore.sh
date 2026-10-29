#!/bin/bash
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'The governed PVC receiver must run as root.'
expected=${SOURCE_ARCHIVE_SHA256:?Exact protected archive hash is required}
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail 'Invalid protected archive fingerprint.'
root=/restore
data=/var/lib/postgresql/data
point=$root/.maintenance103-physical-restore
[[ -d "$root/data" && ! -L "$root/data" && ! -L "$data" ]] || fail 'Original PVC data directory is unavailable.'
[[ "$(stat -c '%d:%i' "$root/data")" == "$(stat -c '%d:%i' "$data")" ]] \
  || fail 'Image data path does not resolve to the original PVC.'
[[ -z "$(find "$data" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail 'Existing database files preserved; restore refused.'
mkdir -m 0700 -- "$point" || fail 'Restore intent already exists; inspect without replay.'
printf '%s\n' "$expected" > "$point/intent.sha256"
sync -f "$point"
cat > "$point/base.tar"
sync -f "$point/base.tar"
line=$(sha256sum -- "$point/base.tar")
[[ "${line%% *}" == "$expected" ]] || fail 'Transfer checksum failed; protected partial retained.'
# Exact bytes were inspected and restored in isolation before this PVC handoff.
tar --extract --file "$point/base.tar" --directory "$data" --same-owner --same-permissions
chown 999:999 -- "$data"
chmod 0700 -- "$data"
[[ "$(cat "$data/PG_VERSION")" == 17 ]] || fail 'Restored PostgreSQL major differs.'
pg_verifybackup --exit-on-error "$data"
identifier=$(LC_ALL=C pg_controldata "$data" | awk -F ': *' '/^Database system identifier:/ {print $2}')
[[ "$identifier" == 7702033148198322214 ]] || fail 'Restored database system identifier differs.'
[[ ! -e "$data/postmaster.pid" ]] || fail 'Unexpected database writer; preserve evidence.'
printf '%s\n' "$expected" > "$point/accepted.sha256"
sync -f "$root"
printf '%s\n' 'Original PVC physical restore verified; database remains stopped.'
