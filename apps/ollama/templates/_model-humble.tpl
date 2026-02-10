{{/*
Humble model creation script.
Creates the Humble model - a family-safe AI assistant.
*/}}

{{- define "ollama.script.model.humble" -}}
{{- if .Values.modelPuller.models.custom.humble.enabled }}
# ============================================
# Create Humble Model
# ============================================
echo "Creating Humble model ({{ .Values.modelPuller.models.custom.humble.base }}, {{ .Values.modelPuller.models.custom.humble.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.Humble
FROM {{ .Values.modelPuller.models.custom.humble.base }}
PARAMETER num_ctx {{ .Values.modelPuller.models.custom.humble.contextSize }}
{{- with .Values.modelPuller.models.custom.humble.repeatPenalty }}
PARAMETER repeat_penalty {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.humble.temperature }}
PARAMETER temperature {{ . }}
{{- end }}
SYSTEM """
{{ .Values.modelPuller.models.custom.humble.systemPrompt | indent 0 }}
"""
MODELFILE_EOF

echo "Removing existing Humble model to enforce update..."
ollama rm Humble || true

if ollama create Humble -f /tmp/Modelfile.Humble; then
    echo "Successfully created Humble model"
else
    echo "Failed to create Humble model" >&2
fi
{{- else }}
echo "Humble model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
