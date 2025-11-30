#!/usr/bin/env bash
set -euo pipefail

# kavita-op-create.sh
# Helper script to create (or upsert) a 1Password item named 'secrets' for the Kavita chart.
# This mirrors the pattern in example-op-create.sh but with Kavita-specific placeholder fields.
# No secret values are printed or stored here. Fill values via 1Password UI or CLI securely.

ITEM_NAME="Kavita secrets"
VAULT_NAME="Server"  # Optionally pass vault name/id as first arg

# Fields to ensure exist (lowercase hyphenated keys)
FIELDS=(
  "admin-password"
  "api-key"
)

echo "[INFO] Ensuring 1Password item '$ITEM_NAME' exists in vault '$VAULT_NAME' with required fields..."

# Check if item exists
if op item get "$ITEM_NAME" --vault "$VAULT_NAME" > /dev/null 2>&1; then
  echo "[INFO] Item exists. Verifying fields..."
  for f in "${FIELDS[@]}"; do
    if ! op item get "$ITEM_NAME" --vault "$VAULT_NAME" --fields label="$f" >/dev/null 2>&1; then
      echo "[INFO] Adding missing field '$f'"
      op item edit "$ITEM_NAME" --vault "$VAULT_NAME" "$f"=changeme >/dev/null
    fi
  done
else
  echo "[INFO] Creating item '$ITEM_NAME' with placeholder fields"
  CREATE_ARGS=()
  for f in "${FIELDS[@]}"; do
    CREATE_ARGS+=("$f=changeme")
  done
  op item create --category database --vault "$VAULT_NAME" --title "$ITEM_NAME" "${CREATE_ARGS[@]}" >/dev/null
fi

echo "[INFO] Done. Replace placeholder values in 1Password UI/CLI as needed."
