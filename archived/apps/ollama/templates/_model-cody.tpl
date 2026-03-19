{{/*
Cody model creation script.
Creates the Cody model - a coding agent specializing in Web Apps, Scripting, and Databases.
*/}}

{{- define "ollama.script.model.cody" -}}
{{- if .Values.modelPuller.models.custom.cody.enabled }}
# ============================================
# Create Cody Model
# ============================================
echo "Creating cody model ({{ .Values.modelPuller.models.custom.cody.base }}, {{ .Values.modelPuller.models.custom.cody.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.cody
FROM {{ .Values.modelPuller.models.custom.cody.base }}
PARAMETER num_ctx {{ .Values.modelPuller.models.custom.cody.contextSize }}
{{- with .Values.modelPuller.models.custom.cody.repeatPenalty }}
PARAMETER repeat_penalty {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.cody.temperature }}
PARAMETER temperature {{ . }}
{{- end }}
SYSTEM """
{{ .Values.modelPuller.models.custom.cody.systemPrompt | indent 0 }}
"""
MODELFILE_EOF

echo "Removing existing cody model to enforce update..."
ollama rm cody || true

if ollama create cody -f /tmp/Modelfile.cody; then
    echo "Successfully created cody model"
else
    echo "Failed to create cody model" >&2
fi
{{- else }}
echo "cody model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
