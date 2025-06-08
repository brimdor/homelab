
{{- define "emby.name" -}}
{{- default "emby" .Values.nameOverride -}}
{{- end -}}

{{- define "emby.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Values.nameOverride | default "emby" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "emby.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}
