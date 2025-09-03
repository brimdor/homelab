#!/usr/bin/env bash
set -euo pipefail

# Create or update 1Password item 'secrets' (Database category) with DeepCode keys
# Keys must be lowercase-hyphens and align with apps/deepcode/values.yaml secretKeyRef.key

OPENAI_API_KEY=""
OPENAI_BASE_URL=""
ANTHROPIC_API_KEY=""
BRAVE_API_KEY=""
BOCHA_API_KEY=""

deepcode_fields="$(cat <<JSON
  {"label":"openai-api-key","value":"$OPENAI_API_KEY","type":"CONCEALED"},
  {"label":"openai-base-url","value":"$OPENAI_BASE_URL","type":"CONCEALED"},
  {"label":"anthropic-api-key","value":"$ANTHROPIC_API_KEY","type":"CONCEALED"},
  {"label":"brave-api-key","value":"$BRAVE_API_KEY","type":"CONCEALED"},
  {"label":"bocha-api-key","value":"$BOCHA_API_KEY","type":"CONCEALED"}
JSON
)"

payload="$(cat <<JSON
{
  "title": "DeepCode Secrets",
  "notes": "DeepCode secrets (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $deepcode_fields
  ]
}
JSON
)"


echo "$payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
echo "Created 1Password item 'secrets' in vault 'Server' with DeepCode fields."
