{{/*
Echo model creation script.
Creates the Echo model - a specialized System Administration Agent.
*/}}

{{- define "ollama.script.model.echo" -}}
{{- if .Values.modelPuller.models.custom.echo.enabled }}
# ============================================
# Create Echo Model
# ============================================
echo "Creating echo model ({{ .Values.modelPuller.models.custom.echo.base }}, {{ .Values.modelPuller.models.custom.echo.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.echo
FROM {{ .Values.modelPuller.models.custom.echo.base }}
PARAMETER num_ctx {{ .Values.modelPuller.models.custom.echo.contextSize }}
{{- with .Values.modelPuller.models.custom.echo.repeatPenalty }}
PARAMETER repeat_penalty {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.echo.temperature }}
PARAMETER temperature {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.echo.topP }}
PARAMETER top_p {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.echo.topK }}
PARAMETER top_k {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.echo.reasoningEffort }}
PARAMETER reasoning {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.echo.numPredict }}
PARAMETER num_predict {{ . }}
{{- end }}
PARAMETER stop "<|channel|>analysis"
PARAMETER stop "<|start|>assistant<|channel|>"
SYSTEM """
{{ .Values.modelPuller.models.custom.echo.systemPrompt | indent 0 }}
"""
MODELFILE_EOF

echo "Removing existing echo model to enforce update..."
ollama rm echo || true

if ollama create echo -f /tmp/Modelfile.echo; then
    echo "Successfully created echo model"
else
    echo "Failed to create echo model" >&2
fi
{{- else }}
echo "echo model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
