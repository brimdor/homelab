#!/usr/bin/env bash
set -euo pipefail

# 1Password item creation/upsert for DeepCode secrets
# - Keys use lowercase-hyphen naming per homelab convention
# - Item category: Database (as requested)

app_name="deepcode"

# Define secrets (generate random where useful)
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""
BRAVE_API_KEY=""
BOCHA_API_KEY=""

fields="$(cat <<JSON
  {"label":"openai-api-key","value":"${OPENAI_API_KEY}","type":"CONCEALED"},
  {"label":"anthropic-api-key","value":"${ANTHROPIC_API_KEY}","type":"CONCEALED"},
  {"label":"brave-api-key","value":"${BRAVE_API_KEY}","type":"CONCEALED"},
  {"label":"bocha-api-key","value":"${BOCHA_API_KEY}","type":"CONCEALED"}
JSON
)"

title="${app_name} Secrets"
payload="$(cat <<JSON
{
  "title": "${title}",
  "notes": "DeepCode secrets for Homelab (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    ${fields}
  ]
}
JSON
)"

# Create or update item in the 'Server' vault
if op item get --vault "Server" "${title}" >/dev/null 2>&1; then
  echo "Updating existing 1Password item: ${title}"
  echo "${payload}" | op item edit --vault "Server" "${title}" --format=json >/dev/null
  echo "Updated."
else
  echo "Creating 1Password item: ${title}"
  echo "${payload}" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "Created."
fi
