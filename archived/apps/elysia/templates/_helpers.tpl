{{- define "elysia.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "elysia.fullname" -}}
{{- if .Chart.Name }}{{ include "elysia.name" . }}{{ end -}}
{{- end -}}
