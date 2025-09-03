{{- define "livekit.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "livekit.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s" $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "livekit.labels" -}}
app: {{ include "livekit.fullname" . }}
chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
release: {{ .Release.Name }}
heritage: {{ .Release.Service }}
{{- end -}}

{{- define "livekit.serviceName" -}}
{{- printf "%s-svc" (include "livekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
