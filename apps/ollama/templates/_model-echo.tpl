{{/*
Echo model creation script.
Creates the Echo model - a specialized System Administration Agent.
*/}}

{{- define "ollama.script.model.echo" -}}
{{- if .Values.modelPuller.models.custom.echo.enabled }}
# ============================================
# Create Echo Model
# ============================================
echo "Creating Echo model ({{ .Values.modelPuller.models.custom.echo.base }}, {{ .Values.modelPuller.models.custom.echo.contextSize }} context)..."

cat <<'MODELFILE_EOF' > /tmp/Modelfile.Echo
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

echo "Removing existing Echo model to enforce update..."
ollama rm Echo || true

if ollama create Echo -f /tmp/Modelfile.Echo; then
    echo "Successfully created Echo model"
else
    echo "Failed to create Echo model" >&2
fi
{{- else }}
echo "Echo model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
