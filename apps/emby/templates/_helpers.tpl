{{- define "emby.name" -}}
emby
{{- end -}}

{{- define "emby.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "emby.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "emby.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}
