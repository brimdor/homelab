{{- define "custom.envMap" }}
{{- range $key, $value := .Values.env }}
  - name: {{ $key | quote }}
    value: {{ $value | quote }}
{{- end }}
{{- end }}
