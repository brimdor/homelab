{{- define "custom.envMap" }}
{{- range $key, $value := .Values.env }}
  - name: {{ $key }}
    value: {{ $value | quote }}
{{- end }}
{{- end }}