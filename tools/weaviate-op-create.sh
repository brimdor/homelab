#!/usr/bin/env bash
set -euo pipefail

# weaviate-op-create.sh
# Create or update a 1Password item for Weaviate and print JSON with ids

APP_NAME="Weaviate"
ITEM_TITLE="${APP_NAME} Secrets"
VAULT_NAME="Server"

# Ensure required fields (lowercase hyphenated)
FIELDS=(
  "root-password"
)

echo "[INFO] Ensuring 1Password item '$ITEM_TITLE' exists in vault '$VAULT_NAME' with fields: ${FIELDS[*]}" 1>&2

if op item get "$ITEM_TITLE" --vault "$VAULT_NAME" >/dev/null 2>&1; then
  for f in "${FIELDS[@]}"; do
    if ! op item get "$ITEM_TITLE" --vault "$VAULT_NAME" --fields label="$f" >/dev/null 2>&1; then
      op item edit "$ITEM_TITLE" --vault "$VAULT_NAME" "$f"=changeme >/dev/null
    fi
  done
else
  CREATE_ARGS=( )
  for f in "${FIELDS[@]}"; do
    CREATE_ARGS+=("$f=changeme")
  done
  op item create --category database --vault "$VAULT_NAME" --title "$ITEM_TITLE" "${CREATE_ARGS[@]}" >/dev/null
fi

# Output the JSON metadata as specified
ITEM_JSON=$(op item get "$ITEM_TITLE" --vault "$VAULT_NAME" --format json)
ITEM_ID=$(echo "$ITEM_JSON" | jq -r .id)
VAULT_ID=$(echo "$ITEM_JSON" | jq -r .vault.id)

jq -n --arg item_id "$ITEM_ID" --arg vault_id "$VAULT_ID" '{
  id: $item_id,
  title: "Weaviate Secrets",
  version: 1,
  vault: { id: $vault_id, name: "Server" }
}'
