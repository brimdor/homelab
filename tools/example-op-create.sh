# -----------------------------------------------------------------------------
# Homelab 1Password Secret Creation Script Template Schema
# -----------------------------------------------------------------------------
# 1. Shebang and strict mode
# 2. App name variable: app_name="<app-name>"
# 3. Secret variables: ALL CAPS, hyphen-case labels
# 4. Fields array: label, value, type (CONCEALED)
# 5. Payload: title, notes, fields
# 6. 1Password CLI logic: get/edit/create item in vault
# 7. Naming: keys lowercase-hyphens, item title "$app_name Secrets"
# -----------------------------------------------------------------------------
# Copy this template and replace placeholders for each app.
# -----------------------------------------------------------------------------

#!/usr/bin/env bash
set -euo pipefail

# Set your application name (used for the 1Password item title)
app_name="<app-name>"

# Define your secret variables below. Use hyphen-case for labels and ALL CAPS for variable names.
# Example:
# OPENAI_API_KEY="$(openssl rand -hex 32)"
# ANTHROPIC_API_KEY=""
# ...
<SECRET_VAR_1>="$(openssl rand -hex 32)"
<SECRET_VAR_2>="$(openssl rand -hex 32)"
<SECRET_VAR_3>=""
<SECRET_VAR_4>=""

# Build the fields JSON array. Each field should have a label (hyphen-case), value, and type (CONCEALED).
fields="$(cat <<JSON
  {"label":"<secret-label-1>","value":"<SECRET_VAR_1>","type":"CONCEALED"},
  {"label":"<secret-label-2>","value":"<SECRET_VAR_2>","type":"CONCEALED"},
  {"label":"<secret-label-3>","value":"<SECRET_VAR_3>","type":"CONCEALED"},
  {"label":"<secret-label-4>","value":"<SECRET_VAR_4>","type":"CONCEALED"}
JSON
)"

# Set the item title and build the payload
title="$app_name Secrets"
payload="$(cat <<JSON
{
  "title": "$title",
  "notes": "Combined secrets for Homelab apps (updated on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)",
  "fields": [
    $fields
  ]
}
JSON
)"

# Create or update the 1Password item named 'secrets' in the 'Server' vault
if op item get --vault "Server" "$title" >/dev/null 2>&1; then
  echo "$payload" | op item edit --vault "Server" "$title" --format=json >/dev/null
  echo "'$title' updated in 1Password vault 'Server'."
else
  echo "$payload" | op item create --vault "Server" --category "Database" --format=json >/dev/null
  echo "1Password item '$title' created in vault 'Server'."
fi