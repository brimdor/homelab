{{/*
Main entrypoint script for model puller.
Orchestrates the common setup, model pulls, and custom model creation.
*/}}

{{- define "ollama.script.entrypoint" -}}
{{ include "ollama.script.common" . }}

{{ include "ollama.script.pull-models" . }}

# ============================================
# Create Custom Models
# ============================================
echo "Creating custom models..."

{{ include "ollama.script.model.echo" . }}

{{ include "ollama.script.model.humble" . }}

{{ include "ollama.script.model.cody" . }}

{{ include "ollama.script.model.opus" . }}

echo "All models requested. Sleeping indefinitely..."
sleep infinity
{{- end -}}
