#!/usr/bin/env bash
set -euo pipefail

# generate Supabase secrets
SUPABASE_POSTGRES_USER="supabase"
SUPABASE_POSTGRES_PASSWORD="$(openssl rand -base64 24)"
SUPABASE_POSTGRES_DB="supabase"
SUPABASE_JWT_ANON_KEY="$(openssl rand -hex 32)"
SUPABASE_JWT_SERVICE_KEY="$(openssl rand -hex 32)"
SUPABASE_JWT_SECRET="$(openssl rand -hex 64)"
SUPABASE_SMTP_USERNAME="your-smtp-user"
SUPABASE_SMTP_PASSWORD="$(openssl rand -hex 16)"
SUPABASE_DASHBOARD_USERNAME="admin-supabase"
SUPABASE_DASHBOARD_PASSWORD="$(openssl rand -base64 24)"

# build payload for Supabase (keys must match apps/supabase/values.yaml secretRefKey names)
supabase_payload="$(cat <<JSON
{
  "title": "Supabase",
  "notes": "Supabase secrets for Helm values (created on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    {"label":"supabase-postgres-user","value":"$SUPABASE_POSTGRES_USER","type":"STRING"},
    {"label":"supabase-postgres-password","value":"$SUPABASE_POSTGRES_PASSWORD","type":"CONCEALED"},
    {"label":"supabase-postgres-db","value":"$SUPABASE_POSTGRES_DB","type":"STRING"},

    {"label":"supabase-jwt-anon-key","value":"$SUPABASE_JWT_ANON_KEY","type":"CONCEALED"},
    {"label":"supabase-jwt-service-key","value":"$SUPABASE_JWT_SERVICE_KEY","type":"CONCEALED"},
    {"label":"supabase-jwt-secret","value":"$SUPABASE_JWT_SECRET","type":"CONCEALED"},

    {"label":"supabase-smtp-username","value":"$SUPABASE_SMTP_USERNAME","type":"STRING"},
    {"label":"supabase-smtp-password","value":"$SUPABASE_SMTP_PASSWORD","type":"CONCEALED"},

    {"label":"supabase-dashboard-username","value":"$SUPABASE_DASHBOARD_USERNAME","type":"STRING"},
  {"label":"supabase-dashboard-password","value":"$SUPABASE_DASHBOARD_PASSWORD","type":"CONCEALED"}
  ]
}
JSON
)"

# upsert into 1Password Server vault item named "secrets" (matches Operator annotations and Secret name)
if op item get --vault "Server" "secrets" >/dev/null 2>&1; then
  echo "$supabase_payload" | op item edit --vault "Server" "secrets" --format=json >/dev/null
  echo "Supabase fields updated in existing 1Password item 'secrets' (vault 'Server')."
else
  echo "$supabase_payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "1Password item 'secrets' created in vault 'Server' with Supabase fields."
fi