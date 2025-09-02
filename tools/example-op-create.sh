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

sim_fields="$(cat <<JSON
  {"label":"better-auth-secret","value":"$SIM_BETTER_AUTH_SECRET","type":"CONCEALED"},
  {"label":"encryption-key","value":"$SIM_ENCRYPTION_KEY","type":"CONCEALED"},
  {"label":"openai-api-key","value":"$SIM_OPENAI_API_KEY","type":"CONCEALED"},
  {"label":"anthropic-api-key-1","value":"$SIM_ANTHROPIC_API_KEY_1","type":"CONCEALED"},
  {"label":"mistral-api-key","value":"$SIM_MISTRAL_API_KEY","type":"CONCEALED"},
  {"label":"elevenlabs-api-key","value":"$SIM_ELEVENLABS_API_KEY","type":"CONCEALED"}
JSON
)"

# Build fields list; include Supabase fields only if defined and non-empty
fields_list="$sim_fields"
if [ -n "${supabase_fields-}" ] && [ -n "${supabase_fields}" ]; then
  fields_list="$supabase_fields, $sim_fields"
fi

combined_payload="$(cat <<JSON
{
  "title": "secrets",
  "notes": "Combined secrets for Homelab apps (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $fields_list
  ]
}
JSON
)"

# Upsert combined fields into 1Password Server vault item named "secrets"
if op item get --vault "Server" "secrets" >/dev/null 2>&1; then
  echo "$combined_payload" | op item edit --vault "Server" "secrets" --format=json >/dev/null
  echo "'secrets' item updated (Supabase + Sim AI fields) in 1Password vault 'Server'."
else
  echo "$combined_payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "1Password item 'secrets' created in vault 'Server' (Supabase + Sim AI fields)."
fi