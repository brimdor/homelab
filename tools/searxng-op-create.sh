#!/usr/bin/env bash
set -euo pipefail

# SearxNG 1Password Secret Creation Script
app_name="searxng"

# Example secrets. Replace or prefill as needed.
SECRET_KEY="$(openssl rand -hex 32)"
GOOGLE_API_KEY=""
BING_API_KEY=""

fields="$(cat <<JSON
  {"label":"secret-key","value":"$SECRET_KEY","type":"CONCEALED"},
  {"label":"google-api-key","value":"$GOOGLE_API_KEY","type":"CONCEALED"},
  {"label":"bing-api-key","value":"$BING_API_KEY","type":"CONCEALED"}
JSON
)"

title="$app_name Secrets"
payload="$(cat <<JSON
{
  "title": "$title",
  "notes": "Combined secrets for Homelab apps (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $fields
  ]
}
JSON
)"

# Create or update the 1Password item in the 'Server' vault
if op item get --vault "Server" "$title" >/dev/null 2>&1; then
  echo "$payload" | op item edit --vault "Server" "$title" --format=json >/dev/null
  echo "'$title' updated in 1Password vault 'Server'."
else
  echo "$payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "1Password item '$title' created in vault 'Server'."
fi
