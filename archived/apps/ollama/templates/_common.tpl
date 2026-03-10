{{/*
Common utilities for model puller scripts.
Contains shared functions used by all model scripts.
*/}}

{{- define "ollama.script.common" -}}
#!/bin/sh
set -eu

echo "Waiting for Ollama service at $OLLAMA_HOST..."
start="$(date +%s)"
timeout_secs={{ .Values.modelPuller.timeoutSeconds | default 1200 }}

while ! ollama list > /dev/null 2>&1; do
  now="$(date +%s)"
  if [ $((now - start)) -gt "$timeout_secs" ]; then
    echo "Timed out waiting for ollama after ${timeout_secs}s" >&2
    exit 1
  fi
  echo "Waiting for ollama..."
  sleep 10
done

echo "Service ready. Starting pulls..."

pull_with_retry() {
  model="$1"
  attempts={{ .Values.modelPuller.pullRetryAttempts | default 5 }}
  delay={{ .Values.modelPuller.pullRetryDelay | default 15 }}

  i=1
  while true; do
    echo "Pulling $model (attempt ${i}/${attempts})..."
    if ollama pull "$model"; then
      return 0
    fi

    if [ "$i" -ge "$attempts" ]; then
      echo "Failed to pull $model after ${attempts} attempts" >&2
      return 1
    fi

    i=$((i + 1))
    sleep "$delay"
  done
}
{{- end -}}

{{/*
Function to pull all base models specified in values.
*/}}
{{- define "ollama.script.pull-models" -}}
# Pull base models
echo "Pulling base models..."
{{- range .Values.modelPuller.models.pull }}
pull_with_retry "{{ . }}"
{{- end }}
echo "Base model pulls complete."
{{- end -}}
