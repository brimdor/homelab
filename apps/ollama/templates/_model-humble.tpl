{{/*
Humble model creation script.
Creates the Humble model - a family-safe AI assistant.
*/}}

{{- define "ollama.script.model.humble" -}}
{{- if .Values.modelPuller.models.custom.humble.enabled }}
# ============================================
# Create Humble Model
# ============================================
echo "Creating humble model ({{ .Values.modelPuller.models.custom.humble.base }}, {{ .Values.modelPuller.models.custom.humble.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.humble
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

echo "Removing existing humble model to enforce update..."
ollama rm humble || true

if ollama create humble -f /tmp/Modelfile.humble; then
    echo "Successfully created humble model"
else
    echo "Failed to create humble model" >&2
fi
{{- else }}
echo "humble model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
