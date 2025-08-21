#!/usr/bin/env bash
set -euo pipefail

# generate Open Notebook secrets
OPEN_NOTEBOOK_PASSWORD="$(openssl rand -base64 24)"
OPENAI_API_KEY="$(openssl rand -hex 24)"
ANTHROPIC_API_KEY="$(openssl rand -hex 24)"
GOOGLE_API_KEY="$(openssl rand -hex 24)"
GOOGLE_APPLICATION_CREDENTIALS="$(openssl rand -base64 64)"
MISTRAL_API_KEY="$(openssl rand -hex 24)"
DEEPSEEK_API_KEY="$(openssl rand -hex 24)"
OLLAMA_API_BASE="http://10.20.30.20:11434"
OPENROUTER_API_KEY="$(openssl rand -hex 24)"
GROQ_API_KEY="$(openssl rand -hex 24)"
XAI_API_KEY="$(openssl rand -hex 24)"
ELEVENLABS_API_KEY="$(openssl rand -hex 24)"
VOYAGE_API_KEY="$(openssl rand -hex 24)"
OPENAI_COMPATIBLE_API_KEY="$(openssl rand -hex 24)"
AZURE_OPENAI_API_KEY="$(openssl rand -hex 24)"
AZURE_OPENAI_ENDPOINT="https://example.azure.net/"
SURREAL_USER="root"
SURREAL_PASSWORD="$(openssl rand -base64 24)"

# build payload for Open Notebook (1Password field keys must match values.yaml secret keys)
payload="$(cat <<JSON
{
  "title": "Open Notebook",
  "notes": "Auto-created Open Notebook secrets (valueFrom keys) - created on $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC",
  "fields": [
    {"label":"open-notebook-password","value":"$OPEN_NOTEBOOK_PASSWORD","type":"CONCEALED"},
    {"label":"openai-api-key","value":"$OPENAI_API_KEY","type":"CONCEALED"},
    {"label":"ollama-api-base","value":"$OLLAMA_API_BASE","type":"STRING"},
    {"label":"surreal-user","value":"$SURREAL_USER","type":"STRING"},
    {"label":"surreal-password","value":"$SURREAL_PASSWORD","type":"CONCEALED"}
  ]
}
JSON
)"

# create item in 1Password Server vault (requires op signed-in)
echo "$payload" | op item create --vault "Server" --category "Database" --format=json

echo "Open Notebook item created in vault 'Server'."