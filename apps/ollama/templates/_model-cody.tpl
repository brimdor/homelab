{{/*
Cody model creation script.
Creates the Cody model - a coding agent specializing in Web Apps, Scripting, and Databases.
*/}}

{{- define "ollama.script.model.cody" -}}
{{- if .Values.modelPuller.models.custom.cody.enabled }}
# ============================================
# Create Cody Model
# ============================================
echo "Creating Cody model ({{ .Values.modelPuller.models.custom.cody.base }}, {{ .Values.modelPuller.models.custom.cody.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.Cody
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

echo "Removing existing Cody model to enforce update..."
ollama rm Cody || true

if ollama create Cody -f /tmp/Modelfile.Cody; then
    echo "Successfully created Cody model"
else
    echo "Failed to create Cody model" >&2
fi
{{- else }}
echo "Cody model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
