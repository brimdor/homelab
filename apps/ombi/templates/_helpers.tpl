{{- define "custom.envMap" }}
{{- range $key, $value := . }}
  - name: {{ $key }}
    value: {{ $value | quote }}
{{- end }}
{{- end }}