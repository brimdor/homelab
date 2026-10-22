#!/bin/bash
umask 077
state=/opt/bitnami/postgresql/tmp/maintenance-103
mkdir -- "$state"
exec 9>"$state/lock"
printf '%s\n' waiting > "$state/phase"
for ((n=0; n<300; n++)); do
    [[ ! -e "$state/claimed" ]] || break
    sleep 0.1
done
flock --exclusive 9
printf '%s\n' normal > "$state/phase"
exec "$@"
