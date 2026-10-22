#!/bin/bash
umask 077
state=/tmp/maintenance-103-gitea
fresh=false
if mkdir -- "$state" 2>/dev/null; then
    fresh=true
else
    [[ ! -L "$state" && $(stat -c '%u:%a' "$state") == 1000:700 ]]
    [[ -f "$state/lock" && ! -L "$state/lock" && $(stat -c '%u:%a:%h' "$state/lock") == 1000:600:1 ]]
    [[ -f "$state/phase" && ! -L "$state/phase" && $(stat -c '%u:%a:%h' "$state/phase") == 1000:600:1 ]]
    case "$(cat "$state/phase")" in waiting|normal|closing) ;; *) exit 1;; esac
    # A container restart closes the old claim window before ordinary startup.
    printf '%s\n' closing > "$state/phase"
fi
exec 9>"$state/lock"
if "$fresh"; then
    printf '%s\n' waiting > "$state/phase"
    for ((n=0; n<300; n++)); do
        [[ ! -e "$state/claimed" ]] || break
        sleep 0.1
    done
fi
flock -x 9
printf '%s\n' normal > "$state/phase"
exit 0
