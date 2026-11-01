{{- define "meowdoku.name" -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
