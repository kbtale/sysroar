{{- define "sysroar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sysroar.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "sysroar.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sysroar.labels" -}}
app.kubernetes.io/name: {{ include "sysroar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "sysroar.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{ .Values.secrets.existingSecret }}
{{- else -}}
{{ include "sysroar.fullname" . }}-secrets
{{- end -}}
{{- end -}}
