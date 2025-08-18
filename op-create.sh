#!/usr/bin/env bash
set -euo pipefail

# generate secrets
ANON_KEY="$(openssl rand -base64 32)"
SERVICE_ROLE_KEY="$(openssl rand -base64 48)"
JWT_SECRET="$(openssl rand -hex 64)"
POSTGRES_PASSWORD="$(openssl rand -base64 24)"
GOTRUE_DB_DATABASE_URL="postgres://supabase_admin:$(openssl rand -base64 12)@localhost:5432/_supabase"
GOTRUE_JWT_SECRET="$(openssl rand -hex 48)"
GOTRUE_JWT_EXP="3600"
GOTRUE_SMTP_ADMIN_EMAIL="no-reply@example.local"
GOTRUE_SMTP_HOST="smtp.example.local"
GOTRUE_SMTP_PORT="587"
GOTRUE_SMTP_USER="smtp-user-$(openssl rand -hex 4)"
GOTRUE_SMTP_PASS="$(openssl rand -base64 18)"
PGRST_DB_URI="postgres://anon:$(openssl rand -base64 12)@localhost:5432/postgres"
PGRST_JWT_SECRET="$JWT_SECRET"
DB_PASSWORD="$POSTGRES_PASSWORD"
SECRET_KEY_BASE="$(openssl rand -hex 64)"
VERIFY_JWT="$(openssl rand -base64 32)"
PGPASSWORD="$POSTGRES_PASSWORD"
PG_META_DB_PASSWORD="$POSTGRES_PASSWORD"
LOGFLARE_PRIVATE_ACCESS_TOKEN="$(openssl rand -base64 28)"
LOGFLARE_PUBLIC_ACCESS_TOKEN="$(openssl rand -base64 20)"
JWT_EXP="3600"

# build payload
payload="$(cat <<JSON
{
  "title": "Supabase",
  "notes": "Auto-created Supabase secrets (valueFrom keys) - created on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC",
  "fields": [
    {"label":"ANON_KEY","value":"$ANON_KEY","type":"CONCEALED"},
    {"label":"SERVICE_ROLE_KEY","value":"$SERVICE_ROLE_KEY","type":"CONCEALED"},
    {"label":"JWT_SECRET","value":"$JWT_SECRET","type":"CONCEALED"},
    {"label":"POSTGRES_PASSWORD","value":"$POSTGRES_PASSWORD","type":"CONCEALED"},
    {"label":"SUPABASE_ANON_KEY","value":"$ANON_KEY","type":"CONCEALED"},
    {"label":"SUPABASE_SERVICE_KEY","value":"$SERVICE_ROLE_KEY","type":"CONCEALED"},
    {"label":"DASHBOARD_USERNAME","value":"dashboard-$(openssl rand -hex 3)","type":"STRING"},
    {"label":"DASHBOARD_PASSWORD","value":"$(openssl rand -base64 18)","type":"CONCEALED"},
    {"label":"GOTRUE_DB_DATABASE_URL","value":"$GOTRUE_DB_DATABASE_URL","type":"STRING"},
    {"label":"GOTRUE_JWT_SECRET","value":"$GOTRUE_JWT_SECRET","type":"CONCEALED"},
    {"label":"GOTRUE_JWT_EXP","value":"$GOTRUE_JWT_EXP","type":"STRING"},
    {"label":"GOTRUE_SMTP_ADMIN_EMAIL","value":"$GOTRUE_SMTP_ADMIN_EMAIL","type":"STRING"},
    {"label":"GOTRUE_SMTP_HOST","value":"$GOTRUE_SMTP_HOST","type":"STRING"},
    {"label":"GOTRUE_SMTP_PORT","value":"$GOTRUE_SMTP_PORT","type":"STRING"},
    {"label":"GOTRUE_SMTP_USER","value":"$GOTRUE_SMTP_USER","type":"STRING"},
    {"label":"GOTRUE_SMTP_PASS","value":"$GOTRUE_SMTP_PASS","type":"CONCEALED"},
    {"label":"PGRST_DB_URI","value":"$PGRST_DB_URI","type":"STRING"},
    {"label":"PGRST_JWT_SECRET","value":"$PGRST_JWT_SECRET","type":"CONCEALED"},
    {"label":"DB_PASSWORD","value":"$DB_PASSWORD","type":"CONCEALED"},
    {"label":"SECRET_KEY_BASE","value":"$SECRET_KEY_BASE","type":"CONCEALED"},
    {"label":"VERIFY_JWT","value":"$VERIFY_JWT","type":"CONCEALED"},
    {"label":"PGPASSWORD","value":"$PGPASSWORD","type":"CONCEALED"},
    {"label":"PG_META_DB_PASSWORD","value":"$PG_META_DB_PASSWORD","type":"CONCEALED"},
    {"label":"LOGFLARE_PRIVATE_ACCESS_TOKEN","value":"$LOGFLARE_PRIVATE_ACCESS_TOKEN","type":"CONCEALED"},
    {"label":"LOGFLARE_PUBLIC_ACCESS_TOKEN","value":"$LOGFLARE_PUBLIC_ACCESS_TOKEN","type":"CONCEALED"},
    {"label":"JWT_EXP","value":"$JWT_EXP","type":"STRING"}
  ]
}
JSON
)"

# create item in 1Password Server vault
# requires you to be signed-in with op already
echo "$payload" | op item create --vault "Server" --category "Database" --format=json

echo "Supabase item created in vault 'Server'."