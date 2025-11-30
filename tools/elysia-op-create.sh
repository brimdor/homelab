#!/usr/bin/env bash
set -euo pipefail

# Elysia 1Password Secret Creation Script
# Generates/updates a 1Password item containing secret fields required by the Elysia deployment.
# Item title: "elysia Secrets" (category: Database) in the "Server" vault.
# Fields map to environment variables in the chart via secretKeyRef:
#   API_KEY -> api-key
#   DB_URL -> db-url
#   WEAVIATE_ENDPOINT -> weaviate-endpoint
#   OLLAMA_URL -> ollama-url
#   OPTIONAL_AUTH_TOKEN -> auth-token (example)

app_name="elysia"

# Placeholder / generated values (adjust or export before running if desired)
API_KEY="$(openssl rand -hex 32)"
DB_URL=""
WEAVIATE_ENDPOINT=""
OLLAMA_URL=""
OPTIONAL_AUTH_TOKEN="$(openssl rand -hex 16)"

fields=$(cat <<JSON
  {"label":"api-key","value":"$API_KEY","type":"CONCEALED"},
  {"label":"db-url","value":"$DB_URL","type":"CONCEALED"},
  {"label":"weaviate-endpoint","value":"$WEAVIATE_ENDPOINT","type":"CONCEALED"},
  {"label":"ollama-url","value":"$OLLAMA_URL","type":"CONCEALED"},
  {"label":"auth-token","value":"$OPTIONAL_AUTH_TOKEN","type":"CONCEALED"}
JSON
)

title="$app_name Secrets"
payload=$(cat <<JSON
{
  "title": "$title",
  "notes": "Secrets for Elysia deployment (generated $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $fields
  ]
}
JSON
)

if op item get --vault "Server" "$title" >/dev/null 2>&1; then
  echo "$payload" | op item edit --vault "Server" "$title" --format=json
  echo "'$title' updated in 1Password vault 'Server'."
else
  echo "$payload" | op item create --vault "Server" --category "Database" --format=json
  echo "1Password item '$title' created in vault 'Server'."
fi
