{{- define "weaviate.name" -}}
{{ .Chart.Name }}
{{- end -}}

{{- define "weaviate.fullname" -}}
{{ include "weaviate.name" . }}
{{- end -}}
