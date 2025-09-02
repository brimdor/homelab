#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Sim AI secret fields (Database category). Keys must match lowercase-hyphen
# labels referenced in apps/sim/values.yaml secretKeyRef.key
# NOTE: These are placeholders/randoms for bootstrap. Replace as needed.
SIM_BETTER_AUTH_SECRET="$(openssl rand -hex 32)"
SIM_ENCRYPTION_KEY="$(openssl rand -hex 32)"
SIM_OPENAI_API_KEY=""
SIM_ANTHROPIC_API_KEY_1=""
SIM_MISTRAL_API_KEY=""
SIM_ELEVENLABS_API_KEY=""
SIM_DATABASE_URL=""

sim_fields="$(cat <<JSON
  {"label":"better-auth-secret","value":"$SIM_BETTER_AUTH_SECRET","type":"CONCEALED"},
  {"label":"encryption-key","value":"$SIM_ENCRYPTION_KEY","type":"CONCEALED"},
  {"label":"openai-api-key","value":"$SIM_OPENAI_API_KEY","type":"CONCEALED"},
  {"label":"anthropic-api-key-1","value":"$SIM_ANTHROPIC_API_KEY_1","type":"CONCEALED"},
  {"label":"mistral-api-key","value":"$SIM_MISTRAL_API_KEY","type":"CONCEALED"},
  {"label":"elevenlabs-api-key","value":"$SIM_ELEVENLABS_API_KEY","type":"CONCEALED"},
  {"label":"database-url","value":"$SIM_DATABASE_URL","type":"CONCEALED"}
JSON
)"

combined_payload="$(cat <<JSON
{
  "title": "Sim AI",
  "notes": "Sim AI secrets for Helm values (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $sim_fields
  ]
}
JSON
)"

# Upsert into 1Password Server vault item named "Sim AI"
if op item get --vault "Server" "Sim AI" >/dev/null 2>&1; then
  echo "$combined_payload" | op item edit --vault "Server" "Sim AI" --format=json >/dev/null
  echo "'Sim AI' item updated in 1Password vault 'Server'."
else
  echo "$combined_payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "1Password item 'Sim AI' created in vault 'Server'."
fi