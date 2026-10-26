#!/usr/bin/env bash
# Run only through the reviewed exact-Pod wrapper; credential JSON arrives on stdin.
set -euo pipefail
umask 077
[[ ${HOSTNAME:-} == radarr-77d66cff54-4hqrb ]] || exit 2
awk '$2 == "/config" && $3 == "ext4" && $1 ~ /^\/dev\/rbd[0-9]+$/ {found=1} END {exit !found}' /proc/mounts
recovery=/config/.maintenance-103-nzbplanet
mkdir -m 700 "$recovery" # Exclusive path prevents uncertain replay.
work=$(mktemp -d "$recovery/work.XXXXXXXX")
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT
IFS= read -r candidate_json
printf '%s\n' "$candidate_json" | jq -e 'type == "object" and keys == ["credential"] and (.credential | type == "string" and test("^[0-9a-fA-F]{32}$"))' >/dev/null
key=$(sed -n 's:.*<ApiKey>\(.*\)</ApiKey>.*:\1:p' /config/config.xml)
[[ $key =~ ^[0-9a-fA-F]{32}$ ]] || exit 2
request() {
    local method=$1 route=$2 output=$3
    shift 3
    printf 'header = "X-Api-Key: %s"\nheader = "Content-Type: application/json"\nurl = "http://127.0.0.1:7878/api/v3/%s"\nsilent\nshow-error\nmax-time = 90\n' "$key" "$route" |
        curl --config - --request "$method" --output "$output" --write-out '%{http_code}' "$@"
}
[[ $(request GET indexer/2 "$recovery/original.json") == 200 ]] || exit 3
jq -e '.id == 2 and .name == "NZBPlanet" and .implementation == "Newznab" and ([.fields[] | select(.name == "apiKey")] | length == 1) and ([.fields[] | select(.name == "baseUrl") | .value | test("^https://(api\\.)?nzbplanet\\.net/?$")] == [true])' "$recovery/original.json" >/dev/null
{ printf '%s\n' "$candidate_json"; cat "$recovery/original.json"; } |
    jq -es '.[0].credential as $key | .[1] | (.fields[] | select(.name == "apiKey").value) = $key' > "$work/candidate.json"
jq -e -s 'def without_key: .fields |= map(if .name == "apiKey" then .value = null else . end); (.[0] | without_key) == (.[1] | without_key)' "$recovery/original.json" "$work/candidate.json" >/dev/null
status=$(request POST indexer/test "$work/test-response.json" --data-binary "@$work/candidate.json")
if [[ $status != 204 ]]; then
    printf '{"tested":false,"http_status":"%s","updated":false}\n' "$status"
    exit 4
fi
[[ $(request GET indexer/2 "$work/current.json") == 200 ]] || exit 3
jq -e -s '.[0] == .[1]' "$recovery/original.json" "$work/current.json" >/dev/null
printf '{"operation":"PUT indexer/2","dispatched_at":"%s"}\n' "$(date -u +%FT%TZ)" > "$recovery/intent.json"
status=$(request PUT indexer/2 "$work/update-response.json" --data-binary "@$work/candidate.json")
[[ $status == 202 ]] || { printf '{"tested":true,"http_status":"%s","updated":"UNCERTAIN"}\n' "$status"; exit 5; }
[[ $(request GET indexer/2 "$work/current.json") == 200 ]] || exit 3
jq -e -s '.[0] == .[1]' "$work/candidate.json" "$work/current.json" >/dev/null
printf '{"tested":true,"updated":true,"exact_readback":true,"other_fields_preserved":true}\n' > "$recovery/accepted.json"
cat "$recovery/accepted.json"
