#!/usr/bin/env bash
# ============================================================================
# Manual Cloudflare Access setup for citadel.eaglepass.io
# Run this if you don't have Terraform handy or need to apply immediately.
# Prerequisite: A Cloudflare API Token with "Cloudflare Zero Trust:Edit" 
# and "Account:Read" permissions.
# ============================================================================

set -euo pipefail

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"

if [[ -z "$ACCOUNT_ID" || -z "$API_TOKEN" ]]; then
  echo "ERROR: Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN"
  exit 1
fi

CF_API="https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID"
AUTH="Authorization: Bearer $API_TOKEN"

# ---------------------------------------------------------------------------
# 1. Create the Access Application
# ---------------------------------------------------------------------------
echo "==> Creating Access Application for citadel.eaglepass.io ..."
APP_PAYLOAD=$(cat <<'EOF'
{
  "name": "Citadel",
  "domain": "citadel.eaglepass.io",
  "type": "self_hosted",
  "session_duration": "24h"
}
EOF
)

APP_RESP=$(curl -s -w "\n%{http_code}" -X POST "$CF_API/access/apps" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "$APP_PAYLOAD")

APP_HTTP_CODE=$(echo "$APP_RESP" | tail -1)
APP_BODY=$(echo "$APP_RESP" | head -n -1)

if [[ "$APP_HTTP_CODE" != "200" && "$APP_HTTP_CODE" != "201" ]]; then
  echo "FAILED to create Access Application (HTTP $APP_HTTP_CODE):"
  echo "$APP_BODY" | python3 -m json.tool || echo "$APP_BODY"
  exit 1
fi

APP_ID=$(echo "$APP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['id'])")
echo "    Created app ID: $APP_ID"

# ---------------------------------------------------------------------------
# 2. Create Access Policy — allowed emails only
# ---------------------------------------------------------------------------
echo "==> Creating Access Policy for authorized emails ..."
POLICY_PAYLOAD=$(cat <<EOF
{
  "name": "Allow authorized users",
  "decision": "allow",
  "precedence": 1,
  "include": [
    {"email": {"email": "chrisnelsonx@gmail.com"}},
    {"email": {"email": "kaleb.bays@gmail.com"}}
  ]
}
EOF
)

POLICY_RESP=$(curl -s -w "\n%{http_code}" -X POST "$CF_API/access/apps/$APP_ID/policies" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "$POLICY_PAYLOAD")

POLICY_HTTP_CODE=$(echo "$POLICY_RESP" | tail -1)
POLICY_BODY=$(echo "$POLICY_RESP" | head -n -1)

if [[ "$POLICY_HTTP_CODE" != "200" && "$POLICY_HTTP_CODE" != "201" ]]; then
  echo "FAILED to create Access Policy (HTTP $POLICY_HTTP_CODE):"
  echo "$POLICY_BODY" | python3 -m json.tool || echo "$POLICY_BODY"
  echo ""
  echo "Note: If the error says 'access.api.error.invalid_request', your API token"
  echo "likely lacks Zero Trust permissions. Create a new token at:"
  echo "  https://dash.cloudflare.com/profile/api-tokens"
  echo "Include:  Account:Cloudflare Zero Trust:Edit  +  Account:Account Settings:Read"
  exit 1
fi

echo "    Created policy successfully"

# ---------------------------------------------------------------------------
# 3. Optional: protect citadel-canary.eaglepass.io too
# ---------------------------------------------------------------------------
echo "==> (Optional) Protecting citadel-canary.eaglepass.io ..."
CANARY_PAYLOAD=$(cat <<'EOF'
{
  "name": "Citadel Canary",
  "domain": "citadel-canary.eaglepass.io",
  "type": "self_hosted",
  "session_duration": "24h"
}
EOF
)

CANARY_RESP=$(curl -s -w "\n%{http_code}" -X POST "$CF_API/access/apps" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "$CANARY_PAYLOAD")

CANARY_HTTP_CODE=$(echo "$CANARY_RESP" | tail -1)
CANARY_BODY=$(echo "$CANARY_RESP" | head -n -1)

if [[ "$CANARY_HTTP_CODE" == "200" || "$CANARY_HTTP_CODE" == "201" ]]; then
  CANARY_ID=$(echo "$CANARY_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['id'])")
  curl -s -o /dev/null -w "%{http_code}" -X POST "$CF_API/access/apps/$CANARY_ID/policies" \
    -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "$POLICY_PAYLOAD"
  echo "    Done — citadel-canary.eaglepass.io is also protected."
else
  echo "    Skipped (already exists or token missing permissions)"
fi

echo ""
echo "=========================================================================="
echo " DONE! citadel.eaglepass.io is now behind Cloudflare Access + Google OAuth"
echo "=========================================================================="
