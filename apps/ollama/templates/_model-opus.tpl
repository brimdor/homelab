{{/*
Opus Modelfile creation script.
Creates the Opus model from a GGUF-based Hugging Face source.
*/}}

{{- define "ollama.script.model.opus" -}}
{{- if .Values.modelPuller.models.custom.opus.enabled }}
# ============================================
# Create Opus Model
# ============================================
echo "Creating opus model ({{ .Values.modelPuller.models.custom.opus.base }}, {{ .Values.modelPuller.models.custom.opus.contextSize }} context)..."

# Ensure the base is pulled before ollama create references it in the Modelfile.
# If it was already pulled earlier in the script this is a no-op.
pull_with_retry "{{ .Values.modelPuller.models.custom.opus.base }}"

cat <<'MODELFILE_EOF' > /tmp/Modelfile.opus
FROM {{ .Values.modelPuller.models.custom.opus.base }}
PARAMETER num_ctx {{ .Values.modelPuller.models.custom.opus.contextSize }}
{{- with .Values.modelPuller.models.custom.opus.repeatPenalty }}
PARAMETER repeat_penalty {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.opus.temperature }}
PARAMETER temperature {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.opus.topP }}
PARAMETER top_p {{ . }}
{{- end }}
{{- with .Values.modelPuller.models.custom.opus.topK }}
PARAMETER top_k {{ . }}
{{- end }}
SYSTEM """
{{ .Values.modelPuller.models.custom.opus.systemPrompt | indent 0 }}
"""
MODELFILE_EOF

echo "Removing existing opus model to enforce update..."
ollama rm opus || true

if ollama create opus -f /tmp/Modelfile.opus; then
    echo "Successfully created opus model"
else
    echo "Failed to create opus model" >&2
fi
{{- else }}
echo "opus model creation skipped (disabled in values)"
{{- end }}
{{- end -}}
